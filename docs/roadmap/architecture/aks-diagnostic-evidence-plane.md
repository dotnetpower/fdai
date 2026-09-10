---
title: AKS Diagnostic Evidence Plane
---
# AKS Diagnostic Evidence Plane

This document defines the bounded read plane that identifies exact Azure Kubernetes Service (AKS)
resources and diagnoses workload, node, storage, endpoint, rollout, and control-plane failures. It
combines authenticated observations without turning correlation, diagnosis, or presentation into
causal or execution authority.

> **Authority boundary:** This plane observes and derives read-only evidence. It cannot approve,
> execute, restart, scale, delete, evict, roll back, or mutate an AKS resource.
>
> **Completeness boundary:** "Complete diagnosis" means complete for one declared competency,
> exact target, source set, and time window. It never means omniscient cluster coverage.
>
> **Privacy boundary:** Secret values, bearer tokens, raw log bodies, environment values, command
> output, and provider-controlled free text do not enter ontology instances or operator responses.

## Design at a glance

Each configured cluster has one immutable ARM identity and one authenticated Kubernetes API
binding. Inventory and watch collectors preserve UID and resource-version identity. Metrics, log
summaries, and Azure observations join only after exact-target verification. Deterministic
reducers then return one evidence-qualified diagnosis with explicit gaps and no execution
authority.

## Diagnostic competencies

| ID | Operator question | Required evidence |
|----|-------------------|-------------------|
| D1 | Which exact cluster object is affected? | Cluster ARM id, API binding digest, kind, namespace, name, UID, resourceVersion, and observation cutoff. |
| D2 | Why is a Pod pending? | Pod scheduling conditions, requests, node selector, tolerations, affinity summary, PVC state, quota, and candidate Node capacity. |
| D3 | Why is a container waiting or restarting? | Container group, waiting and termination reasons, restart delta, probe kinds, Events, and content-free log summary. |
| D4 | Does Node evidence support an impact hypothesis? | Ready, pressure, and network conditions plus allocatable capacity and exact providerID bridge. |
| D5 | Does the Service configure ready backends? | Service selector, EndpointSlice target UID, ready, serving, terminating, port count, and Pod readiness. Traffic arrival requires separate telemetry. |
| D6 | Is a rollout progressing? | Controller generation, replica status, workload revision, Pod revision, and replacement history. |
| D7 | Is storage blocking the workload? | Pod PVC claim, PVC phase and volume binding, PV phase, StorageClass mode, and relevant Events. |
| D8 | Is policy or capacity blocking placement? | PDB, HPA, ResourceQuota, LimitRange, NetworkPolicy summary, requests, and Node capacity. |
| D9 | Is the control plane or Azure substrate degraded? | AKS Resource Health, control-plane diagnostic categories, API reachability, AgentPool, VMSS, Node, NIC, subnet, route, NSG, NAT, and Public IP evidence. |
| D10 | Did the workload recover? | Distinct current and historical observations, exact replacement UIDs, ready transition, restart history, and owner status. |
| D11 | Which evidence is missing or stale? | Per-source state, scope digest, cutoff, freshness ceiling, cursor coverage, truncation, conflicts, and redaction. |
| D12 | What may FDAI do? | Always `execution_authority=false`; action planning and execution remain outside this plane. |

## Cluster source bindings

The runtime accepts a bounded collection of cluster bindings. Each binding contains:

- one canonical AKS ARM id;
- one credential-free HTTPS API endpoint;
- exactly one CA path or CA PEM;
- one `service-account` token path or one workload-identity audience;
- a content digest used in source state instead of the customer identifier.

Bindings are unique by cluster ARM id and API origin. A duplicate, partial, malformed, or
credential-bearing endpoint fails configuration before network I/O. Legacy single-cluster
variables adapt to one binding and cannot be combined with the fleet binding record.
Deployment assigns `Azure Kubernetes Service RBAC Reader` only at each exact managed-cluster ARM
id. Subscription, resource-group, and managed-cluster child scopes are not accepted.

Collection isolates failures by cluster. One unavailable cluster does not erase verified positive
evidence from another cluster, but fleet completeness remains false until every required binding
is current and complete. Source-state keys are `(source, scope_digest)`, so one cluster cannot
overwrite another cluster's unavailable reason.
Each relationship projection combines provider resources with one cluster's API objects. It does
not re-project objects or links accepted from an earlier fleet binding.
Persistence and operator projections retain the bounded fleet states by `(source, scope_digest)`.
The Console exposes the opaque scope digest and never collapses several cluster states into the
first matching source name.

## Exact resource identity

Stable Kubernetes Resource identity is the tuple:

`(cluster_ref, uid)`.

Each versioned observation separately carries:

`(api_version, kind, namespace, name, resource_version, observed_at)`.

UID anchors object identity. API version, kind, name, and namespace are validated observation
metadata and query aliases, not stable identity. `resourceVersion` orders observations within one
API server and is never compared across clusters. A resolver can return:

- `resolved`: exactly one current or historical UID satisfies the exact selector;
- `not_found`: complete evidence proves no matching object in the requested scope;
- `ambiguous`: multiple UIDs or kinds satisfy an underspecified selector;
- `unavailable`: source, access, retention, or cursor evidence cannot prove a result.

Pod replacement retains both UIDs. The resolver never rewrites an old UID to the current object
with the same name.
Snapshots created before the versioned identity contract remain listable during rollout. When all
of `api_version`, `kind`, and `resource_version` are absent, the Operator withholds exact
Kubernetes identity and diagnostics instead of failing the entire instance response or inventing
the missing values. A partially populated versioned identity remains malformed and unavailable.

## Evidence collection

### Kubernetes object snapshot

The complete snapshot covers:

- Namespace, Node, Pod, Service, Endpoints, EndpointSlice;
- Deployment, ReplicaSet, DaemonSet, StatefulSet, Job, CronJob;
- Ingress and IngressClass;
- PersistentVolumeClaim, PersistentVolume, StorageClass;
- HorizontalPodAutoscaler, PodDisruptionBudget, NetworkPolicy;
- ResourceQuota and LimitRange.

The source keeps bounded diagnostic fields only. It records conditions, transition times,
container groups, restart and termination facts, probe kinds, scheduling constraints, resource
requests and limits, capacity, storage binding, replica status, and endpoint health. It never
records Secret or ConfigMap values, container commands, environment values, image pull secrets,
raw event messages, endpoint addresses, or raw log bodies.
The API inventory module owns transport, pagination, and Resource identity. A separate status
normalizer owns bounded Node, Pod, container, and Deployment status facts so the transport module
stays below its enforced structural size limit without duplicating parsing rules.
Collector and Operator bounds are identical. Up to 128 containers can yield 384 probe-kind records
or 256 current and previous termination records; a larger diagnostic sequence is unavailable
instead of being silently truncated.
Operator and Console allowlists cover every content-safe collected rollout, storage, policy, and
ephemeral-container diagnostic field. A collected field is not silently removed from a
complete-looking response.
EndpointSlice readiness keeps omitted or null `ready` values in `ready_unknown`. Forseti emits
`endpoint_unready` only when at least one endpoint exists and both ready and unknown-ready counts
are zero.
An explicit empty NetworkPolicy `podSelector` is preserved as `selector_matches_all: true`. Only
that typed NetworkPolicy marker selects every Pod in the same namespace; an absent selector or an
empty Service selector does not gain match-all meaning.

### Lifecycle history

Each cluster owns an independent Event cursor. Initial list establishes `resourceVersion`; bounded
watch windows append typed observations and bookmarks. HTTP 410 closes the current coverage segment
as incomplete and starts a new segment after reseeding. Kubernetes cannot reconstruct compacted
Events, so the retained gap never becomes complete unless another authoritative source covers the
exact interval. Durable history preserves event UID, involved-object UID, reason, type, count,
source revision, event time, recorded time, and coverage-segment identity.
Each incomplete interval is an immutable, content-addressed PostgreSQL coverage segment. Exact-UID
history queries check overlapping segments before claiming completeness, so later cursor recovery
cannot erase a retained `cursor_expired`, authorization, source, response, or result-limit gap.

### Metrics

Metric evidence uses the existing provider-neutral `MetricProvider`. Fixed semantic names cover:

- container CPU usage and throttled seconds;
- working-set memory, OOM events, network receive/transmit, and filesystem usage;
- Pod requested CPU and memory;
- Node allocatable and pressure capacity.

Every series requires exact `cluster_ref`, namespace, Pod UID or Node UID labels. A diagnostic
metric source also returns source revision, provider cutoff, pagination or truncation state, and
window coverage. The existing point-only `MetricProvider` can supply candidates but cannot claim a
complete diagnostic window by itself. Name-only series, mixed identities, future samples,
point-only sources, and truncated windows remain unavailable. An empty metric query does not prove
zero.
Before signal reduction, Forseti rechecks the metric target tuple, point labels, metric interval,
provider cutoff, and source revision against the exact diagnostic context. A mismatch is retained
as a conflict and its metric cannot contribute a diagnostic signal.
An independent coverage receipt can mark a window complete only when its timezone-aware provider
cutoff reaches or exceeds the requested interval end.

### Logs

Log evidence is queried by exact Pod UID and bounded time window. Raw bodies are discarded after
content hashing. The retained summary contains record count, severity count, timestamps, digests,
source identity and revision, provider cutoff, pagination or truncation state, window coverage, and
a structured limitation. A point-only `LogQueryProvider` cannot claim complete window coverage
without a separate provider receipt. Diagnosis can use only reviewed structured labels and
lifecycle reasons, not free-text interpretation.

### Azure and control-plane evidence

The plane reuses the exact Node-to-VMSS VM bridge and Azure topology from the operational instance
graph. AKS Resource Health, API reachability, and configured control-plane diagnostic categories
are independent observations. Temporal adjacency and topology proximity can support or refute a
hypothesis but cannot prove causation.
An accepted exact-cluster inventory source proves API reachability only at that source cutoff.
Promotion receipts retain `azure_control_plane_evidence_unavailable` until an exact Azure health or
control-plane source is bound; they do not substitute topology or API success for Azure health.

## Agent ownership and deterministic diagnosis

Collectors are mechanical read-plane adapters. After a successful inventory promotion, a bounded
observer validates exact target identity and source state, invokes the deterministic T0 reducer,
and atomically appends the immutable receipt plus a sanitized audit entry. This local derived
read-model step is not agent collaboration and grants no authority. Forseti remains the accountable
root-cause owner named by the receipt.

One reducer classifies one exact target and one cutoff. The initial family set is:

- scheduling and quota;
- image pull and init-container failure;
- crash loop, abnormal exit, OOM, and probe failure;
- eviction and Node pressure;
- Service and EndpointSlice backend health;
- rollout and replacement;
- PVC, PV, and StorageClass binding;
- HPA, PDB, and policy constraints;
- Node network-unavailable plus reviewed Pod sandbox, CNI, and DNS Event reasons;
- AKS control-plane or Azure substrate degradation.

Each evidence receipt includes authenticated principal class, purpose, producer and method
versions, stable target identity, observation revision, ontology release, source revisions and
cutoffs, evidence refs, gaps, conflicts, freshness, completeness, synthetic state, audit
correlation, `cause_claim_supported=false`, and `execution_authority=false`. Conflicting or
incomplete evidence returns an explicit held result. A model can explain a verified Forseti-owned
result but cannot select or change it.

## Persistence and projection

Collectors append typed records. The inventory single writer continues to own current Resource and
relationship projection. Lifecycle history remains append-only. Diagnostic results are
content-addressed read receipts and do not become observed Resource state.

Core stores the immutable receipt behind a read-only repository and projects it through a shared
schema. The Operator API requires an ordinary Reader role and `operations-review` purpose, applies
server-owned redaction, and exposes allowlisted identity, status, evidence health, and diagnostic
receipts. The Console validates the shared schema and renders source, cutoff, gaps, and exact
resource identity. It does not construct Resources, relationships, metric values, diagnoses, or
authorization in the browser.
Receipt identity is content-addressed from the exact target, UID, resourceVersion, ontology
release, canonical JSON timestamps, source cutoffs, and source revisions. Recovery replays pending
promotions even when ontology projection is disabled. Operator exposes a receipt only when its
target identity, inventory generation digest, ontology release, source cutoff, and fleet scope
digest match the selected current Resource; any mismatch renders the diagnosis unavailable.

## Ontology and deployment changes

The catalog adds exact ResourceTypes for PVC, PV, StorageClass, HPA, PDB, NetworkPolicy,
ResourceQuota, and LimitRange before runtime inventory can emit them. Existing `contains`,
`depends_on`, `attached_to`, and `kubernetes_selects` LinkTypes remain sufficient for the first
release; each new mapping pins the updated Kubernetes source-schema digest.

`InventoryProjectionSourceState` gains an optional `scope_digest`, and uniqueness becomes
`(source, scope_digest)`. Existing records omit the field. A fleet binding variable supplies at
most 32 validated records and is mutually exclusive with the legacy single-cluster variables.
Terraform assigns the inventory identity Reader access to every exact cluster ARM scope and passes
no bearer token. The separate Terraform deployer roles use the configured stable runner UAMI
principal, so recreating the runner host can't redirect AKS observation authority.

## Bounds and failure behavior

| Boundary | Initial limit |
|----------|---------------|
| Cluster bindings | 32 |
| Kubernetes objects per cluster generation | 20,000 |
| Pages per kind | 64 |
| Conditions or status entries per object | 128 |
| Event rows per read | 256 |
| Log records per read | 128 over at most 24 hours |
| Metric series | 16 targets and 20 points per series |
| Diagnosis targets | One exact Resource per receipt |

Any exceeded bound keeps prior active evidence and records a typed limitation. Partial input cannot
delete a prior object, relationship, or source receipt.

## Delivery and validation

Implementation proceeds in focused batches:

1. Add fleet-safe bindings and per-cluster source state.
2. Add exact identity and resource-version resolution.
3. Expand bounded Kubernetes diagnostic facts and relationships.
4. Bind endpoint health, metrics, logs, and lifecycle history.
5. Add deterministic diagnosis and no-authority projection.
6. Complete at least ten independent critique and hardening rounds.
7. Validate positive and unavailable cases against one externally prepared exact live AKS cluster.

The evidence plane itself never starts or stops a cluster. In this delivery campaign, the
maintainer's explicit session authorization permits the coding-session operator to start the exact
cluster after focused checks pass and restore its original power and local-binding state after
evidence capture. This test operation does not grant runtime execution authority.

## Related docs

| To learn about | Read |
|----------------|------|
| Implementation status and remaining work | [AKS diagnostic implementation ledger](../../roadmap-implementation/architecture/aks-diagnostic-evidence-plane.md) |
| Continuous source freshness and promotion | [Continuous Operational Instance Graph](continuous-operational-instance-graph.md) |
| Resource and relationship identity | [Ontology Structural Model](ontology-structural-model.md) |
| Root-cause evidence boundaries | [Root Cause Analysis](../rules-and-detection/root-cause-analysis.md) |
