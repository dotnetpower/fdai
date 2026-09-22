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

Reusable quantity conversion and ordinary Pod CPU/memory accounting are defined in the
[connector preflight boundary](aks-outbound-connector.md#capacity-and-storage-preflight).
These pure helpers consume complete Pod records; existing normalized diagnostic quantity text
is unchanged. Arithmetic alone proves neither source completeness nor schedulability. Explicit signed preflight now collects complete Node/Pod lists and exact PVC/PV binding separately; it neither expands diagnostic normalization nor proves placement, mount/write effects or source promotion.
The focused test harness fixes the concrete resource-preflight class before any temporary read-probe substitution, so suite order cannot alter the exact namespace UID boundary or diagnostic evidence.

The [outbound connector](aks-outbound-connector.md) offers explicit certificate-authenticated
snapshot transfer without changing this plane's observation authority. Its stored-source adapter
uses the existing Inventory Job and relationship verifier and is exclusive with direct collection.
Direct collection remains the default; Event history and protected private-cluster validation for
the connector remain open in its implementation ledger.

Subscription discovery also preserves an explicit boolean private-cluster fact independently of
credential availability. It creates a Core-owned [observer deployment proposal](aks-outbound-connector.md#implemented-proposal-boundary), not a new source binding or approval.
Missing preflight evidence remains unknown; repeated discovery is deduplicated and cannot install
an observer, increase diagnostic coverage, or turn an unreachable API into a private-mode finding.
When configured, the proposal path now reads signed, target-scoped preflight receipts and rechecks
verifier revocation. The separate bounded Kubernetes collector proves only the existing reader's
list permissions after exact cluster identity checks, not diagnosis, installation or readiness.
Observer setup recommendations now reach a separate role-gated Operator read projection over the
existing event transport. Its short lease and explicit unavailable states never increase this plane's
diagnostic completeness, and the Console exposes no installation or approval command.

The runtime accepts a bounded collection of cluster bindings. Each binding contains:

- one canonical AKS ARM id;
- one credential-free HTTPS API endpoint;
- exactly one CA path or CA PEM;
- one `service-account` token path or one workload-identity audience;
- a content digest used in source state instead of the customer identifier.

Bindings are unique by cluster ARM id and API origin. A duplicate, partial, malformed, or
credential-bearing endpoint fails configuration before network I/O. Legacy single-cluster
variables adapt to one binding and cannot be combined with the fleet binding record.
For an FDAI-managed AKS runtime, application preparation automatically creates one self-cluster
binding from the exact runtime Terraform output. The inventory CronJob uses
`https://kubernetes.default.svc`, the projected ServiceAccount token, and the mounted cluster CA.
Only that CronJob ServiceAccount receives the reviewed cluster-wide `get`, `list`, and Event
`watch` permissions required by the bounded collector. It receives no Secret, ConfigMap, or write
permission.
Deployed Azure inventory uses the selected subscription as its AKS observation scope. The dedicated
inventory Managed Identity receives subscription-scoped `Reader`, `Azure Kubernetes Service Cluster
User Role`, and `Azure Kubernetes Service RBAC Reader` assignments. Each reconciliation lists the
subscription's current managed clusters, requests exec-format user credentials only to extract the
selected API origin, public CA material, and token audience in memory, and then discards the response.
A returned kubeconfig that embeds a token, client certificate, client key, password, or another
static credential is rejected. A newly created cluster therefore enters the next bounded discovery
run without a Terraform change, while a deleted cluster disappears only after complete subscription
reconciliation proves its absence.
Management-plane discovery and Kubernetes API reads place the validated short-lived token only in
the transient `Authorization: Bearer` request header. The header does not enter configuration,
inventory records, logs, errors, or source-state metadata. A redaction marker is presentation data
and is never sent as an authentication credential.

Private-cluster connection failures retain one sanitized source-state reason without an endpoint,
cluster name, token, response body, or provider-controlled message. The reviewed reasons distinguish
DNS resolution, TLS verification, network connection, request timeout, HTTP 401 authentication,
HTTP 403 authorization, API unavailability, request rejection, and invalid response evidence. These
reasons identify the failed boundary; they do not claim that a route, firewall, identity assignment,
or AKS component is the root cause.

This broader read scope was reviewed against the earlier exact-cluster design. Per-cluster role
assignments required an infrastructure change for every new cluster and left the subscription graph
incomplete by default. Subscription scope removes that onboarding gap, but it does not make every
cluster reachable. Private DNS, routing, API authorized ranges, disabled Microsoft Entra integration,
unsupported credential shape, provider throttling, or a discovery limit keeps that cluster's source
state unavailable and fleet completeness false. The collector never falls back to a human kubeconfig,
an admin credential, local accounts, or Thor's execution identity.

Explicit fleet bindings remain available for a deliberately narrower deployment and for eligible
local development. Local development accepts an owner-only fleet binding file only when Kubernetes
collection is explicitly enabled. It does not inherit subscription discovery, copy credentials into
the repository, or reuse an interactive human identity implicitly.
An explicitly requested local conversation-assurance series may reuse the already selected Azure
CLI human for one bounded `az aks list` discovery. That read supplies private target wording only;
it is not AKS diagnostic evidence. A question becomes selectable only after the exact provider
reference joins the active local inventory and reviewed BusinessService graph, and neither names
nor provider ids enter tracked records or command output.
The isolated public-development Terraform caller may be the verified Azure CLI human, but that
management identity never becomes an AKS evidence reader or runtime executor. Protected deployment
continues to use its stable deploy UAMI, and all Kubernetes reads remain bound to the dedicated
inventory identity.

Collection isolates failures by cluster. One unavailable cluster does not erase verified positive
evidence from another cluster, but fleet completeness remains false until every required binding
is current and complete. Source-state keys are `(source, scope_digest)`, so one cluster cannot
overwrite another cluster's unavailable reason.
When several unavailable scope enrichers run for one generation, each scope state remains durable
while the process emits one generation-level warning. Subscription discovery without current
preflight evidence keeps the observer proposal at `needs_evidence`; it does not create a source
binding or weaken private-cluster access controls.
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
Azure Managed Prometheus's default `cluster` label is a cluster-name alias, not an exact ARM
identity. Inventory-backed analyzer routing therefore remains on Azure Monitor Logs unless an
explicitly composed PromQL catalog preserves an exact `resource_id` label. A Prometheus response
missing any requested identity label fails instead of becoming an empty healthy series.
Before signal reduction, Forseti rechecks the metric target tuple, point labels, metric interval,
provider cutoff, and source revision against the exact diagnostic context. A mismatch is retained
as a conflict and its metric cannot contribute a diagnostic signal.
An independent coverage receipt can mark a window complete only when its timezone-aware provider
cutoff reaches or exceeds the requested interval end.

#### Safe metric failure diagnostics

`MetricProviderError(message)` remains valid and keeps its original message. Its optional
`reason` uses the provider-neutral `MetricFailureReason` enum; `http_status` accepts only an
integer from 100 to 599, excluding booleans. The default is `unknown` with no HTTP status.

| Reason | Observed condition |
|--------|--------------------|
| `unknown` | The provider supplied no classification. |
| `timeout` | The HTTP client reported a timeout. |
| `transport_error` | The HTTP client reported another request failure. |
| `http_error` | An HTTP failure response or status exception was received. |
| `invalid_response` | Response structure, values, or required identity checks failed. |
| `response_limit` | A configured byte, row, or point limit was exceeded. |
| `invalid_query` | The metric template or required query scope was unavailable or unsupported. |
| `provider_error` | The response explicitly reported a metric-level failure. |

Azure Monitor Logs and Azure Monitor Metrics assign these categories at error construction.
The Analyzer's mapped identity boundary retains only validated reason and status fields, renders
them in the redacted error message, and detaches the provider exception chain. It does not copy
provider messages, URLs, resource identifiers, or response bodies. Existing providers that supply
only a message remain unclassified; no retry or provider fallback is added.

These categories describe failures, not established root causes, persistent defects, or diagnostic
coverage. `http_429_rate` is a computed Logs KQL metric name, not evidence that a query returned
HTTP 429. Earlier generic mapped errors cannot establish their historical cause. A successful query
with valid columns and zero rows stays empty, and missing native aggregate bins remain missing
rather than becoming zero. Failures still stop the query; partial results do not authorize an action.

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
Receipt identity includes the cutoff for ordering and a canonical digest of the complete immutable
receipt. Identical replay remains idempotent, while a different assessment for the same target,
UID, resourceVersion, release, and cutoff appends a distinct receipt instead of colliding.
The writer reads an existing key first and skips another atomic insert and audit attempt only when
the complete stored value is byte-identical; absent-key races still use conditional creation and
collision readback. Recovery replays pending promotions even when ontology projection is disabled. Operator exposes a receipt only when its
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
principal, and planning stops when the authenticated principal differs. Recreating the runner host
can't redirect AKS observation authority.

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

Runtime-profile completion follows this order:

1. Render the exact self-cluster binding into the inventory CronJob.
2. Bind the minimum Kubernetes read role to only the inventory ServiceAccount.
3. Accept explicit owner-only fleet bindings for eligible local or external collectors.
4. Fail before provider access when a binding is absent, mixed, malformed, or overly exposed.
5. Validate stopped, unavailable, ready Node, and Pod status paths without treating startup as
   evidence of workload health.

## Related docs

| To learn about | Read |
|----------------|------|
| Implementation status and remaining work | [AKS diagnostic implementation ledger](../../roadmap-implementation/architecture/aks-diagnostic-evidence-plane.md) |
| Continuous source freshness and promotion | [Continuous Operational Instance Graph](continuous-operational-instance-graph.md) |
| Resource and relationship identity | [Ontology Structural Model](ontology-structural-model.md) |
| Root-cause evidence boundaries | [Root Cause Analysis](../rules-and-detection/root-cause-analysis.md) |
