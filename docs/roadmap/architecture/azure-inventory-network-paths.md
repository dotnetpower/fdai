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
| Snapshot authority and stale-state handling | implemented | Inventory sync, projection, and reconciliation tests cited by [CSP-Neutrality Contracts](csp-neutrality.md#implementation-status) | Partial collection cannot replace the last complete promoted generation or authorize an absence claim. |
| Subnet-specific network controls | implemented | `infra/modules/network/main.tf`; `infra/bootstrap/main.tf`; focused network hardening tests | VM-bearing subnets deny Internet inbound through explicit NSGs. Azure-managed delegated and private-endpoint subnets retain their service-owned network-policy contracts. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-21 | in-progress | Moved the existing restricted-network inventory design into a focused owner document without changing runtime behavior or authority. | `current change`; document-size, translation, route, and link checks. | Retain exact-revision protected evidence for the effective network path and at least one failover and recovery transition. |
| 2026-08-25 | implemented | Added explicit NSG protection to the OHL evidence VM subnet and verified the existing deploy-runner subnet association, while preserving Azure-managed delegated subnet constraints. | `current change`; `tests/integration/infra/test_network_hardening.py`; `tests/integration/infra/test_bootstrap_network_hardening.py`; Checkov and Trivy reported no active finding above Low. | Retain deployed evidence that the effective NSG and route policy still permits the required bounded management path. |
| 2026-08-24 | implemented | Serialized the two directional gateway-transit peerings used by the disposable scenario path. | Failed protected applies `32773217323` and `32774040807`; asymmetric peering readback; `infra/scenario-lab/main.tf`; focused scenario-lab contracts. | Retain a protected receipt showing both peerings Connected before workstation route verification. |
| 2026-08-25 | implemented | Pinned the disposable AKS node pool's observed surge policy so provider-flattened upgrade defaults no longer create a perpetual update. | Value-free plan `32793483505`; `infra/scenario-lab/aks.tf`; focused scenario-lab and Terraform checks. | Retain a zero-change protected plan before the live sweep. |

### Remaining work

- [ ] Retain an exact-revision protected deployment receipt that proves token, DNS, TCP/TLS,
  bounded ARG query, private projection write, one unavailable-source fallback, stale retention,
  and successful recovery without widening discovery or executor identity.

## Required network paths

Run the reachability probe from the subnet and identity that will execute discovery, not from an
operator laptop. The exact rules depend on the runtime and Azure cloud, but the deployment should
account for these paths:

| Purpose | Preferred path | Restricted-network options | Notes |
|---|---|---|---|
| ARG and ARM management reads | HTTPS `:443` to the Azure Resource Manager endpoint | NSG egress to the `AzureResourceManager` service tag; UDR through Azure Firewall or an approved proxy with a narrow management-endpoint allowlist; Resource Management Private Link when the target cloud, region, and required ARG operation support it | A private endpoint for a data service does not provide ARM or ARG connectivity. Azure service endpoints are not a replacement for the ARM management path. |
| Workload token | Runtime-provided managed identity or workload identity endpoint | Allow the runtime platform identity path, including `AzurePlatformIMDS` where IMDS is used; use federated workload identity from an approved runner when the app subnet cannot mint a token | Do not add broad Internet egress or a client secret merely to make discovery work. |
| DNS | Azure-provided DNS or an approved custom resolver | Permit the runtime's platform DNS path, including `AzurePlatformDNS` where applicable; forward the required public or Private Link zones through the hub resolver | Resolve and TLS-probe the endpoint before starting a scan. DNS success alone is not reachability. |
| Snapshot publication | Private PostgreSQL and Event Hubs paths | Private endpoints, VNet peering, or hub routing from the discovery runner | The collector never sends inventory through a public console endpoint. |

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
