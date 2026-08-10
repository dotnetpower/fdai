---
title: 코드 맵
translation_of: code-map.md
translation_source_sha: 43dad4edeb7d5649769c363a2e6cc887334d3171
translation_revised: 2026-08-10
---
# 코드 맵

이 페이지는 각 FDAI runtime service와 shared package를 물리 source, test 및 소유 design에
연결합니다. 폐기된 최상위 application tree에 의존하지 않고 현재 service-owned implementation을
찾을 때 사용합니다.

> **범위:** 이 map은 검증된 로컬 IS-08 repository ownership과 IS-07 local upgrade 및 rollback
> proof를 설명합니다. 지연된 remote verification은 IS-09가 소유합니다.

## 설계 개요

- **Service distribution 5개:** 각 runtime process는 `services/` 아래 package 하나를 소유합니다.
- **Shared SDK 1개:** `packages/service-contracts/`는 service implementation 없이 cross-service
  contract를 포함합니다.
- **Service-owned test:** Unit 및 component test는 소유 service 또는 package 옆에 있습니다.
- **Virtual root:** Root `pyproject.toml`은 `package = false`이며 uv workspace를 조정합니다.
- **Integration-only root test:** `tests/integration/`은 cross-service compatibility, topology 및
  repository check를 소유합니다.

## 물리 service 소유권

| 소유자 | Source | Test | Distribution |
|--------|--------|------|--------------|
| Core Control Plane | [fdai](../../../services/core-control-plane/src/fdai/)와 [fdai_core_service](../../../services/core-control-plane/src/fdai_core_service/) | [Core test](../../../services/core-control-plane/tests/) | `fdai-core-control-plane` |
| Operator Service | [fdai_operator_service](../../../services/operator-service/src/fdai_operator_service/) | [Operator test](../../../services/operator-service/tests/) | `fdai-operator-service` |
| Document Ingestion API | [fdai_ingestion_api_service](../../../services/document-ingestion-api/src/fdai_ingestion_api_service/) | [Ingestion API test](../../../services/document-ingestion-api/tests/) | `fdai-document-ingestion-api` |
| Document Processing Worker | [fdai_document_worker_service](../../../services/document-processing-worker/src/fdai_document_worker_service/) | [Worker test](../../../services/document-processing-worker/tests/) | `fdai-document-processing-worker` |
| Isolated Executor | [fdai_executor_service](../../../services/isolated-executor/src/fdai_executor_service/) | [Executor test](../../../services/isolated-executor/tests/) | `fdai-isolated-executor-service` |
| Service contract | [fdai_service_contracts](../../../packages/service-contracts/src/fdai_service_contracts/) | [Contract test](../../../packages/service-contracts/tests/) | `fdai-service-contracts` |
| Cross-service integration | 해당 없음 | [Root integration test](../../../tests/integration/) | Virtual root only |

## Core Control Plane map

Core distribution은 전체 `fdai` namespace를 유지합니다. 내부 module boundary는 물리 이동으로
변경되지 않습니다.

| 영역 | Responsibility | Source | Test |
|------|----------------|--------|------|
| Control loop와 decisioning | Event normalization, tier routing, quality, risk, approval, execution coordination, recovery 및 audit | [core](../../../services/core-control-plane/src/fdai/core/) | [core test](../../../services/core-control-plane/tests/core/) |
| Ontology safety platform | Exact semantic release, principal-scoped query manifest, bounded query, mutation plan, independent effect reconciliation 및 durable reconciliation record | [ontology_platform](../../../services/core-control-plane/src/fdai/core/ontology_platform/) | [ontology platform test](../../../services/core-control-plane/tests/core/ontology_platform/) |
| Agent pantheon | 고정 agent 15개와 typed event runtime | [agents](../../../services/core-control-plane/src/fdai/agents/) | [agent test](../../../services/core-control-plane/tests/agents/) |
| Composition | Provider 및 runtime dependency injection | [composition](../../../services/core-control-plane/src/fdai/composition/) | [composition test](../../../services/core-control-plane/tests/composition/) |
| Core adapter | Core에 남은 provider, persistence, notification 및 platform adapter | [delivery](../../../services/core-control-plane/src/fdai/delivery/) | [delivery test](../../../services/core-control-plane/tests/delivery/) |
| Runtime | Core process lifecycle, readiness, event transport 및 supervision | [runtime](../../../services/core-control-plane/src/fdai/runtime/) | [runtime test](../../../services/core-control-plane/tests/runtime/) |
| Core contract와 provider seam | Core 전용 type, provider Protocol, configuration, streaming 및 telemetry | [shared](../../../services/core-control-plane/src/fdai/shared/) | [shared test](../../../services/core-control-plane/tests/shared/) |
| Rule Catalog pipeline | Catalog schema loading, collection, validation, distillation 및 promotion support | [rule_catalog](../../../services/core-control-plane/src/fdai/rule_catalog/) | [Rule Catalog test](../../../services/core-control-plane/tests/rule_catalog/) |
| Core service entry point | Core distribution startup과 service composition | [fdai_core_service](../../../services/core-control-plane/src/fdai_core_service/) | [Core package test](../../../services/core-control-plane/tests/) |

Safety-core coverage floor는 Core package 안의 deterministic tier와 risk gate에 적용됩니다. 해당
test는 Core 소유 test tree에 유지합니다.

## 독립 service map

| Service | Package responsibility | Package map |
|---------|------------------------|-------------|
| Operator Service | 인증된 operator route family와 process-local composition | [families](../../../services/operator-service/src/fdai_operator_service/families/) 및 [composition.py](../../../services/operator-service/src/fdai_operator_service/composition.py) |
| Document Ingestion API | Upload intake, API 소유 transition 및 service adapter | [package](../../../services/document-ingestion-api/src/fdai_ingestion_api_service/) |
| Document Processing Worker | Durable document processing과 worker 소유 adapter | [package](../../../services/document-processing-worker/src/fdai_document_worker_service/) |
| Isolated Executor | Thor 소유 command handling, provider effect, receipt 및 executor adapter | [package](../../../services/isolated-executor/src/fdai_executor_service/) |

이 package는 `fdai-service-contracts`에 의존할 수 있습니다. 다른 service의 implementation
package는 import하지 않습니다.

## Shared contract SDK

[fdai_service_contracts](../../../packages/service-contracts/src/fdai_service_contracts/)는 process가
공유하는 versioned wire descriptor, codec, compatibility check, readiness record, document contract,
operator contract 및 executor contract를 소유합니다. Service composition, provider implementation,
database access 또는 business workflow는 포함하지 않습니다.

Shared SDK는 Core/Operator boundary에서 사용하는 no-authority ontology-query record도 소유합니다.
Semantic problem frame, bounded query DAG, intent graph, task receipt 및 structural coverage receipt입니다.
Provider client, ontology store, planner model 또는 execution handler는 포함하지 않습니다.

Service distribution 5개는 deployable `0.1.2` image를 N-1, `0.1.3`을 N으로 사용합니다. 기존 contract-set
`1.0.0`/`1.1.0` matrix는 cross-process compatibility boundary로 유지합니다.
Content-addressed live evidence는 exact service와 observation kind도 binding하고 `observed=true`를
요구합니다. Digest를 다시 계산해도 관측하지 않은 claim은 live receipt가 될 수 없습니다.

Package test tree는 SDK behavior를 검증합니다. Cross-service N/N-1 및 topology check는
[root integration test](../../../tests/integration/)에 유지합니다.

## 기타 repository owner

| Path | Responsibility |
|------|----------------|
| [evaluation-sdk/](../../../evaluation-sdk/) | 독립 package evaluation contract와 runner입니다. |
| [benchmarks/](../../../benchmarks/) | 독립 benchmark driver입니다. |
| [extensions/](../../../extensions/) | 선택적 독립 package capability입니다. |
| [rule-catalog/](../../../rule-catalog/) | Catalog-as-code data입니다. |
| [policies/](../../../policies/) | OPA/Rego policy-as-code입니다. |
| [console/](../../../console/) | 얇은 operator SPA입니다. |
| [cli/](../../../cli/) | Operator command-line client입니다. |
| [scripts/agent/design_context.py](../../../scripts/agent/design_context.py)와 [external_operation_guard.py](../../../scripts/agent/external_operation_guard.py) | Design context read를 기록하고 framework 및 constitution edit의 stale context를 hard-block하며, 중복 repository-wide validation을 차단하고 `HEAD`에 validation receipt가 생길 때까지 느린 CI, deployment 및 image 작업을 지연합니다. |

## 관련 문서

| 알아볼 내용 | 문서 |
|-------------|------|
| 전체 package boundary와 dependency injection | [프로젝트 구조](project-structure-ko.md) |
| Conversation 및 ontology query 구현 sequencing | [Ontology Query Coverage 구현 계획](../interfaces/ontology-query-coverage-implementation-plan-ko.md) |
| IS work package와 local-first sequencing | [서비스 분해 실행 계획](service-decomposition-execution-plan-ko.md) |
| Service 승격, data ownership 및 rollback gate | [서비스 승격과 데이터 소유권](service-graduation-and-ownership-ko.md) |
| Control-loop authority | [Architecture instructions](../../../.github/instructions/architecture.instructions.md) |
| Agent role과 permission | [Agent Pantheon](../agents/agent-pantheon-ko.md) |
