---
title: Production deployment hardening
---
# Production deployment hardening

> **Deployment distribution:** The [constitution](../architecture/fdai-constitution.md#article-1-purpose-and-scope) defines three installation paths: the one-command source deployment, the signed offline package, and the [Hub-managed lifecycle](hub-managed-lifecycle.md), which is designed but not yet implemented. Any installation gate in this document that the constitution does not list is superseded and no longer applies.

This document defines the production-only deployment controls that tighten FDAI's development
posture without changing its runtime contracts. It covers teardown behavior, durability, private
networking, trusted images, notification destinations, monitoring, and cost ceilings.

> **Scope:** These values are generic environment parameters. A deployment supplies its own
> destinations and values through protected configuration rather than committing tenant data.
>
> **Execution transport:** Production tenant plans and applies run through `fdaictl provision
> azure` and the manual managed host. GitHub Actions may validate source and publish releases, but
> it is not a production deployment executor.
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
- The application root grants the stable deploy runner `AcrPush` only on the exact registry it
    creates. The managed host uses that role to import signed, digest-bound images and verifies each
    registry digest before application activation.
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

A tenant without public registry egress mirrors the prebuilt release image through an approved
internal registry. The release manifest pins the complete image digest, provenance, SBOM and source
revision. A mirror can change where the bytes come from but never which bytes are accepted. Tenant
provisioning does not invoke Docker, Buildx, ACR Tasks, a remote builder or VM image capture. It
verifies the mirrored digest before planning and reads the running Pod digest back after rollout.

Signed deployment bundles keep regular source files non-executable after extraction. Bootstrap,
policy, migration, and public-path callers launch those authenticated sources only through fixed
trusted interpreters. They never restore execute bits broadly or select an interpreter from an
untrusted ambient path.

The legacy Genesis image-builder and residual recovery paths are being retired. Connected
deployment uses an exact Marketplace host plus a checksum-pinned bootstrap, while artifact-offline
deployment may consume a separately published prebuilt host image. Neither path creates or captures
a host image in the tenant deployment run.

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
As deployment does, the Operator Service plan binds the platform-owned Cost pseudonym key that it
reads from stored platform state. A platform without that key fails the root's evidence with an
explicit reason instead of an unset Terraform variable.
Subscription governance stops the development PostgreSQL server outside working hours, and a
stopped server makes the legacy refresh unreadable. Before the legacy plan, the run reads the server
identity from stored platform state and opens a bounded power window: a Ready server is left
running, and a Stopped server is claimed first, started, and awaited until Ready. After the service
roots, the run stops the server again only when its own claim records that it started it. The
window never changes server configuration, and a server that can't reach Ready fails the evidence
with an explicit reason. The Cost Governance observation export opens the same window, and both
jobs share one concurrency group so neither stops the server under the other.
Accepting reviewed out-of-band changes uses the separate
[`infra-drift-reconcile.yml`](../../../.github/workflows/infra-drift-reconcile.yml) workflow. A
preview run recomputes every root's refresh-only plan and publishes one digest that binds each
changed address, attribute path, move, and output by value hash; values never appear in the log.
An apply run in the protected `drift-reconcile` environment recomputes the same plans, applies the
saved refresh-only plans only when they reproduce the reviewed digest, and then requires every root
to be drift-free. Refresh-only plans record remote objects and outputs in state; they never change
infrastructure, so a reviewer decides separately whether a desired-state change must follow. When the
platform has no Cost pseudonym key binding, the run skips only the Operator Service root and names it
in the summary, because the key prerequisite reads platform outputs that the reconciliation records.
A refresh-only apply also re-evaluates root outputs with the plan's inputs. The run excludes any root
whose plan would turn a deployed output into an empty, null, unknown, or deleted value, and names
those outputs in the summary. For the legacy platform root, both drift workflows reconstruct only
the output-affecting feature inputs from existing non-empty tracked outputs. Model capabilities
come from the exact tracked deployments and preserve the stored resolved-model digest without
depending on a newer repository binding. Missing outputs, partial governed identity sets, or
malformed model deployments stop the run before a plan. The saved refresh-only plan therefore preserves
deploy-owned outputs while recording reviewed provider drift; desired
configuration changes still require a separately reviewed deployment plan. The bounded Cost
pseudonym prerequisite reads the tracked legacy Operator identity directly when the newer
toggle-gated root output is absent, so creating the key does not require a broad platform apply.
Service input materialization loads its standard-library-only approval contract directly from the
exact checked-out source without executing the package's optional runtime imports. It therefore
does not depend on packages that happen to be installed in a particular self-hosted runner
environment.
Outputs for static Key Vault secret names and versionless operator-request seed references derive
from their declared names rather than provider-computed attributes, so a post-reconciliation
refresh plan can prove them without an apply-time unknown.
The installation anchor uses Terraform's plan timestamp with ignored input changes. The first
apply still records one immutable installation time, while later plans can prove the retained
binding and timestamp without an apply-time unknown.
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
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/deployment/production-deployment-hardening.md) |
| Day-zero prerequisites and protected runner | [Deploy and Onboard](deploy-and-onboard.md#prerequisites) |
| Policy and connectivity preflight | [Deployment Preflight](deployment-preflight.md) |
| Private network topology | [Network Connectivity Matrix](network-connectivity-matrix.md) |
