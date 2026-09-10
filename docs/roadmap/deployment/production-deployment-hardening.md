---
title: Production deployment hardening
---
# Production deployment hardening

This document defines the production-only deployment controls that tighten FDAI's development
posture without changing its runtime contracts. It covers teardown behavior, durability, private
networking, trusted images, notification destinations, monitoring, and cost ceilings.

> **Scope:** These values are generic environment parameters. A deployment supplies its own
> destinations and values through protected configuration rather than committing tenant data.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Production plan gates and environment knobs | implemented | `infra/production-gates.tf`; `infra/envs/{staging,prod}.tfvars.example`; Terraform configuration tests | Missing signed image, private network, durability, monitoring, or cost inputs block a production plan. Standard profiles permanently delete globally named resources and leave management locks disabled. |
| Credential-free infrastructure and drift guards | implemented | `.github/workflows/ci.yml`; `.github/workflows/infra-drift.yml`; stable deploy identity helper; runner posture script; CI contract tests | Required CI validates every Terraform root without credentials. Protected workflows select one bootstrap-owned UAMI and verify its token `oid`. Subscription role delegation is conditioned to three read roles for service principals. Drift checks cover every state root and reject missing state, unexpected runner storage, or non-local placement. |
| Baseline-free Terraform security scanning | implemented | `.github/workflows/ci.yml`; inline Checkov and Trivy exceptions; focused infrastructure tests | The path-scoped `terraform-validate` job runs pinned Checkov and Trivy after Terraform validation under the single required CI result. Every intentional exception is attached to one resource and cites its compensating control or managed-service constraint. A new detected issue blocks CI until the source fixes it or records a narrow reviewed exception. |
| Bounded split-service prerequisite bootstrap | implemented | `deploy-dev.yml`; `enforce_plan_scope.py`; deployment CLI and workflow contract tests | A request-bound `plan-rca-*` or `apply-rca-*` mode can create only the dedicated Activity Log RCA reader identity and its Monitoring Reader role before the split Core service consumes the platform output. |
| Bounded analyzer Job convergence | implemented | `deploy-dev.yml`; `observability-analyzer-image.tf`; `update_analyzer_job_image.sh`; focused updater, rollback, scope, and workflow tests | The protected plan targets one state-only Terraform updater. Apply changes only the existing analyzer container image to the verified ACR digest, independently reads it back, and rolls back to the prior digest when effect verification fails. The original Container Apps Job resource remains the declarative owner of all Job configuration. |
| Bot-owned protected Core service apply | implemented | `request-protected-operation.yml`; `service-deploy.yml`; Core apply request verifier and focused workflow tests | The dispatcher accepts only an unexpired model-binding plan for Core in development or staging. The service workflow retains the required human Environment approval and repeats the policy check before mutation. |
| Scenario-lab runner tool bootstrap | implemented | `sre-demo-lab.yml`; `test_scenario_lab.py`; CI contract checks; actionlint; downloaded checksum verification | The protected workflow installs checksum-pinned Helm and kubelogin into runner-temporary storage before prerequisite validation. It no longer assumes Helm is preinstalled on a candidate runner, and the installation changes no Azure resource or runner image. |
| Exact-revision protected production apply evidence | in-progress | [Deploy and Onboard](deploy-and-onboard.md#implementation-status) | Code and plan guards exist, but this owner document does not retain one current production apply proving every control together. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-11 | implemented | Folded baseline-free Checkov and Trivy into the path-scoped `terraform-validate` job while reducing the required CI graph from 20 jobs to 13. Scanner versions, reviewed exceptions, the no-baseline policy, and the aggregate `required` result remain unchanged. | `current change`; `.github/workflows/ci.yml`; focused CI workflow contract tests; `check-ci-contracts.py`; `actionlint`. | Retain one green protected-main run of the minimized required graph before treating the new layout as runtime-validated evidence. |
| 2026-09-11 | implemented | Replaced manual shallow-history secret scanning with a checksum-pinned gitleaks 8.24.3 exact-commit scan after depth two still treated its boundary parent as a root commit. Push and pull requests retain the pinned action and history-aware range; manual exact-main validation uses full history only to evaluate `HEAD^..HEAD`, with redaction and the same failure code. | Manual CI run `34521958778`; `current change`; focused CI workflow contract tests; local exact-diff scan found no leaks. | Produce one green manually dispatched required check on the exact protected main SHA. |
| 2026-09-11 | implemented | Included the protected merge parent in manual CI secret-scan checkout after depth one made the merge snapshot appear as a root commit and reported current-tree test fixtures as new additions. Depth two preserves the exact merge diff without reopening repository history. | Manual CI run `34519737666`; `current change`; focused CI workflow contract tests. | Produce one green manually dispatched required check on the exact protected main SHA. |
| 2026-09-11 | implemented | Bounded the manual CI secret scan to the checked-out protected revision after the first dispatch scanned all 8,205 historical commits in the absence of an event comparison range. Push and pull-request runs retain full-history checkout and their normal commit-range scan. | Manual CI run `34517495951`; `current change`; focused CI workflow contract tests. | Produce one green manually dispatched required check on the exact protected main SHA. |
| 2026-09-11 | implemented | Added a manual CI trigger that preserves the complete required-check graph when a protected main push event is unavailable. The trigger validates the checked-out protected main revision and does not accept a caller-selected commit or weaken push and pull-request CI. | `current change`; focused CI workflow contract tests. | Use the manual trigger only to restore an exact protected-main required check, not to bypass a failing check. |
| 2026-09-10 | implemented | Separated the 900-second trace evidence lookback from the 60-second detection bucket so scheduled continuity checks cover the Log Analytics ingestion floor without weakening repeat idempotency or Incident correlation bounds. | `current change`; focused trace source, runner, CLI, and Terraform binding tests; live one-shot evidence required 900 seconds to observe three ingested scenarios. | Deploy the revised analyzer image and retain one scheduled run that observes an ingested scenario without an execution override. |
| 2026-09-10 | implemented | Scoped post-apply convergence for observability requests to the same state-only updater and added an independent analyzer Job image readback. Other applies retain the full-root convergence and inventory image check. | `current change`; focused convergence-routing tests; protected apply `34438595436` completed the updater and image effect but exposed the prior full-root convergence mismatch. | Retain one successful resumed verification or new exact apply receipt. |
| 2026-09-10 | implemented | Replaced direct analyzer-resource targeting with a state-only Terraform updater because the root compute module's prerequisite graph admitted unrelated configured drift. The updater validates both images as digest-pinned ACR references, updates one named container, verifies authoritative readback, and restores the prior digest on failure. | `current change`; focused success, no-op, rejection, effect-failure, and rollback tests; protected run `34435938544` proved direct targeting still admitted unrelated dependencies after state reconciliation and was correctly blocked. | Retain one create-only protected updater plan, exact apply, and successful analyzer tick receipt. |
| 2026-09-10 | implemented | Replaced unsafe legacy target expansion with state-only address reconciliation before the analyzer plan. The migration fails on coexisting old/current addresses, records state digests, and leaves the Terraform target and permitted change set limited to the analyzer Job. | `current change`; focused reconciliation, exact-target, and negative scope tests; protected run `34432091729` proved target expansion admitted unrelated dependencies and was correctly blocked. | Retain one zero-destroy protected analyzer plan and exact apply. |
| 2026-09-10 | implemented | Registered the bounded analyzer mode at the executable plan-scope CLI boundary after the function-level guard was present but the parser rejected the workflow invocation. | `current change`; CLI admission and negative scope contract tests; failed protected run `34430430009`. | Retain one zero-destroy protected analyzer plan and exact apply. |
| 2026-09-10 | implemented | Added the two legacy Container Apps Job addresses that Terraform requires to close recorded state moves during an analyzer-only plan, without adding them to the permitted change set. | `current change`; workflow target and negative scope contract tests; failed protected plan `34428877985` identified the required closure. | Retain one zero-destroy protected analyzer plan and exact apply. |
| 2026-09-10 | implemented | Added an analyzer-only protected plan route that binds the attested runtime image without exposing unrelated platform resources to the plan. | `current change`; bounded plan-scope and workflow contract tests. | Retain one zero-destroy protected plan, exact apply, and successful live analyzer receipt. |
| 2026-09-09 | implemented | Added subscription read access and constrained role delegation required for platform inventory and RCA service principals without granting general role-administration authority. | `current change`; bootstrap Terraform validation and focused identity contract tests. | Retain effective-role and denied-privileged-role observations from an approved foundation apply. |
| 2026-09-08 | implemented | Fixed SRE demo plan preflight after the candidate self-hosted runner lacked Helm. The workflow now downloads Helm v3.18.6 from the official distribution, verifies its pinned SHA-256, installs it only in runner-temporary storage, and validates the binary before request prerequisites. | `current change`; scenario-lab checks passed 7 cases, CI/workflow contracts passed 54 cases, actionlint passed, the pinned public archive matched its recorded checksum, and the complete Operator surface CI command passed 2,827 Console tests plus typecheck and build. | Push only after the shared branch is reconciled and task-owned changes are committed; then observe a new plan-only run without dispatching apply. |
| 2026-09-05 | implemented | Added a Core-only bot-owned service apply request. The request checks exact run and attempt provenance, one unexpired plan artifact, commit and context digests, the digest-pinned Core image, and the model-binding mode before dispatch. The service apply binds the selected Environment and repeats its approval-policy check before mutation. | `current change`; protected request and service workflows, `verify_core_apply_request.py`, and focused verifier and workflow tests | Pass required CI and supply-chain checks for the merged revision, then retain one bot-requested and independently human-approved exact apply receipt. |
| 2026-09-05 | implemented | Preserved the protected-main Environment validator across the exact-revision checkout by copying its reviewed blob into runner-temporary storage, then consolidated the apply-side policy check with request validation to keep the deployment workflow within its 56-step review budget. | `current change`; deploy workflow diet, protected workflow, and CI contract tests | Retain one independently approved exact apply receipt. |
| 2026-09-05 | implemented | Folded the standalone infrastructure PR workflow into the single required CI graph. Terraform security scanning remains path-scoped, and the shared validation job now covers the scenario-lab root. | `current change`; `.github/workflows/ci.yml`; `resolve_test_scope.py`; focused CI scope, security-scan, and scenario-lab contract tests. | Retain the exact protected production and drift evidence listed below. |
| 2026-09-05 | implemented | Serialized the schema-mutating catalog lifecycle regression after service adoption and restored the root-owned T2 lookup index through a forward Core migration. Two non-expiring signing secrets carry resource-local Checkov exceptions because uncoordinated expiry would invalidate in-flight receipts or retained evidence. | `current change`; focused migration contracts, disposable PostgreSQL lifecycle checks, and Checkov with zero failures. | Retain one exact green required CI and supply-chain receipt before deployment. |
| 2026-09-05 | implemented | Added a bot-owned request path for the exact RCA reader apply and verification resume so a solo maintainer can review a bot-requested deployment without self-review. `fdaictl` routes the exclusive RCA operation through this boundary. The request fails before dispatch unless the Environment disables admin bypass, blocks self-review, and declares required reviewers; the apply job binds the selected Environment and repeats that policy check before mutation. Both checks run the validator from a protected `main` checkout so an older plan cannot downgrade the policy. | `current change`; focused deployment CLI, Environment validator, and protected workflow contract tests. | Retain the independently approved exact apply and effect receipts. |
| 2026-09-05 | implemented | Composed the already validated model, notification-receipt, and RCA reader environment transitions in one Core plan. The guard still requires the exact model digest, canonical notification topic, dedicated RCA identity, and no additional runtime drift. | `current change`; focused service plan guard tests, Ruff, and strict mypy. | Generate and apply one protected Core plan carrying all three transitions, then verify the deployed environment independently. |
| 2026-09-05 | implemented | Added the rollback recovery form of the RCA binding transition: when Terraform state already contains exactly one dedicated `-rca-reader` identity but the restored active revision lacks its client-ID environment value, an explicit model-binding plan may complete that one value. The model guard still rejects every unrelated environment change. | `current change`; focused service plan recovery and negative identity tests. | Apply the protected Core plan and verify the deployed identity and environment value independently. |
| 2026-09-05 | implemented | Allowed a protected service apply to use Azure's distinct `latestReadyRevisionName` as its rollback baseline only when the current revision is not healthy and the exact last-ready revision remains provisioned and healthy. The workflow snapshots that revision without activating it, while the separate post-apply freshness sentinel remains the actual pre-apply current revision. Service Terraform retains two inactive revisions, and the plan guard permits only the bounded `1 -> 2` retention increase, so the stuck current revision and last-ready rollback source survive creation of the new revision. | `current change`; focused recovery, workflow, rollback rejection, Terraform, Ruff, and strict mypy checks. | Apply the protected Core plan and retain both health and rollback evidence. |
| 2026-09-04 | implemented | Added an exact-context bounded bootstrap for the RCA reader identity after live planning proved that the split Core service correctly refused a missing platform output and the general platform plan contained unrelated destructive drift. The mode uses the existing request field, so the workflow remains within GitHub's 25-input limit. | `current change`; focused deployment CLI, request validation, plan-scope, and workflow checks passed 105 cases; Ruff and strict mypy passed. | Run the protected plan and exact apply, then consume the resulting output in the split Core service plan. |
| 2026-08-26 | implemented | Replaced the unresolved Functions deployment action with the authenticated Azure CLI `config-zip` path. The development operations gateway keeps remote build enabled and bounds the publish operation to 900 seconds on the managed-identity runner. | `current change`; focused deployment workflow checks passed 93 cases; CI contracts passed. | Retain one protected gateway publish receipt from the exact committed workflow. |
| 2026-08-26 | implemented | Added a read-only runner storage posture check to scheduled infrastructure drift and blocked both configured and manual deallocation of the ephemeral runner profile. | `current change`; runner posture script, drift workflow, lifecycle helper, and 14 focused contract checks. | Complete the blue/green live runner replacement and retain one successful scheduled posture receipt. |
| 2026-08-21 | in-progress | Moved the existing production hardening controls into a focused owner document without changing infrastructure behavior. | `current change`; document-size, translation, route, and link checks. | Retain one exact-revision protected production plan and apply receipt covering every required control. |
| 2026-08-24 | implemented | Removed controllable teardown and exact-name recreation constraints from all standard environments. Terraform now purges deleted Key Vault and Cognitive accounts, permanently deletes Log Analytics workspaces, allows resource-group deletion with remaining resources, and keeps application and state-account management locks disabled. | `current change`; provider features and environment values under `infra/`; `tests/integration/infra/test_key_vault_lifecycle.py` (`2 passed`); Terraform formatting and validation for the shared, scenario-lab, bootstrap, and dev-access roots. | Retain a protected non-production destroy and exact-name recreation receipt. Azure-owned service delays remain outside Terraform control. |
| 2026-08-24 | implemented | Bound the disposable scenario lab to an existing protected holding resource group instead of granting the private runner subscription-wide creation rights. Apply and destroy grant Contributor only on that group for the protected run and then revoke it; Terraform owns and destroys only tagged child resources. The non-overlapping `10.73.0.0/20` VNet and runner-only sensitive password materialization keep the lab private and fully disposable without a persistent secret store. | `current change`; scenario-lab Terraform validation and zero-finding Trivy and Checkov scans; focused scenario and workflow contracts. | Retain the exact protected plan, apply, VPN, approved sweep, and child-resource destroy receipts. |
| 2026-08-24 | implemented | Bound the disposable scenario lab to an existing protected holding resource group instead of granting the private runner subscription-wide creation rights. Apply and destroy grant Contributor only on that group for the protected run and then revoke it; Terraform owns and destroys only tagged child resources. The workflow requires an explicit runner principal and matches it to the active Azure Resource Manager token `oid` before the grant. The non-overlapping `10.73.0.0/20` VNet and runner-only sensitive password materialization keep the lab private and fully disposable without a persistent secret store. | `current change`; scenario-lab Terraform validation and zero-finding Trivy and Checkov scans; focused scenario and workflow contracts. | Retain the exact protected plan, apply, VPN, approved sweep, and child-resource destroy receipts. |
| 2026-08-24 | implemented | Corrected the preceding in-place history expansion by restoring the original scenario-lab transition and recording the runner identity binding separately. The workflow replaces ambiguous Azure CLI account metadata with an explicit scenario runner principal and requires it to match the active Azure Resource Manager token `oid` before temporary Contributor authority can be granted. | `current change`; `.github/workflows/sre-demo-lab.yml`; `tests/integration/infra/test_scenario_lab.py` (`6 passed`); CI contracts and synthetic matching and mismatched token checks. | Retain the exact protected plan, apply, VPN, approved sweep, and child-resource destroy receipts. |
| 2026-08-25 | implemented | Replaced the stale repository-wide Checkov baseline with resource-local exceptions, added Storage access diagnostics, PostgreSQL audit logging, local-user disablement, managed identities, and bounded NSGs, and made every reusable module declare its Terraform compatibility. | `current change`; Terraform validation across all roots; Checkov `88 passed / 0 failed`; Trivy reported no Medium-or-higher issue; TFLint reported no issue. | Retain the exact protected production plan and apply evidence required by the open items below. |

### Remaining work

- [ ] Retain an exact-revision protected production plan and apply receipt proving the unlocked
    teardown profile, private networking, PostgreSQL durability, trusted image digest, notifications,
    monitoring, and the cost budget together, including one blocked negative plan.
- [ ] Retain a protected non-production destroy and exact-name recreation receipt for Key Vault,
    Cognitive Services, Log Analytics, and the resource group.
- [ ] After green required CI, retain zero-unrelated-destroy UAMI role-migration plans and one
    scheduled runner posture receipt that reports the reviewed VM size, local ephemeral placement,
    no managed OS disk, and the exact deploy principal.
- [ ] Retain the bounded RCA reader identity plan, exact apply, platform output, and split Core
    consumption receipt without allowing any unrelated delete or replacement.

## Bounded split-service prerequisite bootstrap

The split Core service reads the RCA reader identity only from the platform Terraform output. It
doesn't infer an Azure resource name or query by display name. If the output isn't present yet, the
service plan stops before materializing its inputs.

Use the deployment CLI's `--deploy-rca-reader-identity` selection with every ordinary application
selection disabled. The CLI seals this as a `plan-rca-*` or `apply-rca-*` request. The workflow
uses `reconcile_rca_bootstrap_state.sh` to reconcile the two known measurement Job addresses from
all legacy count shapes without changing Azure resources. It then targets only
`module.rca_reader_identity` and `azurerm_role_assignment.rca_monitoring_reader`, while the
plan-scope verifier rejects every other changed address. The workflow records state digests, fails
on ambiguous or coexisting addresses, and retains both plan guards.

## Deployer identity

- Use subscription-scoped **Owner** or **Contributor + User Access Administrator** on the target
    resource group to create the executor Managed Identity and its scoped role assignments.
- The bootstrap runner additionally uses subscription `Reader` and a conditional `Role Based Access
    Control Administrator` assignment limited to `Reader`, `Monitoring Reader`, and
    `Cost Management Reader` grants for service principals. Its separate `Cognitive Services
    Contributor` assignment satisfies the model resolver and cannot delegate roles.
- Grant only the subscription-scoped roles matching the executor's **action whitelist**. See
    [Security and Identity](../architecture/security-and-identity.md).
- A purpose-built custom role that packages the deployer permissions remains an open design choice.

## Hardening controls

All controls default to the development posture, so the live environment is unchanged. Tighten
them through environment-specific tfvars. See
[`staging.tfvars.example`](../../../infra/envs/staging.tfvars.example) and
[`prod.tfvars.example`](../../../infra/envs/prod.tfvars.example).

An exact service apply starts only from a healthy active Container Apps revision and retains one
inactive revision for recovery. A plan may harden legacy retention from `0` to `1`, but it cannot
reduce or widen that rollback boundary without a separately reviewed design change.

| Concern | Knob | Prod value |
|---------|------|------------|
| Management locks | `enable_resource_locks`, bootstrap `enable_state_lock` | `false` |
| Key Vault | `kv_purge_protection_enabled`, `kv_soft_delete_retention_days` | `false`, `7` |
| Postgres network | `enable_private_postgres` | `true` |
| Postgres durability | `postgres_backup_retention_days`, `postgres_geo_redundant_backup` | `35`, `true` |
| Postgres availability | `postgres_high_availability_mode` | `ZoneRedundant` |
| HIL delivery | `enable_chatops_hil`, `chatops_webhook_url`, `chatops_webhook_secret` | enabled + CI secrets |
| Email notifications | `enable_email_notifications`, `notification_email_recipients`, `email_data_location` | enabled + recipient group |
| Registry | `acr_sku` | `Premium` |
| Monitoring | `enable_monitoring`, `alert_email`, `alert_webhook_url` | on + destination |
| Cost | `monthly_budget_amount`, `budget_alert_emails` | set |
| Runner storage | bootstrap `runner_vm_size`, ephemeral `ResourceDisk`, `runner_auto_shutdown_time` | reviewed sustained size, local OS, empty shutdown time |

Every Terraform root that owns a resource group disables the provider's populated-group deletion
check. Roots that own Log Analytics permanently delete the workspace, and the shared root purges
Cognitive accounts and Key Vaults on destroy. Standard production, staging, bootstrap, and
development profiles keep `CanNotDelete` management locks off. These settings make a successful
Terraform destroy irreversible and favor immediate recreation over service-side recovery.

Azure-owned constraints still apply. A Key Vault that already has purge protection enabled cannot
be changed in place and remains protected until its retention period expires. Reusing an Event Hubs
namespace name in another subscription can require a four-hour wait. PostgreSQL retains a dropped
server backup for five days, although that backup does not reserve a fresh server name. Existing
soft-deleted resources created before this profile may require an explicit service purge or
permanent-delete operation before their names are released.

## Trusted image source

A tenant without public registry egress builds the runtime image with
`--build-arg BASE_IMAGE_REGISTRY=<internal-mirror>`. Only the registry host moves; the base image
digests stay pinned in the `Dockerfile`, so a mirror can change where the bytes come from but never
which bytes are accepted. `scripts/quality/ci/check-ci-contracts.py` fails the build when a base
image loses either property. The same contract pins security-upgraded runtime libraries that are
newer than vulnerable versions retained in the accepted base image.

## Private data services

`enable_private_postgres` adds a dedicated subnet delegated to PostgreSQL Flexible Server, links a
private DNS zone to the app and ops VNet, disables public access, and removes the
`AllowAllAzureServices` firewall rule. Turning it on for an existing public server may replace that
server, so review the plan and rehearse backup and restore before promotion. The assertions in
`infra/production-gates.tf` block a production plan until the signed image digest, private
networking, durability, alert destination, and cost budget minimums are supplied.

When `enable_private_networking = true` and delegated-subnet PostgreSQL is off, Terraform adds a
`postgresqlServer` private endpoint and links `privatelink.postgres.database.azure.com` to the app
and ops VNets. Both Event Hubs shards share `privatelink.servicebus.windows.net`; each namespace
has its own private endpoint, and public network access is disabled. This lets startup probes run
from the Container Apps subnet or the peered runner without replacing the development database.

## Existing email adoption

An approved out-of-band ACS Email bootstrap can set
`import_existing_email_notifications=true` for its first development convergence plan. The import
blocks adopt the Communication Service, Email Service, Azure-managed domain, association,
notification identity, and deterministic role assignment. Turn the flag off after the plan is
applied; new environments should let Terraform create the stack directly.

## Continuous infrastructure checks

The required [`CI` workflow](../../../.github/workflows/ci.yml) runs Terraform format and validation
for the platform, bootstrap, and scenario-lab roots. Its path-scoped `terraform-validate` job then
runs Trivy and Checkov only when infrastructure or its CI controls change. The scanners use no
repository-wide finding baseline. An intentional exception stays beside its exact resource and
names the production gate, implemented control, provider limitation, or managed-service constraint.
[`infra-drift.yml`](../../../.github/workflows/infra-drift.yml) runs scheduled
`plan -detailed-exitcode` on the runner for the legacy, five independent-service, and bootstrap
state roots. It fails closed on a missing, unreadable, or changed root, so green covers all seven.
Before the bootstrap plan, it independently reads the runner VM and requires the reviewed size,
`Local` `ResourceDisk` placement, and no managed OS disk. A mismatch reports the blue/green
replacement action and fails without changing Azure state. The ephemeral profile stays allocated;
configured auto-shutdown and the lifecycle helper both reject deallocation because it resets the
OS and GitHub registration. Full-scope drift also compares the stable deploy principal's direct
Azure roles with the exact union in bootstrap and platform Terraform state. Missing roles and
state-external grants both fail and retain a sanitized manifest receipt. The same run requires the
disposable scenario state to be absent or empty of managed resource instances and retains a
separate closure receipt.
Monitoring, when enabled, provisions an action group, metric alerts for PostgreSQL, Key Vault,
Event Hubs, and Container Apps, and diagnostic settings to Log Analytics. Alerts are human signals
only, never autonomous actions.

## Related docs

| To learn about | Read |
|----------------|------|
| Day-zero prerequisites and protected runner | [Deploy and Onboard](deploy-and-onboard.md#prerequisites) |
| Policy and connectivity preflight | [Deployment Preflight](deployment-preflight.md) |
| Private network topology | [Network Connectivity Matrix](network-connectivity-matrix.md) |
