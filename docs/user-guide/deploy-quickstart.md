---
title: Deploy Quickstart
description: Deploy an FDAI Core development environment to your Azure subscription, or use the protected workflow for private and shared environments.
derives_from: [{ source: docs/roadmap/deployment/deploy-and-onboard.md, sha: 9eb4642958691afdbfa71b4b6359c8aa71fac597 }]
---

# Deploy Quickstart

FDAI is provisioned from infrastructure-as-code under `infra/`. Terraform is the
execution engine and the source of truth. We recommend the protected `fdaictl`
workflow for private or shared `dev` and `staging` environments. A contributor
with a clean clone can use the guarded `azd` wrapper to deploy the shared platform
and one independently owned Core service to a public-network development subscription.
Use the noninteractive Genesis router first when the effective network-policy route is unknown.

## Choose a deployment path

| Your environment | Use | Result |
|------------------|-----|--------|
| New private development subscription | After `az login`, run `scripts/deployment/azure/fdai-up.sh` from exact green `main` | Exact target and CI checks, policy routing, approved Foundation and Entra configuration, protected application apply, and a second zero-change plan |
| Personal Azure public-cloud subscription for development | Run `az login`, then `make azd-up` and approve the displayed region | Shared platform, deployment-owned model resources and ACR image, migrated database, authoritative catalogs, Core, canary, and initial inventory verification |
| Private-network, shared, staging, or production environment | Protected `fdaictl` plan and exact apply | Private state, VNet runner, approval policy, all selected independent services, and protected evidence |
| Existing custom Terraform automation | Direct Terraform | Expert integration with deployment-owned state, image, migration, and verification orchestration |

After interactive sign-in, the private development path is one command:

```bash
scripts/deployment/azure/fdai-up.sh
```

The public path is a development bootstrap, not a production shortcut. It keeps autonomous actions
in observation mode and does not deploy Console, Operator API, document services, or the isolated
Executor.

`fdai-up.sh` is the supervised private-subscription entry point. It derives the active target from
`az login`, requires a clean exact `origin/main` revision with green required CI, prepares signed
artifacts, and displays each value-free plan before asking for the exact checkpoint name. One
invocation can continue through runner image, Foundation, enrollment, state handoff, Entra,
repository configuration, protected application apply, and a second zero-change plan. It never
interprets silence as approval. Independent artifact, discovery, provider, policy-probe, Entra,
and image-supply work uses bounded concurrency. Approvals, applies, cleanup, state, and handoffs
remain serial.
The pre-Foundation image plan uses private builder and verifier VMs behind an FQDN-allowlisted
Firewall Basic rather than the Shared-Key-dependent Azure VM Image Builder staging path.

The lower-level Genesis router displays 15 numbered stages, exact progress, skipped-stage counts,
and remaining work. Its `--apply --allow-probe-resources` flags authorize only missing-provider
registration and tagged Key Vault and Storage policy-probe creation with verified cleanup,
including exact deleted-vault purge and absence readback.
Mutation-enabled Genesis also pins and verifies stable Bastion and Microsoft Entra SSH extensions during
toolchain setup; inspection leaves local CLI configuration unchanged. Long commands print a dot to stderr
every 10 seconds while stdout JSON stays unchanged. A `public-dev` result stops after preview for an exact approved plan.
A `private-runner` result can build an exact runner image, apply the Foundation, enroll and attest
the runner through Bastion, and hand state to the private backend when all signed artifact and
private input paths are supplied. Each new effect requires its own current exact approval; the
local approval-file mechanism is limited to a matching manual, single-approver `dev` profile.
Claimed effects resume verification only. Without complete inputs, Genesis reports
`private_foundation_external_artifacts_required`. The lower-level local route stops before
protected application planning. The supervised command composes that boundary but reports
`subscription_ready=false` until complete manifest, model-capacity, and independently verified
active-inventory evidence exists.

If the owner-only `secrets/license-signing-key.pem` matches the packaged public key, the confirmed
public path issues a maximum-30-day token bound to the exact image and deployment and uploads it by
file to a full-token-digest-named Key Vault secret. Token bytes never enter Terraform. Without that
key, Core starts in observation-only Trial and denies acting paths.

## Before you start

- An **Azure subscription** you can create resources in, and the **Azure CLI** (`az`). The protected path also needs
  GitHub CLI (`gh`); direct development needs Azure Developer CLI (`azd`), Terraform, `uv`, `curl`, and `tar`. Mutation-enabled Genesis prepares stable Bastion and Microsoft Entra SSH extensions automatically.
  Run `scripts/deployment/azure/prepare-genesis-access-tools.sh` directly only to prewarm or repair the local CLI.
- For the direct path, use Azure public cloud and an interactive identity that can register resource
  providers, create the platform resources, and assign roles at subscription scope. The script
  temporarily grants `Cognitive Services Contributor` when the exact role is absent and removes
  that grant before success. It also opens one temporary PostgreSQL `/32` rule for schema and
  catalog bootstrap and removes it before Core starts.
- A completed
  [deployment preflight](../roadmap/deployment/deployment-preflight.md). It
  collects quota, permission, connectivity, and rollback blockers before the
  control loop starts.
- Per-environment values in a `*.tfvars` file. For a fresh PostgreSQL server, either provide the administrator password through the protected input or enable Terraform generation without a supplied password. Never commit that file.
- For the interactive direct path, select the intended subscription with Azure CLI. The wrapper
  reads its subscription and tenant from the active `az login` session and displays both before
  continuing. Bootstrap, protected, and non-interactive helpers still use explicit
  `AZURE_SUBSCRIPTION_ID` and `AZURE_TENANT_ID` values and stop before any change on a mismatch.
- Apply `infra/bootstrap` to create the stable deploy UAMI, then publish its
  client and principal IDs as `DEPLOY_RUNNER_CLIENT_ID` and
  `DEPLOY_RUNNER_PRINCIPAL_ID`. Protected workflows select that client ID and
  stop unless the ARM token `oid`, tenant, and subscription all match. The
  permanent VM retains only this UAMI after migration. For a
  closed-network image, use `runner_bootstrap_mode = "offline"` only with an
  exact managed-image or numeric gallery-version ID.
- Migrate deployer roles with the exclusive protected identity plan. It targets only role
  addresses already owned by platform state. A paired storage prerequisite may only disable local
  users while retaining the configured blob and container periods; Console, Entra, database,
  health, and canary work remain outside the operation.
- When you promote a reviewed blue/green candidate, set its existing VM name in
  `runner_vm_name` before importing the VM and network interface into bootstrap
  state. The scheduled posture check compares any model-only OS disk ID with the
  ops resource group's disk inventory. The check reruns when its verifier changes
  and recovers a specialized VM's public SSH input from the protected host before it verifies
  that structured drift actions are empty. It also requires one configured UAMI and no system
  identity. Full-scope runs compare every direct deploy role with the bootstrap and platform
  Terraform states and require the disposable scenario state to be absent or empty. Use manual
  `scope=runner` for the bounded storage and VM identity check;
  scheduled and default runs still verify all roots. Bootstrap preserves the adopted image
  reference until you explicitly review a replacement.
- **Fresh offline subscriptions:** Standalone bootstrap still expects an existing state account
  and application group. The separate genesis root and local coordinator provide exact ARM-only
  image and Foundation planning, approved creation, Bastion enrollment and attestation, and
  private-state migration. Protected application deployment and final readiness remain separate.
  Follow the [offline preparation boundary](../roadmap/deployment/disconnected-deployment.md); a
  prepared artifact, saved plan, or completed Foundation is not installation readiness.
- Attested FDAI service images from `container-supply-chain.yml`. Protected
  service plans verify the exact Core, Operator, Document Ingestion API,
  Document Processing Worker, and Isolated Executor image attestations for the
  selected source revision. Before Terraform initialization or any ACR command,
  a protected platform plan verifies the Core image from the registry-hosted
  GHCR OCI bundle with the exact source revision, SLSA v1 predicate, and signer
  workflow. It has no GitHub API bundle fallback, and its owner-only temporary
  Docker authentication is removed on exit. Binding validates the ACR resource
  ID before import and reports content-free progress for registry lookup,
  import acceptance, and digest readback. Exact apply binds the verified digest
  and never promotes or rebuilds an image.
- Keep the scheduled Inventory Job on the protected platform path. After apply,
  the workflow reads the Job back and stops if its inventory container does not
  use the exact digest-pinned Core image selected by the plan.
- Network access from the deployment host to every private endpoint. In a
  private-only environment, run Terraform from the VNet-connected deployment
  runner rather than an operator workstation. A Premium registry in that
  environment is private too, so build and push the image from the same runner.
- For a protected remote plan, set the non-secret `DEPLOY_PREFLIGHT_INPUT_JSON`
  repository variable with every required live category. A missing profile stops
  the run before Azure login, and a blocked probe logs only sanitized check
  results and detected issues. After Terraform planning, the runner-owned
  `run_live_preflight.py` checks Azure Policy, Compute quota, executor RBAC, and
  value-blind Key Vault secret metadata. An incomplete check stops before the
  plan artifact is stored.
- Retaining a protected plan that renames the Operator API UAMI may include its exact OpenAI User
  role replacement only when the role scope and all non-name UAMI settings are unchanged. Retention
  permits review, not apply; applying the exact plan remains a separate approved operation.
- Deploy the validated five service roots independently from the VNet-connected runner. The
  deployment-gated System Knowledge Service uses its separate
  `system-knowledge-deploy.yml` plan/apply workflow, Blob claim state, Azure Bot, and
  deployment-only Graph installer identity. The Isolated Executor remains the only service that
  may receive an action-specific effect role.
- In a repository with one FDAI maintainer, set the repository variable
  `DEV_DEPLOY_REQUIRED_APPROVALS=0` to run direct `dev` applies without a reviewer.
  Keep the `dev` Environment free of reviewer rules and disable administrator bypass.
  Staging, production, and bot-owned apply paths continue to require one independent reviewer.
- Publish Console and Manual Studio static content through the protected Console
  publisher. The publisher uses the exact apply-synchronized Static Web App
  binding, verifies its Azure resource and hostname identity, and uploads the
  combined static artifact independently. Use the separate catalog refresh to
  run schema migrations, materialize from the exact verified Core image, and
  compare every expected Rule and Ontology projection with PostgreSQL. A
  prebound or prestarted catalog Job is accepted only after image and successful
  execution readback.
- After the Core and Operator services are healthy, run the protected
  `model-settings-projection` workflow for the exact green commit. It refreshes the
  model Settings projection, creates the runtime Settings baseline only when missing,
  and verifies both rows against the target environment. An existing runtime
  projection is preserved.
- To enable the standalone Slack or Teams channel edge, keep provider credentials and principal
  mappings in local-only inputs and Key Vault. Set only the versionless secret-id list in the
  repository variable, then review and apply the platform identity plan before the separate
  Operator service `enable` plan. The edge identity receives no executor role.
- To enable A1 approval, configure the group-connected Teams team, channel, HTTPS Bot activity
  endpoint, and dedicated Bot managed identity together, or configure Slack and its Entra mapping. Keep
  mapping values and signing inputs in Key Vault or local-only deployment inputs. Missing or partial
  channel authority leaves approval unavailable; it never falls back to an Incoming Webhook.
- To enable cross-tenant SharePoint intake, register an application in the Microsoft 365 tenant and
  configure it to trust the Azure ingestion UAMI through a federated identity credential. Grant the
  application only the approved site permission, then set the disabled-by-default
  `sharepoint_connector_*` values in a local `tfvars` file. Bind the exact target tenant,
  application, site, drive, redirect allowlist, collection, access descriptor, audience groups,
  retention policy, and purposes. Don't commit deployment values.
- To provision the bounded OHL scale-out evidence target, enable
  `enable_ohl_scale_out_evidence_target` only in `dev` with private networking and the
  development operations gateway. Supply an exact image version, the protected workflow's SSH
  public-key input, a retry-stable campaign ID, and the human initiator's principal ID. The target
  starts at capacity `1`. Its manual proposal Job publishes one shadow proposal through the normal
  ingress and has no provider-effect authority; protected provider staging may increase capacity
  only to `2` before verified rollback.
- To include AKS runtime topology, supply `inventory_kubernetes_api_server`,
  `inventory_kubernetes_cluster_ref`, `inventory_kubernetes_ca_pem`, and
  `inventory_kubernetes_audience` together. The inventory managed identity receives AKS RBAC
  Reader and acquires a short-lived token at request time. Don't put a Kubernetes bearer token in
  Terraform or environment configuration.
- To observe several AKS clusters, supply `inventory_kubernetes_cluster_bindings_json` instead of
  the legacy four values. Use 1-32 exact cluster ARM ids with credential-free HTTPS endpoints, CA
  PEM, workload-identity audience, and `auth_mode: workload-identity`. The same inventory identity
  receives Reader on each exact cluster scope. Keep the deployment value outside source control.
- To retain rule-watcher snapshots and open draft-only collection reviews, enable
  `enable_rule_catalog_snapshot_storage` and the existing operational ownership
  (`stewardship`) GitOps binding together.
  Supply only the Key Vault secret reference for the GitHub credential. The watcher identity
  receives Blob data access and draft-review authority, but no catalog merge or action authority.
- To enable the operational-history lifecycle, set the non-secret
  `ENABLE_OPERATIONAL_HISTORY` repository variable to `true`, then dispatch the protected
  `history-` plan and apply for the exact attested Core image revision. The scheduled Job remains
  shadow-only under the inventory identity. Enforce and certify require external receipts, and
  only certify can reach the database purge gate. If the exact runner data-owner assignment already
  exists outside Terraform state, the plan adopts it after matching its scope, principal, and role;
  don't delete or recreate it manually. Post-apply checks for this bounded mode ignore unrelated
  Inventory Job image drift. A dedicated A record publishes the evidence private endpoint into the
  Blob DNS zone already linked to the runner. It omits record-set tags that the provider doesn't
  persist.
- To schedule Phase 4 measurement, explicitly enable only the required baseline, pattern-growth, or
  operational-promotion job. All three are disabled by default and share a dedicated measurement
  identity with image-pull, state-secret, and optional model-inference access. They never receive
  the executor identity or a cloud mutation role.
- To enable the Phase 3 scheduler or DB-DR drill, review their separate job identities first. The
  scheduler receives only Event Bus send, image-pull, and state-secret access. DB-DR receives source
  read and PostgreSQL restore/delete only inside its isolated target group. Keep
  `dr_drill_dry_run=true` until the complete configuration plan is reviewed.
- To schedule WARA, configure one umbrella Workload id, its keyed reviewed tags, and either the
  matching hourly or UTC-midnight daily run slot. The Job uses the inventory read identity and can
  send only to the existing Pantheon physical topic. Core T1 RCA uses a different Monitoring Reader
  identity exported by the platform and hydrated into the split service plan. Governed T2 document
  evidence check (`grounding`) additionally requires a separate read-only document DSN secret and exact collection,
  access-reference, and reader-group inputs.

## Provision the minimum inventory

Preview first, and apply only when the plan matches what you expect. The protected
path keeps private plan data on the VNet-connected runner. Specialized exact applies are
re-dispatched by a bot-owned request so the FDAI maintainer remains the distinct GitHub Environment
approver. For Core and Document Ingestion API service plans, the bot validates the exact plan
artifact and derives model, database-host, or SharePoint transition inputs from its sealed
deployment mode.

During a protected move to private networking, FDAI accepts a delete only for a
reviewed retirement or migration that the protected workflow already allows, such
as retiring the broad PostgreSQL Azure-services firewall rule. If the plan shows a
replacement at that address, a drifted version of a reviewed migration, or any
other delete, stop the apply.

When the development operations gateway uses a protected targeted plan, verify that the AI
account and its role collection are both present. This lets network and authorization changes
converge in the same apply instead of leaving a post-apply plan behind. Verify
each service plan changes only its owned state and leaves the other four
service states unchanged.

<!-- fdai:tabs -->

#### fdaictl (protected dev and staging)

```bash
fdaictl deploy plan \
  --profile .fdai/environments/dev.json \
  --repository <owner>/<repository> \
  --commit-sha <git-sha> \
  --run-id <run-id> \
  --output json

fdaictl deploy status \
  --profile .fdai/environments/dev.json \
  --repository <owner>/<repository> \
  --request-id <request-id> \
  --commit-sha <git-sha> \
  --output json

fdaictl deploy apply \
  --profile .fdai/environments/dev.json \
  --repository <owner>/<repository> \
  --plan-id <plan-id> \
  --plan-digest <plan-digest> \
  --plan-expires-at <expires-at> \
  --commit-sha <git-sha> \
  --run-id <run-id> \
  --output json
```

The `--plan-expires-at` value comes from the sanitized `deploy status` plan metadata. The apply
command fails unless the plan has not expired, the repository target and region match the profile,
and the GitHub Environment requires one independent reviewer with self-review and administrator
bypass disabled. Profiles that require more than one approval and all `prod` requests remain
blocked.

#### azd (direct public development Core)

```bash
az login
# Optional when the login can access more than one subscription.
az account set --subscription "<subscription-id>"
# One command reads the active account, asks for the region, previews, and deploys.
make azd-up
```

The wrapper displays the active subscription and tenant, then asks whether to deploy in
`koreacentral`. Type `y` to use that region, enter another Azure region such as `westeurope`, or
press Enter or type `n` to cancel without an Azure mutation. It verifies an alternate region
against the selected subscription. If the Azure Developer CLI has no local session, the same
command starts its tenant-bound sign-in instead of asking you to run another command.

The wrapper creates or selects the `fdai-dev` azd environment, rejects a target mismatch, derives a
stable six-character suffix from the verified subscription for globally scoped Azure names, and
uses an ACR cloud build from the exact clean commit. It stores local Terraform state and generated
inputs under `.fdai/deploy/public-dev-<suffix>/` with private permissions. Set
`FDAI_AZD_CLIENT_IP` to one canonical public IPv4 address when automatic address discovery is not
available. The first platform stage omits every image-backed Job, so a fresh subscription does not
need an existing Core image. After ACR is ready, the wrapper builds the deployment-owned image and
uses its immutable digest for Core and the enabled Jobs.

The preview performs no Azure mutation. If a resource provider is not registered, it stops and
lists the missing namespaces in preview-only mode; only an explicitly confirmed run registers
them. The interactive answer confirms the region, provider registration, and staged deployment in
one command. Terraform still previews each platform change before applying it, disables scheduled
jobs until migrations and Core rollout complete, removes temporary access on failure, and retains
local state for safe reruns. A model that is unavailable or lacks quota remains `hil-only`, which
keeps dependent decisions at human review instead of silently selecting another model.

For non-interactive automation, set both target axes and choose the mode explicitly:
`FDAI_AZD_CONFIRM=0` previews and `FDAI_AZD_CONFIRM=1` deploys. You can set `FDAI_AZURE_REGION` and
`FDAI_AZURE_REGION_SHORT` when the automation does not use the `koreacentral` defaults. A
non-interactive process never infers a deployment target from ambient Azure CLI state.

Bare `azd provision` still manages only the platform root. Use the wrapper when you need a runnable
Core. Use the protected `fdaictl` path when local state, public data-service endpoints, or a
single-user deployment host is not acceptable.

#### terraform (direct expert path)

```bash
az login
export AZURE_SUBSCRIPTION_ID="<expected-subscription-id>"
export AZURE_TENANT_ID="<expected-tenant-id>"
scripts/deployment/azure/verify-azure-context.sh \
   "$AZURE_SUBSCRIPTION_ID" "$AZURE_TENANT_ID"
terraform -chdir=infra init
# copy a template and fill in your values (tfvars are never committed)
cp infra/envs/dev.tfvars.example infra/envs/dev.tfvars
terraform -chdir=infra plan  -var-file=envs/dev.tfvars
terraform -chdir=infra apply -var-file=envs/dev.tfvars
```

<!-- /fdai:tabs -->

## After provisioning

<!-- fdai:steps -->

1. **Verify the inventory.** Check that the resources exist and that the executor
   identity holds only its scoped, minimum permissions (least privilege). Then
   confirm each of these:
   - Subscription Event Grid delivery uses the inventory managed identity to
     reach `fdai.inventory.raw` on the operational Event Hubs shard.
   - The primary shard stays inside its ten-entity Standard limit, and Huginn
     projects a test resource change.
   - The Inventory Job wakes every minute, PostgreSQL keeps healthy full scans
     at six hours, an observed resource change reconciles early, and a failed or
     deadline-exceeded attempt retries under bounded backoff without giving the
     core a job-start role.
   - The Provider Schema Job completes its daily run, retains a durable generation digest in
     PostgreSQL, and sends material changes through Heimdall as shadow Drift. It doesn't update
     the ontology, rules, or policies automatically.
   - When rule collection delivery is enabled, the Rule Watcher Job mirrors content-addressed
     snapshots to its private Blob container and opens at most one draft review for unchanged
     content. Re-verification time doesn't change package identity, and the job never merges or
     activates catalog content.
   - When AKS topology is configured, the inventory identity has only AKS RBAC Reader, the API
     endpoint passes CA verification, and a complete generation includes UID-grounded Kubernetes
     resources without a static token secret.
   - With private networking on, PostgreSQL and both Event Hubs shards resolve to
     private addresses from the runtime subnet or a peered runner, pass their TLS
     checks, and keep Event Hubs public access disabled.
2. **Verify runtime health and identity.** Confirm all five service revisions
  are healthy, all 15 agents report through the Core health snapshot, and the
  first canary publisher Job finished. Then check these boundaries:
   - **Operator API**: browser Entra App Roles work, and its read and command
     credentials stay separate from Thor's executor managed identity.
   - **Operator channel edge**: when enabled, the latest edge revision uses the attested Operator
     image and exactly one non-executor identity, `/health/ready` succeeds over HTTPS, and the
     primary Operator revision remains healthy. A disable or failed first enable must prove the
     public edge resource is absent before recovery is complete.
   - **Document services**: the Document Ingestion API accepts authenticated
     upload lifecycle requests, while the Document Processing Worker alone owns
     durable inspection, extraction, indexing, claims, and reconciliation.
   - **Ownership handover lifecycle**: Core records a current and last-success operational ownership (`stewardship`)
     identity-health snapshot, emits content-free goal and candidate events at the
     configured cadence, and consumes signed merge evidence without receiving IAM
     or executor authority. Operator shows only revision-matched unexpired health.
   - **Isolated Executor**: its internal `/live` and `/ready` probes pass, its
     latest revision is active, and its dedicated identity has image pull,
     command receive, receipt or DLQ send, state-secret read, and only the
     explicitly approved action-specific effect roles. Core and Operator have
     no managed-resource effect role.
   - **Email notifications**: an incident-open message arrives as multipart HTML and plain text.
     When the Console is enabled, its detail link uses the Static Web App origin and Settings >
     Integrations shows the same renderer with synthetic placeholders.
   - **Document OCR**: choose `use_local_retain` for local Korean and English
     OCR without deleting Azure, `use_azure_provision` to plan the private
     Document Intelligence account, or `deprovision_use_local` to select local
     OCR before removal. The ingestion identity has `Cognitive Services User`
     only on the configured Document Intelligence resource. Plan is the default,
     and apply still requires separate approval.
   - **Case history**: only its dedicated managed identity has Blob data access,
     its private network rules retain Defender scanner private-link access, the
     executor has no case-history Blob role, and
     `FDAI_CASE_HISTORY_RETENTION_TICK_SECONDS` matches the approved deletion
     cadence.
   - **Forecast learning**: its opt-in Job publishes raw ticks only. Each
     `FDAI_FORECAST_TARGETS_JSON` entry names a governed `target_kind`, and Core rejects settings that
     weaken the repository policy.
   - **Analyzer tick**: when `FDAI_INVENTORY_DSN` is configured, the Job merges
     explicit targets with only the supported resources in the durable inventory
     projection and reports the configured discovery bound. Unsupported resource
     types stay omitted, and a fully resolved empty target set exits as a clean no-op.
    For a protected deployment, set the `TRACE_TOPOLOGIES_JSON` repository variable;
    the workflow passes it to the Job as `FDAI_TRACE_TOPOLOGIES_JSON`. The same Job and
    reader identity query bounded workspace-based Application Insights evidence. A complete trace
     reports no detected issue, while a missing or disconnected hop reports one in
     observation mode.
     An empty value disables only the continuity check.
   - **OHL scale-out evidence**: when enabled, start the manual proposal Job and confirm exactly
     one shadow proposal reaches the normal ingress with the configured campaign and initiator.
     Its identity has only image pull and primary Event Hubs send permissions, with no
     provider-effect authority.
3. **Verify the development operations gateway.** It is a development tool: it
   terminates a public inbound endpoint behind Easy Auth, and Terraform refuses
   to plan it outside `env=dev`. Leave it off on a closed network. If you
   enabled it, confirm:
   - The protected source archive was deployed after the Terraform apply, and the
     current remote-build deployment succeeded.
   - Both Function triggers are registered, host and idempotency storage use the
     reader managed identity, and registered network reads succeed.
   - With the executor principal, plan one bounded change, submit it with the
     returned one-time receipt, replay it to prove no second ARM call happens, and
     poll the idempotency key while ARM reports `submitted`.
4. **Onboard one bounded scope.** Start with a single resource-group-sized scope
   and name its owner.
5. **Watch it in observation mode.** Let FDAI judge and audit without changing
   anything, and review the actions it would have taken.
6. **Promote one action.** Turn on enforcement only for an action that clears its
   promotion gate, and leave the rest in observation mode.

The [Get started](get-started.md) guide walks through this first safe rollout in
depth, and [deploy and onboard](../roadmap/deployment/deploy-and-onboard.md) is
the full deployment reference.

## Related

<!-- fdai:cards -->

- [Preflight](../roadmap/deployment/deployment-preflight.md) - Resolve blockers before you provision.
- [Deploy and onboard](../roadmap/deployment/deploy-and-onboard.md) - The full deployment reference and Azure inventory.
- [Local Development Quickstart](local-development-quickstart.md) - Configure Docker and the local Console stack.
- [Get started](get-started.md) - Orientation and your first safe rollout.
- [Operator console](../roadmap/interfaces/operator-console.md) - Run and query FDAI once it is live.
