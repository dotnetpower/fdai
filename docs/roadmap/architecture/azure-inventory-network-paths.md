---
title: Restricted-network Azure inventory
---
# Restricted-network Azure inventory

This document defines how Azure inventory discovery remains explicit and fail-closed when an NSG,
route, DNS policy, or private endpoint limits management-plane access. It refines the provider-
neutral [Inventory contract](csp-neutrality.md#5-inventory-contract---resource-graph) without
changing the wire contract or granting discovery any action authority.

> **Scope:** These paths apply to the implemented Azure adapter. A future provider supplies its own
> contract-parity transport and evidence without changing core behavior.

## Design at a glance

An NSG-locked subnet should not turn an unreachable discovery source into an empty inventory. FDAI
treats network reachability, identity, collection, and projection as separate stages and records
which stage failed. An empty successful snapshot means "no resources in scope"; a blocked
endpoint, token failure, incomplete page set, or unavailable collector means "inventory
unavailable" and retains the last complete snapshot.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Restricted-network discovery and ordered source fallback | in-progress | Azure inventory adapters under `delivery/azure/`; deployment preflight and connectivity contracts | The bounded adapters and failure classes exist. This document does not retain one exact-revision protected deployment proving every fallback rung. |
| Isolated fallback certification | implemented | `inventory_network_certification.py`; `infra/inventory-network-certification/`; exact create, migration-recovery, and cleanup plan gates; focused tests | The task-owned sandbox can prove token, DNS, TLS, bounded ARG, private projection, one ARG-to-ARM fallback, active-generation retention, recovery, independent private receipt readback, and exact cleanup without changing the existing development network. Its migration Job advances both legacy and service-owned schema branches before collection. A governed run remains open. |
| Snapshot authority and stale-state handling | implemented | Inventory sync, projection, and reconciliation tests cited by [CSP-Neutrality Contracts](csp-neutrality.md#implementation-status) | Partial collection cannot replace the last complete promoted generation or authorize an absence claim. |
| Subnet-specific network controls | implemented | `infra/modules/network/main.tf`; `infra/bootstrap/main.tf`; focused network hardening tests | VM-bearing subnets deny Internet inbound through explicit NSGs. Azure-managed delegated and private-endpoint subnets retain their service-owned network-policy contracts. |
| AKS fleet observation binding | implemented | `infra/main.tf`; `infra/scenario-lab/aks.tf`; Container Apps Inventory Job; focused AKS identity and scenario tests | Exact workload-identity bindings remain read-only. The disposable scenario may expose one Entra and Azure RBAC protected public API with local accounts disabled; its Trivy and Checkov public-access suppressions remain resource-local. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-28 | implemented | Made the certification migration Job advance the legacy schema and every service-owned migration branch from the exact image before inventory collection. The Core image carries the migration graph only as deployment support, and a one-address recovery plan gate limits adoption by the retained sandbox. | `current change`; focused migration-runner and plan-gate tests; strict mypy; Terraform validation. | Publish the exact image, apply the migration-Job-only recovery plan, rerun migration, and start a new campaign execution. |
| 2026-09-28 | in-progress | Two protected-image campaign executions stopped with sanitized `UndefinedColumn` failures for both ARG and ARM after the legacy-only migration Job reported success. A read-only private diagnostic proved the shared schema gap without another provider read or campaign retry. | Private terminal execution, migration, and diagnostic claims; sanitized failure-type readback. | Preserve both executions and repair migration parity before a new execution. |
| 2026-09-27 | implemented | Replaced a generic TLS ClientHello on PostgreSQL port 5432 with a real `sslmode=require` psycopg connection and authoritative `pg_stat_ssl` readback. | `current change`; focused negotiated-TLS regression and strict mypy. | Publish the fixed image and use a new campaign execution. |
| 2026-09-27 | in-progress | The second combined execution passed management-plane TLS but PostgreSQL reset the generic ClientHello because its wire protocol requires SSLRequest negotiation. No inventory source or semantic write ran. | Exact execution and sanitized traceback. | Keep that execution terminal and run a new execution with negotiated PostgreSQL TLS. |
| 2026-09-27 | implemented | Preserved a successful TLS reachability result when only the best-effort SSL shutdown exceeds its close timeout. DNS, connect, handshake, hostname, and cipher failures still fail the campaign. | `current change`; focused asynchronous close regression and transport checks. | Publish the fixed image and use a new campaign execution. |
| 2026-09-27 | in-progress | The first combined campaign stopped after a successful management-plane TLS handshake because stream shutdown timed out. No inventory source or semantic write ran. | Exact campaign execution and sanitized traceback. | Keep that execution terminal and run a new execution only after the close-boundary fix is merged. |
| 2026-09-27 | implemented | Preserved the Azure Policy-managed Storage `private_link_access` child while retaining Terraform ownership of default-deny and trusted-service rules. | `current change`; authoritative final-plan field readback and Terraform checks. | Merge and rerun plan-only convergence. |
| 2026-09-27 | implemented | Added the exact Azure PostgreSQL extension allowlist and a single-address recovery plan gate after migration reached the database but `vector` creation was denied. | `current change`; focused plan-gate tests and Terraform validation. | Merge and apply only the extension configuration before rerunning migration. |
| 2026-09-27 | in-progress | The second migration execution passed DSN parsing and private connectivity but stopped before schema creation because `vector` was not allowlisted. The candidate migration image remains attached for review and the campaign Job did not start. | Exact migration execution and sanitized database error. | Apply the bounded extension recovery plan, verify zero change, then rerun migration. |
| 2026-09-27 | implemented | Aligned the certification root with authoritative Azure readback without another apply: explicit Consumption workload profile and delegation actions, retained PostgreSQL zone, and lifecycle preservation for policy-managed tags and service endpoints. | `current change`; post-apply drift field readback and focused Terraform checks. | Merge and run plan-only verification against the retained recovery state. |
| 2026-09-27 | in-progress | The recovery create plan applied successfully and produced 37 Terraform state addresses and 13 tagged Azure resources, but its first post-apply plan found six provider or policy normalization updates. No campaign Job was started. | Managed-host apply claim, state, Azure readback, and post-apply plan log. | Keep the sandbox intact until the corrected source yields a zero-change plan. |
| 2026-09-27 | implemented | Recovered the sandbox design without touching shared DNS: PostgreSQL uses a request-unique private zone, Blob connects to the exact private endpoint IP while validating the original hostname through TLS SNI and HTTP Host, and campaign Reader is limited to the application resource group. | `current change`; focused transport tests; Terraform validation; Trivy and Checkov reported 0 failed findings. | Merge and run a new exact request; do not reuse the failed plan. |
| 2026-09-27 | in-progress | The first governed create plan stopped after partial effects when shared private DNS zone names collided and the subscription-scoped Reader assignment was denied. The immutable claim, plan, logs, 24 Terraform state addresses, and 7 tagged Azure resources were preserved. | Private apply claim and plan digest `90e269aac3fb606fef0e7a9d9b6fa2d43f6eabdbfbf0a858cc3cc620956f79d8`; authoritative resource and state readback. | Preserve this failed sandbox for recovery review and use a new request for certification. |
| 2026-09-27 | implemented | Bound sandbox creation to the existing development application resource group because its managed-host UAMI already has exact Contributor and role-assignment authority there. The plan no longer creates, tags, or deletes a resource group. | `current change`; Terraform target fence and exact create/delete address gate. | Run the governed campaign and verify only task-tagged sandbox resources are removed. |
| 2026-09-27 | implemented | Hardened the isolated certification sandbox with infrastructure-encrypted private receipt storage, default-deny network rules, Blob diagnostics, PostgreSQL audit settings, and an NSG on every task-owned subnet. | `current change`; Trivy 0 findings above Low; Checkov 0 failed checks; Terraform validation and exact plan-gate tests passed. | Run the governed exact-revision campaign and verify task-only cleanup. |
| 2026-09-17 | implemented | Extended the disposable scenario's resource-local public-access exceptions to Checkov without broadening the API, identity, or authorization boundary. | `current change`; `infra/scenario-lab/aks.tf`; focused Trivy and Checkov scans and scenario-lab tests. | Retain protected recreation and FDAI Pod-inventory readback. |
| 2026-09-17 | implemented | Added the disposable scenario's authenticated public AKS API path and scoped both public-access scanner suppressions to that one resource. | `current change`; `infra/scenario-lab/aks.tf`; focused Trivy scan and scenario-lab tests. | Retain protected recreation and FDAI Pod-inventory readback. |
| 2026-09-10 | implemented | Added mutually exclusive legacy and fleet AKS observation bindings with exact per-cluster Reader assignments. | `current change`; Terraform formatting and focused identity tests. | Retain protected deployment evidence separately. |
| 2026-08-21 | in-progress | Moved the existing restricted-network inventory design into a focused owner document without changing runtime behavior or authority. | `current change`; document-size, translation, route, and link checks. | Retain exact-revision protected evidence for the effective network path and at least one failover and recovery transition. |
| 2026-08-25 | implemented | Added explicit NSG protection to the OHL evidence VM subnet and verified the existing deploy-runner subnet association, while preserving Azure-managed delegated subnet constraints. | `current change`; `tests/integration/infra/test_network_hardening.py`; `tests/integration/infra/test_bootstrap_network_hardening.py`; Checkov and Trivy reported no active finding above Low. | Retain deployed evidence that the effective NSG and route policy still permits the required bounded management path. |
| 2026-08-24 | implemented | Serialized the two directional gateway-transit peerings used by the disposable scenario path. | Failed protected applies `32773217323` and `32774040807`; asymmetric peering readback; `infra/scenario-lab/main.tf`; focused scenario-lab contracts. | Retain a protected receipt showing both peerings Connected before workstation route verification. |
| 2026-08-25 | implemented | Pinned the disposable AKS node pool's observed surge policy so provider-flattened upgrade defaults no longer create a perpetual update. | Value-free plan `32793483505`; `infra/scenario-lab/aks.tf`; focused scenario-lab and Terraform checks. | Retain a zero-change protected plan before the live sweep. |

### Remaining work

- [ ] Retain an exact-revision protected deployment receipt that proves token, DNS, TCP/TLS,
  bounded ARG query, private projection write, one unavailable-source fallback, stale retention,
  and successful recovery without widening discovery or executor identity.

## Isolated certification sandbox

Restricted-network fault evidence uses one task-owned resource set inside the existing development
application resource group. It creates its own Virtual Network, delegated Container Apps and
PostgreSQL subnets, private DNS zones, private PostgreSQL server, and private Blob receipt store. It
does not tag or delete the existing resource group, and does not peer with, route through, or change
the existing development Virtual Network, DNS, NSG, Private Endpoint, identity, provider
registration, or active inventory generation.

The PostgreSQL private DNS zone is request-unique. Blob receipt I/O connects to the exact private
endpoint address while TLS SNI and the HTTP Host header remain bound to the account hostname, so
the campaign neither links nor writes records into a shared Blob zone.

The exact create plan permits only the reviewed sandbox addresses. One workload identity runs the
`arg,arm` campaign over the bounded `resource-group` type, while a distinct read-only identity
verifies the private receipt. The campaign records workload token, DNS, TCP/TLS, bounded ARG,
private projection write, ARG unavailability, one ARM fallback, retained active generation, and
higher-priority ARG recovery. The same exact image audits complete, incomplete, stale, conflicting,
and unavailable semantic refresh states, permits one canonical partial-overlay write-through, and
re-queries the exact active generation with no authority. Cleanup uses a separate exact delete-only
plan after successful effect verification; an ambiguous campaign or cleanup preserves the sandbox
for recovery review.

## Required network paths

Run the reachability probe from the subnet and identity that will execute discovery, not from an
operator laptop. The exact rules depend on the runtime and Azure cloud, but the deployment should
account for these paths:

| Purpose | Preferred path | Restricted-network options | Notes |
|---|---|---|---|
| ARG and ARM management reads | HTTPS `:443` to the Azure Resource Manager endpoint | NSG egress to the `AzureResourceManager` service tag; UDR through Azure Firewall or an approved proxy with a narrow management-endpoint allowlist; Resource Management Private Link when the target cloud, region, and required ARG operation support it | A private endpoint for a data service does not provide ARM or ARG connectivity. Azure service endpoints are not a replacement for the ARM management path. |
| AKS object inventory | HTTPS `:443` to the exact cluster API | Private routing is preferred; the disposable scenario permits an authenticated public API without a fixed IP allowlist for changing local egress | Public reachability never grants a credential, Kubernetes permission, or execution authority. Microsoft Entra, Azure RBAC, and disabled local accounts remain mandatory. |
| Workload token | Runtime-provided managed identity or workload identity endpoint | Allow the runtime platform identity path, including `AzurePlatformIMDS` where IMDS is used; use federated workload identity from an approved runner when the app subnet cannot mint a token | Do not add broad Internet egress or a client secret merely to make discovery work. |
| DNS | Azure-provided DNS or an approved custom resolver | Permit the runtime's platform DNS path, including `AzurePlatformDNS` where applicable; forward the required public or Private Link zones through the hub resolver | Resolve and TLS-probe the endpoint before starting a scan. DNS success alone is not reachability. |
| Snapshot publication | Private PostgreSQL and Event Hubs paths | Private endpoints, VNet peering, or hub routing from the discovery runner | The collector never sends inventory through a public console endpoint. |
| Genesis progress evidence | Private Foundation Blob service and PostgreSQL | The Bastion-reachable managed host uses its existing state-account data role and private endpoint; Operator reads only PostgreSQL | Blob objects contain count-only hash-chained records, never inventory rows or execution authority. Recurring inventory does not require this bootstrap Blob path. |

Gateway transit uses two directional peerings. Create the gateway-VNet direction with
`allow_gateway_transit` before the workload-VNet direction enables `use_remote_gateways`, express
that order in the Terraform dependency graph, and verify that both directions report Connected.

Terraform applies NSGs according to subnet ownership. Subnets that host the deploy runner or OHL
evidence VM deny Internet inbound explicitly. `GatewaySubnet`, Private DNS Resolver, private
endpoint, Container Apps, and PostgreSQL delegated subnets remain governed by their Azure-managed
service contracts; adding a generic NSG there is not treated as a substitute for service-specific
route and network-policy validation.

Service tags and Resource Management Private Link capabilities can differ by Azure cloud and can
change over time. Confirm the effective routes, DNS answers, and supported operations during
deployment preflight. Prefer service tags or private connectivity over copied IP ranges, and avoid
TLS interception unless the Azure endpoint and client trust model have been validated explicitly.

## Ordered fallback ladder

Use the first method that can produce a complete, bounded snapshot for the declared scope. Changing
transport does not change the `Inventory` contract.

1. **ARG from the runtime subnet** - run the sharded `Resources` queries with managed identity over
   an explicitly allowed ARM management path. This remains the default because it provides broad
   cross-resource discovery and bounded pagination.
2. **ARG from a connected discovery job** - move the same read-only adapter to a VNet-integrated
   Container Apps Job or the self-hosted ops runner when the application subnet intentionally has
   no management-plane egress. Publish batches to the private state store or Kafka ingress; do not
   give the console or core executor identity to the job.
3. **Resource Management Private Link path** - where Azure supports the required ARG calls, route
   the connected job through the approved private endpoint and private DNS. Preflight must execute
   a real bounded ARG query because private DNS resolution alone does not prove operation support.
4. **Direct ARM list adapters** - list each registered resource provider and resource type in
   bounded, paged shards when ARG is unavailable or exceeds the freshness budget. The adapter
   normalizes the same resource and link records and reports unsupported types as coverage gaps.
   Azure CLI and Azure SDK clients are transports for this method, not independent inventory
   sources.
5. **Authoritative scoped inventory** - use Microsoft Defender for Cloud Inventory or another
   approved Azure inventory projection only for resource types and subscriptions its coverage
   manifest declares authoritative. Supplementary findings never imply full estate coverage.
6. **Change-stream continuity** - continue consuming Activity Log changes forwarded through Event
   Hubs while a full-snapshot source is temporarily unavailable. Deltas preserve freshness for
   known resources but cannot bootstrap a graph or prove that unseen resources do not exist.
7. **Declarative recovery snapshot** - import an approved Terraform state/plan export, Azure
   deployment export, or signed declarative inventory file when no live management path is
   available. Mark it `expected` rather than `observed`, attach its generation time and scope, and
   use it for read-only context only. It cannot authorize autonomous remediation.

The ladder is not "try every source and union the rows." Each attempt emits a coverage manifest
containing source, subscription or management-group scope, resource types, start and completion
time, page counts, and errors. FDAI promotes a source only after every declared shard reaches its
final fence. A lower-priority source can replace an unavailable source for its declared coverage,
but it cannot silently fill unknown gaps or overwrite a newer authoritative record.

The Azure implementation prefixes every neutral resource id with an opaque hash of its subscription
scope. This prevents equal resource-group and resource paths in different subscriptions from
colliding without exposing the subscription id in the ontology key. ARG provides `contains`,
`attached_to`, and `depends_on` topology. Direct ARM fallback currently declares `contains`
coverage only, so the active projection reports the missing link kinds and stays degraded for
dependency-absence decisions.

## Failure and freshness policy

- **Preflight first:** verify token acquisition, DNS, TCP/TLS, one bounded query, pagination, and
  write access to the private projection before enabling the schedule.
- **Classify failures:** distinguish `network_blocked`, `dns_failed`, `token_failed`, `forbidden`,
  `throttled`, `partial`, and `source_unavailable`. A zero-row result is never used as the error
  fallback.
- **Retain last known good:** failed or partial scans keep the last complete snapshot and mark it
  stale. They do not replace it with an empty graph.
- **Preserve authority:** an older attempt, a lower-priority source from the same run, or an
  `expected` declarative candidate cannot replace a newer observed snapshot.
- **Degrade autonomy:** when snapshot age exceeds the configured freshness budget, graph-based
  impact-scope decisions and absence claims move to human review. Read-only display may use the
  stale graph when it shows source, age, scope, and degraded status.
- **Keep principals separate:** the discovery identity receives minimum read permissions on only
  the declared scopes. It is distinct from the privileged executor, console identity, and approval
  principal.
- **Audit transitions:** source selection, fallback activation, coverage loss, recovery, and
  snapshot promotion produce structured audit records and metrics.

Example: an NSG denies direct application-subnet egress to ARM. The preflight reports
`network_blocked`, the scheduled scan moves to the VNet-integrated ops runner, ARG completes through
the hub's approved management path, and only the final complete snapshot is promoted. If the runner
also loses reachability, FDAI retains the previous graph, marks it stale, and routes impact-scope-
dependent actions to human review.

## Related docs

| To learn about | Read |
|----------------|------|
| Provider-neutral inventory records and generation rules | [CSP-Neutrality Contracts](csp-neutrality.md#5-inventory-contract---resource-graph) |
| Deployment connectivity checks | [Network Connectivity Matrix](../deployment/network-connectivity-matrix.md) |
| Protected deployment preflight | [Deployment Preflight](../deployment/deployment-preflight.md) |
