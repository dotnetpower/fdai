---
title: Code Map
---
# Code Map

This page maps each FDAI runtime service and shared package to its physical source, tests, and
owning design. Use it to find the current service-owned implementation without relying on the
retired top-level application tree.

> **Scope:** This map describes the validated local IS-08 repository ownership and IS-07 local
> upgrade and rollback proof. IS-09 owns the deferred remote verification.

## Design at a glance

- **Five service distributions:** Every runtime process owns one package under `services/`.
- **One shared SDK:** `packages/service-contracts/` contains cross-service contracts without service
  implementation.
- **Service-owned tests:** Unit and component tests live beside their owning service or package.
- **Virtual root:** The root `pyproject.toml` has `package = false` and coordinates the uv workspace.
- **Integration-only root tests:** `tests/integration/` owns cross-service compatibility, topology,
  and repository checks.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Service-owned source and test map | in-progress | This map, `tests/integration/`, and the scoped IS-08 and IS-07 evidence named above | Local ownership and rollback evidence are mapped; IS-09 remote verification remains open. |
| Exact-generation Rule retrieval | implemented | `shared/providers/catalog_search.py`; `delivery/catalog_search/generation.py`; `delivery/catalog_search/in_memory.py`; `delivery/catalog_search/postgres.py`; focused catalog, ontology query, schema, composition, and live PostgreSQL tests (`44 passed`) | Results are candidate-only, bind the active Rule generation to the exact ontology release and a bounded ordered-document manifest, and carry no judgment, approval, or execution authority. PostgreSQL activation checks the expected prior generation in the same transaction. |
| Objective-aware Rule candidate resolution | implemented | `core/ontology_platform/objective_rule_resolution.py`; `core/ontology_platform/catalog_queries.py`; `shared/providers/catalog_search.py`; `delivery/catalog_search/in_memory.py`; focused ontology query tests (`8 passed`) | Reviewed or promoted active relations narrow the exact-generation candidate set before ranking. Invalid or incomplete context falls back atomically, and objective context changes query identity without adding evaluation or execution authority. |
| Runtime-bound planner visibility | implemented | `composition/wire_semantic_query.py`; `core/conversation/semantic_manifest.py`; `core/ontology_platform/query_manifest.py`; focused composition and manifest tests | Planner descriptors expose only functions registered in the composed runtime. Readable but unbound declarations remain typed structural coverage and gain no authority. |
| Production Rule semantic readiness | implemented | `runtime/bootstrap.py`; `runtime/bootstrap_lifecycle.py`; `composition/wire_semantic_query.py`; `tests/runtime/test_catalog_semantic_bootstrap.py`; focused bootstrap and composition checks (`46 passed`) | Production startup registers Rule semantic search only when the active generation exactly matches the current Rule catalog, semantic schema, ontology release, and embedder dimension. Stable optional-readiness degradation preserves startup without exposing a stale function. |
| Durable Rule generation closure | implemented | `core/rule_semantic_generation/ledger.py`; `rule_catalog/schema/rule_semantic_generation_events.py`; focused contract and ledger checks (`15 passed`) | Core atomically binds the first terminal activation result to one lease-fenced pending publication record. Delivery state grants no semantic-index, policy, approval, mutation, or execution authority. |
| Read-investigation activity identity | implemented | `composition/wire_read_investigation.py`; `test_wire_read_investigation.py`; focused tests | Each invocation shares one opaque correlation across live and durable activity, separate invocations use distinct correlations, and logical request idempotency remains stable. |
| Cross-service semantic Rule projection | implemented | `fdai_service_contracts/semantic_turn.py`; `fdai_core_service/semantic_turn_processor.py`; `fdai_operator_service/postgres_semantic_turn_store.py`; focused semantic tests passed 88 cases | The shared version 1.2 contract, Core processing, and Operator persistence preserve candidate-only authority, bounded deadlines, recoverable ownership, and exact principal-scoped reads. Governed live assurance remains open in the [ontology query coverage plan](../interfaces/ontology-query-coverage-implementation-plan.md#remaining-work). |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-13 | implemented | Adopted the implementation ledger without reconstructing earlier provenance and recorded exact-generation Rule retrieval. | Current change in `catalog_queries.py`, `operational_functions.py`, and `test_catalog_queries.py`; focused tests and diff-scoped validation passed. | Complete the IS-09 remote verification item below. |
| 2026-08-13 | implemented | Bound planner function visibility to actual runtime registrations while retaining unbound readable declarations in typed structural coverage. | Current change in `wire_semantic_query.py`, `semantic_manifest.py`, `query_manifest.py`, and their focused tests. | A durable production semantic index remains outside this change; complete the IS-09 remote verification item below. |
| 2026-08-13 | implemented | Separated invocation correlation from logical request idempotency and replaced durable requester and conversation identities with opaque references. | `current change`; `wire_read_investigation.py` and `test_wire_read_investigation.py`; focused tests passed 5 cases. | Complete the IS-09 remote verification item below. |
| 2026-08-13 | implemented | Bound catalog generations to provider-neutral, bounded ordered-document manifests and made generation identity independently reproducible from the exact document set. | `current change`; `shared/providers/catalog_search.py`, `delivery/catalog_search/generation.py`, `delivery/catalog_search/in_memory.py`, and focused catalog, ontology query, schema, and composition tests passed 41 cases. | Compose and validate the durable production semantic index; complete the IS-09 remote verification item below. |
| 2026-08-13 | implemented | Hardened the shared semantic Rule contract and the Core-to-Operator durable projection boundary. | `current change`; focused semantic tests passed 88 cases, task-scoped Ruff passed, and strict mypy passed 6 production files. | Record the governed live receipts in the ontology query coverage plan and complete IS-09 remote verification. |
| 2026-08-13 | implemented | Added bounded objective-aware candidate resolution to exact-generation Rule retrieval before scoring and top-k. | `current change`; `objective_rule_resolution.py`, `catalog_queries.py`, `catalog_search.py`, `in_memory.py`, and focused ontology query tests passed 8 cases. | P1 binding backfill, P2 durable generation evidence, and P4 rollout assurance remain open in the policy abstraction plan. |
| 2026-08-13 | implemented | Added the durable PostgreSQL generation adapter and expected-prior activation compare-and-swap for exact-generation Rule retrieval. | `current change`; `postgres.py`, lifecycle publishers, direct callers, and focused catalog tests passed 44 cases against in-memory and live PostgreSQL paths; Ruff and strict mypy passed the touched lifecycle sources. | Bind the adapter in production bootstrap and record governed IS-09 remote verification evidence. |
| 2026-08-13 | implemented | Bound the durable Rule semantic index into production startup behind exact active-generation checks and optional readiness degradation. | `current change`; `bootstrap.py`, `bootstrap_lifecycle.py`, `wire_semantic_query.py`, and focused runtime and composition checks passed 46 cases; Ruff and strict mypy passed. | Record governed IS-09 remote verification evidence. |
| 2026-08-13 | implemented | Added Core-owned typed activation closure and a durable terminal-result/outbox aggregate for Rule semantic generations. | `current change`; focused contracts and ledger checks passed 15 cases; task-scoped Ruff, strict mypy, and editor diagnostics passed. | Add exact activation binding, bounded EventBus publication, owning-agent wiring, and governed runtime evidence. |

### Remaining work

- [ ] Record governed IS-09 remote verification evidence and update the service-owned map state when that evidence passes.

## Physical service ownership

| Owner | Source | Tests | Distribution |
|-------|--------|-------|--------------|
| Core Control Plane | [fdai](../../../services/core-control-plane/src/fdai/) and [fdai_core_service](../../../services/core-control-plane/src/fdai_core_service/) | [Core tests](../../../services/core-control-plane/tests/) | `fdai-core-control-plane` |
| Operator Service | [fdai_operator_service](../../../services/operator-service/src/fdai_operator_service/) | [Operator tests](../../../services/operator-service/tests/) | `fdai-operator-service` |
| Document Ingestion API | [fdai_ingestion_api_service](../../../services/document-ingestion-api/src/fdai_ingestion_api_service/) | [Ingestion API tests](../../../services/document-ingestion-api/tests/) | `fdai-document-ingestion-api` |
| Document Processing Worker | [fdai_document_worker_service](../../../services/document-processing-worker/src/fdai_document_worker_service/) | [Worker tests](../../../services/document-processing-worker/tests/) | `fdai-document-processing-worker` |
| Isolated Executor | [fdai_executor_service](../../../services/isolated-executor/src/fdai_executor_service/) | [Executor tests](../../../services/isolated-executor/tests/) | `fdai-isolated-executor-service` |
| Service contracts | [fdai_service_contracts](../../../packages/service-contracts/src/fdai_service_contracts/) | [Contract tests](../../../packages/service-contracts/tests/) | `fdai-service-contracts` |
| Cross-service integration | Not applicable | [Root integration tests](../../../tests/integration/) | Virtual root only |

## Core Control Plane map

The Core distribution retains the complete `fdai` namespace. Internal module boundaries remain
unchanged by the physical move.

| Area | Responsibility | Source | Tests |
|------|----------------|--------|-------|
| Control loop and decisioning | Event normalization, tier routing, exact Rego allow/deny evaluation receipts, quality, risk, approval, execution coordination, recovery, and audit | [core](../../../services/core-control-plane/src/fdai/core/) | [core tests](../../../services/core-control-plane/tests/core/) |
| Ontology safety platform | Exact semantic releases with catalog-loaded Interface and FunctionType declarations, release-aware query profiles and function registration, principal-scoped manifests, verified Resource-to-ResourceType classification, generic and temporal query algebra, bitemporal topology and diffs, immutable direction-generation shadow comparisons with bounded blast-radius deltas and authoritative-inventory rebuild pointers, reviewed metric concepts, topology-aware causal joins, mutation plans, compact typed effect-reconciliation events, authenticated independent-observer binding, and lease-fenced durable terminal outbox delivery | [ontology_platform](../../../services/core-control-plane/src/fdai/core/ontology_platform/) | [ontology platform tests](../../../services/core-control-plane/tests/core/ontology_platform/) |
| Semantic conversation planning | Whole-turn schema proposals, server-owned frame/plan identity, principal-manifest verification, async verified execution, total terminal disposition, deterministic intent graphs, exact-command compatibility cutover, finite question-universe and epistemic-closure release receipts, and continuous coverage gates without execution authority | [conversation](../../../services/core-control-plane/src/fdai/core/conversation/) | [conversation tests](../../../services/core-control-plane/tests/conversation/) |
| Rule semantic generation closure | Typed activation commands and terminal results, atomic StateStore result/outbox persistence, duplicate replay, revision compare-and-swap, lease fencing, retry scheduling, corruption rejection, and broker-acknowledged publication state without semantic-index or execution authority | [rule_semantic_generation](../../../services/core-control-plane/src/fdai/core/rule_semantic_generation/) | [Rule semantic generation tests](../../../services/core-control-plane/tests/core/rule_semantic_generation/) |
| Ontology semantic generations | Provider-neutral bounded ordered-document manifests, self-verifying generation identity, candidate-only concrete indexes, durable PostgreSQL persistence, expected-prior activation compare-and-swap, full/incremental declaration and deployment-object documents, independent validation receipts, stale detection, and rollback | [catalog_search provider](../../../services/core-control-plane/src/fdai/shared/providers/catalog_search.py) and [catalog_search delivery](../../../services/core-control-plane/src/fdai/delivery/catalog_search/) | [catalog search tests](../../../services/core-control-plane/tests/delivery/catalog_search/) |
| Metric semantic provider binding | Alias-free reviewed metric concepts and exact `MetricProvider` windows that distinguish observed zero from provider gaps | [metric_window.py](../../../services/core-control-plane/src/fdai/delivery/metric_window.py) and [metric_semantic_catalog.py](../../../services/core-control-plane/src/fdai/runtime/metric_semantic_catalog.py) | [metric semantic catalog tests](../../../services/core-control-plane/tests/runtime/test_metric_semantic_catalog.py) |
| Operational Hypothesis Loop | Complete graph Dynamic evidence binding, deadline-bounded independent trajectory closure, supervised typed effect reconciliation, immutable operational lineage, and Owner-HIL-governed graph-model pointer promotion | [graph evidence](../../../services/core-control-plane/src/fdai/delivery/azure/graph_dynamic_evidence.py), [closure](../../../services/core-control-plane/src/fdai/core/assurance_twin/graph_closure.py), [reconciliation](../../../services/core-control-plane/src/fdai/delivery/reconciliation_runtime.py), [lineage](../../../services/core-control-plane/src/fdai/core/operational_planning/hypothesis_lineage.py), and [promotion](../../../services/core-control-plane/src/fdai/delivery/graph_model_promotion.py) | [graph evidence tests](../../../services/core-control-plane/tests/delivery/azure/test_graph_dynamic_evidence.py), [closure tests](../../../services/core-control-plane/tests/assurance_twin/test_graph_closure.py), [reconciliation tests](../../../services/core-control-plane/tests/delivery/test_reconciliation_runtime.py), [lineage tests](../../../services/core-control-plane/tests/core/operational_planning/test_hypothesis_lineage.py), and [promotion tests](../../../services/core-control-plane/tests/delivery/test_graph_model_promotion.py) |
| Agent pantheon | Fifteen fixed agents and their typed event runtime | [agents](../../../services/core-control-plane/src/fdai/agents/) | [agent tests](../../../services/core-control-plane/tests/agents/) |
| Composition | Provider and runtime dependency injection, including exact-release semantic query assembly, request-role executor factories, and resource-state activity publication with invocation-scoped opaque correlation | [composition](../../../services/core-control-plane/src/fdai/composition/) | [composition tests](../../../services/core-control-plane/tests/composition/) |
| Core adapters | Provider, persistence, notification, and platform adapters retained by Core | [delivery](../../../services/core-control-plane/src/fdai/delivery/) | [delivery tests](../../../services/core-control-plane/tests/delivery/) |
| Runtime | Core process lifecycle, readiness, event transport, supervision, and semantic runtime availability binding | [runtime](../../../services/core-control-plane/src/fdai/runtime/) | [runtime tests](../../../services/core-control-plane/tests/runtime/) |
| Core contracts and provider seams | Core-only types, provider Protocols, configuration, streaming, and telemetry | [shared](../../../services/core-control-plane/src/fdai/shared/) | [shared tests](../../../services/core-control-plane/tests/shared/) |
| Rule Catalog pipeline | Catalog schema loading, collection, validation, distillation, and promotion support | [rule_catalog](../../../services/core-control-plane/src/fdai/rule_catalog/) | [Rule Catalog tests](../../../services/core-control-plane/tests/rule_catalog/) |
| Core service entry point | Core distribution startup and service composition | [fdai_core_service](../../../services/core-control-plane/src/fdai_core_service/) | [Core package tests](../../../services/core-control-plane/tests/) |

The safety-core coverage floor applies to the deterministic tier and risk gate inside the Core
package. Their tests remain under the Core-owned test tree.

Ontology query execution rechecks the exact release, manifest, role, and purpose at runtime. Its
bounded dependency waves include queue wait in each node deadline, propagate in-flight
cancellation, skip blocked descendants, and emit stable receipts without provider error details.
Composition issues bounded secured ObjectSet receipts and registers the source-derived network
and Pod telemetry functions in the exact release. Function dependencies resolve only an issued
content digest. The `catalog.search_rules` function accepts only the active Rule generation bound to
that exact release and its provider-neutral bounded ordered-document manifest. The generation digest
is independently reproducible from the exact ordered document set, so count, chunk, root, or row
drift fails validation. The PostgreSQL adapter serializes each corpus lifecycle and checks the exact
expected prior generation in the activation transaction before replacing the active pointer.
Retrieval returns candidate-only Rules with a `CatalogRetrievalReceipt` and
grants no judgment, approval, or execution authority. The resource-state investigation path keeps promoted
inventory as answer authority, runs the ontology query in shadow, and stores principal-scoped parity
receipts through StateStore. Each actual invocation receives one opaque `correlation_ref` shared by
its live and durable activity lifecycle, while opaque requester and conversation references keep the
logical question `idempotency_key` stable across retries. Separate invocations do not reuse the
correlation.
The public composition facade exports only the optional resource-state composer; implementation
types remain in the focused binder so the facade stays below its structural ceiling.
Planner manifests apply identical role and purpose filtering to ObjectType and Interface
properties. Function descriptors are emitted only for declarations whose handlers are registered
in the composed runtime. Readable but unbound function declarations remain in structural coverage
as `runtime_binding_unavailable`; this accounting grants no judgment, approval, mutation,
promotion, or execution authority. Intent evidence preserves a terminal reason while also
disclosing bounded evidence-reference truncation.
The verifier rejects outputs that don't name declared DAG nodes before I/O. Answered turns render
only bounded verified query tables, and transient projection publication retries the same durable
idempotent result before dead-lettering.
Azure semantic planning uses existing `httpx` and `WorkloadIdentity` adapters for two validated
JSON-object proposals. Composition exposes only handlers with bound authoritative providers. The
frame proposal applies the shared wire identifier constraints before Core rebuilds server-owned
digests. Structured diagnostics record only the planning stage, candidate index, failure class,
and input-free validation locations; they omit operator text and provider details. The
public composition facade re-exports the dedicated semantic query binder while remaining below its
400-line structural ceiling. Its module contract retains the `composition`, `seam`, and `container`
anchors enforced by the package layout gate. The validated `llm.mode` string selects Azure semantic
composition by value, consistent with every other LLM binder. The ObjectSet handler is rebuilt for each request role,
so a Reader cannot inherit Owner visibility and an Owner is not silently reduced to Reader. Missing
model, release, store, or transport prerequisites
remain explicit startup-readiness failures rather than an implicit `runtime=None`.
Continuous coverage receipts separate deterministic fixture structural validation from production
readiness. Only externally produced `cross_service_e2e` or `live_assurance` question receipts can
set `production_ready`; a committed `deterministic_fixture` keeps it false.
Runtime bootstrap delegates semantic readiness and vertical workload-identity construction to its
existing lifecycle and binding helpers, keeping the primary composition root below the reviewed
fanout ceiling. A thin bootstrap wrapper preserves the injected identity-builder test and fork seam.
The Operational Hypothesis Loop adds no service or agent. Complete graph prerequisites bind at
composition; effect reconciliation uses supervised request/outbox transport with bounded draining;
and model pointer changes remain inside the existing governance ActionType, risk, Owner approval,
Thor execution, rollback, and Saga audit path.

## Independent service map

| Service | Package responsibility | Package map |
|---------|------------------------|-------------|
| Operator Service | Authenticated route families, durable semantic bridge, process-owned bridge health, and ordered managed-identity Kafka lifecycles including bounded Live and Agent SSE fan-out | [families](../../../services/operator-service/src/fdai_operator_service/families/), [adapters](../../../services/operator-service/src/fdai_operator_service/adapters/), [streaming](../../../services/operator-service/src/fdai_operator_service/streaming/), and [composition.py](../../../services/operator-service/src/fdai_operator_service/composition.py) |
| Document Ingestion API | Upload intake, API-owned transitions, and service adapters | [package](../../../services/document-ingestion-api/src/fdai_ingestion_api_service/) |
| Document Processing Worker | Durable document processing and worker-owned adapters | [package](../../../services/document-processing-worker/src/fdai_document_worker_service/) |
| Isolated Executor | Thor-owned command handling, provider effects, receipts, and executor adapters | [package](../../../services/isolated-executor/src/fdai_executor_service/) |

These packages may depend on `fdai-service-contracts`. They do not import another service's
implementation package.
Local composition binds service-owned client lifecycles and loopback adapters inside each package.
The Operator semantic bridge, ingestion publisher, document worker consumer, and isolated Executor
therefore preserve the same logical topics, idempotency, readiness, and receipt boundaries as their
deployed managed-identity adapters.

## Shared contract SDK

[fdai_service_contracts](../../../packages/service-contracts/src/fdai_service_contracts/) owns the
versioned wire descriptors, codecs, compatibility checks, readiness records, document contracts,
operator contracts, and executor contracts shared across processes. It contains no service
composition, provider implementation, database access, or business workflow.

The shared SDK also owns the no-authority ontology-query records used across the Core and Operator
boundary: semantic problem frames, bounded query DAGs, intent graphs, task receipts, and structural
coverage receipts. These records contain no provider client, ontology store, planner model, or
execution handler.
It also owns the versioned, no-authority operational activity record used to carry bounded inventory
scan, ontology projection, and current-state read evidence from Core to Operator surfaces. The
record separates logical agent ownership from the producing process and fixes
`execution_authority=false`.

Version 1.2 of the existing Operator/Core envelopes adds one bounded semantic-turn request and one
evidence-bound terminal result. The request pins authenticated roles, session ordering, purpose,
deadline, and idempotency. An answered result requires exact release, manifest, plan, execution
receipt, and evidence references. The SDK rejects semantic downgrade to N-1 instead of dropping
those fields. Runtime publication and consumption remain service-owned implementations.

The SDK also owns the logical-topic marker and deterministic consumer-group derivation used when
those two semantic channels share a physical Event Hub. Core and Operator keep separate adapters,
codecs, identities, logical topics, and offset groups; neither imports the other's implementation.
The same contract exports the canonical physical-topic default used when targeted Terraform state
has not yet materialized newly declared outputs.

The five service distributions use deployable `0.1.2` images as N-1 and `0.1.3` as N. Their existing contract-set
`1.0.0`/`1.1.0` matrix remains the cross-process compatibility boundary.
Content-addressed live evidence also binds the exact service and observation kind and requires
`observed=true`; recomputing a digest cannot convert an unobserved claim into a live receipt.

The package test tree validates SDK behavior. Cross-service N/N-1 and topology checks remain under
[root integration tests](../../../tests/integration/).

## Other repository owners

| Path | Responsibility |
|------|----------------|
| [evaluation-sdk/](../../../evaluation-sdk/) | Independently packaged evaluation contracts and runner. |
| [benchmarks/](../../../benchmarks/) | Independent benchmark drivers. |
| [extensions/](../../../extensions/) | Optional independently packaged capabilities. |
| [rule-catalog/](../../../rule-catalog/) | Catalog-as-code data. |
| [policies/](../../../policies/) | OPA/Rego policy-as-code. |
| [console/](../../../console/) | Thin operator SPA. |
| [cli/](../../../cli/) | Operator command-line client. |
| [scripts/agent/design_context.py](../../../scripts/agent/design_context.py) and [external_operation_guard.py](../../../scripts/agent/external_operation_guard.py) | Record design-context reads, hard-block stale context for framework and constitutional edits, prevent duplicate repository-wide validation, and defer slow CI, deployment, and image work until `HEAD` has a validation receipt. |

## Related docs

| To learn about | Read |
|----------------|------|
| Complete package boundaries and dependency injection | [Project Structure](project-structure.md) |
| Conversation and ontology query implementation sequencing | [Ontology Query Coverage Implementation Plan](../interfaces/ontology-query-coverage-implementation-plan.md) |
| IS work packages and local-first sequencing | [Service Decomposition Execution Plan](service-decomposition-execution-plan.md) |
| Graduation, data ownership, and rollback gates | [Service Graduation and Data Ownership](service-graduation-and-ownership.md) |
| Control-loop authority | [Architecture instructions](../../../.github/instructions/architecture.instructions.md) |
| Agent roles and permissions | [Agent Pantheon](../agents/agent-pantheon.md) |
