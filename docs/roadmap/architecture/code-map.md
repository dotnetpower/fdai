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
| Receipt-bound operational Context presentation | implemented | `core/operational_context/console_projection.py`; `tests/core/operational_context/test_console_projection.py`; focused tests (`5 passed`) | Purpose, release, cutoff, execution-authority, and graph coverage must match before bounded metadata is projected. Raw properties are excluded, and principal-scoped transport remains unbound. |
| Runtime-bound planner visibility | implemented | `composition/wire_semantic_query.py`; `core/conversation/semantic_manifest.py`; `core/ontology_platform/query_manifest.py`; focused composition and manifest tests | Planner descriptors expose only functions registered in the composed runtime. Readable but unbound declarations remain typed structural coverage and gain no authority. |
| Exact-release schema relationship query | implemented | `core/ontology_platform/relationship_queries.py`; `composition/wire_semantic_query.py`; `fdai_core_service/semantic_relationship_projection.py`; focused composition and processor tests (`42 passed`) | `query.ontology_relationships` reads ObjectType and LinkType declarations, preserves direction, cardinality, and description, and carries no judgment, approval, mutation, or execution authority. Authenticated Browser evidence remains open. |
| Declaration-driven finite question universe | implemented | `core/conversation/question_universe.py`; `core/conversation/__init__.py`; `core/conversation/epistemic_coverage.py`; `core/conversation/coverage_gate.py`; `tests/conversation/test_question_universe.py`; `tests/conversation/test_epistemic_coverage.py`; `tests/conversation/test_coverage_gate.py`; focused release-gate tests (`41 passed`, generator branch coverage `100%`, epistemic branch coverage `99%`, coverage-gate branch coverage `100%`) | Complete principal-scoped manifests expand through a canonical bounded grammar into stable case identities exposed by the conversation package. The grammar and receipt share one 10,000-case ceiling; epistemic and final gate receipts verify their release identity, immutable and serializable evidence counts, pass and production states, and content digests; unavailable declarations remain typed exclusions; overflow fails before expansion; and generated records grant no execution authority. |
| Production Rule semantic readiness | implemented | `runtime/bootstrap.py`; `runtime/bootstrap_lifecycle.py`; `composition/wire_semantic_query.py`; `tests/runtime/test_catalog_semantic_bootstrap.py`; focused bootstrap and composition checks (`46 passed`) | Production startup registers Rule semantic search only when the active generation exactly matches the current Rule catalog, semantic schema, ontology release, and embedder dimension. Stable optional-readiness degradation preserves startup without exposing a stale function. |
| Durable Rule generation closure | implemented | `core/rule_semantic_generation/activation.py`; `core/rule_semantic_generation/ledger.py`; `core/rule_semantic_generation/publication.py`; `rule_catalog/schema/rule_semantic_generation_events.py`; focused activation, contract, ledger, publication, and live PostgreSQL checks | Core verifies the exact validation receipt and expected prior active identity before activation, suppresses completed-command provider replay, atomically binds the first terminal result to one lease-fenced publication record, and marks it published only after an exact-topic broker acknowledgement. Delivery state grants no policy, approval, mutation, or execution authority. |
| Rule generation publication ownership | implemented | `agents/mimir.py`; `agents/_framework/runtime.py`; `runtime/bootstrap.py`; `runtime/bootstrap_bindings.py`; `runtime/bootstrap_lifecycle.py`; focused Mimir, runtime, bootstrap, activation, and publication checks (`32 passed`) | Mimir is the only activation-command and result subscriber. It delegates commands to the exact binder and stores safe-to-retry projection-only result receipts. Readiness-independent draining retries only released transport failures and grants Mimir no index, policy, approval, mutation, or execution authority. |
| Ordinary effect-reconciliation requests | implemented | `core/ontology_platform/reconciliation_producer.py`; `core/ontology_platform/reconciliation_request_outbox.py`; `delivery/reconciliation_request.py`; `delivery/reconciliation_request_publication.py`; focused reconciliation, ControlLoop, runtime, and composition checks (`163 passed`) | An executed Action must already cite a matching exact V2 plan. Independent observation is durably queued before publication, and downstream failure remains held or pending evidence without rewriting the executor outcome. Production artifact and observation adapters remain open. |
| Exact kinetic proposal handoff | implemented | `core/operational_planning/kinetic_proposal.py`; `delivery/kinetic_proposal.py`; `agents/forseti.py`; `agents/thor.py`; focused producer, Forseti, Thor, factory, and framework checks | A complete operational plan can resolve one durable existing exact V2 proposal through the existing Verdict path. Missing proposals preserve legacy behavior, invalid records lower authority to deny, and production source composition plus the pre-dispatch receipt writer remain open. |
| Read-investigation activity identity | implemented | `composition/wire_read_investigation.py`; `test_wire_read_investigation.py`; focused tests | Each invocation shares one opaque correlation across live and durable activity, separate invocations use distinct correlations, and logical request idempotency remains stable. |
| Browser-evidence metadata read contract | implemented | `fdai_service_contracts/operator.py`; `fdai_operator_service/browser_evidence_projection.py`; Operator migration; focused Operator and shared-contract checks (`148 passed`) | `BrowserEvidenceQuery` adds one bounded read-only method to the implementation-free Operator contract. The service role can select only a security-barrier metadata view; captured and structured payloads remain outside the cross-service contract. |
| Cross-service semantic Rule projection | implemented | `fdai_service_contracts/semantic_turn.py`; `fdai_core_service/semantic_turn_processor.py`; `fdai_operator_service/postgres_semantic_turn_store.py`; focused semantic tests passed 94 cases | The shared version 1.2 contract, Core processing, and Operator persistence preserve the exact validated function-invocation receipt and its canonical digest in addition to candidate-only authority, bounded deadlines, recoverable ownership, and exact principal-scoped reads. Contract validation rejects content, digest, task, intent, capability, and terminal-status drift. Governed live assurance remains open in the [ontology query coverage plan](../interfaces/ontology-query-coverage-implementation-plan.md#remaining-work). |
| Console semantic receipt projection | implemented | `semantic_turn.py`; `semantic_turn_processor.py`; `semantic_turn_runtime.py`; `console/src/deck/backend-normalizers.ts`; focused shared, Core, Operator, and Console tests | The typed route, specific clarification answer, unavailable reason, four assurance digests, evidence references, and `execution_authority=false` cross the shared contract, Core result, exact Operator read, terminal stream, durable transcript, replay, and Console presentation without prose inference. Passing governed browser and randomized-assurance records remain open in the ontology query coverage plan. |
| Deterministic missing incident context | implemented | `core/conversation/semantic_planning.py`; `tests/conversation/test_semantic_planning.py`; focused planner and terminal-projection tests (`43 passed`) | A first-turn reference to "this incident" returns one bounded clarification before manifest or model work. Prior incident context continues through normal semantic planning, and neither path grants execution authority. |
| Semantic temporal and evidence composition | implemented | `delivery/persistence/postgres_topology_history.py`; `composition/wire_semantic_query.py`; `runtime/bootstrap.py`; `runtime/bootstrap_bindings.py`; focused composition and provider-selection tests passed 16 cases | PostgreSQL topology history is available only with the state-store DSN. Metric-series and evidence-join capabilities require both the reviewed metric registry and a non-noop provider. One handler map controls verifier and executor availability, and every result remains read-only with `execution_authority=False`. |
| T1-first semantic planning | implemented | `core/conversation/semantic_planning.py`; `core/conversation/semantic_planning_cascade.py`; `core/conversation/semantic_planning_models.py`; `composition/semantic_query_model_targets.py`; `composition/wire_semantic_query.py`; focused tier-routing and composition tests | Semantic planning always uses the resolved T1 mini-model first. Only an unavailable or deterministically invalid T1 frame or plan proposal can retry that same stage once with the optional T2 primary reasoner. Typed clarification requirements distinguish legitimate missing user context, which terminates at T1, from a request for server-bound principal scope or purpose, which invalidates the T1 frame before one frame-only retry. Core also binds one timezone-aware evaluation time to the plan proposal; a bounded T2 plan retry receives the same value, so neither tier invents current query time. The planner never borrows the secondary quality-cross-check role. Scope denial and evidence holds do not invoke T2. |

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
| 2026-08-13 | implemented | Bound validated Rule generation commands to the exact target receipt and expected prior active identity before changing the semantic index. Completed-command replay returns the durable terminal result before provider access, and effect-after-error reconciliation remains fail closed. | `current change`; `activation.py`, `ledger.py`, provider and delivery activation contracts, and focused activation, ledger, generation, and live PostgreSQL checks passed; Ruff and strict mypy passed the touched lifecycle files. | Add bounded EventBus outbox publication, owning-agent wiring, and governed runtime evidence. |
| 2026-08-13 | implemented | Added bounded at-least-once EventBus publication for durable Rule generation activation results. Exact-topic acknowledgement completes the lease-fenced outbox record; failures release it for deterministic retry, cancellation preserves lease recovery, and acknowledgement persistence failure recovers by lease-expired replay. | `current change`; `publication.py`, package export, and focused publication tests passed 7 cases; task-scoped Ruff and strict mypy passed. | Wire the accountable agent and record governed runtime publication evidence. |
| 2026-08-13 | implemented | Wired Mimir as the sole Rule generation command and result subscriber, composed one shared durable ledger, and started readiness-independent outbox draining. Released transport failures retry while receipt-contract and durable-state failures remain fatal. | `current change`; focused Mimir, runtime, bootstrap, activation, and publication checks passed 32 cases; Ruff, strict mypy, translation freshness, and Korean quality checks passed. | Record a governed live runtime publication receipt; IS-09 remote verification remains open. |
| 2026-08-13 | implemented | Bound PostgreSQL topology history and reviewed metric/evidence providers into exact-release semantic query composition with fail-closed optional capability exposure. | `current change`; `postgres_topology_history.py`, `wire_semantic_query.py`, `bootstrap.py`, `bootstrap_bindings.py`, `test_wire_semantic_query.py`, and `test_bootstrap_config.py`; focused checks passed 16 cases. | Record governed live receipts in the ontology query coverage plan and complete IS-09 remote verification. |
| 2026-08-13 | in-progress | Extended the semantic projection through exact Operator reads and durable Console rendering, and added authenticated governed-receipt and seeded bilingual assurance runners. | `current change`; focused shared, Core, Operator, and Console checks pass. | Run both authenticated browser paths and link the two passing retained evidence records before claiming readiness. |
| 2026-08-13 | in-progress | Corrected strict Core receipt typing and prepared one-time Browser Entra session restoration for the authenticated evidence paths without changing principal or authority validation. | `current change`; strict mypy, Ruff, Console typecheck, design-route, and append-only checks pass. | Run both authenticated browser paths and link the two passing retained evidence records before claiming readiness. |
| 2026-08-13 | implemented | Preserved the planner's bounded clarification question in the Core semantic projection instead of replacing it with a generic terminal answer. | `current change`; `fdai_core_service/semantic_turn_processor.py`, `test_semantic_turn_processor.py`, and the focused Core processor suite passed 30 tests. | Record the governed browser and randomized-assurance evidence before claiming runtime validation. |
| 2026-08-13 | implemented | Classified a first-turn unbound incident reference as missing context before manifest or model work while preserving normal planning when prior incident context exists. | `current change`; `semantic_planning.py`, `test_semantic_planning.py`, and focused planner and terminal-projection tests passed 43 cases; task-scoped Ruff and strict mypy passed. | Retain and link governed authenticated-browser evidence before raising this scope to validated. |
| 2026-08-13 | implemented | Added deterministic declaration-driven generation for the finite question-universe denominator. Complete exact-release manifests expand through a canonical bounded grammar, while unavailable declarations remain typed exclusions. | `current change`; `question_universe.py`, `epistemic_coverage.py`, and `test_question_universe.py`; focused question-universe and epistemic-coverage tests passed 10 cases, and task-scoped Ruff and strict mypy passed. | Runtime and governed assurance evidence remain tracked by their owning coverage plan. |
| 2026-08-14 | implemented | Connected ordinary execution to effect-reconciliation request production through an existing exact V2 plan and a durable lease-fenced outbox. | `d3c0437fd`; focused reconciliation, ControlLoop, runtime, and composition checks passed 163 cases; strict mypy passed 12 production files. | Bind production exact-plan artifact and independent-observation adapters, then retain governed live closure evidence. |
| 2026-08-14 | implemented | Added an exact-release read-only FunctionType and localized projection for schema relationship questions. | `current change`; focused composition and processor tests passed 42 cases; Ruff, format, and strict mypy passed. | Restart the local stack and retain one authenticated Browser receipt for the original relationship question. |
| 2026-08-14 | implemented | Bound delivery-owned exact kinetic proposal production to Forseti's existing Verdict path without changing topics or action authority. | `current change`; focused producer, Forseti, Thor, factory, framework, Ruff, and strict mypy checks. | Bind the source in production composition and complete the pre-dispatch receipt and independent-observation path before claiming runtime validation. |
| 2026-08-14 | implemented | Added receipt-bound operational Context presentation without creating a global runtime graph route. | `current change`; `console_projection.py` and 5 focused mismatch and projection tests passed. | Bind only through an existing principal-scoped evidence response and retain authenticated Console evidence. |
| 2026-08-14 | implemented | Replaced immediate T2 semantic planning with a T1-first, deterministically evaluated cascade. | `current change`; focused semantic planner and composition tests prove T1 success, clarification, scope denial, and evidence holds do not spend T2 capacity. | Retain authenticated tier-selection evidence with the existing ontology assurance campaign. |
| 2026-08-15 | implemented | Added a bounded payload-free browser-evidence metadata method to the shared Operator read contract and implemented it behind a security-barrier service view. | `current change`; focused Operator and service-contract checks `148 passed`; service migration inventory checks `46 passed`; strict mypy passed. | Retain authenticated deployed read evidence and add the Console metadata panel. |
| 2026-08-15 | implemented | Bound one trusted evaluation timestamp to each semantic plan proposal and reused it unchanged for a bounded T2 plan retry. | `current change`; focused planner and Azure adapter checks plus task-scoped Ruff and strict mypy. | Retain authenticated evidence that an ObjectSet plan uses the server-bound cutoff. |

### Remaining work

- [ ] Record governed IS-09 remote verification evidence and update the service-owned map state when that evidence passes.
- [x] Wire Mimir as the sole accountable pantheon subscriber for Rule generation commands and results, with focused proof of durable publication and safe-to-retry projection.
- [ ] Record a governed live runtime receipt for durable activation-result publication and safe-to-retry consumption.
- [ ] Retain a governed authenticated-browser receipt proving that a first-turn unbound incident reference returns `semantic_clarification_required` with the caller request id preserved and `execution_authority=false`.

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
| Execution authorization | Provider-neutral requirement outcomes, least-permissive reduction of non-empty decision sets, canonical request and inventory binding, and rejection of ambiguous identity or unbound grant proposals | [execution_authorization](../../../services/core-control-plane/src/fdai/core/execution_authorization/) | [execution authorization tests](../../../services/core-control-plane/tests/core/execution_authorization/) |
| Ontology safety platform | Exact semantic releases with catalog-loaded Interface and FunctionType declarations, release-aware query profiles and function registration, principal-scoped manifests, verified Resource-to-ResourceType classification, generic and temporal query algebra, bitemporal topology and diffs, immutable direction-generation shadow comparisons with bounded blast-radius deltas and authoritative-inventory rebuild pointers, reviewed metric concepts, topology-aware causal joins, mutation plans with separate planner-function and operational-plan lineage plus documented fail-closed argument, evidence, target, and effect validation contracts, compact typed effect-reconciliation events, authenticated independent-observer binding, and lease-fenced durable terminal outbox delivery | [ontology_platform](../../../services/core-control-plane/src/fdai/core/ontology_platform/) | [ontology platform tests](../../../services/core-control-plane/tests/core/ontology_platform/) |
| Semantic conversation planning | Whole-turn schema proposals, server-owned frame/plan identity, principal-manifest verification, async verified execution, total terminal disposition, deterministic intent graphs, exact-command compatibility cutover, declaration-driven bounded question-universe generation, epistemic-closure release receipts, and continuous coverage gates without execution authority | [conversation](../../../services/core-control-plane/src/fdai/core/conversation/) | [conversation tests](../../../services/core-control-plane/tests/conversation/) |
| Rule semantic generation closure | Typed activation commands and terminal results, exact target-receipt and expected-prior compare-and-swap, replay-before-provider suppression, atomic StateStore result/outbox persistence, lease fencing, retry scheduling, corruption rejection, and broker-acknowledged publication state without policy or execution authority | [rule_semantic_generation](../../../services/core-control-plane/src/fdai/core/rule_semantic_generation/) | [Rule semantic generation tests](../../../services/core-control-plane/tests/core/rule_semantic_generation/) |
| Ontology semantic generations | Provider-neutral bounded ordered-document manifests, self-verifying generation identity, candidate-only concrete indexes, durable PostgreSQL persistence, expected-prior activation compare-and-swap, full/incremental declaration and deployment-object documents, independent validation receipts, stale detection, and rollback | [catalog_search provider](../../../services/core-control-plane/src/fdai/shared/providers/catalog_search.py) and [catalog_search delivery](../../../services/core-control-plane/src/fdai/delivery/catalog_search/) | [catalog search tests](../../../services/core-control-plane/tests/delivery/catalog_search/) |
| Metric semantic provider binding | Alias-free reviewed metric concepts and exact `MetricProvider` windows that distinguish observed zero from provider gaps | [metric_window.py](../../../services/core-control-plane/src/fdai/delivery/metric_window.py) and [metric_semantic_catalog.py](../../../services/core-control-plane/src/fdai/runtime/metric_semantic_catalog.py) | [metric semantic catalog tests](../../../services/core-control-plane/tests/runtime/test_metric_semantic_catalog.py) |
| Operational Hypothesis Loop | Complete graph Dynamic evidence binding, deadline-bounded independent trajectory closure, supervised typed effect reconciliation from ordinary exact-plan execution, authority-free exact kinetic proposal handoff, immutable operational lineage, and Owner-HIL-governed graph-model pointer promotion | [graph evidence](../../../services/core-control-plane/src/fdai/delivery/azure/graph_dynamic_evidence.py), [closure](../../../services/core-control-plane/src/fdai/core/assurance_twin/graph_closure.py), [reconciliation](../../../services/core-control-plane/src/fdai/delivery/reconciliation_runtime.py), [ordinary request producer](../../../services/core-control-plane/src/fdai/delivery/reconciliation_request.py), [kinetic proposal producer](../../../services/core-control-plane/src/fdai/delivery/kinetic_proposal.py), [Forseti binding](../../../services/core-control-plane/src/fdai/agents/forseti.py), [lineage](../../../services/core-control-plane/src/fdai/core/operational_planning/hypothesis_lineage.py), and [promotion](../../../services/core-control-plane/src/fdai/delivery/graph_model_promotion.py) | [graph evidence tests](../../../services/core-control-plane/tests/delivery/azure/test_graph_dynamic_evidence.py), [closure tests](../../../services/core-control-plane/tests/assurance_twin/test_graph_closure.py), [reconciliation tests](../../../services/core-control-plane/tests/delivery/test_reconciliation_runtime.py), [kinetic proposal tests](../../../services/core-control-plane/tests/delivery/test_kinetic_proposal.py), [Forseti tests](../../../services/core-control-plane/tests/agents/test_decision_case_e2e.py), [lineage tests](../../../services/core-control-plane/tests/core/operational_planning/test_hypothesis_lineage.py), and [promotion tests](../../../services/core-control-plane/tests/delivery/test_graph_model_promotion.py) |
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
cancellation, and skip blocked descendants. Stable handler type, value, and runtime failures remain
`capability_failed`; their structured diagnostic allowlists only `node_kind` and `failure_type`,
without exception text, arguments, node identifiers, provider payloads, or operator data.
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
JSON-object proposals. Composition binds resolved narrator or `t1.judge` candidates as the T1
planner and keeps `t2.reasoner.primary` candidates in a separate optional escalation adapter. Core
invokes T2 only after the T1 proposal is unavailable or fails deterministic schema, manifest,
build, or plan verification. Each proposal has a 90-second default budget and retries one
throttled candidate at most once when its bounded `Retry-After` delay fits that budget. Composition
exposes only handlers with bound authoritative providers. The
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
composition. Ordinary execution produces an effect-reconciliation request only from an existing
matching exact V2 plan and commits it to a durable outbox before broker publication. Missing
observation or publication failure remains held or pending evidence and never rewrites the executor
outcome. Model pointer changes remain inside the existing governance ActionType, risk, Owner
approval, Thor execution, rollback, and Saga audit path.

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
`IncidentPageProjection` keeps the generic `PageProjection` wire shape stable while binding an
Incident roster page to its same-snapshot outcome metrics under one read-only Operator contract.

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
