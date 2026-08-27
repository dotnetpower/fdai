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

> **Index contract:** This page is navigation-only. Linked owner documents contain current
> implementation status and history. The retired mixed-purpose ledger is preserved in the
> [archived Code Map implementation ledger](../../roadmap-implementation/architecture/code-map.md).

> **Kubernetes recovery contract:** Durable lifecycle reads require a fresh cursor, exact UID scope,
> and a sentinel-row truncation check. Lifecycle-classified termination rows feed the exact-target
> replacement reducer; incomplete lifecycle evidence cannot retain a recovered status.
> Collection completeness and gap state are persisted with the cursor, and incomplete LIST snapshots
> do not advance it.
> The cursor read includes completeness and limitation, preserves SQL `NULL` after expiry, and a
> WATCH count cap is an explicit truncation gap.
> Resource-event rows retain the durable object UID, cluster, recorded time, and source revision so
> the recovery Function can translate its actual query schema into typed replacement evidence.
> WATCH count-cap progress is resumable only when no malformed envelope preceded the safe boundary.
> Historical Pod reduction uses durable lifecycle UIDs with the exact current Pod; it does not issue
> an incompatible historical `as_of` query through the current-state gateway.
> Owner-scoped durable lifecycle reads retain historical old UIDs, while the analyzer Job receives
> the same reviewed Kubernetes bindings as the inventory Job for local/deployed parity.
> LIST pagination drains a bounded 2048-observation batch atomically, and Pod inventory retains
> creation timestamps plus explicitly controller-marked owner identity.

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

Semantic conversation planning keeps `semantic_planning.py`, `semantic_planning_cascade.py`, and
`semantic_planning_frame.py` as compatibility facades. Focused sibling modules own frame checks,
plan dispatch, judgment, validation, frame construction, facets, evidence-specific investigation
normalization, and queries while preserving public imports, deterministic gate order, and
read-only authority.
The semantic-routing baseline records each lexical owner, while the competency fixture pins the
current structural release and Reader manifest without claiming production readiness.

| Area | Responsibility | Source | Tests |
|------|----------------|--------|-------|
| Kubernetes Resource event history | Source-grounded exact-target planning, fail-closed exact identity cardinality, receipt-bound exact-child UID filtering or explicit exact-cluster bounded Kubernetes Event reads, durable bounded LIST continuation, continuous-lookback coverage checks, normalized event time, content-addressed evidence, limitation-aware bilingual answers, independent Azure/Kubernetes family routing, explicit incomplete results, and no raw message, cause, mutation, or execution authority | [semantic planner](../../../services/core-control-plane/src/fdai/core/conversation/semantic_resource_event_planning.py), [FunctionType](../../../services/core-control-plane/src/fdai/core/ontology_platform/resource_event_queries.py), [lifecycle source](../../../services/core-control-plane/src/fdai/delivery/kubernetes_lifecycle_source.py), [durable reader](../../../services/core-control-plane/src/fdai/delivery/durable_kubernetes_resource_event_history.py), [PostgreSQL store](../../../services/core-control-plane/src/fdai/delivery/persistence/postgres_kubernetes_lifecycle.py), [family router](../../../services/core-control-plane/src/fdai/delivery/resource_event_history.py), [runtime binding](../../../services/core-control-plane/src/fdai/runtime/resource_event_providers.py), and [answer projection](../../../services/core-control-plane/src/fdai_core_service/semantic_turn_processor.py) | [semantic planning tests](../../../services/core-control-plane/tests/conversation/test_semantic_planning.py), [lifecycle source tests](../../../services/core-control-plane/tests/delivery/test_kubernetes_lifecycle_source.py), [durable reader tests](../../../services/core-control-plane/tests/delivery/test_durable_kubernetes_resource_event_history.py), [router tests](../../../services/core-control-plane/tests/delivery/test_resource_event_history.py), [FunctionType tests](../../../services/core-control-plane/tests/core/ontology_platform/test_resource_event_queries.py), [answer tests](../../../services/core-control-plane/tests/test_semantic_turn_processor.py), and [runtime tests](../../../services/core-control-plane/tests/runtime/test_resource_health_provider.py) |
| Kubernetes Pod lifecycle cohort | Separate controller-grounded historical replacement evidence that persists immutable Pod identity from complete inventory snapshots, joins events by exact historical UID, requires continuous collection coverage for the requested lookback, keeps current candidates receipt-bound, and never relabels sibling events or trusts Event `related.uid` as ownership | [cohort FunctionType](../../../services/core-control-plane/src/fdai/core/ontology_platform/kubernetes_pod_lifecycle_cohort_queries.py), [identity projection](../../../services/core-control-plane/src/fdai/delivery/kubernetes_pod_lifecycle_identity.py), [durable reader](../../../services/core-control-plane/src/fdai/delivery/durable_kubernetes_pod_lifecycle_cohort.py), and [PostgreSQL store](../../../services/core-control-plane/src/fdai/delivery/persistence/postgres_kubernetes_lifecycle.py) | [cohort tests](../../../services/core-control-plane/tests/delivery/test_durable_kubernetes_pod_lifecycle_cohort.py), [identity tests](../../../services/core-control-plane/tests/delivery/test_kubernetes_pod_lifecycle_identity.py), [reducer and query tests](../../../services/core-control-plane/tests/core/ontology_platform/test_kubernetes_pod_recovery_queries.py), and [composition tests](../../../services/core-control-plane/tests/composition/test_wire_kubernetes_pod_recovery.py) |
| Control loop and decisioning | Event normalization, tier routing, exact Rego allow/deny evaluation receipts, quality, risk, approval, execution coordination, recovery, and audit | [core](../../../services/core-control-plane/src/fdai/core/) | [core tests](../../../services/core-control-plane/tests/core/) |
| Planned-change graph freshness | Exact-target impact analysis bound to stable persisted inventory manifests, one matching projected operating-model revision, the active generation, and the ontology release through a content-addressed no-authority receipt with post-traversal revalidation | [impact assessment](../../../services/core-control-plane/src/fdai/core/impact_analysis/change_assessment.py), [inventory receipt source](../../../services/core-control-plane/src/fdai/delivery/persistence/postgres_graph_freshness.py), and [Pantheon binding](../../../services/core-control-plane/src/fdai/runtime/bootstrap_pantheon.py) | [impact tests](../../../services/core-control-plane/tests/core/impact_analysis/), [receipt source tests](../../../services/core-control-plane/tests/persistence/test_postgres_graph_freshness.py), and [change-chain tests](../../../services/core-control-plane/tests/agents/test_change_management_chain.py) |
| Observation-mode ARB ontology loop | Planned-intent-only typed Huginn Change ingress, exact release-bound context and evidence, bounded copy-on-write scenario, per-key idempotent replay, Forseti-owned observation verdict, Saga audit, and lineage-derived ReviewCase projection with validated `Change -> change_instantiates_process -> Process` provenance that reserves `runs_review` for workflow execution | [observation loop](../../../services/core-control-plane/src/fdai/core/architecture_review/observation_loop.py), [Forseti binding](../../../services/core-control-plane/src/fdai/agents/forseti.py), and [ARB projection](../../../services/core-control-plane/src/fdai/core/architecture_review/projection.py) | [observation trace tests](../../../services/core-control-plane/tests/core/architecture_review/test_observation_loop.py), [projection tests](../../../services/core-control-plane/tests/core/architecture_review/test_projection.py), and [readiness tests](../../../services/core-control-plane/tests/core/architecture_review/test_readiness.py) |
| Control-plane regional recovery shadow path | Provider-neutral ordered failover and failback rehearsal with expected-epoch fencing, verified single-writer state, bounded evidence receipts, and halt-before-next-action behavior without live provider mutation | [shadow recovery](../../../services/core-control-plane/src/fdai/core/verticals/resilience/shadow_recovery.py) and [recovery provider contract](../../../services/core-control-plane/src/fdai/shared/providers/control_plane_recovery.py) | [shadow recovery tests](../../../services/core-control-plane/tests/core/verticals/test_recovery_plan_shadow.py), [recovery plan tests](../../../services/core-control-plane/tests/core/verticals/test_recovery_plan.py), and [recovery coordinator tests](../../../services/core-control-plane/tests/core/verticals/test_recovery_coordinator.py) |
| Hallucination rubric promotion | Paired immutable baseline/treatment evidence, confidence-aware readiness, independent review binding, strict manifest verification, and per-ActionType fail-closed rubric mode resolution without promotion authority | [rubric promotion core](../../../services/core-control-plane/src/fdai/core/quality_gate/promotion.py) and [manifest adapter](../../../services/core-control-plane/src/fdai/delivery/measurement/rubric_promotion_evidence.py) | [rubric promotion tests](../../../services/core-control-plane/tests/core/quality_gate/test_rubric_promotion.py), [adapter tests](../../../services/core-control-plane/tests/delivery/test_rubric_promotion_evidence.py), and [composition tests](../../../services/core-control-plane/tests/composition/test_rubric_promotion_binding.py) |
| Execution authorization | Provider-neutral requirement outcomes, least-permissive reduction of non-empty decision sets, canonical request and inventory binding, and rejection of ambiguous identity or unbound grant proposals | [execution_authorization](../../../services/core-control-plane/src/fdai/core/execution_authorization/) | [execution authorization tests](../../../services/core-control-plane/tests/core/execution_authorization/) |
| Ontology safety platform | Exact semantic releases with catalog-loaded Interface and FunctionType declarations, release-aware query profiles and function registration, principal-scoped manifests, verified Resource-to-ResourceType classification, generic and temporal query algebra, bitemporal topology and diffs, immutable direction-generation shadow comparisons with bounded blast-radius deltas, authoritative-inventory rebuild pointers, and distinct-reviewer regression-bound catalog PR proposals, reviewed metric concepts, topology-aware causal joins, per-Resource freshness-complete graph reads, digest-fenced continuous operating-model replay recovery, evidence-bound reads and copy-on-write scenario branches without production write authority, mutation plans with separate planner-function and operational-plan lineage plus documented fail-closed argument, evidence, target, and effect validation contracts, compact typed effect-reconciliation events, authenticated independent-observer binding, and lease-fenced durable terminal outbox delivery | [ontology_platform](../../../services/core-control-plane/src/fdai/core/ontology_platform/) | [ontology platform tests](../../../services/core-control-plane/tests/core/ontology_platform/) |
| Ontology structural model | Exact ResourceType identity, reviewed ResourceClass aggregation, reviewed Property semantics and capability Interfaces, direct-link roles and semantic traits, exploratory traversal, ordered typed paths, and limitation-preserving graph presentation | [owner design](ontology-structural-model.md), [ontology contracts](../../../services/core-control-plane/src/fdai/shared/contracts/models/ontology.py), [catalog projection](../../../services/core-control-plane/src/fdai/core/ontology_platform/catalog_projection.py), and [query platform](../../../services/core-control-plane/src/fdai/core/ontology_platform/) | [ontology platform tests](../../../services/core-control-plane/tests/core/ontology_platform/), [catalog tests](../../../services/core-control-plane/tests/rule_catalog/), and [Console graph tests](../../../console/src/components/ontology-graph.model.test.ts) |
| Operational instance evidence adapters | Authenticated exact-endpoint runtime-call observations, principal-safe PostgreSQL role evidence, explicit unavailable source state, and verified pre-promotion enrichment through the inventory single writer without action authority | [runtime-call telemetry](../../../services/core-control-plane/src/fdai/core/ontology_platform/runtime_call_telemetry.py), [PostgreSQL role evidence](../../../services/core-control-plane/src/fdai/core/ontology_platform/postgres_role_evidence.py), and [inventory binding](../../../services/core-control-plane/src/fdai/delivery/runtime_call_inventory.py) | [runtime-call telemetry tests](../../../services/core-control-plane/tests/core/ontology_platform/test_runtime_call_telemetry.py), [PostgreSQL role evidence tests](../../../services/core-control-plane/tests/core/ontology_platform/test_postgres_role_evidence.py), and [inventory binding tests](../../../services/core-control-plane/tests/delivery/test_runtime_call_inventory.py) |
| Continuous operational instance graph | Validated source policy, adaptive collection, event/delta/snapshot convergence, local/deployed analyzer scheduling parity, principal-safe health, typed semantic rollups, content-addressed archive lifecycle, five-outcome graph refresh decisions, relationship coverage that gates only snapshots able to state a relationship, safe partial live-evidence write-through, and typed representative competency without action authority | [owner design](continuous-operational-instance-graph.md), [audit contract](../../../config/continuous-operational-instance-graph-audit.json), [analyzer CLI](../../../services/core-control-plane/src/fdai/delivery/analyzer_tick_cli.py), [local analyzer task](../../../scripts/deployment/local/run-analyzer-loop.sh), [rollup core](../../../services/core-control-plane/src/fdai/core/ontology_platform/semantic_rollup.py), [archive core](../../../services/core-control-plane/src/fdai/core/ontology_platform/archive_manifest.py), [graph refresh](../../../services/core-control-plane/src/fdai/core/ontology_platform/graph_evidence_refresh.py), [projection coverage](../../../services/core-control-plane/src/fdai/delivery/persistence/postgres_ontology.py), [competency](../../../services/core-control-plane/src/fdai/core/ontology_platform/operational_instance_competency.py), [inventory adapter](../../../services/core-control-plane/src/fdai/delivery/inventory_rollup.py), [live evidence](../../../services/core-control-plane/src/fdai/delivery/inventory_live_evidence.py), [archive persistence](../../../services/core-control-plane/src/fdai/delivery/persistence/postgres_operational_archive.py), and [Core migration](../../../service-migrations/branches/core-control-plane/versions/20260822_core_operational_archive.py) | [analyzer tests](../../../services/core-control-plane/tests/delivery/test_analyzer_tick_cli_topic.py), [audit tests](../../../tests/integration/scripts/test_continuous_operational_instance_graph_audit.py), [refresh tests](../../../services/core-control-plane/tests/core/ontology_platform/test_graph_evidence_refresh.py), [competency tests](../../../services/core-control-plane/tests/core/ontology_platform/test_operational_instance_competency.py), [live-evidence tests](../../../services/core-control-plane/tests/delivery/test_inventory_live_evidence.py), [rollup tests](../../../services/core-control-plane/tests/core/ontology_platform/test_semantic_rollup.py), [archive tests](../../../services/core-control-plane/tests/core/ontology_platform/test_archive_manifest.py), [purge tests](../../../services/core-control-plane/tests/delivery/test_operational_archive_purge.py), and [cross-lane tests](../../../tests/integration/test_operational_instance_retention.py) |
| Exact-Pod diagnosis evidence | One exact Pod UID joins projected termination state, lifecycle events, and bounded content-free AppTraces, AppExceptions, and ContainerLogV2 evidence without causal or execution authority. | [diagnosis query](../../../services/core-control-plane/src/fdai/core/ontology_platform/kubernetes_pod_diagnosis_queries.py) and [log adapter](../../../services/core-control-plane/src/fdai/delivery/kubernetes_pod_log_evidence.py) | [diagnosis tests](../../../services/core-control-plane/tests/core/ontology_platform/test_kubernetes_pod_diagnosis_queries.py) and [log adapter tests](../../../services/core-control-plane/tests/delivery/test_kubernetes_pod_log_evidence.py) |
| Kubernetes workload evidence | Allowlisted Deployment and Pod observations, exact target selection, issued two-hop ownership evidence in both rollout and Pod-owner directions, reviewed immutable-Pod restart-history metrics, and pure freshness- and conflict-aware rollout, same-UID recovery, and distinct-UID replacement reducers that never claim root cause or execution authority. A durable, resumable lifecycle collector now persists cluster/namespace/UID/reason-typed evidence behind an atomic cursor-plus-append-only store; the retained rows feed the existing Resource-event query dependency and the shared local/deployed analyzer schedule, and the lifecycle-backed replacement reducer selects only exact old-UID termination rows rather than inferring missing historical observations. | [Kubernetes inventory source](../../../services/core-control-plane/src/fdai/delivery/kubernetes_api_inventory.py), [rollout query](../../../services/core-control-plane/src/fdai/core/ontology_platform/kubernetes_rollout_queries.py), [Pod recovery query](../../../services/core-control-plane/src/fdai/core/ontology_platform/kubernetes_pod_recovery_queries.py), [Pod replacement reducer](../../../services/core-control-plane/src/fdai/core/ontology_platform/kubernetes_pod_replacement_evidence.py), [semantic planners](../../../services/core-control-plane/src/fdai/core/conversation/), [durable Resource-event adapter](../../../services/core-control-plane/src/fdai/delivery/durable_kubernetes_resource_event_history.py), [lifecycle observation model](../../../services/core-control-plane/src/fdai/core/ontology_platform/kubernetes_lifecycle_observation.py), [lifecycle source](../../../services/core-control-plane/src/fdai/delivery/kubernetes_lifecycle_source.py), [lifecycle collector](../../../services/core-control-plane/src/fdai/delivery/kubernetes_lifecycle_collector.py), [lifecycle Postgres store](../../../services/core-control-plane/src/fdai/delivery/persistence/postgres_kubernetes_lifecycle.py), [lifecycle Core migration](../../../service-migrations/branches/core-control-plane/versions/20260828_core_kubernetes_lifecycle.py), and [lifecycle collector CLI](../../../services/core-control-plane/src/fdai/delivery/kubernetes_lifecycle_collector_cli.py) | [inventory source tests](../../../services/core-control-plane/tests/delivery/test_kubernetes_api_inventory.py), [workload reducer tests](../../../services/core-control-plane/tests/core/ontology_platform/), [planner tests](../../../services/core-control-plane/tests/conversation/), [composition tests](../../../services/core-control-plane/tests/composition/), [lifecycle observation tests](../../../services/core-control-plane/tests/core/ontology_platform/test_kubernetes_lifecycle_observation.py), [lifecycle source tests](../../../services/core-control-plane/tests/delivery/test_kubernetes_lifecycle_source.py), [lifecycle collector tests](../../../services/core-control-plane/tests/delivery/test_kubernetes_lifecycle_collector.py), [durable adapter tests](../../../services/core-control-plane/tests/delivery/test_durable_kubernetes_resource_event_history.py), [lifecycle Postgres store tests](../../../services/core-control-plane/tests/persistence/test_postgres_kubernetes_lifecycle.py), and [lifecycle CLI tests](../../../services/core-control-plane/tests/delivery/test_kubernetes_lifecycle_collector_cli.py) |
| Ontology declaration workbench projections | Exact-release declaration details, topology-backed dependents, sanitized ObjectType evidence health, retained-release compatibility, role/purpose redaction, and deterministic revisions without mutation authority | [ontology_declaration_projection.py](../../../services/core-control-plane/src/fdai/delivery/ontology_declaration_projection.py), [ontology_dependents_projection.py](../../../services/core-control-plane/src/fdai/delivery/ontology_dependents_projection.py), [ontology_evidence_health_projection.py](../../../services/core-control-plane/src/fdai/delivery/ontology_evidence_health_projection.py), and [ontology_release_diff_projection.py](../../../services/core-control-plane/src/fdai/delivery/ontology_release_diff_projection.py) | [delivery projection tests](../../../services/core-control-plane/tests/delivery/) and [catalog materializer tests](../../../tests/integration/scripts/test_materialize_authoritative_catalogs.py) |
| OI-12 operational certification | Exact-release seven-axis aggregate snapshots, read-only PostgreSQL collection, signed storage growth, explicit unavailable evidence, bounded local rollup/archive/restore exercise, and no-authority receipt emission | [certification contract](../../../services/core-control-plane/src/fdai/core/ontology_platform/operational_instance_certification.py), [certification reducer](../../../services/core-control-plane/src/fdai/delivery/operational_instance_certification.py), [PostgreSQL source](../../../services/core-control-plane/src/fdai/delivery/operational_instance_certification_postgres.py), [archive exercise](../../../services/core-control-plane/src/fdai/delivery/operational_instance_certification_archive.py), and [certification CLI](../../../services/core-control-plane/src/fdai/delivery/operational_instance_certification_cli.py) | [contract tests](../../../services/core-control-plane/tests/core/ontology_platform/test_operational_instance_certification.py), [delivery tests](../../../services/core-control-plane/tests/delivery/test_operational_instance_certification.py), and [archive exercise tests](../../../services/core-control-plane/tests/delivery/test_operational_instance_certification_archive.py) |
| Semantic conversation planning | Whole-turn schema proposals, canonical typed-judgment precedence over later frame proposals, server-owned frame/plan identity, principal-manifest verification, async verified execution, evidence-free typed direct responses, total terminal disposition, deterministic intent graphs, exact-command compatibility cutover, declaration-driven bounded question-universe generation, epistemic-closure release receipts, typed network-versus-application latency investigation with exact service-to-Resource scope and fail-closed Resource state evidence, shape-agnostic resolution of a stated exact Resource identity so no turn asks for a target the utterance already names, and continuous coverage gates without execution authority | [conversation](../../../services/core-control-plane/src/fdai/core/conversation/), [S3 frame normalization](../../../services/core-control-plane/src/fdai/core/conversation/semantic_planning_frame_normalization.py), [target candidate planning](../../../services/core-control-plane/src/fdai/core/conversation/semantic_target_candidate_planning.py), and [investigation planner](../../../services/core-control-plane/src/fdai/core/conversation/semantic_investigation_planning.py) | [conversation tests](../../../services/core-control-plane/tests/conversation/) |
| Durable background-task handoff | Lease-fenced detached read records, atomic terminal outbox, replay-idempotent conversation completion, and single-write completion audit markers without production executor binding | [background_task](../../../services/core-control-plane/src/fdai/core/background_task/) and [completion audit adapter](../../../services/core-control-plane/src/fdai/delivery/persistence/background_task_completion_audit.py) | [background-task tests](../../../services/core-control-plane/tests/core/background_task/) and [completion audit tests](../../../services/core-control-plane/tests/persistence/test_background_task_completion_audit.py) |
| Rule semantic generation closure | Typed activation commands and terminal results, exact target-receipt and expected-prior compare-and-swap, replay-before-provider suppression, atomic StateStore result/outbox persistence, lease fencing, retry scheduling, corruption rejection, and broker-acknowledged publication state without policy or execution authority | [rule_semantic_generation](../../../services/core-control-plane/src/fdai/core/rule_semantic_generation/) | [Rule semantic generation tests](../../../services/core-control-plane/tests/core/rule_semantic_generation/) |
| Ontology semantic generations | Provider-neutral bounded ordered-document manifests, self-verifying generation identity, candidate-only concrete indexes, durable PostgreSQL persistence, expected-prior activation compare-and-swap, full/incremental declaration and deployment-object documents, independent validation receipts, stale detection, and rollback | [catalog_search provider](../../../services/core-control-plane/src/fdai/shared/providers/catalog_search.py) and [catalog_search delivery](../../../services/core-control-plane/src/fdai/delivery/catalog_search/) | [catalog search tests](../../../services/core-control-plane/tests/delivery/catalog_search/) |
| Metric, VM process, and MySQL pressure evidence binding | Alias-free reviewed metric concepts, exact ObjectSet-derived label selectors, dependency-only evidence binding on every object-valued FunctionType input so no plan can substitute a model-authored literal for secured evidence, exact `MetricProvider` windows that distinguish observed zero from provider gaps, bounded per-process VM CPU records, and staged MySQL saturation-versus-demand evidence with no cause or execution authority | [metric_window.py](../../../services/core-control-plane/src/fdai/delivery/metric_window.py), [metric_semantic_catalog.py](../../../services/core-control-plane/src/fdai/runtime/metric_semantic_catalog.py), [VM process contract](../../../services/core-control-plane/src/fdai/core/ontology_platform/vm_process_evidence.py), [Azure Monitor Perf adapter](../../../services/core-control-plane/src/fdai/delivery/azure/vm_process_evidence.py), and [MySQL pressure evidence](../../../services/core-control-plane/src/fdai/core/ontology_platform/mysql_pressure_evidence.py) | [metric semantic catalog tests](../../../services/core-control-plane/tests/runtime/test_metric_semantic_catalog.py), [VM process contract tests](../../../services/core-control-plane/tests/core/ontology_platform/test_vm_process_evidence.py), [Azure adapter tests](../../../services/core-control-plane/tests/delivery/azure/test_vm_process_evidence.py), and [MySQL pressure tests](../../../services/core-control-plane/tests/core/ontology_platform/test_mysql_pressure_evidence.py) |
| Operational Hypothesis Loop | Complete graph Dynamic evidence binding, evidence-floor-aware plan selection, deadline-bounded independent trajectory closure, supervised typed effect reconciliation from ordinary exact-plan execution, authority-free exact kinetic proposal handoff, immutable multi-effect operational lineage with singular historical reads and plural-only new writes, and Owner-HIL-governed graph-model pointer promotion | [graph evidence](../../../services/core-control-plane/src/fdai/delivery/azure/graph_dynamic_evidence.py), [closure](../../../services/core-control-plane/src/fdai/core/assurance_twin/graph_closure.py), [reconciliation](../../../services/core-control-plane/src/fdai/delivery/reconciliation_runtime.py), [ordinary request producer](../../../services/core-control-plane/src/fdai/delivery/reconciliation_request.py), [kinetic proposal producer](../../../services/core-control-plane/src/fdai/delivery/kinetic_proposal.py), [Forseti binding](../../../services/core-control-plane/src/fdai/agents/forseti.py), [lineage](../../../services/core-control-plane/src/fdai/core/operational_planning/hypothesis_lineage.py), and [promotion](../../../services/core-control-plane/src/fdai/delivery/graph_model_promotion.py) | [graph evidence tests](../../../services/core-control-plane/tests/delivery/azure/test_graph_dynamic_evidence.py), [closure tests](../../../services/core-control-plane/tests/assurance_twin/test_graph_closure.py), [reconciliation tests](../../../services/core-control-plane/tests/delivery/test_reconciliation_runtime.py), [kinetic proposal tests](../../../services/core-control-plane/tests/delivery/test_kinetic_proposal.py), [Forseti tests](../../../services/core-control-plane/tests/agents/test_decision_case_e2e.py), [lineage tests](../../../services/core-control-plane/tests/core/operational_planning/test_hypothesis_lineage.py), and [promotion tests](../../../services/core-control-plane/tests/delivery/test_graph_model_promotion.py) |
| Operational learning delivery | Deterministic O3 candidate validation, content-addressed inert draft-PR publication, verifier-backed Heimdall observation replay, and exact-digest O7 measurement without promotion authority | [O3 validator and publisher](../../../services/core-control-plane/src/fdai/delivery/gitops_pr/), [O3 runtime binding](../../../services/core-control-plane/src/fdai/runtime/operational_catalog_review.py), [observation mailbox](../../../services/core-control-plane/src/fdai/delivery/reconciliation_observations.py), and [O7 evidence](../../../services/core-control-plane/src/fdai/delivery/measurement/operational_promotion_evidence.py) | [O3 delivery tests](../../../services/core-control-plane/tests/delivery/test_gitops_catalog_validator.py), [O3 runtime tests](../../../services/core-control-plane/tests/runtime/test_operational_catalog_review.py), [observation tests](../../../services/core-control-plane/tests/delivery/test_reconciliation_observations.py), and [O7 evidence tests](../../../services/core-control-plane/tests/delivery/test_operational_promotion_evidence.py) |
| Discovery-loop shadow dwell | Per-candidate retention of judge-and-log-only observations, self-verifying dwell evidence, and the fail-closed threshold gate Mimir re-derives before a candidate may be considered for promotion | [shadow_dwell.py](../../../services/core-control-plane/src/fdai/core/operational_learning/shadow_dwell.py) | [shadow dwell tests](../../../services/core-control-plane/tests/core/operational_learning/test_shadow_dwell.py) and [discovery dwell tests](../../../services/core-control-plane/tests/agents/test_discovery_shadow_dwell.py) |
| Operational readiness handoff | Typed ownership-transfer ingest, Forseti-accountable read-only review, replay-safe report delivery, and grounded shadow remediation with no approval or execution authority | [readiness composition](../../../services/core-control-plane/src/fdai/composition/readiness.py), [runtime consumer](../../../services/core-control-plane/src/fdai/runtime/consumers.py), and [task binding](../../../services/core-control-plane/src/fdai/runtime/bootstrap_tasks.py) | [runtime ingest tests](../../../services/core-control-plane/tests/runtime/test_operational_readiness_ingest.py), [readiness service tests](../../../services/core-control-plane/tests/composition/test_readiness_service.py), and [remediation tests](../../../services/core-control-plane/tests/core/readiness/test_remediation.py) |
| Architecture review | Manifest readiness, control-only Process projection, bounded legacy projection-status fallback, and the ontology-grounded observation loop whose JSON-safe non-actuation verdict is audited by Saga but excluded from Thor dispatch and Odin action-portfolio counts | [architecture review core](../../../services/core-control-plane/src/fdai/core/architecture_review/), [owner index](architecture-review-board.md), [ontology-agent loop](architecture-review/ontology-agent-loop.md), [evidence-authority contract](architecture-review/evidence-and-authority.md), and [delivery plan](architecture-review/delivery-plan.md) | [architecture review tests](../../../services/core-control-plane/tests/core/architecture_review/) and [readiness checker tests](../../../tests/integration/scripts/test_check_arb_readiness.py) |
| Operator SRE command path | One operator problem-response request bound to exactly one Incident and one idempotent typed ActionProposal under a single correlation, returning authoritative Incident, Trace, Process, and Approval links | [sre_request.py](../../../services/core-control-plane/src/fdai/core/incident/sre_request.py) and [operator_request.py](../../../services/core-control-plane/src/fdai/shared/providers/operator_request.py) | [SRE request tests](../../../services/core-control-plane/tests/core/incident/test_sre_request.py) |
| Agent pantheon | Fifteen fixed agents and their typed event runtime | [agents](../../../services/core-control-plane/src/fdai/agents/) | [agent tests](../../../services/core-control-plane/tests/agents/) |
| Composition | Provider and runtime dependency injection, including exact-release semantic query assembly, request-role executor factories, paired rubric receipt source and verifier binding, and resource-state activity publication with invocation-scoped opaque correlation | [composition](../../../services/core-control-plane/src/fdai/composition/) | [composition tests](../../../services/core-control-plane/tests/composition/) |
| Core adapters | Provider, persistence, notification, and platform adapters retained by Core. Public-web results bind answer spans to exact source digests and a no-authority execution receipt before an Azure adapter can return them. | [delivery](../../../services/core-control-plane/src/fdai/delivery/) | [delivery tests](../../../services/core-control-plane/tests/delivery/) |
| Rule-catalog profile binding | One startup resolution of the governed `FDAI_PROFILE_ID` into the immutable rule tuple the T0 index and workflow guard validation both read, with fail-closed selection and grading and tenant-free startup diagnostics | [rule_profile.py](../../../services/core-control-plane/src/fdai/runtime/rule_profile.py) | [rule profile tests](../../../services/core-control-plane/tests/runtime/test_rule_profile.py) |
| Runtime | Core process lifecycle with an immutable startup plan, typed active-runtime assembly, continuous operating-model subscription, effect reconciliation bound after the ControlLoop exposes its ontology store, focused messaging, incident, semantic, resource-ownership, and task-hook boundaries, explicit shutdown ordering, readiness that separates process-critical state and audit writes from authority-critical full-chain proof, and task supervision | [runtime](../../../services/core-control-plane/src/fdai/runtime/), [bootstrap_plan.py](../../../services/core-control-plane/src/fdai/runtime/bootstrap_plan.py), [bootstrap_core.py](../../../services/core-control-plane/src/fdai/runtime/bootstrap_core.py), [bootstrap_resources.py](../../../services/core-control-plane/src/fdai/runtime/bootstrap_resources.py), [bootstrap_messaging.py](../../../services/core-control-plane/src/fdai/runtime/bootstrap_messaging.py), [bootstrap_incidents.py](../../../services/core-control-plane/src/fdai/runtime/bootstrap_incidents.py), [bootstrap_semantics.py](../../../services/core-control-plane/src/fdai/runtime/bootstrap_semantics.py), and [bootstrap_task_hooks.py](../../../services/core-control-plane/src/fdai/runtime/bootstrap_task_hooks.py) | [runtime tests](../../../services/core-control-plane/tests/runtime/), [bootstrap plan tests](../../../services/core-control-plane/tests/runtime/test_bootstrap_plan.py), [messaging tests](../../../services/core-control-plane/tests/runtime/test_bootstrap_messaging.py), [incident tests](../../../services/core-control-plane/tests/runtime/test_bootstrap_incidents.py), and [shutdown tests](../../../services/core-control-plane/tests/runtime/test_bootstrap_shutdown.py) |
| Core contracts and provider seams | Core-only types, provider Protocols, configuration, streaming, and telemetry | [shared](../../../services/core-control-plane/src/fdai/shared/) | [shared tests](../../../services/core-control-plane/tests/shared/) |
| Rule Catalog pipeline | Catalog schema loading, collection, validation, distillation, and promotion support | [rule_catalog](../../../services/core-control-plane/src/fdai/rule_catalog/) | [Rule Catalog tests](../../../services/core-control-plane/tests/rule_catalog/) |
| Reviewed Property semantic coverage | Measured coverage of reviewed Property semantics over rule-evaluated references, evidence rules for declared provider paths, a non-regression floor, and a deterministic priority backlog | [check-property-semantic-coverage.py](../../../scripts/quality/architecture/check-property-semantic-coverage.py) and [property-semantics.yaml](../../../rule-catalog/vocabulary/property-semantics.yaml) | [coverage gate tests](../../../tests/integration/scripts/test_property_semantic_coverage.py) |
| Core service entry point | Core distribution startup and service composition | [fdai_core_service](../../../services/core-control-plane/src/fdai_core_service/) | [Core package tests](../../../services/core-control-plane/tests/) |

Inventory relationship convergence is owned by the continuous operational instance graph. Reviewed
provider parents shadow generic containment, snapshot and ontology stores enforce cardinality, and
the inventory ontology projector serializes graph replacement with its generation commit marker.
Resource ObjectSet receipts preserve source generation and completeness independently from query
truncation, including zero-result reads.
Principal-scoped operational evidence reads bind receipt-verified Context metadata through the
existing bounded response without adding mutation or execution authority.
The Context projection authenticates receipt issuance, compares complete link observation metadata
including source generation and verification lineage, and budgets the bundle and metadata together.
Detection projections similarly expose only source-derived Forecast and Pattern objects; deferred
relationships require exact endpoint identities before catalog restoration.
Cross-source state adjudication is deterministic and read-only: distinct providers and the
projected-state shadow pair withhold conflicts rather than selecting authority.
Distinct-provider inputs require non-empty provider identities before comparison.
They also require bounded target and generation identities plus an injected verifier for every
provider; a caller boolean cannot attest provider identity.
Forecast and Pattern source projections use an idempotent existing instance-store sink.
Authenticated Context reads and detection projections enforce canonical receipt, identity, and
producer checks before returning or persisting semantic evidence.
Receipt authentication compares the complete retained issued receipt and re-derives completeness
from the secured graph, so scope or completeness relabelling cannot reuse an issued digest.
Evidence reads reserve the Context envelope before bundle truncation, so the configured response
budget remains a graceful hold boundary rather than a post-build failure.
PostgreSQL ontology persistence provides atomic create semantics for detection identity deduplication.
The same projection preserves independently verified `runtime_calls` edges in both directions
without treating mutual service calls as an orientation conflict.

The bounded ARM compute overlay owns VMSS VM and NIC child collection through reviewed parent and
attachment mappings. The Console instance presentation omits role assignments, keeps only the
selected non-scope root's immediate Resource Group, and renders the evidence-backed AKS managed
group, VMSS, VM, and NIC hierarchy without adding provider relationships.

The safety-core coverage floor applies to the deterministic tier and risk gate inside the Core
package. Their tests remain under the Core-owned test tree.

Ontology query execution rechecks the exact release, manifest, role, and purpose at runtime. Its
bounded dependency waves include queue wait in each node deadline, propagate in-flight
cancellation, and skip blocked descendants. Stable handler type, value, and runtime failures remain
`capability_failed`; their structured diagnostic allowlists only `node_kind` and `failure_type`,
without exception text, arguments, node identifiers, provider payloads, or operator data.
Composition issues bounded secured ObjectSet receipts and registers the source-derived network
and Pod telemetry functions in the exact release. Function dependencies resolve only an issued
content digest. Exact-id ObjectSets use fixed indexed batches and stop after the result bound is
decidable. The `catalog.search_rules` function accepts only the active Rule generation bound to
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
and input-free validation locations; they omit operator text and provider details. The public composition facade delegates Azure-specific model and catalog binding to
`semantic_query_azure_composition.py` while remaining below the enforced 800-line limit. Its module
contract retains the `composition`, `seam`, and `container` anchors enforced by the package layout
gate. The validated `llm.mode` string selects Azure semantic composition by value, consistent with
every other LLM binder. The ObjectSet handler is rebuilt for each request role,
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
The [lineage producer](../../../services/core-control-plane/src/fdai/core/operational_planning/hypothesis_lineage.py)
and [control-loop sink](../../../services/core-control-plane/src/fdai/core/control_loop/_execution.py)
submit one single-effect episode only when authoritative planning records, a completed executor
result, and one matching independent scorable observation are all present. Projection failure leaves
the executor result unchanged, and this producer rejects plural effects instead of fabricating
missing outcomes. Focused lineage and control-loop shadow tests pin both boundaries.

## Independent service map

| Service | Package responsibility | Package map |
|---------|------------------------|-------------|
| Environment model binding | Shared authority-free policy contract, exact proposal-to-policy join, three-way-CAS Settings projection, unique capability identities, exact GA and TPM/PTU resolution, bounded provider reads, Core-only attested runtime binding, healthy active-revision CAS, policy-bound exact apply, and independent provider readback | [shared contract](../../../packages/service-contracts/src/fdai_service_contracts/model_binding.py), [resolver schema](../../../services/core-control-plane/src/fdai/rule_catalog/schema/model_binding_policy.py), [proposal validator](../../../scripts/deployment/azure/model_binding_proposal.py), [projection workflow](../../../.github/workflows/model-settings-projection.yml), [projection materializer](../../../scripts/deployment/local/materialize-authoritative-settings.py), [service guard](../../../scripts/deployment/service/guard_plan.py), [plan verifier](../../../scripts/deployment/azure/verify-deployment-plan.py), [active revision verifier](../../../scripts/deployment/azure/verify_active_core_revision.py), [provider readback](../../../scripts/deployment/azure/verify_model_deployments.py), [Operator IAM adapter](../../../services/operator-service/src/fdai_operator_service/postgres_iam.py), and [Console editor](../../../console/src/routes/settings-model-binding-policy.tsx) |
| Operator Service | Authenticated route families, durable semantic bridge, process-owned bridge health, ordered managed-identity Kafka lifecycles, exact-release ontology reads, bounded active-inventory impact traversal, and owner-scoped background-task list, detail, progress, and finite SSE replay | [operations family](../../../services/operator-service/src/fdai_operator_service/families/operations/), [background-task projections](../../../services/operator-service/src/fdai_operator_service/families/conversation/background_tasks.py), [PostgreSQL family store](../../../services/operator-service/src/fdai_operator_service/postgres_family_store.py), [read migration](../../../service-migrations/branches/operator-service/versions/20260823_operator_background_task_read.py), [adapters](../../../services/operator-service/src/fdai_operator_service/adapters/), [streaming](../../../services/operator-service/src/fdai_operator_service/streaming/), and [composition.py](../../../services/operator-service/src/fdai_operator_service/composition.py) |
| FDAI Console background-task inspection | Strict owner-scoped task/progress decoders, bilingual list and selected detail presentation, and explicit refresh without create, cancel, retry, or execute controls | [route](../../../console/src/routes/background-tasks.tsx), [decoder](../../../console/src/routes/background-tasks.model.ts), and [decoder tests](../../../console/src/routes/background-tasks.model.test.ts) |
| FDAI Console ontology workbench | Exact declaration routes, strict projection decoders, evidence/dependent/release sections, localized verification state, and snapshot-bound impact/map presentation with no execution controls | [ObjectType workbench](../../../console/src/routes/ontology-object-type-detail.tsx), [impact route](../../../console/src/routes/blast-radius.tsx), [impact decoder](../../../console/src/routes/blast-radius.model.ts), and [ontology contracts](../../../console/src/routes/ontology.types.ts) |
| Network topology visualization | Shared network vocabulary, authored static-diagram contract, observed-only Console focus and path presentation, and sanitized export with no execution authority | [shared vocabulary](../../../packages/network-topology-contracts/), [diagram compiler](../../../tools/architecture-diagrams/), [Console architecture components](../../../console/src/components/), and [owner design](../interfaces/network-topology-visualization.md) |
| Document Ingestion API | Upload intake, API-owned transitions, and service adapters | [package](../../../services/document-ingestion-api/src/fdai_ingestion_api_service/) |
| Document Processing Worker | Durable document processing and worker-owned adapters | [package](../../../services/document-processing-worker/src/fdai_document_worker_service/) |
| Isolated Executor | Thor-owned command handling, provider effects, receipts, and executor adapters | [package](../../../services/isolated-executor/src/fdai_executor_service/) |

These packages may depend on `fdai-service-contracts`. They do not import another service's
implementation package.
Local composition binds service-owned client lifecycles and loopback adapters inside each package.
The Operator semantic bridge, ingestion publisher, document worker consumer, and isolated Executor
therefore preserve the same logical topics, idempotency, readiness, and receipt boundaries as their
deployed managed-identity adapters. The document worker also parses native PDFs in a spawned
resource-limited process so untrusted decompression cannot terminate its long-lived service.

## Shared contract SDK

[fdai_service_contracts](../../../packages/service-contracts/src/fdai_service_contracts/) owns the
versioned wire descriptors, codecs, compatibility checks, readiness records, document contracts,
operator contracts, and executor contracts shared across processes. It contains no service
composition, provider implementation, database access, or business workflow.
`IncidentPageProjection` keeps the generic `PageProjection` wire shape stable while binding an
Incident roster page to its same-snapshot outcome metrics under one read-only Operator contract.
Its optional `incident_number` is a display-only reference allocated from the current UTC month;
canonical Incident and correlation identities remain unchanged.

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
those fields. Runtime publication and consumption remain service-owned implementations, and the
Operator bridge supervises distinct terminal-projection and progress topics.

Semantic-turn requests also preserve a typed screen or resource-group selection with an opaque
server-issued token. Operator resolves the token against the authenticated principal, ordinary
lowercase role scope, purpose, exact release, source generation, completeness, and id set, then
recomputes the selection digest before Core compiles an exact `Resource.id` scope for
`query.contextual_resources`; a client-forged or
recomputed id, missing-after-restart token, or scope mismatch is typed unavailable rather than a
fallback to the principal-visible collection. No context field grants approval or execution
authority.
Explicit utterance predicates are intersected with the token's set, and an incomplete
object-only contextual table holds the semantic turn instead of becoming an answered claim.
This hold is limited to contextual resource plans; other bounded query tables continue to return
their explicit truncation state.
The contextual FunctionType carries its opaque selection token as a scalar schema input while the
object-valued query result remains dependency-only, so a disconnected model node cannot invoke the
specialized read.
Operator instance projections issue the token from the authenticated principal and active
generation, while truncated projections omit the identity entirely.
The shared scope digest uses lowercase ordinary roles (`reader`, `contributor`, `approver`, or
`owner`) and rejects `BreakGlass`. Exact id predicates use batches of at most 128 ids and omit
relationship materialization and relationship-completeness gating for these object-only reads.
The wire contract permits a conservative bounded 512-id context envelope; the general ObjectSet
and store limits remain 1,000.
The context contract rejects mixed incident, screen, and resource-group identities, while exact
selection reads retain the source-generation receipt.
The same 512 bound is enforced by the Operator/Core schema, so oversized client context cannot
enter planning.
The bounded semantic query JSON envelope remains within its existing byte limit for the 512-id
selection without removing the existing row and byte limits on ordinary outputs.

The SDK also owns the logical-topic marker and deterministic consumer-group derivation used when
those two semantic channels share a physical Event Hub. Core and Operator keep separate adapters,
codecs, identities, logical topics, and offset groups; neither imports the other's implementation.
The same contract exports the canonical physical-topic default used when targeted Terraform state
has not yet materialized newly declared outputs.

The SDK also owns the execution-venue contract: the one resolver for `FDAI_EXECUTION_VENUE` and
the one table of venue-selected capability flags. It lives here rather than in a service because
every process resolves the same variable, and an independent service cannot import the core
control plane. `fdai/runtime/venue.py` re-exports it and declares no binding of its own.

The five service distributions use deployable `0.1.2` images as N-1 and `0.1.3` as N. Their existing contract-set
`1.0.0`/`1.1.0` matrix remains the cross-process compatibility boundary.
Content-addressed live evidence also binds the exact service and observation kind and requires
`observed=true`; recomputing a digest cannot convert an unobserved claim into a live receipt.

The package test tree validates SDK behavior. Cross-service N/N-1 and topology checks remain under
[root integration tests](../../../tests/integration/).

## Other repository owners

| Path | Responsibility |
|------|----------------|
| [evaluation-sdk/](../../../evaluation-sdk/) | Dormant independently packaged evaluation contracts and runner, preserved by package-scoped CI. |
| [benchmarks/](../../../benchmarks/) | Dormant external-harness driver packages and the explicit independent CyberGym shadow runner. |
| [eval/golden-dataset/](../../../eval/golden-dataset/) | Bilingual cloud-operations semantic questions with locale-neutral ontology traversal and answer oracles. |
| [services/core-control-plane/src/fdai/delivery/golden_question_dataset.py](../../../services/core-control-plane/src/fdai/delivery/golden_question_dataset.py) | Bounded loader for the repository golden dataset and deterministic typed-observation adapter. Missing semantic axes fail certification before release evidence. |
| [extensions/](../../../extensions/) | Optional independently packaged capabilities. |
| [rule-catalog/](../../../rule-catalog/) | Catalog-as-code data. |
| [policies/](../../../policies/) | OPA/Rego policy-as-code. |
| [console/](../../../console/) | Thin operator SPA. |
| [cli/](../../../cli/) | Operator command-line client. |
| [scripts/agent/design_context.py](../../../scripts/agent/design_context.py) | Record design-context reads, reserve dirty edit paths, hard-block stale context for framework and constitutional edits, guard commit scope and destructive Git, and route repository-wide validation to explicit integration or release boundaries. |

## Related docs

| To learn about | Read |
|----------------|------|
| Physical service and package ownership | [Multi-Service Repository Layout](multi-service-repository-layout.md) |
| Module boundaries and dependency injection | [Project Structure](project-structure.md) |
| Conversation and ontology query implementation sequencing | [Ontology Query Coverage Implementation Plan](../interfaces/ontology-query-coverage-implementation-plan.md) |
| IS work packages and local-first sequencing | [Service Decomposition Execution Plan](service-decomposition-execution-plan.md) |
| Graduation, data ownership, and rollback gates | [Service Graduation and Data Ownership](service-graduation-and-ownership.md) |
| Control-loop authority | [Architecture instructions](../../../.github/instructions/architecture.instructions.md) |
| Agent roles and permissions | [Agent Pantheon](../agents/agent-pantheon.md) |
