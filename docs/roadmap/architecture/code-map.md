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
| Control loop and decisioning | Event normalization, tier routing, quality, risk, approval, execution coordination, recovery, and audit | [core](../../../services/core-control-plane/src/fdai/core/) | [core tests](../../../services/core-control-plane/tests/core/) |
| Ontology safety platform | Exact semantic releases, production Interface compilation, principal-scoped manifests, generic and temporal query algebra, bitemporal topology and diffs, reviewed metric concepts, topology-aware causal joins, mutation plans, independent effect reconciliation, and durable reconciliation records | [ontology_platform](../../../services/core-control-plane/src/fdai/core/ontology_platform/) | [ontology platform tests](../../../services/core-control-plane/tests/core/ontology_platform/) |
| Semantic conversation planning | Whole-turn schema proposals, server-owned frame/plan identity, principal-manifest verification, async verified execution, total terminal disposition, deterministic intent graphs, exact-command compatibility cutover, and continuous coverage gates without execution authority | [conversation](../../../services/core-control-plane/src/fdai/core/conversation/) | [conversation tests](../../../services/core-control-plane/tests/conversation/) |
| Ontology semantic generations | Candidate-only concrete index, full/incremental declaration and deployment-object documents, independent validation receipts, atomic activation, stale detection, and rollback | [catalog_search](../../../services/core-control-plane/src/fdai/delivery/catalog_search/) | [catalog search tests](../../../services/core-control-plane/tests/delivery/catalog_search/) |
| Metric semantic provider binding | Alias-free reviewed metric concepts and exact `MetricProvider` windows that distinguish observed zero from provider gaps | [metric_window.py](../../../services/core-control-plane/src/fdai/delivery/metric_window.py) and [metric_semantic_catalog.py](../../../services/core-control-plane/src/fdai/runtime/metric_semantic_catalog.py) | [metric semantic catalog tests](../../../services/core-control-plane/tests/runtime/test_metric_semantic_catalog.py) |
| Agent pantheon | Fifteen fixed agents and their typed event runtime | [agents](../../../services/core-control-plane/src/fdai/agents/) | [agent tests](../../../services/core-control-plane/tests/agents/) |
| Composition | Provider and runtime dependency injection, including exact-release semantic query assembly and request-role executor factories | [composition](../../../services/core-control-plane/src/fdai/composition/) | [composition tests](../../../services/core-control-plane/tests/composition/) |
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
Planner manifests apply identical role and purpose filtering to ObjectType and Interface
properties. Intent evidence preserves a terminal reason while also disclosing bounded
evidence-reference truncation.
The verifier rejects outputs that don't name declared DAG nodes before I/O. Answered turns render
only bounded verified query tables, and transient projection publication retries the same durable
idempotent result before dead-lettering.
Azure semantic planning uses existing `httpx` and `WorkloadIdentity` adapters for two validated
JSON-object proposals. Composition exposes only handlers with bound authoritative providers. The
public composition facade re-exports the dedicated semantic query binder while remaining below its
400-line structural ceiling. Its module contract retains the `composition`, `seam`, and `container`
anchors enforced by the package layout gate. The ObjectSet handler is rebuilt for each request role,
so a Reader cannot inherit Owner visibility and an Owner is not silently reduced to Reader. Missing
model, release, store, or transport prerequisites
remain explicit startup-readiness failures rather than an implicit `runtime=None`.
Continuous coverage receipts separate deterministic fixture structural validation from production
readiness. Only externally produced `cross_service_e2e` or `live_assurance` question receipts can
set `production_ready`; a committed `deterministic_fixture` keeps it false.
Runtime bootstrap delegates semantic readiness and vertical workload-identity construction to its
existing lifecycle and binding helpers, keeping the primary composition root below the reviewed
fanout ceiling. A thin bootstrap wrapper preserves the injected identity-builder test and fork seam.

## Independent service map

| Service | Package responsibility | Package map |
|---------|------------------------|-------------|
| Operator Service | Authenticated route families, durable semantic bridge, and managed-identity Kafka transport | [families](../../../services/operator-service/src/fdai_operator_service/families/), [adapters](../../../services/operator-service/src/fdai_operator_service/adapters/), and [composition.py](../../../services/operator-service/src/fdai_operator_service/composition.py) |
| Document Ingestion API | Upload intake, API-owned transitions, and service adapters | [package](../../../services/document-ingestion-api/src/fdai_ingestion_api_service/) |
| Document Processing Worker | Durable document processing and worker-owned adapters | [package](../../../services/document-processing-worker/src/fdai_document_worker_service/) |
| Isolated Executor | Thor-owned command handling, provider effects, receipts, and executor adapters | [package](../../../services/isolated-executor/src/fdai_executor_service/) |

These packages may depend on `fdai-service-contracts`. They do not import another service's
implementation package.

## Shared contract SDK

[fdai_service_contracts](../../../packages/service-contracts/src/fdai_service_contracts/) owns the
versioned wire descriptors, codecs, compatibility checks, readiness records, document contracts,
operator contracts, and executor contracts shared across processes. It contains no service
composition, provider implementation, database access, or business workflow.

The shared SDK also owns the no-authority ontology-query records used across the Core and Operator
boundary: semantic problem frames, bounded query DAGs, intent graphs, task receipts, and structural
coverage receipts. These records contain no provider client, ontology store, planner model, or
execution handler.

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
