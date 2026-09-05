---
title: Subscription Genesis Provisioning
---
# Subscription Genesis Provisioning

This document defines the zero-to-ready lifecycle for provisioning FDAI into a new or partially
configured Azure subscription. It composes the existing Terraform, protected runner, database,
catalog, model, and inventory paths behind one resumable `fdaictl` operation without weakening
exact-plan approval or private-network boundaries.

> **Scope:** Azure is the implemented target. The operator can connect through a VPN, but every
> deployment data-plane operation runs on an approved host inside Azure. The laptop is a control
> surface, not a private-endpoint bypass.
>
> **Safety:** "One operation" means one durable run that can pause, resume, and report progress.
> It does not mean one unreviewed mutation. A new private backend requires a foundation approval,
> followed by approval of the exact application plan produced from that backend.
>
> **Implementation ledger:** Delivery state and observable remaining work are tracked in
> [Subscription Genesis Provisioning implementation ledger](../../roadmap-implementation/deployment/subscription-genesis-provisioning.md).
> The cross-stage security, completeness, recovery, cost, and progress gates are defined in
> [Subscription Genesis Assurance](subscription-genesis-assurance.md).

## Design at a glance

`fdaictl` owns orchestration and presentation. Terraform remains the infrastructure source of
truth, service migration tools own schema changes, repository catalogs own ontology and rules, and
the inventory single writer owns observed resource instances.

```text
inspect -> reconcile current state -> foundation plan/apply -> attest runner
        -> application plan/apply -> migrate -> materialize catalogs and defaults
        -> deploy and verify models -> scan and promote inventory -> readiness receipt
```

The run closes as `ready` only when all required stages have independent postcondition evidence.
An Azure create response, Terraform apply completion, migration process exit, model deployment
state, or inventory stream completion is not sufficient on its own.

## Current gaps

The repository contains most low-level mechanisms, but they do not yet form one complete
subscription-onboarding product:

| Area | Current evidence | Gap this design closes |
|------|------------------|------------------------|
| Operator entry point | `fdaictl` provides bootstrap reconciliation plus protected application plan, exact apply, status, and verification-only resume | Approved foundation apply, remote-state handoff, and one complete ready receipt remain open. |
| Genesis progress | `genesis-up.sh` is a fail-closed compatibility shim; the CLI and Console share a bounded status snapshot that separates stage completion from readiness | No authoritative Azure producer or durable Blob-to-Operator mirror exists. |
| Database bootstrap | Integrated and service-owned migrations plus a fail-closed database/semantic readback contract exist | Pre-runtime marker production and runtime-principal evidence are not unified into a complete zero-to-ready receipt. |
| Ontology and rules | Catalogs are versioned in the repository and can be materialized as immutable Operator projections | Catalog projection is conditional on the Operator API path and is not a required subscription readiness gate. |
| Model deployment | The live resolver, capability assessment, Terraform modules, and keyless roles exist | Requested capacity has no explicit minimum, utilization headroom, workload profile, or end-to-end throughput acceptance gate. |
| Initial resource scan | The continuous inventory Job promotes only a complete generation; the Console separates estimated scan counters from verified closure | The protected run does not yet publish durable provider progress or retain the governed full-subscription receipt. |

The inventory CLI delegates sanitized collection-health assembly to a focused pure helper before it
persists the result through the existing state-store adapter. A one-shot scheduled run still fails
when every inventory source is exhausted so the genesis orchestrator can observe the failure. The
local long-running profile records that exact failure and retries only after its configured loop
interval. Neither mode changes source authority or readiness semantics.

## Target operator experience

The high-level path uses the canonical command groups and adds durable run identity:

```bash
fdaictl provision inspect --profile .fdai/environments/dev.json
fdaictl provision init --profile .fdai/environments/dev.json
fdaictl onboard guided --profile .fdai/environments/dev.json \
  --source-commit <git-sha> --run-id <run-id> \
  --journal .fdai/runs/<run-id>.jsonl \
  --repository <owner>/<repository> --output json
fdaictl deploy status --profile .fdai/environments/dev.json \
  --repository <owner>/<repository> \
  --request-id <request-id> --commit-sha <git-sha> --output json
fdaictl onboard guided --profile .fdai/environments/dev.json \
  --source-commit <git-sha> --run-id <run-id> \
  --journal .fdai/runs/<run-id>.jsonl \
  --repository <owner>/<repository> --plan-id <plan-id> \
  --plan-digest <plan-digest> --plan-expires-at <expires-at> \
  --approve-application --output json
fdaictl onboard status --journal .fdai/runs/<run-id>.jsonl --output json
```

- `provision inspect` and `provision init` never mutate Azure.
- `onboard guided` composes low-level `deploy plan` and `deploy apply`; `deploy status` returns the
  request-bound workflow state and sanitized plan metadata including `expires_at`. Application apply
  requires `--plan-expires-at` (from `deploy status` plan metadata) and `--approve-application`.
- `status` reads a sanitized projection. It never downloads Terraform state, secret values, DSNs,
  tokens, model request content, or provider payloads.

Use `--deploy-dev-operations-gateway` when the exact dev plan must preserve or provision the
private-resource operations Function gateway. The selection is sealed into the context digest
shared by plan, apply, and status, and it remains subject to the existing cutover, executor-effect,
and OHL safeguards. The bounded gateway target set includes both moved measurement-runner job
addresses so Terraform can complete state-address migration before planning dependent resources.

```bash
fdaictl deploy plan \
  --profile .fdai/environments/dev.json \
  --repository <owner>/<repository> \
  --commit-sha <git-sha> \
  --run-id <run-id> \
  --deploy-dev-operations-gateway \
  --output json
```
- `resume-verification` never retries Terraform apply. A stage without an apply claim can restart;
  an apply claim without a receipt can resume verification; a failed claim requires a new plan and
  approval. It cannot skip a failed postcondition or approve changed context.
- Human output shows subscription and tenant names for confirmation but redacts identifiers.
  Stable JSON carries digests and opaque references needed for automation.

### Console handoff

Before the Console exists, `fdaictl` and the protected runner are the only provisioning status
surfaces. Foundation, database, semantic, and model failures therefore remain visible through the
CLI even when no browser surface can start.

The application stage starts the authenticated Console before the initial inventory stage. After
the Operator projection and Console health checks pass, the operator can open `/provisioning`:

- The page evolves the existing `provision.*` stream and `/provisioning` route. It does not create a
  second Genesis route or read Terraform output directly.
- A one-way importer mirrors sanitized, ordered events from the private Blob ledger into the
  Operator projection. The Console and Operator API never receive Blob access, Terraform state,
  provider payloads, or deployment secrets.
- Earlier stages appear as durable replay. Initial inventory and final system verification can
  continue as a live tail after the page opens.
- Run progress, checkpoint progress, database readiness, semantic readiness, model readiness, and
  inventory progress remain separate values. A generic `done` event, Terraform completion, or an
  estimated resource count cannot produce `ready`.
- Inventory totals are labeled estimates until the independent postcondition observer verifies the
  active generation and coverage manifest. The page reaches 100 percent only from the terminal
  readiness receipt.
- Approval waits and blockers are read-only. The page shows the run reference and exact `fdaictl`
  next action instead of adding a browser-side execution path.
- After completion, the route remains available as the sanitized run history and links into the
  relevant database, ontology, model, inventory, and audit evidence views.

## Desired-state profile

`fdaictl provision init` writes a mode-`0600` profile in a mode-`0700` directory. The schema records
intent, not discovered secrets:

| Field group | Required intent |
|-------------|-----------------|
| Target | cloud, tenant reference, subscription reference, environment, application region, optional model region |
| Connectivity | existing Azure host or managed VM, transport, VPN expectation, private DNS and management-plane path |
| Adoption | create-only, explicit adoption allowlist, permitted Terraform import addresses, conflict policy |
| Services | Core, Operator API, Console, ingestion, isolated Executor, dev operations gateway, monitoring, and scheduled Job selections |
| Database | availability and retention profile, extension set, backup policy, migration deadline |
| Models | workload profile, capability policy, minimum capacity, target capacity, quota reserve, allowed regions and SKUs |
| Inventory | subscription or management-group scopes, source order, resource-type scope, page and request budgets |
| Safety | shadow-only default, approval policy and quorum, plan expiry, cancellation, cost ceiling, total and no-progress deadlines |

The profile never contains a password, access token, client secret, webhook value, private key,
connection string, Terraform state, or customer data.

When the plan preserves an already-deployed isolated Executor, `--runtime-image-revision` pins the
verified runtime image source commit. The value is a lowercase 40-character git SHA present in
both ACR and GHCR. It is sealed into the deployment context digest so plan, apply, and status
share one consistent selection. The runner retains ancestor, image, and attestation checks.

## Reconcile before create

Provisioning supports an empty subscription and the operator's existing partially configured
state. Inspection classifies every intended object:

| Classification | Behavior |
|----------------|----------|
| `managed` | The object is already in the expected Terraform state and matches ownership tags. |
| `adoptable` | The object exactly matches type, scope, immutable settings, ownership evidence, and an explicit profile allowlist. Planning proposes a precise import. |
| `external_dependency` | FDAI references the object but does not own its lifecycle. |
| `conflict` | The name or address exists without sufficient ownership or compatibility evidence. Planning stops. |
| `missing` | The object can be proposed for creation. |

Name similarity is never adoption evidence. Imports are part of the sealed plan, require approval,
and are followed by a zero-unrelated-destroy plan. Existing foreign endpoints or borrowed model
accounts are reported as conflicts or external dependencies rather than silently reused.

### Versioned provisioning manifest

Planning compiles one signed `SubscriptionProvisioningManifest` from the selected profile, exact
source revision, and Terraform plans. It enumerates every required and selected conditional Azure
resource in the [minimum resource inventory](deploy-and-onboard.md#azure-resource-inventory-minimum-set),
provider registration, role assignment, external prerequisite, database artifact, semantic
artifact, model deployment, runtime service, and inventory scope. Each entry declares its owner,
desired state, Terraform address or external evidence, postcondition, and rollback class.

Readiness requires a terminal disposition for every manifest entry. Optional means explicitly
disabled in the profile, not silently omitted. A missing provider registration is a planned
mutation and postcondition, not an inspection warning.

## Durable run and approval model

The empty-subscription foundation has an explicit bootstrap boundary:

1. The CLI creates a mode-`0700` ephemeral foundation directory and a mode-`0600` local Terraform
   state cache. The signed-in operator runs the sealed foundation plan locally because no Azure
   execution host exists yet. This phase performs Azure control-plane operations only and never
   writes a private data service.
2. Foundation creation includes the ops and empty application resource groups, state account,
   network, stable deployment identity, and runner. Every created resource carries the run digest.
3. The attested runner creates the private state container, migrates the exact local Terraform
   state to the remote backend, and proves a zero-change plan. It compares lineage, serial, address
   set, resource ids, and managed count before the remote state becomes authoritative.
4. The local state is a recovery cache, never approval or readiness authority. It is retained until
   remote reconstruction and readback succeed, then securely removed. A crash before that point
   resumes from the sealed foundation plan and Azure Activity Log observations, not name matching.
5. The runner writes hash-chained, sequence-numbered events and immutable receipts to versioned
   private Blob storage using Microsoft Entra authentication. Entries include authenticated actor,
   retention, and prior-entry digest; configured immutable retention or a signed anchor makes
   deletion detectable.
6. After PostgreSQL is ready, a read-only projection is mirrored for the Operator API and Console.
   The private Blob ledger remains the bootstrap authority.

Each mutating checkpoint binds the target tenant and subscription, source commit, profile digest,
Terraform root, backend identity, plan digest, expiry, approver, runner identity, and expected
postconditions. Before private Blob exists, the approval is the external protected-environment
record plus the sealed plan digest. Azure Activity Log independently identifies the mutating actor.
A changed input invalidates the checkpoint.

Two approval checkpoints are normally required for a new private subscription. Each checkpoint
requires one current accountable human at minimum, and high-impact plans use the configured quorum:

1. **Foundation approval:** private state account, ops network, deployment identity, and runner.
2. **Application approval:** the exact plan produced by the attested runner against the new backend.

An existing healthy foundation skips the first approval. An `--approve-all` or silence-based
approval mode is not supported.

## Provisioning stage contract

Stages are dependency ordered and persist a terminal receipt before the next stage starts:

| # | Stage | Required postcondition |
|---|-------|------------------------|
| 0 | Inspect context | Signed-in user, target match, required role-assignment ability, provider registration state, policy blockers, quotas, network paths, and toolchain are reported without mutation. |
| 1 | Reconcile current state | Every intended object is classified, conflicts are blocked, and proposed imports are explicit. |
| 2 | Plan and apply foundation | Resource groups, private backend, ops network, stable deploy identity, and execution host exist; remote state reconstruction, effective roles, provider registrations, and private storage access are read back. |
| 3 | Attest execution host | Exact source revision, bundle digests, Azure context, runner principal, tool versions, DNS, and private endpoint reachability match the plan. |
| 4 | Plan and apply data substrate | Application network, Key Vault, PostgreSQL, Event Hubs, registries, identities, and migration Jobs converge without unrelated destroy. Runtime consumers remain closed. |
| 5 | Bootstrap database | Legacy baseline and every service migration reach their declared heads; extensions, roles, grants, statement deadlines, and rollback references pass verification. |
| 6 | Materialize semantic defaults | The exact ontology release, rules, workflows, ResourceTypes, settings defaults, and shadow-only promotion state are written or projected with source digests. |
| 7 | Resolve and deploy models | Region, family, version, publisher, SKU, endpoint, role, and capacity satisfy the approved model plan and readback. |
| 8 | Deploy runtime services | Digest-pinned revisions start only after database and semantic readiness markers exist. Health and guarded-processing readiness pass. |
| 9 | Run initial inventory | A complete provider generation is counted, collected, verified, projected, atomically promoted, and independently read back. |
| 10 | Verify system readiness | Canary, event flow, database reads, catalog digests, model probes, inventory freshness, audit closure, and Console read projections pass. |

Failure stops dependent stages. Completed safe-to-retry stages are not repeated unless their
evidence expired or their inputs changed.

## Database and semantic bootstrap

The database stage uses a versioned bootstrap manifest so "migration succeeded" is not confused
with "the product is ready":

- **Schema ownership:** Run the legacy Alembic baseline, then each service-owned branch in declared
  dependency order. Record every head and adoption receipt.
- **Extensions and roles:** Verify required PostgreSQL extensions, separate migration and runtime
  roles, minimum grants, statement timeouts, and the absence of runtime DDL authority.
- **Ontology:** Persist the exact repository-loaded ontology release and verify its digest before
  accepting instance writes. Migrations provide only compatibility seeds.
- **Rules and workflows:** Keep catalog-as-code authoritative. The day-zero baseline is every
  schema-valid generic ontology, rule, workflow, ResourceType, and product-default entry in the
  signed bundle at the exact source revision. The bootstrap manifest lists every id, version,
  digest, dependency, and readback check. Materialize immutable read projections; do not turn
  copied database rows into a second rule source.
- **Defaults:** Write only versioned product defaults and deployment-owned scope bindings. All
  actions remain in shadow mode, and no default grants execution authority.
- **Readback:** Query through runtime identities, not the migration principal, and compare counts,
  release digests, schema heads, and role capabilities with the manifest.

The data-substrate apply keeps runtime consumers closed. Service activation occurs only after the
database and semantic readiness markers commit, preventing a fresh Container App revision from
racing its own schema.

## Model capacity and verification

"Enough TPM" is a measured deployment property rather than a fixed large number. Genesis requires
the nonempty core set `t1.embedding`, `t1.judge`, and `t2.reasoner.primary`, plus
`t2.reasoner.secondary` when mixed-model mode is active. `hil-only` cannot satisfy model readiness.
The model plan uses these inputs for each capability:

- minimum usable TPM or provisioned throughput units;
- target peak requests, input tokens, output tokens, and concurrent calls;
- target utilization ceiling, with a default planning ceiling of 70 percent;
- subscription quota reserve, with a default reserve of 20 percent;
- invocation class such as steady, novel-case, or disagreement-only;
- allowed publisher, family, stable version, SKU, region, and data-residency constraints.

The minimum capacity is computed from the versioned workload envelope, not accepted as an
unsupported operator guess:

`minimum_tpm = ceil(peak_requests_per_minute * max_tokens_per_request / utilization_ceiling)`

The value is rounded to the provider SKU unit. The profile also pins validation duration,
concurrency, request rate, success ratio, maximum throttled ratio, and maximum p95 latency.

The resolver ranks regions deterministically by required-capability coverage, SKU-qualified
available quota after reserve, policy compatibility, private-network support, and declared region
preference. Application and model regions can differ when the approved profile permits it.

For a required capability, capacity below the minimum blocks the plan. Capacity between minimum and
target requires explicit degraded acceptance. Optional capabilities can become human approval only
when the plan names the functional impact. Provisioning never consumes all visible quota merely
because it is available.

After apply, the runner:

1. reads back account, deployment, model version, SKU, capacity, private access, and role bindings;
2. confirms runtime endpoints belong to the newly managed accounts;
3. performs bounded keyless inference probes for every required capability;
4. runs the pinned workload envelope below the approved cost and token budget and requires its
   declared success, throttling, throughput, and p95 latency thresholds; and
5. records observed throttling, latency, and achieved throughput without storing prompts or output.

Only successful readback and probes close model readiness.

## Run-level progress

After planning seals the manifest, every surface shows exact
`checkpoints_completed / checkpoints_total`, `stages_completed / stages_total`, the current stage
and attempt, skipped optional stages, pending approval, blocking reason, last progress time, and
deadline. Overall progress uses fixed stage weights recorded in the sealed plan; reconnects cannot
regress it, and retries do not increase the total. An approval wait is a visible `waiting` state,
not apparent activity. Overall 100 percent requires the terminal readiness receipt.

## Initial inventory progress

The initial scan is an explicit onboarding stage. It does not wait for the next scheduled cron.
Progress uses one durable schema shared by the CLI, workflow summary, Operator API, and Console:

| Field | Meaning |
|-------|---------|
| `run_id`, `attempt_id`, `sequence` | Replay and reconnect identity |
| `stage`, `state`, `reason_code` | Count, collect, stage, enrich, validate, promote, verify, complete, or failed |
| `scopes_completed`, `scopes_total` | Exact configured scope progress |
| `provider_types_completed`, `provider_types_total` | Exact discovered type-shard progress |
| `resources_observed`, `resources_expected` | Current count and pre-scan provider count snapshot |
| `pages_completed`, `pages_expected` | Bounded page-work estimate, revised monotonically when continuation tokens add work |
| `links_observed`, `unmapped_objects`, `coverage_gaps` | Useful completeness context |
| `started_at`, `last_progress_at`, `deadline_at` | Elapsed time and stall visibility |
| `fraction`, `fraction_basis` | Monotonic overall progress and the counters used to derive it |

The pre-scan count is labeled as an estimate because resources can change during collection.
`fraction=1` is emitted only after the final fence, provider coverage reconciliation, atomic graph
promotion, and independent active-generation readback. If the count changes, the display can show
more observed resources than the original estimate without claiming more than 100 percent.

Genesis always scans the exact target subscription root with no resource-type filter. A narrowed
scope is available only for later operator-requested refreshes and cannot satisfy onboarding.
The runtime rejects resource-type subset promotion before the global active snapshot or ontology
projection can change, so a narrowed refresh cannot delete identities outside its requested set.
Provider-native object coverage, including materialized unmapped types, must be complete and
untruncated. Classified relationship gaps can close object inventory while keeping relationship
coverage limited and graph-dependent autonomy lowered. Relationship drops added by verified
enrichment remain in the same promotion metadata and cannot disappear during handoff. Partial source
coverage, unclassified drops, invalid verification metadata, or a missing final fence block
readiness.
Projection-source metadata can include only sanitized nonnegative coverage counts; malformed counts
block the projection record instead of becoming readiness evidence.

After a complete promotion, the inventory single writer can append verified
`resource.operational_state` changes to the Core-owned PostgreSQL transition ledger. The write uses
the retained `StateFactMetadata` authority, time, freshness, completeness, conflict, and evidence
fields. Snapshot comparison is recorded as `initial_state_only` or `snapshot_interval_only`; it
does not satisfy Genesis readiness or claim continuous observation. Transition persistence must
complete before topology history advances, so a retry cannot silently lose a state edge.

The Core service migration head must include the normalized inventory observation journal before
the inventory Job starts. The Job dual-writes the promoted full snapshot to that journal before
ontology projection and advances the ontology watermark only after the graph commit succeeds.
Journal lag or an unconfirmed tombstone keeps inventory source completeness false, so Genesis
readiness cannot hide a sparse event that the ontology has not projected. This prerequisite does
not complete the later incarnation, correction-partition, retention, or archive work.

Core migrations now add those lifecycle records after the normalized journal. Inventory promotion
binds observations to exact incarnations and logical time-and-scope partitions, and projection
closes late corrections with replay evidence. Deployment-supplied retention policies replace the
safe `retain` defaults only after schema validation. The archive writer, verified principal-scoped
reader, database purge gate, and fixed shadow schedule are ready for a dedicated Job binding; until
that Job and its protected receipt exist, Genesis reports the archive lifecycle as incomplete.
CI applies the complete service-owned migration chain before database integration tests and points
those tests at that migrated database, matching the Genesis runtime ordering.

Every emitted batch advances the durable heartbeat. A no-progress deadline fails the attempt,
retains the previous complete graph, and leaves a resumable cursor or a bounded restart decision.
The Console shows `observed / expected`, type and scope counts, current stage, elapsed time, last
progress time, and an estimated completion time only when a stable recent rate exists.

## Failure, rollback, and resume

- Foundation failure leaves an explicit partial-foundation receipt and a generated cleanup plan.
- Application failure retains the exact Terraform plan and state lock evidence. Resume rechecks the
  target and drift before retry.
- A duplicate, ambiguous, or failed Terraform apply claim is never automatically retried. An
  unapplied stage is replanned; an applied stage resumes verification only under the exact existing
  claim; a failed claim requires operator review and a newly approved plan.
- Migration failure prevents runtime activation. Recovery follows the migration-specific rollback
  or backup/restore contract; it never guesses a downgrade.
- Catalog failure keeps semantic readiness false even when schemas are current.
- Model failure leaves deterministic tiers available but cannot mark the deployment ready when a
  required capability is missing.
- Inventory failure retains the last complete generation and reports incomplete onboarding.
- Cleanup failure is a terminal incomplete state requiring operator review, not a success-shaped
  warning.

## Implementation plan

Implementation follows these dependency-ordered work packages:

1. **P0 - Freeze contracts:** Add the CLI package skeleton, canonical command namespace, profile
   and provisioning manifest schemas, run/event schemas, stage state machine, error codes,
   redaction contract, semantic baseline generator, and golden JSON fixtures.
2. **P1 - Read-only planning:** Implement `inspect`, current-state classification, provider and
   quota preflight, deterministic desired-state compilation, and sanitized human/JSON reports.
3. **P2 - Foundation orchestration:** Wrap `infra/bootstrap/` with sealed plans, explicit adoption,
   runner attestation, durable private-blob events, status, and resume.
4. **P3 - Application convergence:** Compose the protected platform workflow as child stages,
   separate data substrate from runtime activation, and bind exact-plan approvals and receipts.
5. **P4 - Database and semantic readiness:** Add the versioned bootstrap manifest, ordered
   migration gate, product-default materializer, ontology/catalog readback, and runtime-role tests.
6. **P5 - Model capacity:** Extend the capability policy with minimum, target, utilization, reserve,
   and workload inputs; implement deterministic region selection, capacity readback, and bounded
   keyless probes.
7. **P6 - Inventory progress:** Add count planning, durable progress events, initial-scan dispatch,
   active-generation verification, CLI rendering, Operator projection, and Console rendering.
8. **P7 - End-to-end assurance:** Test empty, partially configured, interrupted, quota-constrained,
   policy-blocked, throttled, and rerun scenarios. Retain one governed new-subscription receipt.

P4, P5, and P6 can proceed in parallel after P0. P7 begins only after their contracts merge through
P3's state machine.

## Design critique and revisions

The first draft assumed a single approval, omitted the first executor and complete resource
manifest, reused the application database for progress, treated requested TPM as sufficient, and
displayed one percentage for inventory. Those choices fail under a new private subscription:

- The exact application plan cannot be sealed against a backend that does not exist yet.
- The runner cannot create itself, and local bootstrap state cannot silently become remote truth.
- "All resources" and "all defaults" are unverifiable without enumerable manifests.
- PostgreSQL cannot be the authority for events that occur before PostgreSQL exists.
- Requested capacity does not prove quota, headroom, endpoint ownership, or usable throughput.
- Resource counts can change during a scan, so an unlabeled exact percentage would be false
  precision.
- Applying runtime services before schema and catalog readiness creates a startup race.
- Automatic adoption by matching names can take ownership of unrelated resources.

The revised design therefore defines a bounded local foundation executor with verified remote-state
reconstruction, two approval checkpoints when foundation creation is necessary, versioned resource
and semantic manifests, canonical command ownership, claim-safe resume, a hash-chained private-Blob
ledger, measured capacity gates, run-level and inventory-level counters, full-subscription object
coverage, delayed runtime activation, and explicit adoption evidence.

## New-subscription acceptance criteria

- [ ] Read-only inspection on a new subscription reports the exact target, missing permissions,
  provider registrations, policy blockers, network paths, and model quota without mutation.
- [ ] A reviewed run provisions the private foundation and application stack without a laptop data
  path, long-lived cloud credential, public data service, or unrelated Terraform destroy.
- [ ] Every required and selected manifest entry, including provider registrations and role
  assignments, reaches its declared postcondition; no optional entry is omitted implicitly.
- [ ] Interrupting the run after every stage and invoking `resume` either continues safely or stops
  with a stable reason; no completed effect is duplicated.
- [ ] A second full run reports no unplanned infrastructure or data mutation.
- [ ] Every database migration head, runtime role, required extension, ontology release digest,
  catalog projection digest, product default, and shadow-only mode passes independent readback.
- [ ] The required nonempty model baseline meets workload-derived minimum capacity, belongs to the
  deployment, uses keyless private access, passes quantitative inference and load thresholds, and
  reports any degraded target.
- [ ] Run-level UI continuously shows completed and total stages and checkpoints, current attempt,
  approval waits, blockers, last progress, and deadline.
- [ ] The initial inventory UI continuously shows completed and total scopes, provider types,
  resources, and pages; completion reaches 100 percent only after active-generation verification.
- [ ] Inventory covers the complete target subscription with no genesis type filter, materializes
  unmapped provider identities, distinguishes relationship limitations from object incompleteness,
  records materialized, reviewed-unavailable, and unclassified relationship candidate counts,
  advances the private-safe Resource Graph change cursor only after canonical observation ingress,
  and retains the prior complete graph on an injected partial failure.
- [ ] Runtime health, canary, event flow, audit closure, and Console projections pass before the run
  becomes `ready`.
- [ ] Logs, artifacts, local journals, summaries, and receipts contain no secrets, DSNs, tokens,
  prompts, provider payloads, or tenant-specific values suitable for source control.

## Related docs

| To learn about | Read |
|----------------|------|
| Concrete Azure resources and bootstrap order | [Deploy and Onboard](deploy-and-onboard.md) |
| CLI installation and low-level commands | [Installable Deployment CLI](installable-deployment-cli.md) |
| Host, transport, and access choices | [Provisioning Execution Profiles](provisioning-execution-profiles.md) |
| Deployment feasibility checks | [Deployment Preflight](deployment-preflight.md) |
| Model capability selection | [LLM Strategy](../architecture/llm-strategy.md) |
| Continuous inventory semantics | [Continuous Operational Instance Graph](../architecture/continuous-operational-instance-graph.md) |
| Cross-stage safety and completeness gates | [Subscription Genesis Assurance](subscription-genesis-assurance.md) |
