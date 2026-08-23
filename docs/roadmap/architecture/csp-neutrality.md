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

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Event bus, runtime, secret, and workload-identity contracts | implemented | `shared/providers/`; `delivery/azure/`; `infra/modules/event-bus/`; `infra/modules/compute/`; `infra/modules/secret-store/`; focused adapter and infrastructure tests | Azure uses Kafka on Event Hubs, OCI Container Apps, native secret references, and workload identity behind provider-neutral contracts. |
| Inventory collection, complete-generation relationships, and bounded graph projection | implemented | `shared/providers/inventory.py`; `delivery/azure/generation_relationships.py`; `delivery/inventory_sync.py`; `delivery/inventory_live_evidence.py`; `core/ontology_platform/graph_evidence_refresh.py`; focused inventory, relationship, refresh, and projection tests | Continuous collection, exact relationship evidence and explicit drop reasons, atomic promotion, graph-first refresh decisions, safe live-evidence write-through, and bounded read projections are implemented. Ordinary semantic query composition does not yet bind refresh selection and live write-through end to end. Deployed completeness remains separate validation evidence. |
| Metric, log, and trace query contracts | implemented | `shared/providers/metric.py`; `log_query.py`; `trace_query.py`; `delivery/azure/metric_logs.py`; `delivery/azure/log_query.py`; `delivery/azure/telemetry_query.py` | Azure Monitor and Log Analytics adapters exist, while absent configuration intentionally leaves the no-op bindings active. |
| Governed operational evidence for all eight contracts | in-progress | [Deploy and Onboard implementation status](../deployment/deploy-and-onboard.md#implementation-status); observation campaign adapters under `delivery/azure/` | Independent-service deployment is validated, but this owner document does not retain one current governed campaign proving every inventory and telemetry contract together. |
| Non-Azure provider implementations | deferred | [Implementation Focus](../../../.github/copilot-instructions.md#implementation-focus-must) | Contract shapes are retained for portability. No AWS, GCP, or other provider adapter is in the approved implementation scope. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-19 | implemented | Aligned the scheduled inventory reconciliation CLI with the composition binding for unclassified provider identities. The CLI already attached provider-scope coverage but omitted the bounded unmapped-resource callback, so its ARG source could not produce an identity-complete 1.1 fence even though the composed adapter could. ARG now binds both callbacks, while the ARM fallback binds neither. | [Issue #217](https://github.com/dotnetpower/fdai/issues/217); the source-specific wiring regression and the full inventory job configuration file pass 18 focused cases; task-scoped Ruff and strict mypy pass. | Promote a fresh full reconciliation from this revision and verify the 1.1 coverage receipt, snapshot-to-ontology identity parity, and empty realtime overlay. |
| 2026-08-19 | validated | Bound operating-scope coverage into the authenticated read-only inventory graph route. Each bounded response Resource carries `service_ref`; an absent or conflicting reviewed mapping is `unknown_service`, and input truncation or any unmapped result degrades the response with an explicit gap. | [Issue #217](https://github.com/dotnetpower/fdai/issues/217); 4 focused consumer tests and strict mypy pass; a read-only loopback response annotated 213/213 Resources and retained `operating_scope_unmapped`. | Supply deployment-reviewed service mappings; the route and completeness receipt are implemented. |
| 2026-08-19 | implemented | Added identity-level closure for provider types outside the reviewed neutral vocabulary. The Azure adapter reads those rows through a separate bounded ARG query, materializes them as the single reviewed `unclassified-resource` type, and accepts the generation only when provider-type identity counts exactly match the final-fence coverage aggregate. The reserved type has no provider mapping or query terms and grants no type-specific rule or action support. | [Issue #217](https://github.com/dotnetpower/fdai/issues/217); focused provider, sync, ARG, Azure inventory, composition, CLI, ontology, catalog, and value-domain checks pass 259 cases; task-scoped Ruff and strict mypy pass. | Promote one fresh full reconciliation and verify identity-complete coverage, snapshot-to-ontology parity, and realtime-overlay cleanup before changing this row to `validated`. |
| 2026-08-19 | validated | Hardening Round 3 rechecked 12 count, fence, cancellation, ARG, normalization, fallback, seed recovery, precedence, catalog ownership, parent parsing, graph parity, and evidence lenses. No verified Medium-or-higher defect remains. Eleven observations are Low guard confirmations or optional diagnostics, and one precedence concern was rejected after tracing the exact mapping path and retained live parity. | [Issue #216](https://github.com/dotnetpower/fdai/issues/216); Round 3 reviewed current HEAD after the Round 1 exact-parent guard and Round 2 count-shape guard; the focused suites, retained 533/57/15 coverage, 2/2 SQL snapshot-to-ontology parity, and signed framework snapshots remain the evidence boundary. | None for issue #216 hardening. |
| 2026-08-19 | implemented | Hardening Round 2 reviewed 14 contract, fence, query, fallback, mapping, parent, verifier, digest, and evidence concerns. One Medium defect was accepted independently of the proposed findings: Python booleans passed as integer counts, and an impossible positive-object/zero-type manifest was valid. Coverage counts now require exact integers, zero object and type counts agree, and observed type count cannot exceed object count. The repeated unseeded-generation, ARG filter, shard/fence, overlapping-glob, malformed parent, parent evidence, and digest concerns were rejected against focused tests, the exact-string mapping grammar, bounded request timeouts, complete-generation verification, and retained live 533/57/15 plus SQL parity evidence. | [Issue #216](https://github.com/dotnetpower/fdai/issues/216); six negative cases fail before the guard and seven cases including `ProviderTypeCount` boolean rejection pass after it. | Run Round 3 with at least 10 lenses to confirm only Low or rejected observations remain. |
| 2026-08-19 | implemented | Hardening Round 1 reviewed 13 coverage, fence, query, mapping, cardinality, and evidence concerns. One Medium defect was accepted: two exact parent-containment mappings for one source type could pass catalog load and later freeze ontology projection. The loader now rejects that ambiguous ownership before provider I/O. Empty provider scope, coverage failure after resource yield, null ARM mappings, enum decoding, and final-fence concerns were rejected because the final fence is execution evidence, all Azure coverage work completes before any resource batch is yielded, and the typed loader/tests already enforce those boundaries. | [Issue #216](https://github.com/dotnetpower/fdai/issues/216); the new catalog regression fails before the guard and passes after it; focused provider mapping, ARG, and relationship verification remain the validation surface. | Run a second 10-or-more-lens review to confirm no Medium-or-higher defect remains; the truncated-observation drop detail and timestamp precision observations are Low. |
| 2026-08-19 | validated | Promoted the corrected SQL containment generation and verified parity between the active inventory snapshot and ontology read model. Every observed SQL database has one logical-server `parent_id` and one `contains(sql-server, sql-database)` edge in both stores. No ontology observer failure was emitted. | [Issue #216](https://github.com/dotnetpower/fdai/issues/216); one-shot job reported `inventory snapshot promoted from arg`; loopback PostgreSQL reports 2 snapshot SQL databases, 2 with parent ids, 2 snapshot SQL edges, 2 ontology SQL databases, and 2 ontology SQL edges. | None for SQL logical-parent containment. |
| 2026-08-19 | implemented | Corrected SQL containment after live projection showed that retaining both the wildcard resource-group parent and the exact logical-server parent violates `contains` one-to-many cardinality. For the same contained child, an exact source-type `contains` mapping now shadows the wildcard mapping. Different child levels remain independent, so resource-group-to-VNet and VNet-to-subnet containment both remain. `Resource.parent_id` uses the same reviewed exact mapping as the edge. | [Issue #216](https://github.com/dotnetpower/fdai/issues/216); the promoted snapshot succeeded but ontology projection failed with `contains violates one_to_many cardinality`; SQL and VNet controls plus the focused ARG, mapping-audit, and verifier suite pass 117 cases; strict mypy passes. | Commit the correction, rerun full reconciliation, and verify snapshot and ontology SQL containment agree. |
| 2026-08-19 | implemented | Added a reviewed Azure provider-parent mapping for `Microsoft.Sql/servers/databases`. The adapter resolves only a structurally valid immediate nested ARM parent and emits `contains(sql-server, sql-database)` while preserving the existing resource-group containment candidate. Missing parents or missing complete-generation endpoints produce no verified edge. | [Issue #216](https://github.com/dotnetpower/fdai/issues/216); focused ARG, exact mapping-direction audit, and complete-generation verifier checks pass 116 cases; task-scoped Ruff and strict mypy plus ontology and Property coverage gates pass. | Run one full reconciliation and verify the SQL server-to-database edge in the promoted snapshot and ontology projection. |
| 2026-08-19 | validated | Promoted one full ARG reconciliation with provider-scope coverage in the active local snapshot. The snapshot stores 516 materialized Resource rows separately from 533 provider-native objects: 476 objects map to the reviewed vocabulary and 57 objects across 15 provider types remain explicitly unmapped. The 40-row difference between mapped provider objects and snapshot Resources remains the previously measured nested-resource materialization plus subscription anchor, not hidden provider coverage. | [Issue #216](https://github.com/dotnetpower/fdai/issues/216); committed callback returned 533/476/57 objects and 68/15 types; the one-shot job reported `inventory snapshot promoted from arg`; the loopback PostgreSQL active row reports `source=arg`, `status=active`, `resource_count=516`, and the same coverage counts with all 15 type/count rows. | None for provider-scope coverage recording. SQL server-to-database containment remains the next inventory gap. |
| 2026-08-19 | implemented | Corrected the provider-scope Kusto pipeline after the first committed live probe returned HTTP 400. ARG accepts `Resources &#124; summarize ... &#124; union (...)`; it rejects the prefix form `union (Resources ...), (...)` used by the initial producer. The parser now pins the explicit `resource_count` aggregate column. | [Issue #216](https://github.com/dotnetpower/fdai/issues/216); the one-shot job retained the prior snapshot and reported both sources unavailable, an isolated callback reproduced `ArgQueryError` HTTP 400, the corrected read-only Azure CLI query returned bounded type/count rows, and focused ARG plus composition checks pass 99 cases. | Commit the repair and rerun the full reconciliation before claiming promoted 57-resource coverage evidence. |
| 2026-08-19 | implemented | Bound an Azure Resource Graph type aggregation to the full-snapshot fence. It counts raw `Resources` plus resource-group `ResourceContainers`, compares normalized provider types with the complete reviewed ARM vocabulary, and records every undeclared type and count without materializing it as a supported Resource. Subscription anchors and derived nested subnets stay outside this provider-scope measure. | [Issue #216](https://github.com/dotnetpower/fdai/issues/216); focused ARG, Azure inventory, composition, and inventory-job checks pass 136 cases; task-scoped Ruff and strict mypy pass. | Run one full reconciliation and verify the promoted metadata reproduces the retained 57-resource, 15-type measurement before treating it as runtime evidence. |
| 2026-08-19 | implemented | Added bounded provider-native scope coverage to the CSP-neutral `InventoryBatch` final fence and projected it into immutable snapshot metadata only during promotion. Counts reconcile before construction, non-final batches cannot carry the evidence, and static source metadata cannot impersonate a completed capture. | [Issue #216](https://github.com/dotnetpower/fdai/issues/216); focused provider-contract and inventory-sync tests pass 31 cases; task-scoped Ruff and strict mypy pass. | Bind the Azure scope-wide type aggregation producer and retain the measured unmapped counts in a promoted snapshot. |
| 2026-08-14 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance and recorded Azure contract implementations separately from operational evidence and deferred non-Azure adapters. | `current change`; provider, delivery, infrastructure, and deployment evidence listed in the scope table. | Retain one governed eight-contract campaign and keep non-Azure work deferred until explicitly scoped. |
| 2026-08-20 | implemented | Made inventory collection continuous without creating a second graph writer. The minute tick drains provider changes before its due check, a configurable floor coalesces change-triggered scans, all ARG shards share proactive pacing, reactive resets are capped, and each source has re-arming progress plus absolute deadlines. | [Issue #139](https://github.com/dotnetpower/fdai/issues/139); current source and focused ARG, inventory, scheduling, configuration, projection, and infrastructure checks. | Retain an exact-revision protected apply, measured minute cadence and cost, and one real provider-change reconciliation receipt before changing this scope to `validated`. |
| 2026-08-23 | implemented | Extended Contract 5 from snapshot and delta transport to complete-generation relationship evidence and graph-first read behavior. Reviewed provider mappings carry exact source and endpoint evidence, suppressed candidates retain typed drop and unavailable reasons, the pure refresh reducer selects one of five no-authority outcomes, and verified bounded live reads write through canonical partial overlays. Read-only Console projections preserve stored relationship type, direction, evidence, and incomplete coverage without becoming a second inventory source. | `current change`; [Continuous Operational Instance Graph](continuous-operational-instance-graph.md), [Network Topology Visualization](../interfaces/network-topology-visualization.md), `shared/providers/inventory.py`, `core/ontology_platform/graph_evidence_refresh.py`, `delivery/inventory_live_evidence.py`, and the focused checks recorded by those owner documents. | Bind refresh selection and live write-through into ordinary semantic query composition, retain an exact-revision governed campaign, and preserve deployed freshness, pressure, and cost evidence before raising the new slices to `validated`. |

### Remaining work

- [ ] Retain a governed Azure campaign receipt that binds the exact revision and proves event, runtime, secret, identity, inventory, metric, log, and trace behavior with failure and freshness cases.
- [ ] Bind graph refresh selection and live-evidence write-through into ordinary semantic query composition, then retain a composed receipt covering all five outcomes without observation, mutation, or execution authority.
- [ ] Retain exact-revision governed inventory graph and Console evidence that covers rooted traversal, relationship drop and unavailable reasons, stored-edge direction, truncation, incomplete-graph `unknown`, stale fallback, and no authority gain.
- [ ] Keep non-Azure adapters unimplemented until an approved target supplies contract-parity tests for ordering, replay, identity, inventory, and telemetry behavior.

## Principle

Anything the core touches from a cloud provider MUST be reached through **one wire-level
contract per concern**, not through a vendor SDK. The Azure implementation of each contract
is what we build today; a fork or a future phase adds another CSP by registering a new
implementation of the **same contract**, without editing `core/`.

**Concurrency**: the I/O-bearing provider seams are **async by default** (Kafka poll loop,
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
| Azure | **Event Hubs** (Kafka 1.0+ endpoint, `<ns>.servicebus.windows.net:9093`) | SASL/OAUTHBEARER with Entra token | Standard 1-TU namespace shards keep governed ingress separate from parser-specific operational signals |
| AWS | **MSK Serverless** | SASL/OAUTHBEARER with AWS IAM SigV4 | truly serverless (partition-hour billed) |
| GCP | **Managed Service for Apache Kafka** (GA) | SASL/OAUTHBEARER with Google IAM token | broker fleet is always-on; use the smallest cluster |
| Multi-cloud | **Confluent Cloud** / **Redpanda Cloud** / **Aiven Kafka** | SASL/PLAIN or SASL/OAUTHBEARER | escape hatch when vendor-lock even to a hyperscaler is unacceptable |
| Self-hosted | **Strimzi Kafka** on AKS/EKS/GKE, or **Redpanda** | SASL or mTLS | last resort; adds ops burden |

**Rules (MUST):**

- The core produces/consumes with a **Kafka client only** (e.g. `librdkafka`, `kafka-python`,
  `KafkaJS`, `Sarama`); no `ServiceBusClient`, `SqsClient`, `PubSubClient`, or any other
  vendor SDK is imported.
- The Azure adapter sets Kafka `connections.max.idle.ms` and `metadata.max.age.ms` equivalents to
  180,000 ms and rejects values at or above 240,000 ms. This follows the
  [Event Hubs Kafka client configuration](https://learn.microsoft.com/azure/event-hubs/apache-kafka-configurations)
  constraint and prevents reuse of sockets the managed broker already closed.
- The same adapter sets the documented Event Hubs producer request timeout to 60,000 ms, caps
  requests at 1,000,000 bytes, keeps the consumer heartbeat/session pair at 3,000/30,000 ms, and
  uses a one-second retry backoff after transport failures. Because aiokafka's OAUTHBEARER seam
  accepts only the token string, the adapter retains the injected `IdentityToken.expires_at` and
  deterministically staggers consumer restarts 30-45 seconds before expiry. The restart occurs
  between polls, never across caller processing, and preserves commit-after-yield at-least-once
  delivery.
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
  plus a redrive worker. Every provider writes the same JSON envelope with
  `original_topic`, `reason`, and the original object under `payload`; transport headers are
  not part of the redrive contract. Providers that offer native DLQ (Event Hubs does not) MUST
  be ignored in favor of the topic convention so behavior is uniform. A multiplexing adapter
  maps logical DLQ subscriptions onto the physical DLQ and restores the logical topic before
  redrive.
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
  cursor, driven by the provider's native change stream. In production, resource create,
  update, and delete signals enter the canonical Kafka ingress continuously. Huginn owns the
  real-time discovery ingress and publishes normalized `Event` records, while an injected
  inventory projector applies ordered resource, link, and tombstone deltas to a durable overlay.
  The Azure adapter also keeps a direct Activity Log REST factory (`AzureActivityLogFactory`)
  as a bounded recovery source. The periodic full snapshot remains authoritative for
  reconciliation and atomically replaces the base generation after repairing missed signals.

Complete generations can also emit reviewed provider relationships. Each candidate carries the
mapping revision, exact source property, provider endpoint types, observation receipt, freshness
ceiling, and stored direction before independent verification. A candidate that cannot close both
endpoints is not converted into an edge. Its bounded `RelationshipDrop` instead preserves a typed
drop reason and, when known, a stable unavailable reason such as `target_outside_active_generation`,
`target_provider_type_unmodeled`, or `reference_not_observed`.

The read-only console consumes a separate projection of the promoted graph through
`GET /inventory/graph`. The route is enabled only when
`OperatorApiConfig.inventory_graph_provider` is injected. It returns CSP-neutral `Resource`
records plus typed links such as `contains`, `attached_to`, `depends_on`, `peered_with`, and
`routes_to`, snapshot freshness, and
truncation metadata. The route never calls Azure Resource Graph directly and never receives
the executor identity. Each returned Resource also carries a reviewed operating-scope
`service_ref`. A bounded reverse lookup over `workload_runs_on` and `implemented_by` emits
`unknown_service` for no mapping or conflicting mappings, and the response degrades when that
coverage is unmapped or truncated.

The Console can derive instance-focus and Network presentations from the same authoritative
response, as defined by [Network Topology Visualization](../interfaces/network-topology-visualization.md).
These read-only projections preserve stored relationship type, source, target, mapping evidence,
freshness, and completeness. Layout order never becomes traffic or reachability evidence, and an
incomplete relationship set returns `unknown` instead of claiming that no observed path exists.

A resource-centered request supplies `root=<resource-id>`, `depth=1..8`, and
`limit=1..1000`. The provider traverses both incoming and outgoing allowlisted links over the
active snapshot plus its ordered real-time overlay inside one repeatable-read, read-only database
transaction. It returns only the bounded neighborhood and sets `truncated=true` when either the
resource or relationship cap is reached. An unknown root
returns `404`; it never widens to a named view or the complete inventory. This rooted mode lets
the console expand one resource at a time without loading a large tenant graph. `scope` and `root`
are mutually exclusive, and a custom `limit` is accepted only with `root`. Relationship filters
accept at most 64 repeated `link` values, and each `link` or comma-separated `include` value is
bounded to 512 characters before parsing. Within one depth, traversal orders edges deterministically
and expands unseen neighbors round-robin by frontier resource, so one high-degree resource cannot
consume every remaining result slot. Local and deployed providers also sort internal relationships
and return at most `max(64, limit * 8)` edges, marking the neighborhood truncated when more exist.
When truncated, providers return stable machine reasons from `resource_limit`,
`adjacent_edge_limit`, `internal_edge_limit`, and `source_limit`. Unknown or contradictory reason
metadata fails closed at the read route.

The projection publishes named architecture views. A request without `scope` returns only
FDAI's own control plane, identified by the authoritative `fdai:managed=true` plus
`fdai:workload=fdai` inventory-tag pair. An unambiguous accepted service tag whose value is
exactly `fdai` is also reserved as an FDAI ownership signal for helper resources that don't carry
the full pair. Parent resource-group and subscription boundaries may be included to preserve
containment, but unrelated resources aren't included. When neither ownership signal is present,
the default remains an empty FDAI view instead of widening to the whole subscription.

Additional views partition non-FDAI resources with deterministic evidence:

- **Service view**: a non-empty service tag identifies the service. The accepted keys are
  `fdai:service`, `service`, `application`, `app`, `workload`, and `azd-service-name`.
  Providers don't infer service identity from resource names. When accepted keys resolve to
  conflicting values, classification is ambiguous and uses the resource-group fallback. A
  service view may contain resources from more than one resource group and includes the required
  parent boundaries.
- **Resource-group fallback view**: when a resource has no usable service tag, its containing
  resource group becomes the view boundary. This fallback preserves observed structure without
  inventing a service identity.

Supplying `scope=<view-id>` returns that view's bounded resource and link set while preserving
the same CSP-neutral wire contract. View metadata records `kind=fdai|service|resource_group`
and the classification evidence (`ownership_tag`, `service_tag`, or `resource_group_fallback`).
A named-view provider returns `404` when an explicit view id isn't registered; it doesn't
substitute the default view. The console can then load the default manifest to show the
registered recovery links. The Postgres production projection and local Azure CLI projection
use the same view-classification rules so local and deployed consoles keep the same meaning.

| CSP / substrate | Inventory source | Delta source | Wire |
|---|---|---|---|
| Azure | **Azure Resource Graph** (Kusto over ARM) | Activity Log resource changes through the [event-bus](#1-event-bus-contract--kafka-wire-protocol), normalized by Huginn and projected as an ordered overlay | HTTPS + `Authorization: Bearer <OIDC>` |
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
- **Provider scope coverage closes on the final fence.** A complete adapter may attach one bounded `ProviderScopeCoverage` to the terminal `InventoryBatch`. It distinguishes provider-native object
  and type counts from materialized snapshot records, lists only native types absent from the declared vocabulary, and reconciles mapped plus unmapped counts before construction. The sync
  coordinator copies this evidence into immutable snapshot metadata only after the final fence; a partial stream or static source manifest cannot claim completed provider coverage.
- **Coverage counts are exact bounded integers.** Boolean values are not counts. Zero provider objects require zero observed provider types and vice versa, and each observed type owns at least
  one object, so `provider_type_count` cannot exceed `provider_object_count`. Mapped and unmapped object counts must still reconcile exactly with the provider total.
- **Azure coverage counts provider-native rows, not projected graph objects.** The coverage query groups all ARG `Resources` and resource-group rows from `ResourceContainers` by normalized ARM
  type. It excludes the subscription anchor and derived nested resources such as materialized subnets, then compares those groups with the complete reviewed ARM vocabulary. A provider type
  absent from the vocabulary remains an explicit unmapped count and is never auto-declared.
- **Unclassified identity is visibility, not semantic support.** The Azure adapter queries every
  provider row outside the reviewed ARM vocabulary and maps only its bounded identity, native type,
  display fields, and containment parent to the reviewed `unclassified-resource` ResourceType. The
  final fence is withheld unless those identities reconcile exactly with every unmapped type count.
  The reserved type has no provider mapping or query terms, and no shipped Rule applies to it.
- **Exact containment owns one child over a wildcard fallback.** When an exact source-type mapping
  and a wildcard `contains` mapping both claim the same contained child, the exact mapping shadows
  the wildcard candidate. Mappings that contain different children remain independent. The same
  selected mapping supplies `Resource.parent_id`, so the object and edge cannot disagree.
- **Complete ARG reads page beyond 1,000 records**: Azure Resource Graph returns at most 1,000 records per response. Complete-result adapters set `$top` to at most 1,000, follow each `$skipToken` until exhaustion under a configured page cap, and order by a unique projected key such as inventory `id` or deployment-history `row_id`. Raw responses are capped at 10 MB per page and 64 MB per query before JSON projection.
  Every page consumes one query quota. A repeated token, a page-cap breach, or `resultTruncated=true` without a continuation token makes the read incomplete and fails closed. Bounded interactive reads instead request their explicit result cap plus one and report truncation. See [Guidance for pagination](https://learn.microsoft.com/azure/governance/resource-graph/concepts/paging-results).
- **ARG calls respect service quota signals**: one shared gate per adapter reads `x-ms-user-quota-remaining` and `x-ms-user-quota-resets-after` from every response and delays concurrent shards when quota reaches zero. HTTP `429` retries wait for `Retry-After`; transport failures, `408`, and selected `5xx` responses use bounded exponential backoff.
  Retry exhaustion fails closed instead of publishing a partial result. Fixed query-rate constants are not used because Azure can change the allocated quota. See [Guidance for throttled requests](https://learn.microsoft.com/azure/governance/resource-graph/concepts/guidance-for-throttled-requests).
- **Idempotent generation storage** stages a complete scan in
  `inventory_snapshot_resource` and `inventory_snapshot_link`, keyed by generation plus the
  neutral `resource_id` or `(from_id, link_type, to_id)`. A complete fence atomically swaps the
  `inventory_active` pointer. Ordered changes land in `inventory_realtime_resource` and
  `inventory_realtime_link` until the next generation covers them. Readers merge the active
  generation and overlay into one effective ontology-shaped resource graph; they don't dual-write
  scanned resources into the generic `ontology_resource` and `ontology_link` instance store.
  Snapshot staging converts and writes resources and links in chunks of 1,000 rows by default,
  permits a validated ceiling of 10,000, and keeps all chunks for one input batch in the same
  database transaction. After validation and endpoint locking, one delta event sends all
  reconciled realtime link upserts through one batched `executemany` pipeline and retains the
  aggregate applied-row count. Endpoint resource ids are deduplicated, sorted, and locked by one
  ordered PostgreSQL statement, preserving deadlock-safe order without one client round trip per
  endpoint.
- **Fail-closed**: a partial snapshot never lands in a state that would let a stale graph
  drive an autonomous decision. Either the snapshot completes and is atomically promoted,
  or the previous graph is retained and the failure is audited.
- **Deltas flow through the event bus**, not through a separate side-channel. A provider
  change signal (Activity Log, Config item, Asset feed, apiserver watch) is forwarded into
  a Kafka topic and consumed exactly like any other `Signal` - same idempotency, same DLQ.
- **Delta ordering is fenced by the active snapshot.** An observation at or before the active
  generation's start is already covered and becomes a no-op; an observation beyond the configured
  server-clock skew is rejected. Resource and link endpoint types must all belong to active
  coverage, and each event has a bounded link count. At equal observation time, delete wins over
  upsert so replay cannot resurrect a tombstoned resource; same-kind ties use event id.
- **Huginn owns real-time discovery ingress** while provider adapters own cloud parsing and
  point enrichment. The inventory projector owns durable resource, link, and tombstone
  application. Heimdall monitors freshness, delivery lag, fallback, and coverage degradation;
  it does not query the cloud inventory.
- **Continuous reconciliation remains required**. The Inventory path continuously combines the
  change stream, resumable deltas, and complete ARG/ARM reconciliation generations. A delta stream
  is never treated as proof of completeness. Durable source policy controls target freshness,
  minimum and maximum intervals, priority, request and byte budgets, concurrency, provider
  `Retry-After`, bounded backoff, and circuit state. The implemented deterministic scheduler selects
  one bounded next action from those inputs; deployed cadence, pressure, and cost remain operational
  validation evidence. A change is
  unreconciled when this control plane recorded it after the active snapshot started. One attempt
  has a re-arming no-progress deadline and an absolute ceiling, and all ARG shards share a
  sustained request budget. Local refresh and deployed workers share durable attempt transitions,
  active-pointer verification, and bounded activity publication. Recovery deltas serialize each
  scope before reading or advancing its cursor. Workers retain the read-only inventory identity,
  and Heimdall neither queries the provider nor starts collection. Retention, rollup, archive, and
  purge rules are owned by
  [Continuous Operational Instance Graph](continuous-operational-instance-graph.md).
- **Graph-first refresh is deterministic and authority-free**. The verified query requirement,
  current graph freshness and completeness, ontology release, conflicts, explicit live-read policy,
  deadline, and archive status reduce to exactly one result: `use_graph`, `refresh_then_query`,
  `use_live_evidence`, `query_archive`, or `hold`. The result chooses a bounded read path only. It
  carries no observation, mutation, or execution authority, and verified live evidence re-enters
  inventory through the canonical partial overlay without replacing complete properties or links.
- **Unknown `ResourceType` or LinkType** opens an issue and is dropped; the adapter never
  auto-registers a new ontology type at runtime. Full provider scans may preserve an otherwise
  unknown native resource identity only through the predeclared `unclassified-resource` type
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

The network paths, ordered source fallback, and freshness behavior for this deployment case are
owned by [Restricted-network Azure inventory](azure-inventory-network-paths.md).

## 6. Metric Query Contract - CSP-Neutral Sample Iterator

Consumes external metrics (Prometheus, Azure Monitor Logs, CloudWatch, Datadog) via
`MetricProvider.query(MetricQuery) -> AsyncIterator[MetricPoint]`
([`shared/providers/metric.py`](../../../services/core-control-plane/src/fdai/shared/providers/metric.py)).
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
([`shared/providers/log_query.py`](../../../services/core-control-plane/src/fdai/shared/providers/log_query.py)).
The `expression` field carries the vendor-specific query string; `labels` carry the
CSP-neutral pre-filter the adapter maps to its label surface. Kept separate so a caller
can compose a CSP-neutral filter with a vendor-specific tail without hard-coding the
tail into `core/`.

## 8. Trace Query Contract - Distributed-Trace Spans

Consumes spans (App Insights, Tempo, Jaeger, Honeycomb) via
`TraceQueryProvider.query(TraceQuery) -> AsyncIterator[Span]`
([`shared/providers/trace_query.py`](../../../services/core-control-plane/src/fdai/shared/providers/trace_query.py)).
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
  Protocol - enforced by [`scripts/quality/architecture/check-core-imports.sh`](../../../scripts/quality/architecture/check-core-imports.sh).

## Azure-Phase Realization (Summary)

The current Azure realization is the one recorded in the contract table and implementation ledger
above; confirm concrete tiers at adoption time. Provider-native event sources may forward into the
Kafka bus, but they never become a `core/` runtime dependency.

## Approved Alternative Azure Implementations

Azure-internal alternates swap at the infrastructure module or composition boundary without
changing `core/`. The contract column remains stable; only the selected module and configuration change.

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

Every alternate preserves the default module output contract, ships as a separate selected module,
follows the deployment naming convention, and receives its own shadow validation. An alternate
never introduces a vendor SDK dependency in `core/`.

## Non-Azure Path (Additive)

Adding another CSP is a **fork-level configuration exercise**, not a core change:

1. Register new implementations of the eight provider interfaces in `shared/providers/` at
   the composition root ([project-structure.md](project-structure.md#customization-via-dependency-injection)).
2. Point `bootstrap.servers`, `SecretProvider`, `RuntimeAdapter`, `WorkloadIdentity`,
  `Inventory`, `MetricProvider`, `LogQueryProvider`, and `TraceQueryProvider` at the new CSP.
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
