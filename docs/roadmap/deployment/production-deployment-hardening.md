---
title: Production deployment hardening
---
# Production deployment hardening

This document defines the production-only deployment controls that tighten FDAI's development
posture without changing its runtime contracts. It covers resource locks, durability, private
networking, trusted images, notification destinations, monitoring, and cost ceilings.

> **Scope:** These values are generic environment parameters. A deployment supplies its own
> destinations and values through protected configuration rather than committing tenant data.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Production plan gates and environment knobs | implemented | `infra/production-gates.tf`; `infra/envs/{staging,prod}.tfvars.example`; Terraform configuration tests | Missing signed image, private network, durability, monitoring, or cost inputs block a production plan. |
| Credential-free infrastructure and drift guards | implemented | `.github/workflows/infra-lint.yml`; `.github/workflows/infra-drift.yml`; CI contract tests | The checks cover all declared state roots and fail closed on a missing, unreadable, or changed root. |
| Exact-revision protected production apply evidence | in-progress | [Deploy and Onboard](deploy-and-onboard.md#implementation-status) | Code and plan guards exist, but this owner document does not retain one current production apply proving every control together. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-21 | in-progress | Moved the existing production hardening controls into a focused owner document without changing infrastructure behavior. | `current change`; document-size, translation, route, and link checks. | Retain one exact-revision protected production plan and apply receipt covering every required control. |

### Remaining work

- [ ] Retain an exact-revision protected production plan and apply receipt proving resource locks,
  private networking, PostgreSQL durability, trusted image digest, notifications, monitoring, and
  the cost budget together, including one blocked negative plan.

## Deployer identity

- Use subscription-scoped **Owner** or **Contributor + User Access Administrator** on the target
    resource group to create the executor Managed Identity and its scoped role assignments.
- Grant only the subscription-scoped roles matching the executor's **action whitelist**. See
    [Security and Identity](../architecture/security-and-identity.md).
- A purpose-built custom role that packages the deployer permissions remains an open design choice.

## Hardening controls

All controls default to the development posture, so the live environment is unchanged. Tighten
them through environment-specific tfvars. See
[`staging.tfvars.example`](../../../infra/envs/staging.tfvars.example) and
[`prod.tfvars.example`](../../../infra/envs/prod.tfvars.example).

| Concern | Knob | Prod value |
|---------|------|------------|
| Delete protection | `enable_resource_locks`, bootstrap `enable_state_lock` | `true` |
| Key Vault | `kv_purge_protection_enabled`, `kv_soft_delete_retention_days` | `true`, `90` |
| Postgres network | `enable_private_postgres` | `true` |
| Postgres durability | `postgres_backup_retention_days`, `postgres_geo_redundant_backup` | `35`, `true` |
| Postgres availability | `postgres_high_availability_mode` | `ZoneRedundant` |
| HIL delivery | `enable_chatops_hil`, `chatops_webhook_url`, `chatops_webhook_secret` | enabled + CI secrets |
| Email notifications | `enable_email_notifications`, `notification_email_recipients`, `email_data_location` | enabled + recipient group |
| Registry | `acr_sku` | `Premium` |
| Monitoring | `enable_monitoring`, `alert_email`, `alert_webhook_url` | on + destination |
| Cost | `monthly_budget_amount`, `budget_alert_emails`, bootstrap `runner_auto_shutdown_time` | set |

## Trusted image source

A tenant without public registry egress builds the runtime image with
`--build-arg BASE_IMAGE_REGISTRY=<internal-mirror>`. Only the registry host moves; the base image
digests stay pinned in the `Dockerfile`, so a mirror can change where the bytes come from but never
which bytes are accepted. `scripts/quality/ci/check-ci-contracts.py` fails the build when a base
image loses either property.

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

CI adds two credential-free guards: [`infra-lint.yml`](../../../.github/workflows/infra-lint.yml)
runs format, validation, tfsec, and Checkov on every infrastructure PR.
[`infra-drift.yml`](../../../.github/workflows/infra-drift.yml) runs scheduled
`plan -detailed-exitcode` on the runner for the legacy, five independent-service, and bootstrap
state roots. It fails closed on a missing, unreadable, or changed root, so green covers all seven.
Monitoring, when enabled, provisions an action group, metric alerts for PostgreSQL, Key Vault,
Event Hubs, and Container Apps, and diagnostic settings to Log Analytics. Alerts are human signals
only, never autonomous actions.

## Related docs

| To learn about | Read |
|----------------|------|
| Day-zero prerequisites and protected runner | [Deploy and Onboard](deploy-and-onboard.md#prerequisites) |
| Policy and connectivity preflight | [Deployment Preflight](deployment-preflight.md) |
| Private network topology | [Network Connectivity Matrix](network-connectivity-matrix.md) |
