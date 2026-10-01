---
title: Deployment
---
# Deployment

Deployment follows the app shape: a **headless, event-driven core** with one replica by default,
an opt-in **thin console + Operator API**, and **PR-native + ChatOps** delivery (see
[app-shape.instructions.md](../../../.github/instructions/app-shape.instructions.md)).
Infrastructure is code; every release is reversible through the layered rollback paths defined
in [Release and Rollback](#release-and-rollback).

> **Tenant deployment execution:** Connected and artifact-offline tenant deployments use
> `fdaictl provision azure` and a manual managed host inside the target VNet. GitHub Actions may
> validate and publish release artifacts, but it is not a tenant plan, apply, resume, or teardown
> transport.

The core is **CSP-neutral by design**: cloud access sits behind provider adapters, so the
Azure mapping below is the one implemented target. **Non-Azure providers are TBD** (see
[Implementation Focus](../../../.github/copilot-instructions.md#implementation-focus-must)); the
adapter surface is preserved so a future target is additive. A downstream distribution may supply
provider implementations without editing core; each deployment supplies identities and state
bindings through configuration (see
[generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md)).
## Environments

Promotion is **one-way** (`dev → staging → prod`) and **by artifact**: the same signed image
that passed staging is promoted to prod - never rebuilt per environment. Staging mirrors the
prod topology so shadow evaluation is representative.

| Environment | Purpose | Autonomy level |
|-------------|---------|----------------|
| `dev` | development and integration validation | authoritative promotion state; same risk/HIL gates |
| `staging` | pre-prod validation, shadow evaluation of new rules/actions (prod-mirrored) | shadow, selective enforce |
| `prod` | live operations | enforce for low-risk; HIL for high-risk |

- Config differs per environment; **no environment values in source** - all injected at runtime.
- A deployment supplies its environment config without editing core. Environment never promotes or
  demotes a capability; see [ADR-0002](../architecture/decisions/0002-independent-runtime-axes.md).
- **Console and executor deploy as distinct identities** - the console is read-only and never
  holds the executor's privileged Managed Identity (see
  [security-and-identity.md](../architecture/security-and-identity.md)).

## Infrastructure as Code

- All infrastructure defined in `infra/` (Terraform primary; Bicep optional for Azure-only
  bits). The **core engine stays CSP-neutral**; vendor-specific IaC lives behind the same
  provider boundary as the runtime adapters.
- **State management**: the app layer uses a locked remote backend with **per-environment state
  isolation**. The first `infra/bootstrap/` apply keeps local state because it creates the state
  backend. After the backend and VNet runner are available, bootstrap state moves to the dedicated
  `ops/bootstrap/<environment>.tfstate` key. The migrated remote key is authoritative; the local
  source remains only as a bounded migration backup until lineage, serial, and resource count are
  verified.
- **Independent-service state cutover**: each runtime service uses its own backend key. The
  migration tool backs up both states, moves one declared address, and accepts cutover only when
  the source contains zero copies and the destination contains exactly one. The legacy deployment
  plan gate blocks any later create, update, replacement, or delete at a migrated source address.
  Protected service plans and successful applies pull all four peer states before and after the
  operation. They compare the canonical state digest, serial, lineage digest, and managed-resource
  count for every peer. Raw state is deleted immediately and never uploaded; the workflow retains
  the sealed peer-isolation receipt for 90 days.
- **Initial service runtime cutover**: after state ownership moves, the first protected plan uses
  the explicit `initial_cutover` mode. The sealed plan may replace the legacy command,
  environment, secret bindings, and primary probes with the service-owned contract while keeping
  the resource identity, platform, workload identities, resource limits, secret provenance, and
  sidecars unchanged. Core may remove the already-active isolated-Executor cutover marker; no
  service may add authority. Later plans return to image-only updates unless another reviewed
  deployment mode is introduced. The service contract includes every environment value consumed
  by its production entry point. For example, Core binds the Azure tenant, subscription, region,
  PostgreSQL host, and database before the protected plan can pass startup validation.
- **Bounded database host binding**: after initial cutover, the explicit `database_host_binding`
  mode may add or replace only the non-secret `POSTGRES_HOST` environment binding and the canonical
  runtime bindings described below while preserving resource identity, command, unrelated
  environment values, workload identity, platform, sidecars, secrets, and rollback fields. Existing
  Operator workloads with the historical `-readapi` suffix remain eligible for an in-place update,
  while newly declared Operator resources continue to use `-operator-api`. During input
  materialization, the workflow resolves the hostname from the platform state's `postgres_fqdn`
  output and overwrites only `database.host`. For Operator, it uses the protected
  `CONSOLE_DEFAULT_HOSTNAME` publication binding and replaces `cors_allow_origins` with that single
  normalized Static Web Apps HTTPS origin. It also resolves the canonical primary ingress,
  pipeline-stage, and Pantheon-object topics from platform state and overwrites only their owned
  `event_topics` fields for Core, Operator, and the document services. The write-only service
  tfvars secret remains the source for DSN references, roles, and other inputs. An unrelated
  current Operator channel edge and its platform identity are preserved from exact service-state readback, and a previously
  absent `FDAI_EXECUTION_VENUE` binding can be adopted only as the exact `deployed` value. Core may add
  the canonical `fdai.notifications.delivery-receipts` topic once; the guard requires that exact
  non-secret value and rejects every accompanying command, identity, or environment change. All
  primary-container comparisons normalize equivalent numeric CPU encodings and use exact
  environment name-to-binding maps, so provider number formatting or Terraform list order does not
  create a false drift finding. A rejection reports changed binding names without
  logging their values.
- **Degraded Operator recovery baseline**: `degraded_recovery` can accompany only an Operator
  `database_host_binding` plan. It does not expand the accepted Terraform changes. When Azure has
  no distinct healthy revision, pre-apply capture may use the current revision only if it is active,
  provisioned, running with at least one replica, and already marked unhealthy. The plan and context
  seal the explicit recovery intent. If apply or health verification fails, rollback restores the
  exact captured image, container, sidecar, secret-reference, identity, and platform contract. A
  degraded rollback is accepted only when the restored revision reaches the same bounded running
  state; the deployment still fails and retains the rollback evidence.
- **Bounded Core model binding**: the Core-only `model_binding_transition` mode may change only the
  attested resolved-model digest, fixed runtime mode and manifest path, resolved HTTPS endpoint,
  and validated web-search settings. The active Core revision must already use canonical Event Bus topic bindings. Platform model-only plans target the `azurerm_cognitive_deployment.capability` resource collection directly instead of the enclosing model module, so existing account and role-assignment resources cannot enter through target expansion. The plan may compose this mode only with `database_host_binding` and the exact
  first-time notification receipt topic addition. Each guard validates its complete allowlist, the
  host, topic, and endpoint map come from authoritative platform-state output, and the sealed
  deployment mode records the exact combination. When a resolver-only manifest omits optional
  narrator routing metadata, materialization selects the single Azure OpenAI endpoint from that
  authoritative map and still verifies its provider reference and hostname. Resolver artifacts are
  canonicalized before plan hashing so the plan and image attestation use the same content digest.
  A resource-no-op recovery plan is accepted only when that digest differs from the attested active
  Core digest, and the apply still requires model-specific provider readback. The attested model
  digest may remain unchanged when the validated endpoint map is the model binding being added. No
  identity, authority, secret, command, or unrelated environment change is accepted.
- **Bounded Core evidence binding adoption**: the Core-only
  `core_evidence_bindings_transition` mode may add only previously absent decision-evidence storage
  and operating-intent source bindings. It runs independently from initial cutover, database,
  model, channel-edge, and SharePoint transitions. The guard requires one HTTPS Blob container URL,
  a path under `/app/config/`, an exact revision, a SHA-256 content digest, a positive rollout
  generation, and exact positive counts for all six operating-intent types. An optional
  revalidation interval is capped at eight hours. The sealed deployment mode and prior healthy
  revision preserve rollback, while command, identity, secret, authority, rebinding, removal, and
  unrelated environment changes remain blocked.
- **Metering ledger ownership**: Core owns and appends `llm_invocation` records with only
  `SELECT, INSERT`; Operator consumes the same table with `SELECT` only. The service migration
  graph treats Operator as the read-only consumer and blocks provider rollback until the Operator
  metering grant is removed. Both provider and consumer migrations revoke `PUBLIC` access; neither
  runtime receives update or delete privileges. Core rehydrates incident lifecycle state before
  readiness, then a readiness-gated background worker replays durable A2 notifications. Slow or
  unavailable notification subscribers cannot block unrelated Core startup; sent checkpoints keep
  replay idempotent, and transient delivery failures retry without granting authority. Incident lifecycle
  recovery reads the indexed `audit_log.action_kind` path; its partial index is built concurrently
  so active audit writers remain available. A later readiness refresh exception closes guarded
  processing immediately but does not terminate Core when the failure is a recoverable connection,
  timeout, operating-system, or PostgreSQL operational error. The supervisor schedules the next
  check no later than the earliest evidence expiry, closes processing before reevaluation, and
  keeps the prior report for diagnosis. Programming errors still propagate after readiness closes,
  and only a complete successful refresh reopens processing.
- **Drift detection**: a scheduled read-only refresh plan covers the legacy platform root, the five
  independent service roots, and the bootstrap root for each environment. Refresh-only planning
  compares live resources with the last applied state and cannot interpret missing dispatch-only
  feature inputs as deletion intent. Protected deploy plans separately compare code and deployment
  configuration with state. A change to the drift workflow or its state parser also starts this
  read-only check on `main`, which validates the detector without a separate dispatch. The root
  contract uses distinct backend keys and resolves service images from pre-refresh state, so an
  out-of-band image change remains visible. Missing state, missing inputs, unreadable evidence, and
  detected drift all fail the run; drift is never silently applied.
- Provisioned resources - **minimum cost-efficient set** (full inventory + tier decisions in
  [deploy-and-onboard.md](deploy-and-onboard.md#azure-resource-inventory-minimum-set); the
  inventory renders the CSP-neutral contracts in [csp-neutrality.md](../architecture/csp-neutrality.md)):
  - **Container Apps environment** (Consumption) running **one control-loop core Container
    App** for `event-ingest` + `trust-router` + `executor` +
    `audit-writer`, deployed from an **OCI image + Knative-compatible manifest subset** so
    the runtime is portable ([csp-neutrality.md § Runtime contract](../architecture/csp-neutrality.md#2-runtime-contract--oci-image--knative-compatible-manifest)).
    The core has no sidecar or ingress. The opt-in Operator API, public ingestion API, internal
    ingestion worker with its ClamAV sidecar, and Isolated Executor are separate Container Apps.
    The Executor has no ingress; default deployment remains shadow-only, and the explicit SD-08
    cutover moves gateway caller authority and action identities away from Core.
  - **Container Apps Jobs** in the same environment for scheduled probes, light triggers, and
    bounded deployment preparation (replaces Azure Functions for runtime scheduling). The Operator
    deployment runs its schema migration Job first, then a separate digest-pinned Core-image Job
    writes immutable Rule and Ontology reference projections. An opt-in development-only FC1
    Function App is the narrow exception: it relays registered operations to private resources and
    is not a scheduler or control-loop runtime.
  - **Event Hubs** (two Standard 1-TU namespace shards, auto-inflate off) consumed **only via
    Kafka endpoints on `:9093`** - the CSP-neutral event bus contract
    ([csp-neutrality.md § Event bus contract](../architecture/csp-neutrality.md#1-event-bus-contract--kafka-wire-protocol)).
    The primary shard owns governed ingress, its DLQs, HIL, and pipeline stages. The operational
    shard owns canary + DLQ, startup round-trip, raw inventory, Executor command + DLQ, and
    Executor receipt entities. This stays within the Standard tier's ten-entity namespace limit.
    Subscription resource writes/deletes are forwarded to `fdai.inventory.raw` by a managed-identity
    Event Grid subscription. No Service Bus or custom Event Grid topic exists.
  - **PostgreSQL Flexible Server** (Burstable B1ms, 1 zone, 7-day backup) as the single store
    for audit + KPI + pattern library + **pgvector** T1 embeddings.
  - **Private StorageV2 case-history account** with Shared Key disabled, Blob versioning,
    soft delete, bounded version lifecycle, a dedicated non-executor workload identity, and a private endpoint.
    It stores content-addressed case revisions; PostgreSQL keeps only the rebuildable hot index.
  - **Key Vault** as the secret backend, consumed by the app via **Container Apps native
    secret + Key Vault reference** - the app reads env vars only and never imports a secret
    SDK ([csp-neutrality.md § Secret contract](../architecture/csp-neutrality.md#3-secret-contract--environment--k8s-secret)).
  - **Multiple User-assigned Managed Identities** with scoped role assignments, exposed as
    the `WorkloadIdentity` interface (OIDC token) - see
    [security-and-identity.md](../architecture/security-and-identity.md) and
    [csp-neutrality.md § Workload identity contract](../architecture/csp-neutrality.md#4-workload-identity-contract--oidc-token).
    Executor, inventory, canary, and three vertical identities ship by default; read, command,
    isolated-Executor shadow transport, ingestion API, ingestion worker, ingestion migration, and
    notification identities are opt-ins. The shadow transport identity has no effect roles.
  - **Log Analytics workspace + workspace-based Application Insights** (30-day default).
  - **Azure Container Registry** (Basic) for signed images.
  - Free-tier / non-billable elements: opt-in Static Web Apps (console), workload identity
    federation (CI/CD), and app registrations for console SPA + API + approval bot. A downstream
    Teams channel may supply Azure Bot; upstream Terraform does not provision it
    ([user-rbac-and-identity.md](../interfaces/user-rbac-and-identity.md)).
- Explicitly deferred: separate vector DB, standalone Service Bus / custom Event Grid topics,
  Front Door / API Management, secondary-region DR resources (Phase 4 - TBD).
- IaC passes Terraform validate plus pinned Trivy and Checkov scans in CI.

## CI/CD Pipeline

![CI/CD Pipeline. The main stages are Pull Request, lint + repository gates, unit tests: T0 engine + risk gate, block merge/promotion, IaC + dependency + secret scan, build + SBOM + sign + attest, deploy same artifact to staging, shadow evaluation + regression, promote code?, deploy same image to prod, enable enforce?, enforce per action.](../../diagrams/generated/fdai-roadmap-deployment-deployment-01.en.svg)

- **CI identity**: the pipeline authenticates with a **short-lived, OIDC-federated** identity
  (no long-lived cloud keys in CI). Secrets are pulled from the secret store at runtime and
  are **never** written to logs or build artifacts (secret scanning gates the merge).
- **PR packaging checks**: `.github/workflows/container-supply-chain.yml` builds and scans affected
  images only when Dockerfiles, base-image pins, dependency metadata, build helpers, or packaged
  assets change. Ordinary Python source, unit-test, and package-documentation changes do not build
  images. Shared lockfiles, workspace metadata, build overrides, and unknown service inputs select
  all images conservatively. Runtime assets, including packaged scenarios, retain their consumer
  checks. PR jobs stay hosted, read-only, and secret-free, including for fork PRs. They cannot
  publish images or generate release SBOMs or attestations.
- **Explicit image candidates**: full build, scan, publication, software bill of materials (SBOM),
  and provenance run only through an explicitly authorized `workflow_dispatch` on protected
  `main`. Routine `main` pushes and version tags do not publish images. Supply `commit_sha` equal
  to that workflow run's `github.sha`; historical or alternate-ref builds are not supported.
  The protected workflow verifier runs before input-validation code or candidate source checkout.
  Required pushed-SHA CI and deployment preflight remain separate release requirements.
- **Image selection**: `images` is required and has no default. Supply comma-separated targets:
  `core-control-plane`, `cost-governance`, `operator-service`, `document-ingestion-api`,
  `document-processing-worker`, `isolated-executor`, or `system-knowledge-service`. Their
  `fdai-`-prefixed image names are also accepted. Selecting a runtime service selects its default
  image only; the optional Cost Governance profile requires its own selection. Use `all` alone
  only when every image is intentionally needed. Empty, unknown, duplicate, or mixed `all`
  selections fail before any build. For example, `images=operator-service,document-ingestion-api`
  publishes just those two candidate images.
- **Supervised callers**: Genesis requests the three images its resolver consumes. Candidate run
  metadata must cover that set before orchestration reuses a successful run; PR or partial-set
  success is insufficient. The resolver still independently verifies every digest and attestation.
- **Candidate evidence**: selected builds block on MEDIUM/HIGH/CRITICAL Trivy findings both before
  publication and against the exact pushed digest. Each image retains CycloneDX SBOM evidence,
  build provenance, and an SPDX SBOM attestation; Core also binds the resolved-model material
  digest. Base images stay digest-pinned and run as uid 65532. The Core builder cold-imports
  production bootstrap after installing its wheel, so missing runtime dependencies block
  publication. Deployment still verifies the exact source revision, trusted signer workflow,
  attestations, and image digest before rollout.
- **Evidence reuse**: promote an existing matching, verified digest without rebuilding when the
  deployment verifier accepts its source and evidence. Recheck applicable freshness and policy.
  A local validation cache, a PR scan, or an image tag alone is never deployment authority.
- **Artifact registry**: images and their SBOM/attestations are retained with an explicit
  retention policy so any prod revision can be traced and re-verified.
- **ACR handoff**: upstream GHCR is the generic build-evidence registry. A fork that requires
  ACR copies the verified image without rebuilding so the digest stays stable, creates or
  copies the target-registry attestations, and binds that ACR digest as
  `signed-image-provenance` in the ARB evidence manifest. Building a second image for ACR is
  not accepted because it produces a different subject. The private-runner Executor plan resolves
  one source revision to its attested GHCR digest. OCI verification renders the workflow token in
  process into a mode-0600 file inside a mode-0700 transient Docker config, never places the token
  in process arguments or output, and removes the credential directory at step exit. The plan
  optionally imports that exact subject only under an
  explicit promotion input, normalizes the Terraform ACR output or verified deployed Job image to
  its exact Azure login host, verifies the ACR digest is identical, and then binds the digest to
  Terraform. Exact apply cannot promote or replace the image recorded in the protected plan.
  Protected OI-12 binding prefers the platform root outputs for the inventory Job, history Job, and
  archive container URL. When a deployed state predates those outputs, it enumerates only
  `Microsoft.App/jobs` under a 64-resource bound and reads each resource through the stable
  Container Apps `2024-03-01` API with a 30-second bound. If the resource-group output is empty, the
  unique inventory and history runtime contracts must report the same provider-observed group before
  the workflow adopts it. Any non-empty root output must match the selected ARM runtime. The fallback
  does not derive Job identity from a naming pattern or retain provider output after the step.
  Job resolution, exact OCI provenance verification, and ACR binding run as separate protected
  steps. Only the exact verified repository, revision, and digest cross from verification to
  binding through the job environment.
  Inventory refresh uses the stable ARM start action with the reviewed live Job template and changes
  only the canonical `inventory` container image. It does not use the CLI image shortcut, which
  replaces the container name, command, and environment.
- **Promotion gate checklist** (all must pass): T0-engine and risk-gate unit tests green at the
  coverage bar; IaC + dependency + secret scans clean; shadow evaluation shows **zero
  policy-violation escapes** and the regression suite passes; staging SLOs healthy.
- **Promotion to enforce** for any new autonomous action is a **separate, explicit approval** -
  deploying code never auto-enables enforce (default stays shadow, see
  [security-and-identity.md](../architecture/security-and-identity.md)).

## Progressive Delivery (target state)

Traffic-split canary strategies are not automated yet. The platform deploy workflow applies a
single revision and runs the canary publisher smoke. In contrast, the independent-service workflow
captures a healthy active revision and image before exact apply, retains one inactive revision,
verifies the new resource id, subscription, component tag, image digest, and revision, and
automatically creates and verifies a recovery revision when that immediate health check fails. An
unhealthy baseline blocks apply. SLO-window traffic rollback remains a target design.

- **Core (Container Apps revisions)**: **canary** by traffic split. Promote in steps
  (e.g. 5% → 25% → 100%) gated on health signals; **automated rollback** triggers on SLO burn,
  error-rate spikes, or a rise in the guard metrics
  ([goals-and-metrics.md](../architecture/goals-and-metrics.md)).
- **Console (static hosting)**: **blue/green** - publish the new version alongside the old and
  cut over atomically, since it is read-only and holds no state.
- **Database migrations**: **expand/contract**, forward-only. Ship additive schema first,
  deploy code that tolerates both shapes, then remove the old shape in a later release.
  Migrations run as a gated step **before** the app revision takes traffic and stay
  backward-compatible so a revision rollback does not break the schema. Online Alembic runs
  serialize revision inspection, DDL, and version-row updates with a database-scoped transaction
  lock, so concurrent startup or test workers cannot apply one revision twice. Connections fail
  within 10 seconds, lock waits fail within 5 minutes, and the protected migration stage closes
  within 20 minutes; the two-hour deployment budget is never the first migration deadline. After the Operator
  migration succeeds, deployment runs a separate Core-image Job that deterministically refreshes
  immutable repository catalog projections. These rows describe reviewed reference declarations;
  they do not create findings, inventory, incidents, readiness, or execution authority.

## Release and Rollback

Every autonomous action carries the seven safeguards (stop-condition, rollback path,
blast-radius limit, dry-run, resource lock, idempotency, audit entry) from
[architecture.instructions.md](../../../.github/instructions/architecture.instructions.md);
deployment rollback complements, not replaces, per-action rollback.

- **Application rollback**: an independent-service deploy accepts only a healthy active rollback
  baseline and retains one inactive revision. It restores the exact captured revision and
  digest-pinned image after immediate health failure, verifies the recovery revision, then
  deactivates the failed revision and confirms it is inactive before closing the deployment as
  failed. Core image changes also bind `FDAI_SOURCE_REVISION` to the exact protected commit. The
  fixed Azure Heimdall recovery observer can be added only once through the explicit
  `core_evidence_bindings_transition`; rebinding or unrelated environment drift blocks the plan.
  The isolated Executor also returns its cutover setting to the declared `core-in-process`
  authority fallback.
- **Ingestion topology rollback**: restore the exact prior Document Ingestion API and Document
  Processing Worker revisions and digest-pinned images without changing consumer groups or
  offsets. The retired `ingestion_cohost_worker` input is rejected before planning.
- **Action rollback**: PR-native actions revert via git; stateful actions (e.g. DB DR) follow
  the per-action rollback path (snapshot/replica restore) and **verify** the restore against
  the action's stop-condition before closing.
- **Rule-catalog rollback**: rules are catalog-as-code and versioned; a bad rule set is
  reverted via the update pipeline. Promotion of a rule set requires the **regression suite to
  pass with zero escapes**; a failing regression blocks promotion or demotes the rule set (see
  [phase-2-quality-and-t1.md](../phases/phase-2-quality-and-t1.md)).

## Control-Plane Disaster Recovery

The control plane must recover itself, not only remediate others. The canonical
[control-plane disaster-recovery design](control-plane-disaster-recovery.md) defines the active-
passive profiles, single-writer recovery epoch, primary fencing, state and event recovery,
failback, and evidence gates.

Dead-letter queues alone are not regional event recovery. Event Hubs metadata disaster recovery
does not replicate event data, and PostgreSQL geo-redundant backup is not remote point-in-time
restore. Each production deployment binds an explicit event source, data recovery method, numeric
RPO/RTO, traffic strategy, and measured failover/failback drill evidence.

## Observability, SLOs, and Alerting

- **Telemetry**: OpenTelemetry traces/metrics/logs feed the KPI dashboard (metrics 1-4 and the
  guard metrics in [goals-and-metrics.md](../architecture/goals-and-metrics.md)); every autonomous action emits
  an audit record and KPI event with a correlation id.
- **SLOs**: define control-plane SLOs (event-processing latency per tier, action success rate,
  console availability) with **error budgets**; SLO burn feeds progressive-delivery rollback.
- **Alerting**: two lanes - **operational** alerts (pipeline failure, IaC drift, DLQ depth,
  SLO burn, verifier failure rate) route to on-call; **HIL** alerts route high-risk approvals
  to the Teams channel.
- **On-call and runbooks**: maintain runbooks for rollback, DR failover, DLQ drain, and drift
  reconciliation. If ChatOps is down, high-risk HIL items **queue and alert via a fallback**;
  nothing auto-executes without approval.

## Cost Posture

All cost claims below are **directional targets to validate against a measured baseline**
([goals-and-metrics.md](../architecture/goals-and-metrics.md)), not guarantees.

- The core keeps one replica until a Kafka scaler is verified. Scheduled Jobs scale to zero
  between executions.
- Only a **small minority (~5-10%)** of events are designed to reach a frontier model; token
  budgets cap spend and overflow degrades to HIL rather than uncapped inference.
- OSS components (OPA, IaC scanners, OpenCost, Chaos Mesh) avoid per-seat license cost.

## Open Decisions

- [x] IaC engine - **resolved: Terraform**. Bicep and OpenTofu remain compatible alternatives;
  the current deployment graph is owned by `infra/` HCL (see [tech-stack.md](../architecture/tech-stack.md)).
- [x] Compute target - **resolved: Azure Container Apps + Jobs**. Revisit AKS only for a
  measured need such as custom networking, DaemonSets, or GPUs.
- [ ] Canary step function and automated-rollback thresholds for enforce promotion.
- [x] Azure remote state and identity - **resolved: private Storage backend + stable deploy UAMI
  attached to a VNet managed deployment host**, with a state key per environment. Per-CSP identity for non-Azure targets is TBD; see
      [Implementation Focus](../../../.github/copilot-instructions.md#implementation-focus-must)
      and [security-and-identity.md](../architecture/security-and-identity.md)).

## Related docs

| To learn about | Read |
|----------------|------|
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/deployment/deployment.md) |
