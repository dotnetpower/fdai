---
title: 코드 맵
translation_of: code-map.md
translation_source_sha: db8d440d96e8c860520dd463ab0d1e498c1c80f6
translation_revised: 2026-08-12
---
# 코드 맵

이 페이지는 각 FDAI 런타임 서비스와 shared 패키지를 물리 출처, 테스트 및 소유 design에
연결합니다. 폐기된 최상위 애플리케이션 트리에 의존하지 않고 현재 service-owned 구현을
찾을 때 사용합니다.

> **범위:** 이 지도는 검증된 로컬 IS-08 저장소 소유권과 IS-07 로컬 업그레이드 및 롤백
> 증명을 설명합니다. 지연된 원격 검증은 IS-09가 소유합니다.

## 설계 개요

- **서비스 분포 5개:** 각 런타임 프로세스는 `services/` 아래 패키지 하나를 소유합니다.
- **Shared SDK 1개:** `packages/service-contracts/`는 서비스 구현 없이 서비스 간
  계약을 포함합니다.
- **Service-owned 테스트:** 단위 및 컴포넌트 테스트는 소유 서비스 또는 패키지 옆에 있습니다.
- **가상 루트:** 루트 `pyproject.toml`은 `package = false`이며 uv workspace를 조정합니다.
- **Integration-only 루트 테스트:** `tests/integration/`은 서비스 간 호환성, 토폴로지 및
  저장소 검사를 소유합니다.

## 물리 서비스 소유권

| 소유자 | 출처 | 테스트 | 분포 |
|--------|--------|------|--------------|
| Core 컨트롤 플레인 | [fdai](../../../services/core-control-plane/src/fdai/)와 [fdai_core_service](../../../services/core-control-plane/src/fdai_core_service/) | [Core 테스트](../../../services/core-control-plane/tests/) | `fdai-core-control-plane` |
| Operator 서비스 | [fdai_operator_service](../../../services/operator-service/src/fdai_operator_service/) | [Operator 테스트](../../../services/operator-service/tests/) | `fdai-operator-service` |
| 문서 인제스트 API | [fdai_ingestion_api_service](../../../services/document-ingestion-api/src/fdai_ingestion_api_service/) | [인제스트 API 테스트](../../../services/document-ingestion-api/tests/) | `fdai-document-ingestion-api` |
| 문서 처리 워커 | [fdai_document_worker_service](../../../services/document-processing-worker/src/fdai_document_worker_service/) | [워커 테스트](../../../services/document-processing-worker/tests/) | `fdai-document-processing-worker` |
| Isolated 실행기 | [fdai_executor_service](../../../services/isolated-executor/src/fdai_executor_service/) | [실행기 테스트](../../../services/isolated-executor/tests/) | `fdai-isolated-executor-service` |
| 서비스 계약 | [fdai_service_contracts](../../../packages/service-contracts/src/fdai_service_contracts/) | [계약 테스트](../../../packages/service-contracts/tests/) | `fdai-service-contracts` |
| 서비스 간 통합 | 해당 없음 | [루트 통합 테스트](../../../tests/integration/) | 가상 루트 only |

## Core 컨트롤 플레인 지도

Core 분포는 전체 `fdai` 이름 공간을 유지합니다. 내부 모듈 경계는 물리 이동으로
변경되지 않습니다.

| 영역 | Responsibility | 출처 | 테스트 |
|------|----------------|--------|------|
| 컨트롤 루프와 decisioning | Event 정규화, 계층 라우팅, quality, risk, 승인, 실행 coordination, 복구 및 감사 | [코어](../../../services/core-control-plane/src/fdai/core/) | [코어 테스트](../../../services/core-control-plane/tests/core/) |
| 온톨로지 안전성 platform | 카탈로그에서 로드한 Interface 및 FunctionType 선언을 포함하는 exact 의미 release, release-aware 조회 profile 및 함수 등록, principal 범위로 한정된 매니페스트, 범용/temporal 조회 algebra, bitemporal 토폴로지/차이, 범위가 제한된 blast-radius 차이와 authoritative inventory rebuild pointer를 포함하는 immutable direction-generation shadow comparison, 검토된 메트릭 개념, topology-aware causal 결합, 변경 계획, compact typed effect-reconciliation event, 인증된 독립 observer binding 및 lease-fenced 영속 terminal outbox 전달 | [ontology_platform](../../../services/core-control-plane/src/fdai/core/ontology_platform/) | [온톨로지 platform 테스트](../../../services/core-control-plane/tests/core/ontology_platform/) |
| 의미 대화 계획 수립 | Whole-turn 스키마 제안, 서버가 소유한 프레임/계획 신원, principal-manifest 검증, 비동기 검증된 실행, 합계 최종 처리 결과, 결정론적 의도 그래프, exact-command 호환성 전환 및 실행 권한이 없는 continuous 커버리지 게이트 | [대화](../../../services/core-control-plane/src/fdai/core/conversation/) | [대화 테스트](../../../services/core-control-plane/tests/conversation/) |
| 온톨로지 의미 세대 | 후보 전용 구체적인 인덱스, full/incremental 선언 및 deployment-object 문서, 독립적인 검증 증적, atomic activation, stale detection 및 롤백 | [catalog_search](../../../services/core-control-plane/src/fdai/delivery/catalog_search/) | [카탈로그 검색 테스트](../../../services/core-control-plane/tests/delivery/catalog_search/) |
| 메트릭 의미 프로바이더 연결 | Alias-free 검토된 메트릭 개념과 관찰된 zero를 프로바이더 공백과 구분하는 exact `MetricProvider` 구간 | [metric_window.py](../../../services/core-control-plane/src/fdai/delivery/metric_window.py) 및 [metric_semantic_catalog.py](../../../services/core-control-plane/src/fdai/runtime/metric_semantic_catalog.py) | [메트릭 의미 카탈로그 테스트](../../../services/core-control-plane/tests/runtime/test_metric_semantic_catalog.py) |
| 에이전트 pantheon | 고정 에이전트 15개와 타입이 지정된 이벤트 런타임 | [에이전트](../../../services/core-control-plane/src/fdai/agents/) | [에이전트 테스트](../../../services/core-control-plane/tests/agents/) |
| 조립 | Exact-release 의미 조회 assembly와 request-role 실행기 factory를 포함한 프로바이더/런타임 의존성 주입 | [조립](../../../services/core-control-plane/src/fdai/composition/) | [조립 테스트](../../../services/core-control-plane/tests/composition/) |
| Core 어댑터 | Core에 남은 프로바이더, 영속성, 알림 및 platform 어댑터 | [전달](../../../services/core-control-plane/src/fdai/delivery/) | [전달 테스트](../../../services/core-control-plane/tests/delivery/) |
| 런타임 | Core 프로세스 수명 주기, 준비 상태, 이벤트 전송 계층, supervision 및 의미 런타임 가용성 연결 | [런타임](../../../services/core-control-plane/src/fdai/runtime/) | [런타임 테스트](../../../services/core-control-plane/tests/runtime/) |
| Core 계약과 프로바이더 경계 | Core 전용 타입, 프로바이더 프로토콜, 구성, 스트리밍 및 텔레메트리 | [shared](../../../services/core-control-plane/src/fdai/shared/) | [shared 테스트](../../../services/core-control-plane/tests/shared/) |
| Rule 카탈로그 파이프라인 | 카탈로그 스키마 로딩, 수집, 검증, 정제 및 승격 support | [rule_catalog](../../../services/core-control-plane/src/fdai/rule_catalog/) | [Rule 카탈로그 테스트](../../../services/core-control-plane/tests/rule_catalog/) |
| Core 서비스 항목 지점 | Core 분포 시작과 서비스 조립 | [fdai_core_service](../../../services/core-control-plane/src/fdai_core_service/) | [Core 패키지 테스트](../../../services/core-control-plane/tests/) |

Safety-core 커버리지 하한은 Core 패키지 안의 결정론적 계층과 risk 게이트에 적용됩니다. 해당
테스트는 Core 소유 테스트 트리에 유지합니다.

온톨로지 조회 실행은 런타임에서 exact release, 매니페스트, 역할 및 용도를 다시 검사합니다.
범위가 제한된 의존성 wave는 노드 기한에 큐 wait를 포함하고 in-flight 취소를 전파하며
차단된 descendant를 건너뜀하고 프로바이더 오류 상세 없는 고정된 증적을 발행합니다.
플래너 매니페스트는 ObjectType 및 Interface 속성에 동일한 역할/용도 filtering을 적용합니다. 의도
근거는 최종 사유를 보존하면서 범위가 제한된 evidence-reference 잘림도 공개합니다.
검증기는 I/O 전에 declared DAG 노드를 가리키지 않는 출력을 거부합니다. Answered 턴은 범위가 제한된
검증된 조회 표만 렌더링하며 transient 변환 결과 게시는 dead-letter 전에 같은 영속
멱등적 결과를 재시도합니다.
Azure 의미 계획 수립은 기존 `httpx` 및 `WorkloadIdentity` 어댑터를 사용하여 검증된 JSON-object
제안 두 개를 만듭니다. 조립은 권위 있는 프로바이더가 연결된 핸들러만 노출합니다. 공개
조립 파사드는 dedicated 의미 조회 연결기를 re-export하면서 400-line structural 상한 아래를
유지합니다. 모듈 계약은 패키지 배치 게이트가 강제하는 `composition`, `seam` 및 `container`
기준점을 보존합니다. 검증된 `llm.mode` 문자열은 다른 LLM 연결기와 동일하게 값 비교로 Azure
의미 조립을 선택합니다.
ObjectSet 핸들러는 각 요청 역할에 맞게 다시 만들어지므로 읽기 담당이 Owner 가시성을 상속하지 않고
Owner도 읽기 담당으로 조용히 축소되지 않습니다. 모델, release, 저장소 또는 전송 계층 선행 조건이 없으면
암시적 `runtime=None` 대신 명시적 startup-readiness 실패로 유지됩니다.
Continuous 커버리지 증적은 결정론적 고정본 structural 검증과 운영 준비 상태를
분리합니다. 외부에서 생성된 `cross_service_e2e` 또는 `live_assurance` 질문 증적만
`production_ready`를 설정할 수 있으며 committed `deterministic_fixture`는 false로 유지합니다.
런타임 초기화는 의미 준비 상태와 버티컬 workload-identity construction을 기존 수명 주기 및
연결 보조 로직에 위임하여 기본 조립 루트를 검토된 fanout 상한 아래로 유지합니다. Thin
초기화 래퍼는 injected identity-builder 테스트 및 포크 경계를 보존합니다.

## 독립 서비스 지도

| 서비스 | 패키지 responsibility | 패키지 지도 |
|---------|------------------------|-------------|
| Operator 서비스 | 인증된 경로 계열, 영속 의미 브리지 및 managed-identity Kafka 전송 계층 | [families](../../../services/operator-service/src/fdai_operator_service/families/), [어댑터](../../../services/operator-service/src/fdai_operator_service/adapters/) 및 [composition.py](../../../services/operator-service/src/fdai_operator_service/composition.py) |
| 문서 인제스트 API | 업로드 intake, API 소유 전이 및 서비스 어댑터 | [패키지](../../../services/document-ingestion-api/src/fdai_ingestion_api_service/) |
| 문서 처리 워커 | 영속 문서 처리와 워커 소유 어댑터 | [패키지](../../../services/document-processing-worker/src/fdai_document_worker_service/) |
| Isolated 실행기 | Thor 소유 명령 처리, 프로바이더 효과, 증적 및 실행기 어댑터 | [패키지](../../../services/isolated-executor/src/fdai_executor_service/) |

이 패키지는 `fdai-service-contracts`에 의존할 수 있습니다. 다른 서비스의 구현
패키지는 가져오기하지 않습니다.

## Shared 계약 SDK

[fdai_service_contracts](../../../packages/service-contracts/src/fdai_service_contracts/)는 프로세스가
공유하는 versioned wire 서술자, codec, 호환성 검사, 준비 상태 기록, 문서 계약,
운영자 계약 및 실행기 계약을 소유합니다. 서비스 조립, 프로바이더 구현,
데이터베이스 접근 또는 business 작업 흐름은 포함하지 않습니다.

Shared SDK는 Core/Operator 경계에서 사용하는 no-authority ontology-query 기록도 소유합니다.
의미 problem 프레임, 범위가 제한된 조회 DAG, 의도 그래프, 작업 증적 및 structural 커버리지 증적입니다.
프로바이더 클라이언트, 온톨로지 저장소, 플래너 모델 또는 실행 핸들러는 포함하지 않습니다.

기존 Operator/Core 묶음의 버전 1.2는 범위가 제한된 semantic-turn 요청 하나와 근거에 묶인 최종
결과 하나를 추가합니다. 요청은 인증된 역할, 세션 정렬, 용도, 기한 및 멱등성을
pin합니다. Answered 결과에는 exact release, 매니페스트, 계획, 실행 증적 및 근거 참조가
필요합니다. SDK는 해당 필드를 폐기하는 대신 의미 downgrade to N-1을 거부합니다. 런타임
게시와 consumption은 service-owned 구현으로 유지됩니다.

SDK는 두 semantic channel이 하나의 physical Event Hub를 공유할 때 사용하는 logical-topic marker와
결정론적 consumer-group 파생 규칙도 소유합니다. Core와 Operator는 서로 다른 adapter, codec,
identity, logical topic 및 offset group을 유지하며 상대 서비스 구현을 가져오지 않습니다. 같은 계약은
targeted Terraform 상태가 새 output을 아직 materialize하지 않았을 때 사용하는 canonical physical-topic
기본값도 제공합니다.

서비스 분포 5개는 deployable `0.1.2` 이미지를 N-1, `0.1.3`을 N으로 사용합니다. 기존 contract-set
`1.0.0`/`1.1.0` 매트릭스는 프로세스 간 호환성 경계로 유지합니다.
내용 기반 주소를 가진 실제 운영 근거는 exact 서비스와 관측 종류도 연결하고 `observed=true`를
요구합니다. 다이제스트를 다시 계산해도 관측하지 않은 점유는 실제 운영 증적이 될 수 없습니다.

패키지 테스트 트리는 SDK 행동을 검증합니다. 서비스 간 N/N-1 및 토폴로지 검사는
[루트 통합 테스트](../../../tests/integration/)에 유지합니다.

## 기타 저장소 소유자

| 경로 | Responsibility |
|------|----------------|
| [evaluation-sdk/](../../../evaluation-sdk/) | 독립 패키지 evaluation 계약과 실행기입니다. |
| [benchmarks/](../../../benchmarks/) | 독립 벤치마크 driver입니다. |
| [extensions/](../../../extensions/) | 선택적 독립 패키지 기능입니다. |
| [rule-catalog/](../../../rule-catalog/) | Catalog-as-code 데이터입니다. |
| [policies/](../../../policies/) | OPA/Rego policy-as-code입니다. |
| [콘솔/](../../../console/) | 얇은 운영자 SPA입니다. |
| [cli/](../../../cli/) | Operator command-line 클라이언트입니다. |
| [scripts/agent/design_context.py](../../../scripts/agent/design_context.py)와 [external_operation_guard.py](../../../scripts/agent/external_operation_guard.py) | Design 맥락 읽기를 기록하고 framework 및 constitution 편집의 stale 맥락을 hard-block하며, 중복 repository-wide 검증을 차단하고 `HEAD`에 검증 증적이 생길 때까지 느린 CI, 배포 및 이미지 작업을 지연합니다. |

## 관련 문서

| 알아볼 내용 | 문서 |
|-------------|------|
| 전체 패키지 경계와 의존성 주입 | [프로젝트 구조](project-structure-ko.md) |
| 대화 및 온톨로지 조회 구현 순서 | [온톨로지 조회 커버리지 구현 계획](../interfaces/ontology-query-coverage-implementation-plan-ko.md) |
| IS 작업 패키지와 local-first 순서 | [서비스 분해 실행 계획](service-decomposition-execution-plan-ko.md) |
| 서비스 승격, 데이터 소유권 및 롤백 게이트 | [서비스 승격과 데이터 소유권](service-graduation-and-ownership-ko.md) |
| Control-loop 권한 | [아키텍처 instructions](../../../.github/instructions/architecture.instructions.md) |
| 에이전트 역할과 권한 | [에이전트 Pantheon](../agents/agent-pantheon-ko.md) |
