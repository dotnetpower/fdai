---
title: 코드 맵
translation_of: code-map.md
translation_source_sha: 55aa28bdb88f4022c5b64f123c8e9bf786e714a6
translation_revised: 2026-08-13
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

## 구현 상태

### 구현 범위

| 영역 | 상태 | 근거 | 참고 |
|------|------|------|------|
| Service-owned 출처 및 테스트 지도 | 진행 중 | 이 지도, `tests/integration/` 및 위에 명시한 범위가 제한된 IS-08과 IS-07 근거 | 로컬 소유권과 롤백 근거는 매핑되었으며 IS-09 원격 검증은 남아 있습니다. |
| Exact-generation Rule 검색 | 구현됨 | `shared/providers/catalog_search.py`, `delivery/catalog_search/generation.py`, `delivery/catalog_search/in_memory.py`, `delivery/catalog_search/postgres.py`, focused 카탈로그, 온톨로지 조회, 스키마, 조립 및 실제 PostgreSQL 테스트(`44 passed`) | 결과는 후보 전용이며 활성 Rule 세대를 exact 온톨로지 release와 범위가 제한된 순서 보장 문서 매니페스트에 연결하고 판단, 승인 또는 실행 권한을 포함하지 않습니다. PostgreSQL 활성화는 같은 트랜잭션에서 예상 이전 세대를 확인합니다. |
| 목표 인식 Rule 후보 확인 | 구현됨 | `core/ontology_platform/objective_rule_resolution.py`, `core/ontology_platform/catalog_queries.py`, `shared/providers/catalog_search.py`, `delivery/catalog_search/in_memory.py`, 집중 온톨로지 조회 테스트(`8 passed`) | 검토 또는 승격된 활성 관계는 순위 계산 전에 exact-generation 후보 집합을 좁힙니다. 유효하지 않거나 불완전한 맥락은 원자적으로 대체 경로를 사용하며, 목표 맥락은 평가 또는 실행 권한을 추가하지 않고 조회 ID를 변경합니다. |
| 런타임 바인딩 기반 플래너 가시성 | 구현됨 | `composition/wire_semantic_query.py`, `core/conversation/semantic_manifest.py`, `core/ontology_platform/query_manifest.py`, focused 조립 및 매니페스트 테스트 | 플래너 서술자는 조립된 런타임에 등록된 함수만 노출합니다. 읽을 수 있지만 바인딩되지 않은 선언은 타입이 지정된 구조 coverage에 남으며 어떤 권한도 얻지 않습니다. |
| 선언 기반 유한 질문 집합 | 구현됨 | `core/conversation/question_universe.py`, `core/conversation/__init__.py`, `core/conversation/epistemic_coverage.py`, `core/conversation/coverage_gate.py`, `tests/conversation/test_question_universe.py`, `tests/conversation/test_epistemic_coverage.py`, `tests/conversation/test_coverage_gate.py`, 집중 release gate 테스트(`39 passed`, 생성기 branch coverage `100%`, 인식 상태 branch coverage `99%`, coverage gate branch coverage `100%`) | Principal 범위의 완전한 매니페스트를 정규화된 범위 제한 문법으로 확장해 conversation 패키지가 노출하는 안정적인 사례 ID를 만듭니다. 문법과 receipt는 10,000개라는 하나의 사례 상한을 공유하고, 사용할 수 없는 선언은 타입 기반 제외 항목으로 유지하며, 한도 초과는 확장 전에 실패하고, 생성된 레코드는 실행 권한을 부여하지 않습니다. |
| 운영 Rule 의미 준비 상태 | 구현됨 | `runtime/bootstrap.py`, `runtime/bootstrap_lifecycle.py`, `composition/wire_semantic_query.py`, `tests/runtime/test_catalog_semantic_bootstrap.py`, 집중 bootstrap 및 구성 검사(`46 passed`) | 운영 시작은 활성 세대가 현재 Rule 카탈로그, 의미 스키마, 온톨로지 release 및 embedder 차원과 정확히 일치할 때만 Rule 의미 검색을 등록합니다. 안정적인 선택적 준비 상태 저하는 오래된 함수를 노출하지 않고 시작을 유지합니다. |
| 영속 Rule 세대 종결 | 구현됨 | `core/rule_semantic_generation/activation.py`, `core/rule_semantic_generation/ledger.py`, `core/rule_semantic_generation/publication.py`, `rule_catalog/schema/rule_semantic_generation_events.py`, 집중 활성화, 계약, ledger, 발행 및 실제 PostgreSQL 검사 | Core는 활성화 전에 정확한 검증 증적과 예상 이전 활성 식별자를 확인하고, 완료된 명령이 프로바이더에 다시 전달되지 않게 하며, 첫 최종 결과를 lease로 차단된 하나의 발행 레코드에 원자적으로 연결하고, exact-topic broker 확인 뒤에만 발행 완료로 표시합니다. Delivery 상태는 정책, 승인, 변경 또는 실행 권한을 부여하지 않습니다. |
| Rule 세대 발행 소유권 | 구현됨 | `agents/mimir.py`, `agents/_framework/runtime.py`, `runtime/bootstrap.py`, `runtime/bootstrap_bindings.py`, `runtime/bootstrap_lifecycle.py`, 집중 Mimir, 런타임, bootstrap, 활성화 및 발행 검사(`32 passed`) | Mimir만 활성화 명령과 결과를 구독합니다. 명령을 exact binder에 위임하고 안전하게 재시도할 수 있는 변환 전용 결과 증적을 저장합니다. 준비 상태와 독립적인 drain은 해제된 전송 실패만 재시도하며 Mimir에 인덱스, 정책, 승인, 변경 또는 실행 권한을 부여하지 않습니다. |
| 읽기 조사 활동 ID | 구현됨 | `composition/wire_read_investigation.py`, `test_wire_read_investigation.py`, focused 테스트 | 각 호출은 실시간 및 영속 활동에서 하나의 불투명한 상관관계 값을 공유하고, 별도 호출은 서로 다른 상관관계 값을 사용하며, 논리적 요청 멱등성은 안정적으로 유지됩니다. |
| 서비스 간 의미 Rule 변환 결과 | 구현됨 | `fdai_service_contracts/semantic_turn.py`, `fdai_core_service/semantic_turn_processor.py`, `fdai_operator_service/postgres_semantic_turn_store.py`, 통과한 의미 경로 테스트 94개 | 공유 버전 1.2 계약, Core 처리 및 Operator 영속성은 후보 전용 권한, 범위가 제한된 기한, 복구 가능한 소유권 및 principal 범위의 exact 읽기와 함께 검증된 정확한 함수 호출 증적 및 정규 다이제스트를 보존합니다. 계약 검증은 내용, 다이제스트, 작업, 의도, 기능 및 최종 상태 차이를 거부합니다. 통제된 실제 운영 보증은 [온톨로지 조회 coverage 계획](../interfaces/ontology-query-coverage-implementation-plan-ko.md#남은-작업)에 열린 항목으로 남아 있습니다. |
| Console 의미 증적 projection | 구현됨 | `semantic_turn.py`, `semantic_turn_processor.py`, `semantic_turn_runtime.py`, `console/src/deck/backend-normalizers.ts`, focused shared, Core, Operator 및 Console 테스트 | 타입이 지정된 경로, 구체적인 명확화 답변, 사용 불가 사유, 네 개의 보증 다이제스트, 근거 참조 및 `execution_authority=false`가 prose 추론 없이 shared 계약, Core 결과, exact Operator 읽기, 최종 스트림, 영속 transcript, replay 및 Console 표현을 통과합니다. 통과한 실제 브라우저 및 무작위 보증 기록은 온톨로지 조회 coverage 계획의 열린 항목으로 남아 있습니다. |
| 결정론적 누락 incident 맥락 | 구현됨 | `core/conversation/semantic_planning.py`, `tests/conversation/test_semantic_planning.py`, 집중 플래너 및 최종 projection 테스트(`43 passed`) | 첫 turn의 "this incident" 참조는 매니페스트 또는 모델 작업 전에 범위가 제한된 명확화 하나를 반환합니다. 이전 incident 맥락이 있으면 일반 의미 계획 수립을 계속하며 어느 경로도 실행 권한을 부여하지 않습니다. |
| 의미 시간 및 근거 조립 | 구현됨 | `delivery/persistence/postgres_topology_history.py`, `composition/wire_semantic_query.py`, `runtime/bootstrap.py`, `runtime/bootstrap_bindings.py`, 통과한 집중 조립 및 프로바이더 선택 테스트 16개 | 상태 저장소 DSN이 있을 때만 PostgreSQL 토폴로지 이력을 사용할 수 있습니다. 메트릭 시계열과 근거 결합 기능에는 검토된 메트릭 레지스트리와 no-op이 아닌 프로바이더가 모두 필요합니다. 하나의 핸들러 맵이 검증기와 실행기의 가용성을 함께 제어하며 모든 결과는 `execution_authority=False`인 읽기 전용으로 유지됩니다. |

### 구현 이력

| 날짜 | 상태 | 변경 | 근거 | 남은 작업 |
|------|------|------|------|-----------|
| 2026-08-13 | 구현됨 | 이전 출처 이력을 재구성하지 않고 구현 ledger를 도입했으며 exact-generation Rule 검색을 기록했습니다. | 현재 변경의 `catalog_queries.py`, `operational_functions.py`, `test_catalog_queries.py`, 통과한 focused 테스트 및 diff-scoped 검증 | 아래 IS-09 원격 검증 항목을 완료합니다. |
| 2026-08-13 | 구현됨 | 플래너 함수 가시성을 실제 런타임 등록에 연결하고 바인딩되지 않은 읽기 가능 선언을 타입이 지정된 구조 coverage에 유지했습니다. | 현재 변경의 `wire_semantic_query.py`, `semantic_manifest.py`, `query_manifest.py` 및 해당 focused 테스트 | 영속 production 의미 인덱스는 이 변경 범위 밖에 있으며 아래 IS-09 원격 검증 항목을 완료합니다. |
| 2026-08-13 | 구현됨 | 호출 상관관계를 논리적 요청 멱등성과 분리하고 영속 요청자 및 대화 ID를 불투명 참조로 바꿨습니다. | `current change`, `wire_read_investigation.py`, `test_wire_read_investigation.py`, 통과한 focused 테스트 5개 | 아래 IS-09 원격 검증 항목을 완료합니다. |
| 2026-08-13 | 구현됨 | 카탈로그 세대를 프로바이더 중립적이고 범위가 제한된 순서 보장 문서 매니페스트에 연결하고 exact 문서 집합에서 세대 ID를 독립적으로 재현할 수 있게 했습니다. | `current change`, `shared/providers/catalog_search.py`, `delivery/catalog_search/generation.py`, `delivery/catalog_search/in_memory.py`, 통과한 focused 카탈로그, 온톨로지 조회, 스키마 및 조립 테스트 41개 | 영속 production 의미 인덱스를 조립하고 검증한 뒤 아래 IS-09 원격 검증 항목을 완료합니다. |
| 2026-08-13 | 구현됨 | 공유 의미 Rule 계약과 Core에서 Operator로 이어지는 영속 변환 결과 경계를 강화했습니다. | `current change`, 통과한 의미 경로 테스트 88개, 통과한 작업 범위 Ruff 및 운영 파일 6개의 strict mypy 통과 | 온톨로지 조회 coverage 계획에 통제된 실제 증적을 기록하고 IS-09 원격 검증을 완료합니다. |
| 2026-08-13 | 구현됨 | 점수 계산과 상위 결과 선택 전에 exact-generation Rule 검색에 범위가 제한된 목표 인식 후보 확인을 추가했습니다. | `current change`, `objective_rule_resolution.py`, `catalog_queries.py`, `catalog_search.py`, `in_memory.py`, 통과한 집중 온톨로지 조회 테스트 8개 | 정책 추상화 계획의 P1 바인딩 채우기, P2 영속 세대 근거 및 P4 롤아웃 보증은 열려 있습니다. |
| 2026-08-13 | 구현됨 | Exact-generation Rule 검색을 위한 영속 PostgreSQL 세대 어댑터와 예상 이전 세대 활성화 compare-and-swap을 추가했습니다. | `current change`, `postgres.py`, 수명 주기 게시자, 직접 호출자 및 in-memory와 실제 PostgreSQL 경로에서 통과한 focused 카탈로그 테스트 44개, 변경한 수명 주기 출처의 Ruff와 strict mypy 통과 | Production bootstrap에서 어댑터를 연결하고 통제된 IS-09 원격 검증 근거를 기록합니다. |
| 2026-08-13 | 구현됨 | 정확한 활성 세대 검사와 선택적 준비 상태 저하 뒤에서 영속 Rule 의미 인덱스를 운영 시작에 연결했습니다. | `current change`, `bootstrap.py`, `bootstrap_lifecycle.py`, `wire_semantic_query.py`, 통과한 집중 런타임 및 구성 검사 46개, Ruff 및 strict mypy 통과 | 통제된 IS-09 원격 검증 근거를 기록합니다. |
| 2026-08-13 | 구현됨 | Rule 의미 세대에 Core 소유 타입 기반 활성화 종결과 영속 최종 결과/outbox aggregate를 추가했습니다. | `current change`, 집중 계약 및 ledger 검사 15개 통과, 작업 범위 Ruff, strict mypy 및 편집기 진단 통과 | 정확한 활성화 연결, 범위가 제한된 EventBus 발행, 담당 agent 연결 및 통제된 런타임 근거를 추가합니다. |
| 2026-08-13 | 구현됨 | 검증된 Rule 세대 명령이 의미 인덱스를 변경하기 전에 정확한 대상 증적과 예상 이전 활성 식별자에 연결되도록 했습니다. 완료된 명령의 replay는 프로바이더 접근 전에 영속 최종 결과를 반환하며, 효과 발생 후 오류 조정은 안전하게 닫힌 상태를 유지합니다. | `current change`, `activation.py`, `ledger.py`, 프로바이더와 delivery 활성화 계약, 통과한 집중 활성화, ledger, 세대 및 실제 PostgreSQL 검사, 변경한 수명 주기 파일의 Ruff와 strict mypy 통과 | 범위가 제한된 EventBus outbox 발행, 담당 agent 연결 및 통제된 런타임 근거를 추가합니다. |
| 2026-08-13 | 구현됨 | 영속 Rule 세대 활성화 결과를 위한 범위가 제한된 at-least-once EventBus 발행을 추가했습니다. Exact-topic 확인은 lease로 차단된 outbox 레코드를 완료하고, 실패는 결정론적 재시도를 위해 레코드를 해제하며, 취소는 lease 복구를 보존하고, 확인 영속성 실패는 lease 만료 replay로 복구합니다. | `current change`, `publication.py`, 패키지 export 및 통과한 집중 발행 테스트 7개, 작업 범위 Ruff와 strict mypy 통과 | 담당 agent를 연결하고 통제된 런타임 발행 근거를 기록합니다. |
| 2026-08-13 | 구현됨 | Mimir를 유일한 Rule 세대 명령 및 결과 subscriber로 연결하고 하나의 공유 영속 ledger를 조립했으며 준비 상태와 독립적인 outbox drain을 시작했습니다. 해제된 전송 실패는 재시도하지만 receipt 계약 및 영속 상태 실패는 치명적으로 유지합니다. | `current change`, 집중 Mimir, 런타임, bootstrap, 활성화 및 발행 검사 32개 통과, Ruff, strict mypy, 번역 freshness 및 한국어 품질 검사 통과 | 통제된 실제 런타임 발행 증적을 기록하며 IS-09 원격 검증은 열려 있습니다. |
| 2026-08-13 | 구현됨 | PostgreSQL 토폴로지 이력과 검토된 메트릭 및 근거 프로바이더를 선택적 기능이 안전하게 닫히는 exact-release 의미 조회 조립에 연결했습니다. | `current change`, `postgres_topology_history.py`, `wire_semantic_query.py`, `bootstrap.py`, `bootstrap_bindings.py`, `test_wire_semantic_query.py`, `test_bootstrap_config.py`, 통과한 집중 검사 16개 | 온톨로지 조회 coverage 계획에 통제된 실제 증적을 기록하고 IS-09 원격 검증을 완료합니다. |
| 2026-08-13 | 진행 중 | 의미 projection을 exact Operator 읽기와 영속 Console 렌더링까지 확장하고 인증된 통제 증적 및 seed 기반 이중 언어 보증 실행기를 추가했습니다. | `current change`, 통과한 focused shared, Core, Operator 및 Console 검사 | 준비 상태를 주장하기 전에 인증된 두 브라우저 경로를 실행하고 통과한 두 보존 근거 기록을 연결합니다. |
| 2026-08-13 | 진행 중 | Principal 또는 권한 검증을 바꾸지 않고 엄격한 Core 증적 typing을 바로잡고 인증된 근거 경로를 위한 일회성 Browser Entra 세션 복원을 준비했습니다. | `current change`, 통과한 strict mypy, Ruff, Console typecheck, 설계 경로 및 append-only 검사 | 준비 상태를 주장하기 전에 인증된 두 브라우저 경로를 실행하고 통과한 두 보존 근거 기록을 연결합니다. |
| 2026-08-13 | 구현됨 | 플래너의 범위가 제한된 명확화 질문을 일반적인 최종 답변으로 바꾸지 않고 Core 의미 projection에 보존했습니다. | `current change`, `fdai_core_service/semantic_turn_processor.py`, `test_semantic_turn_processor.py`, 통과한 Core processor 집중 테스트 30개 | 런타임 검증을 주장하기 전에 통제된 브라우저 및 무작위 보증 근거를 기록합니다. |
| 2026-08-13 | 구현됨 | 이전 incident 맥락이 있으면 일반 계획 수립을 보존하면서 첫 turn의 바인딩되지 않은 incident 참조를 매니페스트 또는 모델 작업 전에 누락 맥락으로 분류했습니다. | `current change`, `semantic_planning.py`, `test_semantic_planning.py`, 통과한 집중 플래너 및 최종 projection 테스트 43개, 통과한 작업 범위 Ruff와 strict mypy | 이 범위를 검증됨으로 올리기 전에 통제된 인증 브라우저 근거를 보존하고 연결합니다. |
| 2026-08-13 | 구현됨 | 유한 질문 집합의 분모를 위해 결정론적인 선언 기반 생성을 추가했습니다. 완전한 exact-release 매니페스트는 정규화된 범위 제한 문법으로 확장하고, 사용할 수 없는 선언은 타입 기반 제외 항목으로 유지합니다. | `current change`, `question_universe.py`, `epistemic_coverage.py`, `test_question_universe.py`, 통과한 집중 질문 집합 및 인식 상태 coverage 테스트 10개, 작업 범위 Ruff 및 strict mypy 통과 | 런타임 및 통제된 보증 근거는 해당 coverage 계획에서 계속 추적합니다. |

### 남은 작업

- [ ] 통제된 IS-09 원격 검증 근거를 기록하고 해당 근거가 통과하면 service-owned 지도 상태를 갱신합니다.
- [x] Mimir를 Rule 세대 명령 및 결과의 유일한 담당 pantheon subscriber로 연결하고 영속 발행 및 안전하게 재시도할 수 있는 변환 결과를 집중 검사로 입증합니다.
- [ ] 영속 활성화 결과 발행 및 안전하게 재시도할 수 있는 소비의 통제된 실제 런타임 증적을 기록합니다.
- [ ] 첫 turn의 바인딩되지 않은 incident 참조가 호출자 요청 ID와 `execution_authority=false`를 보존하면서 `semantic_clarification_required`를 반환함을 입증하는 통제된 인증 브라우저 증적을 보존합니다.

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
| 컨트롤 루프와 decisioning | Event 정규화, 계층 라우팅, 정확한 Rego allow/deny 평가 증적, quality, risk, 승인, 실행 coordination, 복구 및 감사 | [코어](../../../services/core-control-plane/src/fdai/core/) | [코어 테스트](../../../services/core-control-plane/tests/core/) |
| 실행 권한 부여 | 프로바이더 중립적인 요구 사항 결과, 비어 있지 않은 결정 집합의 최소 권한 축소, 정규 요청 및 인벤토리 연결, 모호한 ID 또는 연결되지 않은 권한 부여 제안 거부 | [execution_authorization](../../../services/core-control-plane/src/fdai/core/execution_authorization/) | [실행 권한 부여 테스트](../../../services/core-control-plane/tests/core/execution_authorization/) |
| 온톨로지 안전성 platform | 카탈로그에서 로드한 Interface 및 FunctionType 선언을 포함하는 exact 의미 release, release-aware 조회 profile 및 함수 등록, principal 범위로 한정된 매니페스트, 검증된 Resource와 ResourceType 분류, 범용/temporal 조회 algebra, bitemporal 토폴로지/차이, 범위가 제한된 blast-radius 차이와 authoritative inventory rebuild pointer를 포함하는 immutable direction-generation shadow comparison, 검토된 메트릭 개념, topology-aware causal 결합, 안전하게 닫히도록 문서화된 인자, 근거, 대상 및 효과 검증 계약이 있는 변경 계획, compact typed effect-reconciliation event, 인증된 독립 observer binding 및 lease-fenced 영속 terminal outbox 전달 | [ontology_platform](../../../services/core-control-plane/src/fdai/core/ontology_platform/) | [온톨로지 platform 테스트](../../../services/core-control-plane/tests/core/ontology_platform/) |
| 의미 대화 계획 수립 | Whole-turn 스키마 제안, 서버가 소유한 프레임/계획 신원, principal-manifest 검증, 비동기 검증된 실행, 전체 최종 처리 결과, 결정론적 의도 그래프, exact-command 호환성 전환, 선언 기반의 범위가 제한된 질문 집합 생성, 인식 상태 완결성 release 증적 및 실행 권한이 없는 연속 커버리지 게이트 | [대화](../../../services/core-control-plane/src/fdai/core/conversation/) | [대화 테스트](../../../services/core-control-plane/tests/conversation/) |
| Rule 의미 세대 종결 | 타입 기반 활성화 명령 및 최종 결과, 정확한 대상 증적과 예상 이전 세대 compare-and-swap, 프로바이더 접근 전 replay 차단, 원자적 StateStore 결과/outbox 영속성, lease 차단, 재시도 예약, 손상 거부 및 정책 또는 실행 권한이 없는 broker 확인 기반 발행 상태 | [rule_semantic_generation](../../../services/core-control-plane/src/fdai/core/rule_semantic_generation/) | [Rule 의미 세대 테스트](../../../services/core-control-plane/tests/core/rule_semantic_generation/) |
| 온톨로지 의미 세대 | 프로바이더 중립적이고 범위가 제한된 순서 보장 문서 매니페스트, 자체 검증 가능한 세대 ID, 후보 전용 구체적인 인덱스, 영속 PostgreSQL 저장, 예상 이전 세대 활성화 compare-and-swap, full/incremental 선언 및 deployment-object 문서, 독립적인 검증 증적, stale detection 및 롤백 | [catalog_search 프로바이더](../../../services/core-control-plane/src/fdai/shared/providers/catalog_search.py) 및 [catalog_search 전달](../../../services/core-control-plane/src/fdai/delivery/catalog_search/) | [카탈로그 검색 테스트](../../../services/core-control-plane/tests/delivery/catalog_search/) |
| 메트릭 의미 프로바이더 연결 | Alias-free 검토된 메트릭 개념과 관찰된 zero를 프로바이더 공백과 구분하는 exact `MetricProvider` 구간 | [metric_window.py](../../../services/core-control-plane/src/fdai/delivery/metric_window.py) 및 [metric_semantic_catalog.py](../../../services/core-control-plane/src/fdai/runtime/metric_semantic_catalog.py) | [메트릭 의미 카탈로그 테스트](../../../services/core-control-plane/tests/runtime/test_metric_semantic_catalog.py) |
| 운영 가설 루프 | 완전한 graph Dynamic 근거 연결, 기한이 제한된 독립 궤적 종결, 감독되는 타입 기반 효과 조정, 변경 불가능한 운영 계보 및 Owner 사람 승인을 거치는 graph-model pointer 승격 | [graph 근거](../../../services/core-control-plane/src/fdai/delivery/azure/graph_dynamic_evidence.py), [종결](../../../services/core-control-plane/src/fdai/core/assurance_twin/graph_closure.py), [조정](../../../services/core-control-plane/src/fdai/delivery/reconciliation_runtime.py), [계보](../../../services/core-control-plane/src/fdai/core/operational_planning/hypothesis_lineage.py) 및 [승격](../../../services/core-control-plane/src/fdai/delivery/graph_model_promotion.py) | [graph 근거 테스트](../../../services/core-control-plane/tests/delivery/azure/test_graph_dynamic_evidence.py), [종결 테스트](../../../services/core-control-plane/tests/assurance_twin/test_graph_closure.py), [조정 테스트](../../../services/core-control-plane/tests/delivery/test_reconciliation_runtime.py), [계보 테스트](../../../services/core-control-plane/tests/core/operational_planning/test_hypothesis_lineage.py) 및 [승격 테스트](../../../services/core-control-plane/tests/delivery/test_graph_model_promotion.py) |
| 에이전트 pantheon | 고정 에이전트 15개와 타입이 지정된 이벤트 런타임 | [에이전트](../../../services/core-control-plane/src/fdai/agents/) | [에이전트 테스트](../../../services/core-control-plane/tests/agents/) |
| 조립 | Exact-release 의미 조회 assembly, request-role 실행기 factory 및 호출 범위의 불투명 상관관계를 사용하는 리소스 상태 활동 게시를 포함한 프로바이더/런타임 의존성 주입 | [조립](../../../services/core-control-plane/src/fdai/composition/) | [조립 테스트](../../../services/core-control-plane/tests/composition/) |
| Core 어댑터 | Core에 남은 프로바이더, 영속성, 알림 및 platform 어댑터 | [전달](../../../services/core-control-plane/src/fdai/delivery/) | [전달 테스트](../../../services/core-control-plane/tests/delivery/) |
| 런타임 | Core 프로세스 수명 주기, 준비 상태, 이벤트 전송 계층, supervision 및 의미 런타임 가용성 연결 | [런타임](../../../services/core-control-plane/src/fdai/runtime/) | [런타임 테스트](../../../services/core-control-plane/tests/runtime/) |
| Core 계약과 프로바이더 경계 | Core 전용 타입, 프로바이더 프로토콜, 구성, 스트리밍 및 텔레메트리 | [shared](../../../services/core-control-plane/src/fdai/shared/) | [shared 테스트](../../../services/core-control-plane/tests/shared/) |
| Rule 카탈로그 파이프라인 | 카탈로그 스키마 로딩, 수집, 검증, 정제 및 승격 support | [rule_catalog](../../../services/core-control-plane/src/fdai/rule_catalog/) | [Rule 카탈로그 테스트](../../../services/core-control-plane/tests/rule_catalog/) |
| Core 서비스 항목 지점 | Core 분포 시작과 서비스 조립 | [fdai_core_service](../../../services/core-control-plane/src/fdai_core_service/) | [Core 패키지 테스트](../../../services/core-control-plane/tests/) |

Safety-core 커버리지 하한은 Core 패키지 안의 결정론적 계층과 risk 게이트에 적용됩니다. 해당
테스트는 Core 소유 테스트 트리에 유지합니다.

온톨로지 조회 실행은 런타임에서 exact release, 매니페스트, 역할 및 용도를 다시 검사합니다.
범위가 제한된 의존성 wave는 노드 기한에 큐 wait를 포함하고 in-flight 취소를 전파하며
차단된 descendant를 건너뜁니다. 안정적인 핸들러 타입, 값 및 런타임 실패는
`capability_failed`로 유지됩니다. 구조화된 진단에는 `node_kind`와 `failure_type`만 허용하며,
예외 본문, 인자, 노드 식별자, 프로바이더 페이로드 또는 운영자 데이터는 포함하지 않습니다.
조립은 범위가 제한된 secured ObjectSet 증적을 발급하고 source-derived 네트워크 및 Pod
텔레메트리 함수를 exact release에 등록합니다. 함수 dependency는 발급된 content 다이제스트만
해석합니다. `catalog.search_rules` 함수는 해당 exact release와 프로바이더 중립적이고 범위가
제한된 순서 보장 문서 매니페스트에 연결된 활성 Rule 세대만 허용합니다. 세대 다이제스트는 exact
순서 보장 문서 집합에서 독립적으로 재현할 수 있으므로 개수, 청크, 루트 또는 행 드리프트가 있으면
검증에 실패합니다. PostgreSQL 어댑터는 각 코퍼스 수명 주기를 직렬화하고 활성 포인터를 교체하기
전에 활성화 트랜잭션에서 예상 이전 세대를 정확히 확인합니다. 검색은 `CatalogRetrievalReceipt`와
함께 후보 전용 Rule을 반환하며 판단, 승인
또는 실행 권한을 부여하지 않습니다. Resource-state 조사 경로는 promoted 인벤토리를 답변 권한으로
유지하고 온톨로지 조회를 shadow로 실행하며 principal-scoped 동등성 증적을 StateStore에
저장합니다. 실제 호출마다 실시간 및 영속 활동 수명 주기에서 공유하는 불투명한
`correlation_ref` 하나를 받고, 불투명한 요청자 및 대화 참조는 재시도 간 논리적 질문
`idempotency_key`를 안정적으로 유지합니다. 별도 호출은 상관관계 값을 재사용하지 않습니다.
공개 조립 파사드는 선택적 resource-state composer만 내보냅니다. 구현 타입은 focused binder에
유지해 파사드가 structural 상한 아래에 머물도록 합니다.
플래너 매니페스트는 ObjectType 및 Interface 속성에 동일한 역할/용도 filtering을 적용합니다.
함수 서술자는 조립된 런타임에 handler가 등록된 선언에만 발행됩니다. 읽을 수 있지만 바인딩되지
않은 함수 선언은 `runtime_binding_unavailable`로 구조 coverage에 남으며, 이 accounting은 판단,
승인, 변경, 승격 또는 실행 권한을 부여하지 않습니다. 의도 근거는 최종 사유를 보존하면서 범위가
제한된 evidence-reference 잘림도 공개합니다.
검증기는 I/O 전에 declared DAG 노드를 가리키지 않는 출력을 거부합니다. Answered 턴은 범위가 제한된
검증된 조회 표만 렌더링하며 transient 변환 결과 게시는 dead-letter 전에 같은 영속
멱등적 결과를 재시도합니다.
Azure 의미 계획 수립은 기존 `httpx` 및 `WorkloadIdentity` 어댑터를 사용하여 검증된 JSON-object
제안 두 개를 만듭니다. 각 제안은 기본 90초 예산을 가지며, 범위가 제한된 `Retry-After` 지연이
이 예산 안에 들어올 때 제한된 후보 하나를 최대 한 번 재시도합니다. 조립은 권위 있는 프로바이더가
연결된 핸들러만 노출합니다. 공개
프레임 제안은 Core가 서버 소유 다이제스트를 다시 만들기 전에 shared wire 식별자 제약을
적용합니다. 구조화된 진단은 계획 단계, 후보 인덱스, 실패 클래스 및 입력을 포함하지 않는
검증 위치만 기록하며 운영자 텍스트와 프로바이더 상세는 제외합니다. 공개
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
운영 가설 루프는 service 또는 agent를 추가하지 않습니다. 완전한 graph prerequisite는
composition에서 연결되고 effect reconciliation은 범위가 제한된 drain을 포함하는 supervised
request/outbox transport를 사용하며 model pointer 변경은 기존 governance ActionType, risk, Owner
승인, Thor execution, rollback 및 Saga audit 경로 안에 유지됩니다.

## 독립 서비스 지도

| 서비스 | 패키지 responsibility | 패키지 지도 |
|---------|------------------------|-------------|
| Operator 서비스 | 인증된 경로 계열, 영속 의미 브리지, 프로세스 소유 브리지 상태 및 범위가 제한된 실시간/에이전트 SSE 전달을 포함하는 순서가 정해진 Managed Identity Kafka 수명 주기 | [families](../../../services/operator-service/src/fdai_operator_service/families/), [어댑터](../../../services/operator-service/src/fdai_operator_service/adapters/), [streaming](../../../services/operator-service/src/fdai_operator_service/streaming/) 및 [composition.py](../../../services/operator-service/src/fdai_operator_service/composition.py) |
| 문서 인제스트 API | 업로드 intake, API 소유 전이 및 서비스 어댑터 | [패키지](../../../services/document-ingestion-api/src/fdai_ingestion_api_service/) |
| 문서 처리 워커 | 영속 문서 처리와 워커 소유 어댑터 | [패키지](../../../services/document-processing-worker/src/fdai_document_worker_service/) |
| Isolated 실행기 | Thor 소유 명령 처리, 프로바이더 효과, 증적 및 실행기 어댑터 | [패키지](../../../services/isolated-executor/src/fdai_executor_service/) |

이 패키지는 `fdai-service-contracts`에 의존할 수 있습니다. 다른 서비스의 구현
패키지는 가져오기하지 않습니다.
로컬 조립은 각 패키지 안에서 service-owned client lifecycle과 loopback adapter를 연결합니다.
따라서 Operator semantic bridge, ingestion publisher, 문서 worker consumer 및 isolated Executor는
배포된 managed-identity adapter와 동일한 logical topic, 멱등성, 준비 상태 및 증적 경계를
보존합니다.

## Shared 계약 SDK

[fdai_service_contracts](../../../packages/service-contracts/src/fdai_service_contracts/)는 프로세스가
공유하는 versioned wire 서술자, codec, 호환성 검사, 준비 상태 기록, 문서 계약,
운영자 계약 및 실행기 계약을 소유합니다. 서비스 조립, 프로바이더 구현,
데이터베이스 접근 또는 business 작업 흐름은 포함하지 않습니다.

Shared SDK는 Core/Operator 경계에서 사용하는 no-authority ontology-query 기록도 소유합니다.
의미 problem 프레임, 범위가 제한된 조회 DAG, 의도 그래프, 작업 증적 및 structural 커버리지 증적입니다.
프로바이더 클라이언트, 온톨로지 저장소, 플래너 모델 또는 실행 핸들러는 포함하지 않습니다.
또한 Core에서 Operator 화면으로 범위가 제한된 인벤토리 검사, 온톨로지 변환 및 현재 상태 읽기 근거를
전달하는 버전이 지정된 no-authority 운영 활동 기록을 소유합니다. 이 기록은 논리적 에이전트 소유권과
생산 프로세스를 분리하고 `execution_authority=false`를 고정합니다.

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
