---
title: Deploy Quickstart
description: Provision FDAI's minimum Azure inventory with the protected fdaictl workflow, or preview the infrastructure-only development path with azd.
derives_from: [{ source: docs/roadmap/deployment/deploy-and-onboard.md, sha: 2556ece21373ba60309629ec1b86ab1b49020d6e }]
---

# Deploy Quickstart

FDAI is provisioned from infrastructure-as-code under `infra/`. Terraform is the
execution engine and the source of truth. We recommend the protected `fdaictl`
workflow for private `dev` and `staging` environments. The `azd` wrapper is an
infrastructure-only path for direct public-network development, and direct
Terraform remains an expert path.

## Before you start

- An **Azure subscription** you can create resources in, and the **Azure CLI**
  (`az`). The protected path also needs the GitHub CLI (`gh`); the direct
  development path needs the Azure Developer CLI (`azd`).
- A completed
  [deployment preflight](../roadmap/deployment/deployment-preflight.md). It
  collects quota, permission, connectivity, and rollback blockers before the
  control loop starts.
- Per-environment values in a `*.tfvars` file. Never commit that file.
- The approved target exported as `AZURE_SUBSCRIPTION_ID` and
  `AZURE_TENANT_ID`. Bootstrap and turnkey helpers stop before making any change
  if the active identity or the selected `azd` environment does not match that
  exact pair.
- Apply `infra/bootstrap` to create the stable deploy UAMI, then publish its
  client and principal IDs as `DEPLOY_RUNNER_CLIENT_ID` and
  `DEPLOY_RUNNER_PRINCIPAL_ID`. Protected workflows select that client ID and
  stop unless the ARM token `oid`, tenant, and subscription all match.
- Attested FDAI service images from `container-supply-chain.yml`. Protected
  service plans verify the exact Core, Operator, Document Ingestion API,
  Document Processing Worker, and Isolated Executor image attestations for the
  selected source revision. Exact apply binds those digests and never promotes
  or rebuilds an image.
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
- Deploy the five service roots independently from the VNet-connected runner.
  Each service owns its image, Terraform state, migration branch, health
  probes, and workload identity. The Isolated Executor is the only service that
  may receive an action-specific effect role.
- Publish Console and Manual Studio static content through the protected Console
  publisher. The publisher uses the exact apply-synchronized Static Web App
  binding, verifies its Azure resource and hostname identity, and uploads the
  combined static artifact independently. Use the separate catalog refresh to
  run schema migrations, materialize from the exact verified Core image, and
  compare every expected Rule and Ontology projection with PostgreSQL. A
  prebound or prestarted catalog Job is accepted only after image and successful
  execution readback.
- To enable the standalone Slack or Teams channel edge, keep provider credentials and principal
  mappings in local-only inputs and Key Vault. Set only the versionless secret-id list in the
  repository variable, then review and apply the platform identity plan before the separate
  Operator service `enable` plan. The edge identity receives no executor role.
- To enable A1 approval, configure the group-connected Teams team, channel, and HTTPS Bot activity
  endpoint together, or configure the Slack workspace and user-to-Entra mapping together. Keep
  mapping values and signing inputs in Key Vault or local-only deployment inputs. Missing or partial
  channel authority leaves approval unavailable; it never falls back to an Incoming Webhook.
- To enable cross-tenant SharePoint intake, keep the SharePoint and Power Platform connection in the
  Microsoft 365 tenant and set the disabled-by-default `power_platform_*` policy values in a local
  `tfvars` file. Bind the exact source tenant, approved OAuth clients, FDAI API audience, collection,
  access descriptor, audience groups, retention policy, and purposes. Don't commit deployment
  values or provider credentials.
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
- To retain rule-watcher snapshots and open draft-only collection reviews, enable
  `enable_rule_catalog_snapshot_storage` and the existing operational ownership
  (`stewardship`) GitOps binding together.
  Supply only the Key Vault secret reference for the GitHub credential. The watcher identity
  receives Blob data access and draft-review authority, but no catalog merge or action authority.
- To enable the operational-history lifecycle, set the non-secret
  `ENABLE_OPERATIONAL_HISTORY` repository variable to `true`, then dispatch the protected
  `history-` plan and apply for the exact attested Core image revision. The scheduled Job remains
  shadow-only under the inventory identity. Enforce and certify require external receipts, and
  only certify can reach the database purge gate.
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
  grounding additionally requires a separate read-only document DSN secret and exact collection,
  access-reference, and reader-group inputs.

## Provision the minimum inventory

Preview first, and apply only when the plan matches what you expect. The protected
path keeps private plan data on the VNet-connected runner and requires the
configured GitHub Environment approval before exact apply.

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

#### azd (direct development infrastructure)

```bash
azd auth login
azd env new fdai-dev
export AZURE_SUBSCRIPTION_ID="<expected-subscription-id>"
export AZURE_TENANT_ID="<expected-tenant-id>"
# safe preview - runs `azd provision --preview`, applies nothing
scripts/deployment/azure/azd-up.sh
# provision infrastructure for real - runtime images use protected service workflows
FDAI_AZD_CONFIRM=1 scripts/deployment/azure/azd-up.sh
```

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
   - **Forecast learning**: its opt-in Job publishes raw ticks only, and the core
     has the reviewed `FDAI_FORECAST_TARGETS_JSON` document.
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
- [Get started](get-started.md) - Orientation and your first safe rollout.
- [Operator console](../roadmap/interfaces/operator-console.md) - Run and query FDAI once it is live.
