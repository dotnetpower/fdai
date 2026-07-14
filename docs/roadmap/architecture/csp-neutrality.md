---
title: CSP-Neutrality Contracts
---
# CSP-Neutrality Contracts

Names the concrete **contracts** that keep the core CSP-neutral even though
[Azure is the only implemented target](../../../.github/copilot-instructions.md#implementation-focus-must).
The contracts are wire-level (protocols, artifacts, token formats) so that a future non-Azure
adapter is **additive configuration**, not a core rewrite.

Complements the topology in
[app-shape.instructions.md](../../../.github/instructions/app-shape.instructions.md), the module
boundaries in [project-structure.md](project-structure.md), the tech choices in
[tech-stack.md](tech-stack.md), and the identity model in
[security-and-identity.md](security-and-identity.md).

## Principle

Anything the core touches from a cloud provider MUST be reached through **one wire-level
contract per concern**, not through a vendor SDK. The Azure implementation of each contract
is what we build today; a fork or a future phase adds another CSP by registering a new
implementation of the **same contract**, without editing `core/`.

**Concurrency**: the eight provider Protocols are **async by default** (Kafka poll loop,
Postgres asyncpg, Key Vault HTTP, OIDC token exchange, inventory-graph queries, and the
three telemetry-ingestion queries in § 6-8 are all I/O-bound). Sync is reserved for CPU /
startup-only seams - `SchemaRegistry`, `ContractValidator`, `ConfigProvider` - so they do
not block the event loop. See
[project-structure.md § Injectable Seams](project-structure.md#injectable-seams) for the
canonical seam list.

Eight contracts govern the CSP-touching surface (five wire-level foundations plus three
telemetry-ingestion seams added per [scope-expansion.md § 3.2](../fork-and-sequencing/scope-expansion.md)):

| # | Contract | Wire / artifact | Azure implementation |
|---|----------|-----------------|----------------------|
| 1 | **Event bus** | Apache Kafka wire protocol | Event Hubs (Kafka endpoint on port `9093`) |
| 2 | **Runtime** | OCI container image + Knative-compatible manifest subset | Container Apps (Consumption, KEDA) |
| 3 | **Secret** | environment variables (or K8s Secret mount) - never a CSP secret SDK call from the app | Container Apps native secret + Key Vault reference |
| 4 | **Workload identity** | OIDC token (federated) | User-assigned Managed Identity + workload identity federation |
| 5 | **Inventory** | resource-graph query surface returning `(Resource, Link[])` batches over an HTTP + OIDC-bearer wire | Azure Resource Graph (ARG) + Activity Log delta |
| 6 | **Metric ingestion** | `MetricProvider.query(MetricQuery) -> AsyncIterator[MetricPoint]` (CSP-neutral names + labels) | Azure Monitor Logs (KQL) - upstream auto-binds `AzureMonitorLogsMetricProvider` when `FDAI_MONITOR_WORKSPACE_ID` is set, else keeps `NoopMetricProvider` |
| 7 | **Log ingestion** | `LogQueryProvider.query(LogQuery) -> AsyncIterator[LogRecord]` (vendor `expression` + CSP-neutral label filter) | Log Analytics (KQL) - upstream ships `NoopLogQueryProvider` |
| 8 | **Trace ingestion** | `TraceQueryProvider.query(TraceQuery) -> AsyncIterator[Span]` (`trace_id`, `service`, `operation`, `min_duration`) | Application Insights - upstream ships `NoopTraceQueryProvider` |

Every one of the eight MUST NOT leak provider specifics into `core/`. See
[Anti-Patterns](#anti-patterns) for the concrete violations to reject.

## 1. Event Bus Contract - Kafka Wire Protocol

The event bus is expressed as a **Kafka producer/consumer** with a small,
provider-independent surface (`bootstrap.servers`, `sasl.mechanism`, `security.protocol`,
plus a per-provider token/credential source). All three major CSPs and multiple
multi-cloud vendors expose a Kafka-compatible endpoint, so the same client library and the
same code path serve every target.

| CSP / vendor | Managed Kafka endpoint | Auth mechanism | Notes |
|---|---|---|---|
| Azure | **Event Hubs** (Kafka 1.0+ endpoint, `<ns>.servicebus.windows.net:9093`) | SASL/OAUTHBEARER with Entra token | one namespace hosts topics; idle cost stays low on Standard 1 TU |
| AWS | **MSK Serverless** | SASL/OAUTHBEARER with AWS IAM SigV4 | truly serverless (partition-hour billed) |
| GCP | **Managed Service for Apache Kafka** (GA) | SASL/OAUTHBEARER with Google IAM token | broker fleet is always-on; use the smallest cluster |
| Multi-cloud | **Confluent Cloud** / **Redpanda Cloud** / **Aiven Kafka** | SASL/PLAIN or SASL/OAUTHBEARER | escape hatch when vendor-lock even to a hyperscaler is unacceptable |
| Self-hosted | **Strimzi Kafka** on AKS/EKS/GKE, or **Redpanda** | SASL or mTLS | last resort; adds ops burden |

**Rules (MUST):**

- The core produces/consumes with a **Kafka client only** (e.g. `librdkafka`, `kafka-python`,
  `KafkaJS`, `Sarama`); no `ServiceBusClient`, `SqsClient`, `PubSubClient`, or any other
  vendor SDK is imported.
- The event schema uses **CloudEvents envelope** on top of JSON Schema
  ([tech-stack.md](tech-stack.md)); this stays identical across providers.
- **Schema evolution** is guarded by `check_schema_compatibility`
  (`shared/contracts/compatibility.py`): each versioned schema
  (`event/1.0.0` -> `event/1.1.0`) is immutable, and a catalog-validation gate
  rejects a bump that is not additive-only (a removed field, a changed or
  newly-added type or `enum` constraint, a newly-required field, or a
  narrowed enum is `BREAKING`, including changes nested inside an object
  property or an array's `items`). This keeps a rolling
  deploy or mixed-version replicas from silently failing to decode - old and new
  producers/consumers stay interoperable.
- **DLQ** = a Kafka **dead-letter topic** with a naming convention (e.g. `<topic>.dlq`)
  plus a redrive worker; providers that offer native DLQ (Event Hubs does not) MUST be
  ignored in favor of the topic convention so behavior is uniform.
- **Ordering** is preserved by partition key (per-resource key ⇒ per-resource ordering).
  Any provider-specific ordering primitive (Service Bus sessions, FIFO groups) MUST NOT
  leak into core.
- **Idempotency** is enforced by the app-level idempotency key on the event, not by
  provider "exactly-once" flags. The executor keeps an in-process L1 cache and,
  when the `IdempotencyStore` seam (`shared/providers/idempotency.py`) is wired,
  a durable L2 guard (`PostgresIdempotencyStore`, `INSERT ... ON CONFLICT DO
  NOTHING`): a post-restart or cross-replica re-delivery of a *mutating* action
  is returned from the store instead of re-executed. Only mutating outcomes are
  recorded - abstains do not mutate, so re-evaluating them is harmless. The
  narrow window between "mutation applied" and "result recorded" is closed by the
  `OutboxStore` seam (`shared/providers/outbox.py`; `PostgresOutboxStore` backs
  it): a claim written *before* the mutation means a crash-suspect retry finds an
  `IN_PROGRESS` marker and re-runs the idempotent mutation to completion rather
  than losing or double-applying it. The outbox matters once actions mutate
  (enforce / P2); P1 is shadow-only, so nothing is applied twice there.
- **Cross-replica per-resource exclusion** is enforced by the `ResourceLock` seam
  (`shared/providers/resource_lock.py`): the in-process `asyncio.Lock`
  (`ResourceLockManager`) is the single-replica default, and
  `PostgresAdvisoryResourceLock` (a Postgres session advisory lock keyed by
  `hashtextextended(resource_id)`) gives cross-replica mutual exclusion once the
  executor scales past one replica. Partition-key ordering serializes a *stream*;
  the lock serializes concurrent *actions* on the same resource - both are needed
  under scale-out. The lock is crash-safe (a dropped connection releases the
  session lock) and bound by `lock_timeout` so a stuck holder fails closed rather
  than wedging a replica.
- **Downstream failure isolation** uses the `CircuitBreaker` primitive
  (`shared/resilience/circuit_breaker.py`): a composition root wraps a provider
  adapter's outbound call (Azure ARM, GitHub, Postgres, Kafka) so a run of
  failures trips the circuit OPEN and fails fast instead of hammering a dead
  dependency (a retry storm), then probes with a single HALF_OPEN call before
  closing. It is a pure, I/O-free state machine with an injectable clock, wired
  at the composition root (never in `core`), so it stays CSP-neutral and
  complements the pantheon bridge's self-healing restart.
- **System-level fail-toward-safety** is the `DegradationController`
  (`shared/resilience/degradation.py`): it aggregates the circuit breakers into a
  `NORMAL` / `DEGRADED` mode and caps autonomy to shadow when a critical
  dependency is OPEN - a failing audit store or unreachable substrate MUST NOT
  drive an enforce mutation. The control loop consults `autonomy_permitted()`
  and passes the result to the risk-gate authority as `system_degraded`, which
  adds a `system_health` ceiling axis capped to shadow (execution-model.md 2.6a)
  before any action is promoted.
- **Backpressure** (`shared/resilience/backpressure.py`) bounds concurrency with
  a semaphore and *sheds* (fast-rejects, re-queued to the broker / DLQ) once both
  the in-flight slots and a bounded wait queue are full, so an event storm
  degrades predictably instead of exhausting the process.

**Anti-patterns (MUST NOT):**

- Using Event Hubs through the AMQP native SDK (or the Service Bus SDK). If Event Hubs is
  chosen, **only the Kafka endpoint on `:9093`** is permitted.
- Using Dapr's pub/sub building block - it adds a sidecar dependency and re-locks the
  runtime layer.

## 2. Runtime Contract - OCI Image + Knative-Compatible Manifest

The core ships as one or more **OCI container images** and a small **Knative-compatible
manifest subset** describing traffic, revisions, autoscaling triggers, health probes, and
env/secret bindings. Provider adapters render this into the CSP-specific resource shape.

| CSP / substrate | Runtime | Scale-to-zero | Deployment shape rendered from the contract |
|---|---|---|---|
| Azure | **Container Apps** (Consumption + KEDA) | ✓ | `containerapp` resource generated from the manifest via Bicep/Terraform |
| AWS | **App Runner** (request-based) or **ECS Fargate** + KEDA | App Runner ✓ / Fargate - | rendered from the same manifest |
| GCP | **Cloud Run** (services & jobs) | ✓ | Cloud Run is native Knative; the manifest applies directly |
| Any K8s (AKS/EKS/GKE) | **Knative Serving** + KEDA | ✓ | manifest applies directly |
| Fallback | bare `Deployment` + HPA + KEDA | - (idle ≥ 1 replica) | rendered when scale-to-zero is unavailable |

**Rules (MUST):**

- The image exposes standard **`/healthz` and `/readyz`** endpoints. Container Apps probes,
  K8s probes, App Runner probes, and Cloud Run probes all point at these two.
- **Scale triggers are contract-level signals** (e.g. `scale-on: kafka-lag`, or a CPU
  target). Provider adapters translate them to KEDA CRDs, App Runner concurrency,
  Cloud Run CPU utilization, etc.
- The core does **NOT** depend on Dapr sidecars, Envoy-specific ingress annotations, or any
  Container Apps-only feature (e.g. built-in KEDA scaler references that only exist in
  Container Apps YAML).
- Where Azure ships a scheduled worker as a Container Apps Job, other providers render the
  same contract as a K8s `CronJob`, an AWS EventBridge-triggered task, or a Cloud Run Job -
  all interchangeable.

**Anti-patterns (MUST NOT):**

- Baking Container Apps-only YAML (Dapr components, native KEDA scaler refs) into the
  application's own repo.
- Requiring an Envoy-flavored ingress rule; use a portable ingress abstraction or handle
  the routing in-app.

## 3. Secret Contract - Environment / K8s Secret

The application reads **only environment variables** (or, on Kubernetes, files mounted from a
`Secret`). It **never** calls a CSP secret SDK directly. The injection layer bridges the
CSP secret backend to the container's environment.

| CSP / substrate | Injection layer | Backend | Auth |
|---|---|---|---|
| Azure Container Apps | native `secret` field with **Key Vault reference** | Key Vault | user-assigned MI |
| Any K8s | **External Secrets Operator (ESO)** with a `SecretStore` CRD | Key Vault / AWS Secrets Manager / GCP Secret Manager / Vault | Workload Identity per CSP |
| AWS (ECS/App Runner) | native task-def secret reference | Secrets Manager / Parameter Store | IRSA |
| GCP (Cloud Run) | native environment-from-secret reference | Secret Manager | Workload Identity |
| Multi-cloud OSS | **ESO + HashiCorp Vault** | Vault | JWT/OIDC |
| Dev/local | file / `sops`-encrypted git | files | GPG/age |

**Rules (MUST):**

- The core reads secrets **only** through the injected `SecretProvider` interface in
  `shared/providers/` ([project-structure.md](project-structure.md#injectable-seams)); no
  `SecretClient` from any vendor SDK appears in `core/`.
- **Secret names follow a stable schema** (upper-snake env var names) across all providers so
  the app is provider-blind.
- **Fail-closed**: if the injection layer cannot resolve a required secret at startup, the
  process fails fast - it never falls back to a cached or embedded value
  ([security-and-identity.md](security-and-identity.md#secrets-and-config)).
- **Rotation** is the injection layer's job; the app tolerates a rolled secret by re-reading
  env on process restart. Long-lived caches of decrypted secret material aren't supported.

**Anti-patterns (MUST NOT):**

- Calling `SecretClient.GetSecret()` (or the equivalent) from application code.
- Committing plaintext or encrypted secrets to source (SOPS in git is allowed **only** for
  dev/local; never for staging or prod).

## 4. Workload Identity Contract - OIDC Token

The executor authenticates to the CSP with a **short-lived OIDC token** obtained from the
runtime substrate; the token is exchanged for CSP credentials at the adapter boundary. No
long-lived key or shared secret is held by the executor.

| CSP / substrate | Workload identity primitive | Token exchange |
|---|---|---|
| Azure | User-assigned Managed Identity | IMDS → Entra token (SASL/OAUTHBEARER, ARM, KV) |
| AWS | IAM Roles for Service Accounts (IRSA) | pod token → `AssumeRoleWithWebIdentity` |
| GCP | Workload Identity Federation | K8s SA token → GCP STS |
| Any K8s | **SPIFFE/SPIRE** | SVID (JWT/X.509) exchanged per adapter |
| CI/CD | GitHub Actions OIDC / Azure DevOps federated credential | issuer → CSP-side federation trust |

**Rules (MUST):**

- The core sees only a `WorkloadIdentity` interface exposing "get a token audience-scoped to
  X"; the concrete token issuer is a provider-adapter concern.
- **Approval identity ≠ execution identity** ([security-and-identity.md](security-and-identity.md#execution-identity)).
  This holds across every CSP mapping above.
- **No long-lived keys** in the executor's process, config, or secret store. Where a
  CSP-side credential is unavoidable (e.g. legacy service), it MUST be short-lived and
  auto-rotated, and its use MUST be recorded in the audit log.

**Anti-patterns (MUST NOT):**

- `DefaultAzureCredential()` or any similarly named SDK entry point in `core/` - that is a
  vendor SDK call, not the contract. It is allowed **only** in the Azure provider adapter,
  behind the interface.
- Sharing the executor's identity with the console, ChatOps, or any read-only surface.

## 5. Inventory Contract - Resource Graph

The core reasons over an ontology graph of resources and typed edges
([llm-strategy.md § Ontology Foundation](llm-strategy.md#ontology-foundation)); the
**Inventory** contract is how that graph is populated and kept fresh. The core sees a
single `Inventory` Protocol with two operations returning CSP-neutral records:

- `full_snapshot(since=None) -> AsyncIterator[InventoryBatch]` - the initial or periodic
  reconciliation load, emitted as batches of typed `Resource` records and
  `contains` / `attached_to` / `depends_on` link records.
- `delta(cursor) -> AsyncIterator[InventoryBatch]` - incremental changes since the given
  cursor, driven by the provider's native change stream. The Azure adapter realizes this
  behind an injected `ActivityLogFetchFn` seam that pages the forwarded change stream into
  idempotent-upsert batches with an advancing cursor and the same `final=True` atomic-promote
  fence as `full_snapshot`. Two bindings satisfy the seam: the event-bus-native path (a
  Diagnostic-Settings-forwarded Kafka topic, the production default per the MUST below) and a
  direct Activity Log REST factory (`AzureActivityLogFactory`) for environments where the
  forwarder is not yet provisioned. With no fetch bound, `delta` returns an empty `final=True`
  fence.

The read-only console consumes a separate projection of the promoted graph through
`GET /inventory/graph`. The route is enabled only when
`ReadApiConfig.inventory_graph_provider` is injected. It returns CSP-neutral `Resource`
records plus `contains` / `attached_to` / `depends_on` links, snapshot freshness, and
truncation metadata. The route never calls Azure Resource Graph directly and never receives
the executor identity.

The projection publishes named architecture views. The default view is FDAI's own control
plane; additional `application` views partition the services FDAI can judge and observe.
Supplying `scope=<view-id>` returns that view's bounded resource and link set while preserving
the same CSP-neutral wire contract.

| CSP / substrate | Inventory source | Delta source | Wire |
|---|---|---|---|
| Azure | **Azure Resource Graph** (Kusto over ARM) | Activity Log via the [event-bus](#1-event-bus-contract--kafka-wire-protocol) contract (a Diagnostic-Settings-forwarded Kafka topic) | HTTPS + `Authorization: Bearer <OIDC>` |
| AWS *(TBD)* | AWS Config + Resource Explorer | Config configuration-item stream forwarded to Kafka | HTTPS + SigV4 |
| GCP *(TBD)* | Cloud Asset Inventory | Asset feed forwarded to Kafka | HTTPS + Google IAM |
| Any K8s | `apiserver` list-watch through a resource-model translator | `watch` stream forwarded to Kafka | HTTPS + service-account token |

**Rules (MUST):**

- The core reads inventory only through the injected `Inventory` interface in
  `shared/providers/` ([project-structure.md § Injectable Seams](project-structure.md#injectable-seams)).
  No `ResourceManagementClient`, `ArmClient`, `boto3.client("config")`,
  `google.cloud.asset` - no cloud-inventory SDK appears in `core/`.
- Records are **CSP-neutral** at the wire: `Resource.type` is the canonical `resource_type`
  vocabulary ([rule-catalog-collection.md](../rules-and-detection/rule-catalog-collection.md#collection-sources))
  and link kinds are the ones declared in
  `shared/contracts/ontology/link-type.json`. Vendor-native ids may ride in a redacted
  `provider_ref` field on the Resource, never as the primary key.
- **Initial full snapshot is parallelized** with bounded concurrency: the adapter shards the
  workload by `ResourceType` (and further by scope when a single type is too broad), fans
  out queries under a semaphore, and streams batches into the ingest pipeline. The core
  never assumes a single-connection blocking scan.
- **Idempotent upsert** into `ontology_resource` + `ontology_link` keyed by the neutral
  `resource_id` and `(from_id, link_type, to_id)`; re-running the full scan converges the
  graph, it never duplicates.
- **Fail-closed**: a partial snapshot never lands in a state that would let a stale graph
  drive an autonomous decision. Either the snapshot completes and is atomically promoted,
  or the previous graph is retained and the failure is audited.
- **Deltas flow through the event bus**, not through a separate side-channel. A provider
  change signal (Activity Log, Config item, Asset feed, apiserver watch) is forwarded into
  a Kafka topic and consumed exactly like any other `Signal` - same idempotency, same DLQ.
- **Unknown `ResourceType` or LinkType** opens an issue and is dropped; the adapter never
  auto-registers a new ontology type at runtime
  ([llm-strategy.md § Fork Extension](llm-strategy.md#fork-extension-self-extending-ontology)).
- Untrusted vendor properties (tags, descriptions) MUST be redacted or length-bounded
  before write and are inert data, never instructions.

**Anti-patterns (MUST NOT):**

- Importing `azure-mgmt-*`, `boto3`, or `google-cloud-*` clients from `core/`. Cloud
  inventory SDKs live only in the provider adapter package.
- Embedding Kusto / ARG queries inside `core/` code paths (they belong in the Azure
  adapter, driven by manifest or query template).
- Running the initial full scan under a global lock, or under the executor's
  per-resource lock; inventory sync and remediation execution are separate concerns with
  independent concurrency budgets.
- Trusting a partial delta stream as authoritative; the periodic full-snapshot
  reconciliation is required to catch dropped events.

### Azure inventory under restricted NSG egress

An NSG-locked subnet should not turn an unreachable discovery source into an empty
inventory. FDAI treats network reachability, identity, collection, and projection as
separate stages, and records which stage failed. An empty successful snapshot means "no
resources in scope"; a blocked endpoint, token failure, incomplete page set, or unavailable
collector means "inventory unavailable" and retains the last complete snapshot.

#### Required network paths

Run the reachability probe from the subnet and identity that will execute discovery, not
from an operator laptop. The exact rules depend on the runtime and Azure cloud, but the
deployment should account for these paths:

| Purpose | Preferred path | Restricted-network options | Notes |
|---|---|---|---|
| ARG and ARM management reads | HTTPS `:443` to the Azure Resource Manager endpoint | NSG egress to the `AzureResourceManager` service tag; UDR through Azure Firewall or an approved proxy with a narrow management-endpoint allowlist; Resource Management Private Link when the target cloud, region, and required ARG operation support it | A private endpoint for a data service does not provide ARM or ARG connectivity. Azure service endpoints are not a replacement for the ARM management path. |
| Workload token | Runtime-provided managed identity or workload identity endpoint | Allow the runtime platform identity path, including `AzurePlatformIMDS` where IMDS is used; use federated workload identity from an approved runner when the app subnet cannot mint a token | Do not add broad Internet egress or a client secret merely to make discovery work. |
| DNS | Azure-provided DNS or an approved custom resolver | Permit the runtime's platform DNS path, including `AzurePlatformDNS` where applicable; forward the required public or Private Link zones through the hub resolver | Resolve and TLS-probe the endpoint before starting a scan. DNS success alone is not reachability. |
| Snapshot publication | Private PostgreSQL and Event Hubs paths | Private endpoints, VNet peering, or hub routing from the discovery runner | The collector never sends inventory through a public console endpoint. |

Service tags and Resource Management Private Link capabilities can differ by Azure cloud and
can change over time. Confirm the effective routes, DNS answers, and supported operations
during deployment preflight. Prefer service tags or private connectivity over copied IP
ranges, and avoid TLS interception unless the Azure endpoint and client trust model have
been validated explicitly.

#### Ordered fallback ladder

Use the first method that can produce a complete, bounded snapshot for the declared scope.
Changing transport does not change the `Inventory` contract.

1. **ARG from the runtime subnet** - run the sharded `Resources` queries with managed
   identity over an explicitly allowed ARM management path. This remains the default because
   it provides broad cross-resource discovery and bounded pagination.
2. **ARG from a connected discovery job** - move the same read-only adapter to a
   VNet-integrated Container Apps Job or the self-hosted ops runner when the application
   subnet intentionally has no management-plane egress. Publish batches to the private state
   store or Kafka ingress; do not give the console or core executor identity to the job.
3. **Resource Management Private Link path** - where Azure supports the required ARG calls,
   route the connected job through the approved private endpoint and private DNS. Preflight
   must execute a real bounded ARG query because private DNS resolution alone does not prove
   operation support.
4. **Direct ARM list adapters** - list each registered resource provider and resource type in
   bounded, paged shards when ARG is unavailable or exceeds the freshness budget. The adapter
   normalizes the same resource and link records and reports unsupported types as coverage
   gaps. Azure CLI and Azure SDK clients are transports for this method, not independent
   inventory sources.
5. **Authoritative scoped inventory** - use Microsoft Defender for Cloud Inventory or another
   approved Azure inventory projection only for resource types and subscriptions its coverage
   manifest declares authoritative. Supplementary findings never imply full estate coverage.
6. **Change-stream continuity** - continue consuming Activity Log changes forwarded through
   Event Hubs while a full-snapshot source is temporarily unavailable. Deltas preserve
   freshness for known resources but cannot bootstrap a graph or prove that unseen resources
   do not exist.
7. **Declarative recovery snapshot** - import an approved Terraform state/plan export, Azure
   deployment export, or signed declarative inventory file when no live management path is
   available. Mark it `expected` rather than `observed`, attach its generation time and scope,
   and use it for read-only context only. It cannot authorize autonomous remediation.

The ladder is not "try every source and union the rows." Each attempt emits a coverage
manifest containing source, subscription or management-group scope, resource types, start and
completion time, page counts, and errors. FDAI promotes a source only after every declared
shard reaches its final fence. A lower-priority source can replace an unavailable source for
its declared coverage, but it cannot silently fill unknown gaps or overwrite a newer
authoritative record.

The Azure implementation prefixes every neutral resource id with an opaque hash of its
subscription scope. This prevents equal resource-group and resource paths in different
subscriptions from colliding without exposing the subscription id in the ontology key. ARG
provides `contains`, `attached_to`, and `depends_on` topology. Direct ARM fallback currently
declares `contains` coverage only, so the active projection reports the missing link kinds and
stays degraded for dependency-absence decisions.

#### Failure and freshness policy

- **Preflight first:** verify token acquisition, DNS, TCP/TLS, one bounded query, pagination,
  and write access to the private projection before enabling the schedule.
- **Classify failures:** distinguish `network_blocked`, `dns_failed`, `token_failed`,
  `forbidden`, `throttled`, `partial`, and `source_unavailable`. A zero-row result is never
  used as the error fallback.
- **Retain last known good:** failed or partial scans keep the last complete snapshot and mark
  it stale. They do not replace it with an empty graph.
- **Preserve authority:** an older attempt, a lower-priority source from the same run, or an
  `expected` declarative candidate cannot replace a newer observed snapshot.
- **Degrade autonomy:** when snapshot age exceeds the configured freshness budget, graph-based
  blast-radius decisions and absence claims move to human review. Read-only display may use
  the stale graph when it shows source, age, scope, and degraded status.
- **Keep principals separate:** the discovery identity receives minimum read permissions on
  only the declared scopes. It is distinct from the privileged executor, console identity,
  and approval principal.
- **Audit transitions:** source selection, fallback activation, coverage loss, recovery, and
  snapshot promotion produce structured audit records and metrics.

Example: an NSG denies direct application-subnet egress to ARM. The preflight reports
`network_blocked`, the scheduled scan moves to the VNet-integrated ops runner, ARG completes
through the hub's approved management path, and only the final complete snapshot is promoted.
If the runner also loses reachability, FDAI retains the previous graph, marks it stale, and
routes blast-radius-dependent actions to human review.

## 6. Metric Query Contract - CSP-Neutral Sample Iterator

Consumes external metrics (Prometheus, Azure Monitor Logs, CloudWatch, Datadog) via
`MetricProvider.query(MetricQuery) -> AsyncIterator[MetricPoint]`
([`shared/providers/metric.py`](../../../src/fdai/shared/providers/metric.py)).
`MetricQuery` is vendor-neutral (`metric_name`, `labels`, `since`, `until`, `aggregation`
hint); the adapter maps the CSP-neutral name to its vendor namespace and honors the
hint on a best-effort basis. Upstream ships `NoopMetricProvider` (empty result) +
`StaticMetricProvider` (test double); Azure adapter lands under `delivery/azure/`.

**Design rules:**

- Async by contract (an external metric query is I/O-bound and would otherwise block
  the event loop, matching § 1 / § 3 / § 4 / § 5).
- Empty result IS a valid answer (no samples in the window ≠ error).
- The caller MUST NOT auto-remediate on a partial result; abstain and route to HIL
  per [architecture.instructions.md § Safety Invariants](../../../.github/instructions/architecture.instructions.md#safety-invariants).

## 7. Log Query Contract - Structured Log Records

Consumes structured logs (Log Analytics KQL, Loki LogQL, Elasticsearch, CloudWatch
Logs) via `LogQueryProvider.query(LogQuery) -> AsyncIterator[LogRecord]`
([`shared/providers/log_query.py`](../../../src/fdai/shared/providers/log_query.py)).
The `expression` field carries the vendor-specific query string; `labels` carry the
CSP-neutral pre-filter the adapter maps to its label surface. Kept separate so a caller
can compose a CSP-neutral filter with a vendor-specific tail without hard-coding the
tail into `core/`.

## 8. Trace Query Contract - Distributed-Trace Spans

Consumes spans (App Insights, Tempo, Jaeger, Honeycomb) via
`TraceQueryProvider.query(TraceQuery) -> AsyncIterator[Span]`
([`shared/providers/trace_query.py`](../../../src/fdai/shared/providers/trace_query.py)).
`Span` carries `trace_id`, `span_id`, `parent_span_id`, `service`, `operation`, `start`,
`duration`, `status`, and CSP-neutral `labels` so RCA can walk a request across services
without knowing which backend recorded it.

**Design rules for § 6 - § 8** (shared):

- The three telemetry-ingestion Protocols exist so anomaly detection, SLO burn-rate
  evaluation, and RCA can ground on real telemetry rather than only on rule / policy
  citations. Their design contract lives in
  [scope-expansion.md § 3.2](../fork-and-sequencing/scope-expansion.md).
- Upstream defaults are no-op providers so downstream consumers can be authored
  against a stable interface before any concrete adapter is wired.
- Vendor SDK imports stay confined to `delivery/<vendor>/`; `core/` imports only the
  Protocol - enforced by [`scripts/check-core-imports.sh`](../../../scripts/check-core-imports.sh).

## Azure-Phase Realization (Summary)

Today's implementation slots into the four contracts as follows. Every named service is a
**recommendation to confirm at adoption time** ([tech-stack.md](tech-stack.md)); the
contract is what does not change.

| Contract | Azure realization | Idle cost posture |
|---|---|---|
| Event bus | **Event Hubs Standard** (Kafka endpoint on `:9093`, 1 TU, auto-inflate off) | low idle; scales on TU |
| Runtime | **Container Apps** (Consumption, KEDA scale-to-zero) - one app + sidecars | `$0` when idle |
| Secret | Container Apps native secret + **Key Vault reference** | negligible |
| Workload identity | **User-assigned MI** + workload identity federation for CI/CD | free |
| Inventory | **Azure Resource Graph** (initial parallel full-scan sharded by `resource_type`) + **Activity Log** delta forwarded to a Kafka topic | free (ARG); Log-based delta covered by the observability inventory |

`Service Bus` and `Event Grid` are **not** in the minimum inventory going forward; the
event bus is Kafka wire only. Any provider-native pub/sub is used solely as a **source of
events into the Kafka bus** (e.g. an Event Grid subscription that forwards to an Event Hubs
Kafka topic) and never as a runtime dependency of `core/`.

## Approved Alternative Azure Implementations

The five wire-level contracts already keep the core CSP-portable. This table lists the
**Azure-internal** alternates each contract may swap to, without touching `core/`. Swapping
**Azure-internal** alternates each contract may swap to, without touching `core/`. Swapping
happens at the **infra module boundary** - a fork picks a different sub-module under
`infra/modules/<seam>/` (or overrides the DI binding at the composition root when the
change is purely code-level). Everything in the "What stays" column is contract, not
implementation, and is preserved across the swap; anything in "What changes" is confined to
the swapped module and its immediate config.

| Seam | Day-zero default | Approved alternates (Azure) | What changes on swap | What stays (contract) |
|------|------------------|-----------------------------|----------------------|------------------------|
| Event bus | Event Hubs Standard (Kafka `:9093`) | Kafka on AKS via **Strimzi**; **Confluent Cloud** (multi-cloud managed); **Redpanda** on AKS | broker endpoint, auth mechanism, cost profile | Kafka wire protocol, topic + DLQ naming (`<topic>.dlq`), idempotency key, ordering-by-partition-key |
| Runtime | Container Apps (Consumption + KEDA) | **AKS** + Knative Serving + KEDA; **Azure Functions** (Premium plan) for burst / bindings; **App Service** where a public HTTPS surface is unavoidable | scale trigger rendering, probe wiring, sidecar layout | OCI image, Knative-compatible manifest subset, `/healthz` + `/readyz` contract, scale-on:kafka-lag signal |
| State store | PostgreSQL Flexible + `pgvector` | **Cosmos DB** (SQL API) when RU-metering and geo-write outgrow a single primary; **Azure SQL Managed Instance** when TDE / SQL-Server compat is mandated | SQL dialect, migration tool, RU cost model | audit hash-chain schema, versioned event/action/rule contracts, `SchemaRegistry`+`ContractValidator` seams |
| Vector store | `pgvector` (co-located with the state store) | **Azure AI Search** vector index; **Qdrant** / **Milvus** on AKS | index type (HNSW/IVFFlat), distance metric, refresh path | embedding dimension, model choice (configured), T1 similarity threshold |
| Secret | Container Apps native `secret` + Key Vault reference | **AKS + External Secrets Operator** with a `SecretStore` CRD pointing at Key Vault; **Key Vault Premium** (HSM-backed) for FIPS-regulated data | injection layer (Container Apps native ↔ ESO) | env-var-only reads, upper-snake env names, fail-closed on startup, no SDK calls in `core/` |
| Workload identity | User-assigned MI | **Federated workload identity** (GH Actions OIDC ↔ Entra federated credential; AKS workload identity federation); **System-assigned MI** where the resource principal is single-owner | trust configuration and token audience | `WorkloadIdentity` interface, JIT-scoped roles, deny cross-domain assumption |
| Container registry | ACR Basic | **ACR Standard/Premium** (geo-replication, private endpoint); **GHCR** or **Docker Hub** as external registries | tier cost, signature + attestation location | pin-by-digest, no `latest`, SBOM + provenance recorded |
| Observability | Log Analytics workspace + App Insights bound to it | Application Insights standalone; **Grafana Managed for Azure** + Prometheus + Loki; a vendor APM behind the OTel exporter | dashboards, alert rules, retention pricing | OpenTelemetry SDK, `correlation_id`, one telemetry source per KPI |
| HIL chat | Azure Bot (Free tier) via Bot Framework / Teams | **Custom webhook adapter** on a Container App; Slack native bot via the [`chatops`] delivery adapter | authenticated transport, Adaptive Card renderer | approval-message contract, action-bound HIL id, fail-closed timeout |
| Read-only console hosting | Static Web Apps (Free) | Storage static-website + **Front Door**; **App Service Static Sites** | HTTPS surface, custom domain wiring | read-only guarantee, Entra sign-in, no privileged calls |
| Inventory | Azure Resource Graph + Activity Log delta | Direct **ARM list** polling (per-resource-type, sharded) for tenants where ARG lags; **Microsoft Defender for Cloud Inventory** when its coverage is authoritative for the target set | query language (Kusto vs REST), delta cursor semantics, freshness lag | `Inventory` Protocol shape, CSP-neutral `resource_type` + link kinds, idempotent upsert, fail-closed partial snapshot |

**Rules across the whole table (MUST):**

- Every alternate uses the **same output contract** its default module exposes
  (`endpoint`, `identity_resource_id`, `secret_ref_envelope`, `event_topic_names`, ...) so
  downstream Terraform / `main.tf` composition never branches on the alternate.
- Alternates ship as **separate Terraform sub-modules** under `infra/modules/<seam>/`,
  selected by a top-level `var.<seam>_kind` (e.g. `var.runtime_kind = "container_apps"`).
- Any alternate MUST honor the **naming convention** in
  [deploy-and-onboard.md § Resource Naming Convention](../deployment/deploy-and-onboard.md#resource-naming-convention);
  a swap does not license a hand-picked name.
- Alternates are **build-when-needed**: only the default lands with W4.1. Adding an
  alternate is its own PR with its own shadow-mode validation.
- No alternate is allowed to re-introduce a vendor SDK dependency in `core/`. That is the
  original CSP-neutrality rule and it wins.

## Non-Azure Path (Additive)

Adding another CSP is a **fork-level configuration exercise**, not a core change:

1. Register a new implementation of the five provider interfaces in `shared/providers/` at
   the composition root ([project-structure.md](project-structure.md#customization-via-dependency-injection)).
2. Point `bootstrap.servers`, the `SecretProvider`, the `RuntimeAdapter`, the
   `WorkloadIdentity`, and the `Inventory` bindings at the new CSP.
3. Render the same OCI image + Knative-compatible manifest into the target runtime.
4. Ship in **shadow mode** ([architecture.instructions.md](../../../.github/instructions/architecture.instructions.md#safety-invariants))
   until parity with the Azure implementation is measured.

**Non-Azure targets remain TBD**
([Implementation Focus](../../../.github/copilot-instructions.md#implementation-focus-must));
the contract exists so a future adapter is additive.

## Anti-Patterns (concise)

- Wrapping each CSP's native pub/sub (`Service Bus` + `SQS/SNS` + `Pub/Sub`) behind one
  interface. Ack semantics, ordering keys, DLQ shapes, and exactly-once behavior diverge
  enough that provider-specific bugs leak through - **use one wire protocol (Kafka) instead**.
- Introducing **Dapr** as a portability layer. It moves the lock-in from the CSP to Dapr,
  adds a sidecar dependency, and complicates local dev.
- Using **Event Hubs via the native AMQP SDK** to "save on Kafka client complexity." That
  re-Azurizes the code. Use the Kafka endpoint or don't use Event Hubs.
- Reading secrets by calling `SecretClient` from application code (see contract 3).
- `DefaultAzureCredential()` (or its equivalents) inside `core/` (see contract 4).

## Related Docs

| To learn about | Read |
|----------------|------|
| The concrete stack that realizes these contracts | [tech-stack.md](tech-stack.md) |
| The Azure resource inventory rendered from the contracts | [deploy-and-onboard.md#azure-resource-inventory-minimum-set](../deployment/deploy-and-onboard.md#azure-resource-inventory-minimum-set) |
| The identity model and secret handling in depth | [security-and-identity.md](security-and-identity.md) |
| The DI seams that expose each contract to the composition root | [project-structure.md#injectable-seams](project-structure.md#injectable-seams) |
