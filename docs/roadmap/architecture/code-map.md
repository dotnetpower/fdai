---
title: Code Map
---
# Code Map

This page maps FDAI runtime distributions and repository areas to their source, tests, and owning designs. Use it to find an implementation boundary, not to track feature status or implementation history.

> **Scope:** This index records stable repository ownership. Each linked design owns its behavior and current implementation ledger.
>
> **Historical record:** The retired mixed-purpose status ledger remains in the [archived Code Map implementation ledger](../../roadmap-implementation/architecture/code-map.md).

## Design at a glance

- **Service ownership:** Each deployable service owns its package, tests, migrations, and runtime composition.
- **Core ownership:** The Core Control Plane keeps deterministic decisions, ontology processing, agents, and authority gates inside the `fdai` namespace.
- **Shared contracts:** Cross-process wire types live in implementation-free packages. Services retain validation and business decisions.
- **Integration ownership:** Root integration tests verify cross-service compatibility, repository structure, deployment topology, and rollback boundaries.

## Physical service ownership

| Owner | Source | Tests | Distribution |
|-------|--------|-------|--------------|
| Core Control Plane | [fdai](../../../services/core-control-plane/src/fdai/) and [fdai_core_service](../../../services/core-control-plane/src/fdai_core_service/) | [Core tests](../../../services/core-control-plane/tests/) | `fdai-core-control-plane` |
| Operator Service | [fdai_operator_service](../../../services/operator-service/src/fdai_operator_service/) | [Operator tests](../../../services/operator-service/tests/) | `fdai-operator-service` |
| Document Ingestion API | [fdai_ingestion_api_service](../../../services/document-ingestion-api/src/fdai_ingestion_api_service/) | [Ingestion API tests](../../../services/document-ingestion-api/tests/) | `fdai-document-ingestion-api` |
| Document Processing Worker | [fdai_document_worker_service](../../../services/document-processing-worker/src/fdai_document_worker_service/) | [Worker tests](../../../services/document-processing-worker/tests/) | `fdai-document-processing-worker` |
| Isolated Executor | [fdai_executor_service](../../../services/isolated-executor/src/fdai_executor_service/) | [Executor tests](../../../services/isolated-executor/tests/) | `fdai-isolated-executor-service` |
| System Knowledge Service | [fdai_system_knowledge_service](../../../services/system-knowledge-service/src/fdai_system_knowledge_service/) | [System Knowledge tests](../../../services/system-knowledge-service/tests/) | `fdai-system-knowledge-service` |
| Service contracts | [fdai_service_contracts](../../../packages/service-contracts/src/fdai_service_contracts/) | [Contract tests](../../../packages/service-contracts/tests/) | `fdai-service-contracts` |
| Optional Cost Governance package | [fdai_cost_governance](../../../extensions/cost-governance/src/fdai_cost_governance/) | [Package tests](../../../extensions/cost-governance/tests/) | `fdai-cost-governance` |
| Cross-service integration | Not applicable | [Root integration tests](../../../tests/integration/) | Virtual root only |

## Core Control Plane map

The Core distribution retains the complete `fdai` namespace. The following table points to stable subsystem boundaries; the linked designs and their implementation ledgers contain behavioral detail and delivery evidence.

| Area | Source | Tests | Owning design |
|------|--------|-------|---------------|
| Control loop and decision cases | [control_loop](../../../services/core-control-plane/src/fdai/core/control_loop/) and [decision_case](../../../services/core-control-plane/src/fdai/core/decision_case/) | [Core tests](../../../services/core-control-plane/tests/core/) | [Execution Model](../decisioning/execution-model.md) |
| Agent runtime | [agents](../../../services/core-control-plane/src/fdai/agents/) | [Agent tests](../../../services/core-control-plane/tests/agents/) | [Agent Pantheon](../agents/agent-pantheon.md) |
| Conversation, typed judgment normalization, and semantic query | [conversation](../../../services/core-control-plane/src/fdai/core/conversation/) and [knowledge](../../../services/core-control-plane/src/fdai/core/knowledge/) | [Conversation tests](../../../services/core-control-plane/tests/conversation/) | [Hierarchical Conversation Planning](../interfaces/hierarchical-conversation-planning.md) |
| Operating ontology and instance graph | [ontology_platform](../../../services/core-control-plane/src/fdai/core/ontology_platform/) | [Ontology tests](../../../services/core-control-plane/tests/core/ontology_platform/) | [Operating Ontology Platform](operating-ontology-platform.md) |
| Operational context | [operational_context](../../../services/core-control-plane/src/fdai/core/operational_context/) | [Operational context tests](../../../services/core-control-plane/tests/core/operational_context/) | [Operating Intent Source](operating-intent-source.md) |
| Detection and investigation | [detection](../../../services/core-control-plane/src/fdai/core/detection/) and [investigation](../../../services/core-control-plane/src/fdai/core/investigation/) | [Detection tests](../../../services/core-control-plane/tests/core/detection/) and [investigation tests](../../../services/core-control-plane/tests/core/investigation/) | [Observability and Detection](../rules-and-detection/observability-and-detection.md) |
| Root-cause analysis and assessments | [RCA](../../../services/core-control-plane/src/fdai/core/rca/) and [framework_assessment](../../../services/core-control-plane/src/fdai/core/framework_assessment/) | [RCA tests](../../../services/core-control-plane/tests/core/rca/) and [assessment tests](../../../services/core-control-plane/tests/core/framework_assessment/) | [Root Cause Analysis](../rules-and-detection/root-cause-analysis.md) |
| Workflow and execution coordination | [workflow](../../../services/core-control-plane/src/fdai/core/workflow/) and [executor](../../../services/core-control-plane/src/fdai/core/executor/) | [Workflow tests](../../../services/core-control-plane/tests/core/workflow/) and [executor tests](../../../services/core-control-plane/tests/core/executor/) | [Execution Authorization Ontology](../decisioning/execution-authorization-ontology.md) |
| Rule Catalog runtime | [rule_catalog](../../../services/core-control-plane/src/fdai/rule_catalog/) | [Rule Catalog tests](../../../services/core-control-plane/tests/rule_catalog/) | [Rule Catalog Collection](../rules-and-detection/rule-catalog-collection.md) |
| Measurement and governed cohort evidence | [measurement core](../../../services/core-control-plane/src/fdai/core/measurement/) and [measurement delivery](../../../services/core-control-plane/src/fdai/delivery/measurement/) | [measurement tests](../../../services/core-control-plane/tests/core/measurement/) and [delivery measurement tests](../../../services/core-control-plane/tests/delivery/measurement/) | [Goals and Metrics](goals-and-metrics.md) |
| Prompt and model bindings | [prompts](../../../services/core-control-plane/src/fdai/core/prompts/) and [LLM composition](../../../services/core-control-plane/src/fdai/composition/wire_llm.py) | [Prompt tests](../../../services/core-control-plane/tests/core/prompts/) | [Prompt Composition](../decisioning/prompt-composition.md) |
| Delivery and persistence adapters | [delivery](../../../services/core-control-plane/src/fdai/delivery/) | [Delivery tests](../../../services/core-control-plane/tests/delivery/) and [persistence tests](../../../services/core-control-plane/tests/persistence/) | [Project Structure](project-structure.md) |
| Composition and runtime | [composition](../../../services/core-control-plane/src/fdai/composition/) and [runtime](../../../services/core-control-plane/src/fdai/runtime/) | [Composition tests](../../../services/core-control-plane/tests/composition/) and [runtime tests](../../../services/core-control-plane/tests/runtime/) | [Project Structure](project-structure.md) |
| Core service entry point | [fdai_core_service](../../../services/core-control-plane/src/fdai_core_service/) | [Core service tests](../../../services/core-control-plane/tests/) | [Multi-Service Repository Layout](multi-service-repository-layout.md) |

## Independent service map

| Service | Responsibility | Package map |
|---------|----------------|-------------|
| Operator Service | Authenticated operator APIs, read models, approval channels, and durable conversation projection | [package](../../../services/operator-service/src/fdai_operator_service/) and [design](../interfaces/operator-console.md) |
| Document Ingestion API | Upload intake, connector state, document policy, and ingestion publication | [package](../../../services/document-ingestion-api/src/fdai_ingestion_api_service/) and [design](../interfaces/document-ingestion.md) |
| Document Processing Worker | Durable extraction, optical character recognition, indexing, and publication | [package](../../../services/document-processing-worker/src/fdai_document_worker_service/) and [design](../interfaces/document-lifecycle-governance.md) |
| Isolated Executor | Thor-owned command handling, provider effects, and execution receipts | [package](../../../services/isolated-executor/src/fdai_executor_service/) and [design](../decisioning/execution-model.md) |
| System Knowledge Service | Release-bound repository knowledge retrieval through mutually exclusive Bot Framework or HMAC-authenticated Outgoing Webhook mention ingress, with no operational authority | [package](../../../services/system-knowledge-service/src/fdai_system_knowledge_service/) and [design](../interfaces/system-knowledge-service.md) |
| Cost Governance extension | Optional independently packaged cost analysis and policy integration | [package](../../../extensions/cost-governance/src/fdai_cost_governance/) and [design](finops-package-architecture.md) |
| Console | Thin operator single-page application over Operator Service contracts | [package](../../../console/) and [design](../interfaces/operator-console.md) |

Services depend on [fdai-service-contracts](../../../packages/service-contracts/), not on another service implementation. Local and deployed composition preserve the same logical topics, idempotency, readiness, and receipt boundaries.

## Shared contract SDK

| Package | Responsibility | Tests |
|---------|----------------|-------|
| [fdai-service-contracts](../../../packages/service-contracts/) | Versioned cross-process wire descriptors, codecs, readiness records, and compatibility checks without service composition or provider I/O | [Contract tests](../../../packages/service-contracts/tests/) |
| [github-app-auth](../../../packages/github-app-auth/) | Refreshable GitHub App credentials shared by approved service images | [Package tests](../../../packages/github-app-auth/tests/) |

The [shared contract runtime reference](../../reference/shared-contract-runtime.md) documents version negotiation, logical topics, execution venues, and compatibility rules.

## Other repository owners

| Path | Responsibility |
|------|----------------|
| [evaluation-sdk](../../../evaluation-sdk/) and [benchmarks](../../../benchmarks/) | Independently packaged evaluation contracts and external harness drivers |
| [eval/golden-dataset](../../../eval/golden-dataset/) | Bilingual semantic questions, typed observations, and answer oracles |
| [extensions](../../../extensions/) | Optional independently packaged capabilities |
| [rule-catalog](../../../rule-catalog/) | Catalog-as-code schemas, vocabulary, rules, and collected sources |
| [policies](../../../policies/) | OPA/Rego policy-as-code |
| [console](../../../console/) | Operator web application |
| [infra](../../../infra/) | Terraform modules and deployment roots |
| [cli](../../../cli/) and [deployment-cli](../../../packages/deployment-cli/) | Operator and deployment command-line tooling |
| [scripts](../../../scripts/) | Repository quality, development, deployment, and agent workflow automation |

## Maintaining this map

- Update this page only when a stable owner, source root, test root, distribution, or owning design changes.
- Record behavior, implementation status, validation evidence, and delivery history in the owning design and its implementation ledger.
- Keep entries at subsystem or package granularity. Link to focused documents instead of appending feature narratives.
- Update the English and Korean pages together. The document-size gate limits this index so it cannot become a status ledger again.

## Related docs

| To learn about | Read |
|----------------|------|
| Physical service and package ownership | [Multi-Service Repository Layout](multi-service-repository-layout.md) |
| Module boundaries and dependency injection | [Project Structure](project-structure.md) |
| Service work packages and local-first sequencing | [Service Decomposition Execution Plan](service-decomposition-execution-plan.md) |
| Service promotion, data ownership, and rollback | [Service Graduation and Data Ownership](service-graduation-and-ownership.md) |
| Control-loop authority | [Architecture instructions](../../../.github/instructions/architecture.instructions.md) |
| Agent roles and permissions | [Agent Pantheon](../agents/agent-pantheon.md) |
