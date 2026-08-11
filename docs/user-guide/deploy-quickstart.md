---
title: Deploy Quickstart
description: Provision the FDAI minimum-set inventory on Azure - two equivalent paths (azd turnkey or Terraform direct), preview first, apply only when the plan looks right.
derives_from: [{ source: docs/roadmap/deployment/deploy-and-onboard.md, sha: 4922d670e12ca7dee495db5b597e4e0cb5d0f9a8 }]
---

# Deploy Quickstart

FDAI is provisioned from infrastructure-as-code under `infra/`. Terraform is the
execution engine and the source of truth. Two paths stand up the same minimum
Azure inventory: a turnkey `azd` wrapper, or Terraform on its own. Both preview
first, so you can review the plan before you run the separate apply step.

## Before you start

- An **Azure subscription** you can create resources in, and the **Azure CLI**
  (`az`). The turnkey path also needs the **Azure Developer CLI** (`azd`).
- A completed
  [deployment preflight](../roadmap/deployment/deployment-preflight.md). It
  collects quota, permission, connectivity, and rollback blockers before the
  control loop starts.
- Per-environment values in a `*.tfvars` file. Never commit that file.
- The approved target exported as `AZURE_SUBSCRIPTION_ID` and
  `AZURE_TENANT_ID`. Bootstrap and turnkey helpers stop before making any change
  if the active identity or the selected `azd` environment does not match that
  exact pair.
- An attested FDAI runtime image from `container-supply-chain.yml`. An Executor
  plan verifies the GHCR attestation for `runtime_image_revision` and binds the
  identical digest already present in ACR. Use `promote_runtime_image=true` only
  to import that verified digest before planning; exact apply never promotes or
  rebuilds an image.
- Network access from the deployment host to every private endpoint. In a
  private-only environment, run Terraform from the VNet-connected deployment
  runner rather than an operator workstation. A Premium registry in that
  environment is private too, so build and push the image from the same runner.
- For a protected remote plan, set the non-secret `DEPLOY_PREFLIGHT_INPUT_JSON`
  repository variable with every required live category. A missing profile stops
  the run before Azure login, and a blocked probe logs only sanitized check
  results and detected issues.
- To preview the internal Isolated Executor, select `deploy_isolated_executor`
  in the private-runner workflow. It remains plan-only until you separately
  approve apply, and the shadow identity receives no action-specific effect role.

## Provision the minimum inventory

Preview first, and apply only when the plan matches what you expect. Both paths
provision the same `infra/` Terraform, so pick whichever fits your workflow.

During a protected move to private networking, the only delete FDAI accepts is
retiring the broad PostgreSQL Azure-services firewall rule. If the plan shows a
replacement at that address, or any other delete, stop the apply.

When the development operations gateway uses a protected targeted plan, verify that the AI
account and its role collection are both present. This lets network and authorization changes
converge in the same apply instead of leaving a post-apply plan behind. When you also select
`deploy_isolated_executor`, verify that the isolated Executor module and its dependency graph
appear in that targeted plan.

<!-- fdai:tabs -->

#### azd (turnkey)

```bash
azd auth login
azd env new fdai-dev
export AZURE_SUBSCRIPTION_ID="<expected-subscription-id>"
export AZURE_TENANT_ID="<expected-tenant-id>"
# safe preview - runs `azd provision --preview`, applies nothing
scripts/deployment/azure/azd-up.sh
# provision for real - second gate prevents an accidental apply
FDAI_AZD_CONFIRM=1 scripts/deployment/azure/azd-up.sh
```

#### terraform (direct)

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
     reach `aw.inventory.raw` on the operational Event Hubs shard.
   - The primary shard stays inside its ten-entity Standard limit, and Huginn
     projects a test resource change.
   - The Inventory Job wakes every 10 minutes, PostgreSQL keeps healthy full
     scans at six hours, and a failed or abandoned attempt retries on the next
     tick without giving the core a job-start role.
   - With private networking on, PostgreSQL and both Event Hubs shards resolve to
     private addresses from the runtime subnet or a peered runner, pass their TLS
     checks, and keep Event Hubs public access disabled.
2. **Verify runtime health and identity.** Confirm the internal core probes are
   healthy, all 15 agents report through the health snapshot, and the first canary
   publisher Job finished. Then check the features you enabled:
   - **Operator API**: browser Entra App Roles work, and its read and command
     credentials stay separate from Thor's executor managed identity.
   - **Isolated Executor**: when enabled, its internal `/live` and `/ready`
     probes pass, its latest revision is active, and its dedicated identity has
     only image pull, command receive, receipt or DLQ send, and state-secret read.
     It has no action-specific effect role before authority cutover.
   - **Email notifications**: an incident-open message arrives as multipart HTML and plain text.
     When the Console is enabled, its detail link uses the Static Web App origin and Settings >
     Integrations shows the same renderer with synthetic placeholders.
   - **Document OCR**: the ingestion identity has `Cognitive Services User` only
     on the configured Document Intelligence resource.
   - **Case history**: only its dedicated managed identity has Blob data access,
     its private network rules retain Defender scanner private-link access, the
     executor has no case-history Blob role, and
     `FDAI_CASE_HISTORY_RETENTION_TICK_SECONDS` matches the approved deletion
     cadence.
   - **Forecast learning**: its opt-in Job publishes raw ticks only, and the core
     has the reviewed `FDAI_FORECAST_TARGETS_JSON` document.
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
