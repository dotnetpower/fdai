---
title: 코드 맵
translation_of: code-map.md
translation_source_sha: 601cdc368a462790f874d4d7472785be8474fa4d
translation_revised: 2026-09-05
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
- **가상 루트:** 루트 `pyproject.toml`은 `package = false`이며 uv workspace를 조정합니다. `pytest-timeout`은 테스트당 120초 상한을 적용하여 중단된 테스트가 xdist 샤드를 무기한 차단하지 못하게 하며, `faulthandler_timeout`(90초)은 강제 종료 전에 모든 스레드 스택을 덤프하여 진단 증거를 보존합니다.
- **Integration-only 루트 테스트:** `tests/integration/`은 서비스 간 호환성, 토폴로지 및
  저장소 검사를 소유합니다.

> **인덱스 계약:** 이 페이지는 탐색 전용입니다. 현재 구현 상태와 이력은 연결된 소유
> 문서에서 관리합니다. 기존 혼합 목적 원장은
> [보관된 코드 맵 구현 원장](../../roadmap-implementation/architecture/code-map.md)에 보존합니다.

## 물리 서비스 소유권

| 소유자 | 출처 | 테스트 | 분포 |
|--------|--------|------|--------------|
| Core 컨트롤 플레인 | [fdai](../../../services/core-control-plane/src/fdai/)와 [fdai_core_service](../../../services/core-control-plane/src/fdai_core_service/) | [Core 테스트](../../../services/core-control-plane/tests/) | `fdai-core-control-plane` |
| Operator 서비스 | [fdai_operator_service](../../../services/operator-service/src/fdai_operator_service/) | [Operator 테스트](../../../services/operator-service/tests/) | `fdai-operator-service` |
| 문서 인제스트 API | [fdai_ingestion_api_service](../../../services/document-ingestion-api/src/fdai_ingestion_api_service/) | [인제스트 API 테스트](../../../services/document-ingestion-api/tests/) | `fdai-document-ingestion-api` |
| 문서 처리 워커 | [fdai_document_worker_service](../../../services/document-processing-worker/src/fdai_document_worker_service/) | [워커 테스트](../../../services/document-processing-worker/tests/) | `fdai-document-processing-worker` |
| Isolated 실행기 | [fdai_executor_service](../../../services/isolated-executor/src/fdai_executor_service/) | [실행기 테스트](../../../services/isolated-executor/tests/) | `fdai-isolated-executor-service` |
| 서비스 계약 | [fdai_service_contracts](../../../packages/service-contracts/src/fdai_service_contracts/) | [계약 테스트](../../../packages/service-contracts/tests/) | `fdai-service-contracts` |
| 선택적 비용 거버넌스 패키지 | [fdai_cost_governance](../../../extensions/cost-governance/src/fdai_cost_governance/) | [패키지 테스트](../../../extensions/cost-governance/tests/) 및 [레거시 자문 가드 커버리지](../../../extensions/cost-governance/tests/test_legacy_advisory_guards.py) | `fdai-cost-governance` |
| 서비스 간 통합 | 해당 없음 | [루트 통합 테스트](../../../tests/integration/) | 가상 루트 only |

문서 인제스트 API는 FDAI-native 교차 테넌트 SharePoint 커넥터도 소유합니다. Federated
Managed Identity가 대상 테넌트의 Microsoft Graph 토큰을 얻고, 영속 delta 및 인제스트
어댑터가 변경 파일을 서버 소유 문서 정책에 연결합니다. Power Platform은 런타임 의존성이
아닙니다. 이 서비스는 선택적 비용 거버넌스 패키지를 가져오거나 비용 권한을 변경하지
않습니다.

## Core 컨트롤 플레인 지도

Core 분포는 전체 `fdai` 이름 공간을 유지합니다. 내부 모듈 경계는 물리 이동으로
변경되지 않습니다.

서비스 마이그레이션 인벤토리 테스트는 이름이 변경된 파티션이 생성 계보를 유지하고 현재
마이그레이션 헤드의 유효 테이블 이름을 사용하며, 레거시 스키마 계약 핑거프린트가
이름 변경 후 테이블 집합과 카운트를 반영하는지 검증합니다. CI는 격리된 서비스 데이터베이스에
서비스 소유 마이그레이션을 적용하기 전에 root rollback 검사를 실행한 뒤 해당 서비스 헤드에서
서비스 의존 테스트를 실행합니다. Operator의 Core 소유 Cost Governance 객체 읽기 접근 같은
서비스 간 데이터베이스 부여는 Core 브랜치가 아닌 Operator 소유 다운스트림 마이그레이션에
위치하므로 부트스트랩 순서에서 나중에 생성되는 역할을 필요로 하지 않습니다.
마이그레이션 소유권 인벤토리는 영속 대화 채널 메시지 claim과 Cost Governance 수명 주기, 정산 및
보존 테이블도 각 패키지가 배포되기 전에 고정합니다. 하나의 필수 CI 그래프는 Terraform 유효성 검사와
보안 검사를 소유하고, 경로 범위가 지정된 컨테이너 공급망 workflow는 이미지 빌드, 취약성 검사 및
attestation을 소유합니다. 외부 action은 전체 commit SHA로 계속 고정하고, 리포지토리 로컬 composite
action은 checkout된 상대 경로로만 허용하며 보호된 workflow 원본 검증기가 검사합니다.
Terraform 보안 검사는 각 Key Vault secret에 만료일 또는 명시적인 조정 로테이션 근거를
요구합니다.
루트 통합 테스트는 논리 `object.*` 이벤트를 영속 게시 완료로 표시하기 전에 라우팅하는
문서 처리 워커 outbox 규칙도 계약으로 고정합니다.
컨트롤 루프 엔드투엔드 테스트는 게시된 작업과 확인되지 않은 그래프 기반 영향 범위 판단
보류를 별도로 계수합니다.
Azure 의미 조회 구성은 `semantic_query_azure_composition.py`에 있습니다.
`wire_semantic_query.py`는 기존 공개 가져오기를 유지하면서 해당 생성자를 직접 다시
내보내며, 일반 배선 모듈은 적용되는 800줄 상한 아래를 유지합니다.

의미 기반 리소스 상태 계획은 이제 컬렉션 상태, 정확한 리소스 식별자, 명시적인 이름 또는
태그 필터, 시간 범위가 있는 근거 요청을 구분합니다. Core 조회 경로는 공급자 완전성과 사유
코드를 보존하며, Operator 표현 및 콘솔 대시보드는 일반 인벤토리 행으로 대체하지 않고
부분적이거나 사용할 수 없는 관측을 표시합니다.
Inventory 변경 수집은 이제 타입이 지정된 `inventory_observation.py` 계약을 사용하고, 기존
overlay를 현재 조회 경로로 유지하면서 Core 소유의 추가 전용 PostgreSQL 관측 원장에 이중
기록합니다. 원장 replay는 명시적인 속성 마스크를 적용하고 작업 상태를 리소스 상태와 분리하며,
원본 완전성 검사에 원장 및 온톨로지 변환 결과 watermark를 제공합니다.
`operational_history_lifecycle.py`와 `operational_history_certification.py`는 수명 인스턴스,
partition, correction, checkpoint, pin, 보존, 저장소 압력, recovery 및 고정 개정 certification
의미를 소유합니다. Delivery adapter는 이러한 레코드를 PostgreSQL, 검증된 비공개 Blob artifact,
principal 범위 조회, database 소유 purge gate 및 고정 shadow schedule에 결속합니다.

프롬프트 조립은 역할 및 안전 레이어를 `core/prompts/`에 유지하고 Azure 시작 조립을
`composition/wire_azure_prompts.py`로 분리합니다. 리비전 기반 대화 설정은 Operator
서비스가 공유 `runtime-settings:policy` 레코드에 기록하며 Core는 시작 시 한 번 읽습니다.
프롬프트 ablation은 선택적 맥락만 제거하고 모든 제외 항목을 재실행을 위해 기록합니다.
질문 캠페인 문구는 `core/conversation/question_candidates.py`를 서버 소유 의미 경계로
사용합니다. Azure 및 명시적 Copilot 생성기는 완전한 불변 사례를 받지만 `question` 필드만
반환할 수 있습니다. Core가 독립 의미 검토 전에 사례를 결속하므로 생성된 문구가 범위, 권한,
기능, 근거 상태 또는 결과 형태를 대체할 수 없습니다.
생성된 질문 bank 산출물은 현재 Console catalog digest를 기록합니다. 따라서 검토된 표현 계약이
변경되면 JSON bank와 review catalog를 함께 다시 생성합니다.
생성된 question bank는 두 Console 메시지 카탈로그를 다이제스트로 결속하며, 검토된 원본
카탈로그가 변경될 때마다 다시 생성합니다.
Console 정적 카탈로그 inventory는 Dashboard v2 카탈로그를 포함한 shared, route-local,
optional package 카탈로그를 해석하므로 새 경로가 누락된 English fallback key를 숨길 수 없습니다.

의미 대화 계획은 `semantic_planning.py`, `semantic_planning_cascade.py`,
`semantic_planning_frame.py`를 호환성 facade로 유지합니다. `semantic_planning_fallbacks.py`는
결정론적 명확화와 후보 복구를 소유합니다. 집중 sibling 모듈은 공개 import,
결정론적 gate 순서 및 읽기 전용 권한을 보존하면서 frame 검사, plan dispatch, 고정된 인시던트와
명시된 값 필터 plan 생성, 판단, 검증, frame 생성, facet, 근거별 조사 정규화, 타입이 지정된
다중 pair 관계 계획 및 조회를 소유합니다. 타입이 지정된 Rule 추적은 답변 전에 정확한 Rule 선언과
필요한 모든 LinkType 증적을 결속합니다. 서비스와 담당 Agent 간 관계는 정확한 release 및
principal 범위에 고정된 단일 복합 읽기 증적을 사용합니다. 실행 권한을 부여하지 않으면서 각
BusinessService에서 Agent로 이어지는 실제 인스턴스 경로를 보존합니다. 실제 경로가 없으면
신원 주장을 답변 완료로 만들지 않고 보류합니다. 리소스 상태 컬렉션 계획은 객체 전용
ObjectSet을 명시적으로 요청합니다. 다른 ObjectSet은 기본적으로 관계를 포함하며 기존 재실행
다이제스트가 바뀌지 않도록 기본값은 이전 직렬화 정의에서 생략됩니다.
검증된 `Document` 판단과 이름이 정확한 리소스 그룹 구성원 조회는 결정론적 builder를 통해
잔여 frame 모델을 우회합니다. 문서 경로는 초안 전용이며 인증된 principal의 직전 검증 결과에
원본을 바인딩합니다.
Core 패키지는 Kafka consumer가 사용하는 Snappy codec을 고정합니다. 따라서 압축된 EventBus
레코드가 readiness를 통과한 뒤 필수 runtime task를 종료하지 않습니다.
의미 판단은 엄격한 구조화 출력을 사용하며 첫 번째 턴의 운영 조회는 소셜 사전 검사를
생략하되 직접 소셜 응답 후보와 이전 턴이 있는 요청은 계속 독립적으로 확인합니다.
검증된 `query.ontology_declaration` 개수 판단에서는 고유한 canonical 선언 `*Type` target이
충돌하는 frame subject보다 우선합니다.
선언이 아닌 영역 target은 선언 선택에 참여하지 않습니다. 판단에 canonical 선언 target이 없을
때만 정확한 선언 종류 또는 canonical `*Type` frame subject를 사용합니다. 충돌하는 canonical
선언 target은 해결되지 않은 상태로 유지합니다. 정규화된 선언 개수 frame은 전용 매니페스트
플래너를 사용해 모델 작성 계획 없이 `query.manifest`와 `count`를
컴파일합니다. Core 의미 턴 처리기는 완전한 그룹 값을 선언 종류별 개수로 표시하고
집계 행 개수만 보고하는 대신 읽기 전용 매니페스트 출처를 밝힙니다. 표시할 선언 종류는 모델이
작성한 노드 ID가 아니라 검증된 frame subject에 결속됩니다. 이 모듈들은 공개 import, 결정론적
gate 순서 및 읽기 전용 권한을 보존합니다.
Resource Health 상태 그룹 파생은 `semantic_query_health_values.py`에 있으며 public 의미
composition facade를 강제된 800줄 제한 아래로 유지하면서 등록 순서는 바꾸지 않습니다.
토폴로지 엔드포인트 명확화 정규화는 `semantic_planning_topology_normalization.py`에 있으며
호환성 파사드는 공개 import, 결정론적 gate 순서 및 읽기 전용 권한을 보존합니다.
이력 및 활동 frame 생성은 `semantic_planning_temporal_frames.py`, 인벤토리 수집 상태 조립은
`inventory_collection_health_reporting.py`, PostgreSQL 인벤토리 출처 완전성 축약은
`postgres_ontology_source_coverage.py`가 담당합니다. 기존 소유 모듈은 import 표면을 유지하고,
서로 응집된 이 도우미는 구조 크기 기준 아래로 유지됩니다. 서비스 이미지 빌드는 보안 수정 버전으로
해석된 OPA 전이 모듈을 검증하며, 각 Python 배포판은 고정된 workspace 잠금 파일을 통해 공통
`pypdf` 보안 하한을 고정합니다.
semantic-routing 기준선은 각 어휘 판단 소유자를 기록하고 결정론적 모델 출력 검증을 의미 추론과
구분합니다. 내용이 없는 판단 텔레메트리는 발화, 맥락 또는 제안 다이제스트를 보존하지 않으면서
프로필 및 모델 구성 개정, 계층, 신뢰도, 지연 시간, 결과 및 판단 보류 비율을 제공합니다.
competency fixture는 운영 준비 완료를 주장하지 않으면서 현재 구조 release와 Reader 매니페스트를
하나의 결합된 신원으로 고정합니다. ARB 근거 fixture는 런타임 읽기에 필요한 인증된 principal
context를 사용하고, Cost Governance는 선언이 추가되면 정확한 release 프로필과 fixture digest를 갱신합니다.
대화형 의미 턴은 요청마다 감사되는
`conversation.t2_escalation.aggressive_enabled` 런타임 설정을 읽을 수 있습니다. 개발 환경에서는
기본적으로 활성화하고 스테이징과 운영 환경에서는 기본적으로 비활성화합니다. 조건에 맞는 읽기 전용
T1 명확화, 사용 불가 및 수락되지 않은 제안 결과는 간결한 타입 기반 복구 맥락으로 같은 단계의 T2
재시도를 한 번 받을 수 있습니다. Golden 캠페인, 액션 초안, 서버 결속 범위, 권한 부여, 결정론적
검증 및 실행 권한 경계는 변경되지 않습니다. Operator 설정 저장소는 기존 리비전 기반 상태를 하나의
원자적 제안 트랜잭션으로 진행하며, 로컬 준비 과정은 설정 변환 결과를 새로 고칠지 결정할 때 런타임
설정 정의 소스를 포함합니다.
Kubernetes Resource Event 변환 결과는 선택적 객체 UID, 클러스터, 기록 시각 및 출처 리비전을
보존합니다. 따라서 후속 복구 근거는 원시 프로바이더 페이로드 없이 신원과 출처 계보를 유지할 수
있습니다.
의미 답변 권한은 Core `OntologyFunctionRegistry` 호출 증적에서 처음 생성됩니다. 쿼리 실행은
타입이 지정된 권한을 동일한 근거 참조와 함께 `QueryNodeResult`, `GoalTaskReceipt`, 의도 그래프
근거 v2로 전달합니다. Operator 의미 표현은 이 증적만 읽습니다. 구독 상태, 인벤토리 그래프,
사용량 측정, 온톨로지 매니페스트 출처를 서로 구분하고 모델 또는 클라이언트 권한 텍스트를
무시하며, 권한이 없거나 충돌하면 검증하지 않고 보류합니다.
혼합 리소스 상태 답변은 인벤토리와 Resource Health 출력 증적을 분리해 사용합니다. Service
Health는 구독 범위 요약을 별도로 사용하며, Operator는 합성된 결합 권한을 만들지 않고 각
원본의 권한, 완전성, 제한 사항을 보존합니다.
필터링하지 않은 Service Health 답변은 완전한 `service_issue` 이벤트 행에서만 장애 상태를
파생합니다. 상태 권고와 예정된 유지 관리는 별도의 활성 이벤트 범주로 유지하며, 범주 범위가
잘렸으면 장애가 있다고 결론 내리지 않고 확인 불가로 표시합니다.
서버에 구성되거나 서버가 관리 또는 참조하는 구독은 서버 소유 질의 범위에 속하며, 정확한 서버
Resource 신원이나 리소스 이름 명확화 대상으로 바뀌지 않습니다.
인벤토리 승격은 검증된 상태 변경을 Core 소유의
추가 전용 운영 상태 전이 원장에도 기록합니다. 온톨로지는 다시 만들 수 있는 현재 상태 변환
결과로 유지하고, 원장은 재생에 필요한 유효 시각, 기록 시각, 근거, 양의 커버리지를 보존합니다.
타입이 지정된 리소스 상태 대상을 여러 개 포함한 집합 질문은 정확한 단일 대상 확인을 건너뛰고
그룹화된 읽기 계획을 유지합니다. 종속 FunctionType 읽기에는 승인된 보안 ObjectSet 증적이
계속 필요합니다. 결정 근거 승인이 없으면 범위가 제한된 원본 사용 불가 결과를 반환하며, 쿼리
실행은 이 검사를 약화하지 않고 진단에 필요한 비민감 거부 이유를 기록합니다.
RCA 가설은 이제 T0, T1, T2 전체에서 하위 호환 가능한 원인 영역을 전달합니다. T0 구성 위반은
기본적으로 인프라를 사용하고, T1은 루트 변경 영역을 보존하며, T2 parser는 검토된 영역 enum만
수락합니다. 감사 및 읽기 변환 결과는 이전 레코드 또는 지원되지 않는 값을 `unknown`으로
표시합니다. 이 분류는 근거 전용이며 작업을 승인할 수 없습니다.
보안이 적용된 운영 맥락 표현은 서비스, 워크로드, 목표, 제약, 담당 체계, 의존성 및 종류별
커버리지 메타데이터를 제공하기 전에 명명된 모든 의미 신원이 증적에 결속된 ObjectSet에 있는지
확인합니다. 이 변경은 Console을 그래프 원본으로 만들지 않고 변환 결과 공백을 닫습니다.
검증된 각 Context 신원 목록은 기대 ObjectType 집합도 적용합니다. 따라서 증적에 결속되어
있더라도 타입이 혼동된 객체를 담당 체계, 서비스, 워크로드, 목표, 제약 또는 의존성 근거로
표시할 수 없습니다.
관리되는 RCA 문서 근거는 기존 `OperationalEvidenceBundle` 계약 위에서 별도의 어댑터와
수집기를 사용합니다. 컬렉션 범위 검색 이후 현재 문서 권한과 개정 번호를 다시 확인하고 불투명한
인용만 제공하며, 관리되는 근거를 사용할 수 없을 때 범위가 지정되지 않은 KnowledgeSource로
대체할 수 없습니다.
관리되는 수집기는 문서 발췌와 문서 lane 인용 매니페스트 사이의 정확한 집합 일치도 독립적으로
요구합니다. 따라서 추가되거나 중복되거나 누락된 매니페스트 항목은 RCA 인용이 될 수 없습니다.
관리되는 맥락을 명시적으로 요청했는데 수집기가 인용과 보류를 모두 반환하지 않으면
`document_evidence_missing`으로 정규화합니다. 관련 없는 원격 측정이 누락된 관리 근거 요구
사항을 조용히 충족할 수 없습니다.
WARA 평가는 변경할 수 없는 생성 교차워크 위에 정확한 평가기 바인딩 카탈로그를 추가합니다.
Azure delivery 어댑터는 승인된 관리 토큰 대상과 정확한 ARM 리소스 범위만 허용하며 overlay
다이제스트를 읽기 계획, 관측, 근거, 결과 및 재생 신원 전체에 전달합니다.
WARA 평가 서비스는 이제 평가 전에 적합한 모든 exact-bound 읽기를 실행하는 선택적 관측
실행기를 조립할 수 있습니다. 수동 증적을 보존하고 프로바이더 사용 불가를 충족 결과가 아니라
범위가 제한된 감사 근거로 기록합니다.
수집 후 실행기는 요청의 평가 및 기록 기준 시각을 최신 수집 증적까지 전진시킵니다. 따라서
유효한 최신 관측이 미래 근거로 잘못 분류되지 않습니다.
해당 실행에서 프로바이더로부터 수집한 근거만 기준 시각 전진에 참여합니다. 호출자가 제공한
근거에는 요청의 독립적인 원래 기준 시각을 계속 적용합니다.
원래 기준 시각을 넘은 호출자 증적은 프로바이더 수집 전에 허용되지 않는 것으로 표시합니다.
따라서 관련 없는 이후 관측이 해당 증적을 소급 허용할 수 없습니다.
일치 행 WARA 평가기가 위반 0건을 충족으로 처리하기 전에 Azure 어댑터는 같은 신원과 제한
시간을 사용하는 보조 정확한 ID 커버리지 쿼리에서 모든 대상을 관측하도록 요구합니다.
변경할 수 없는 WARA 요청, 근거, 상태, 컨트롤 및 결과 계약은 `core/wara/models.py`에 있습니다.
`core/wara/runtime.py`는 결정론적 평가, 관측 수집, 감사 및 게시를 유지하면서 기존 공개 계약을
다시 내보냅니다.
기본 ControlLoop 조립은 event-time `IncidentRcaContextSource` 하나를 연결합니다. 이벤트의
인벤토리 세대에서 정확한 프로바이더 신원을 해석하고 bitemporal topology history를 구성하며
lifecycle Incident 하나를 매칭하고 모든 세대가 일치할 때만 배포 멤버를 허용합니다. 전용 읽기
신원, sovereign endpoint, split 서비스 hydration 및 전체 timeout은 범위 없는 운영
상관관계로 대체하지 않고 실패 시 차단합니다.
`runtime/control_loop_auxiliary.py`는 결정론적 RCA 카탈로그 신원과 IRP handler 조립을 소유합니다.
`runtime/control_loop.py`는 권위 있는 루프 조립을 유지하고 기존 private bootstrap hook을 다시
내보냅니다. Package-wide strict type 검사에서도 이 경계를 인식하도록 명시적인 `__all__`
항목을 사용합니다.
자동 Incident T2에도 짝으로 구성되는 관리 문서 바인딩이 있습니다. Core는 별도의 읽기 전용
DSN과 정확한 컬렉션, 접근 참조, 읽기 그룹 구성을 받고 고정 Forseti 주체 맥락을 만들며, 권한
있는 문서 근거를 사용할 수 없으면 RCA 판단을 보류합니다.

| 영역 | Responsibility | 출처 | 테스트 |
|------|----------------|--------|------|
| 사람 승인 콜백 및 결정 전달 | Teams Bot 서비스와 OBO 행위자 검증, 매핑된 Slack 재인증, 정확한 콜백 맥락, 정제된 2단계 감사, 리스 펜싱 Operator 보낼 편지함, 워크플로 정족수 라우팅 및 BreakGlass나 실행기 권한이 없는 액션 전용 재개 | [Operator 콜백 기능군](../../../services/operator-service/src/fdai_operator_service/families/iam/), [Operator 보낼 편지함](../../../services/operator-service/src/fdai_operator_service/families/iam/hil_decision_outbox.py), [Core 결정 소비자](../../../services/core-control-plane/src/fdai/runtime/consumers.py), [HIL 레지스트리](../../../services/core-control-plane/src/fdai/shared/providers/hil_registry.py) | [Operator IAM 테스트](../../../services/operator-service/tests/test_operator_iam_family.py), [Teams 콜백 테스트](../../../services/operator-service/tests/test_hil_teams_callback.py), [보낼 편지함 재생 테스트](../../../services/operator-service/tests/test_hil_decision_outbox_replay.py), [서비스 간 라우팅 테스트](../../../tests/integration/test_hil_decision_routing.py) |
| 사용자 할당 담당 체계 조정 | 안전하게 다시 시도할 수 있는 shadow 담당 체계 초안 게시, 정확한 케이스, PR 및 내용 다이제스트 병합 상관관계, 담당 체계 결과 기록, 형식이 지정된 shadow IAM 적용 요청 | [사용자 할당 코어](../../../services/core-control-plane/src/fdai/core/human_assignment/) 및 [담당 체계 조정기](../../../services/core-control-plane/src/fdai/core/human_assignment/ownership_coordination.py) | [사용자 할당 테스트](../../../services/core-control-plane/tests/core/human_assignment/) |
| Azure Resource Health 정확한 분모 근거 | 보안이 적용된 정확한 Resource 분모, 대괄호 속성 표기만 사용하는 고정 공급자 쿼리, 정규화된 가용성 상태, 대상별 범위, 분리된 수집 시각과 공급자 시각, 결정론적 주장 변환 결과, 제한 사항을 표시하는 Operator 표현, 실행 권한 없음 | [근거 계약](../../../services/core-control-plane/src/fdai/core/ontology_platform/resource_health_evidence.py), [FunctionType](../../../services/core-control-plane/src/fdai/core/ontology_platform/resource_health_queries.py), [Azure 읽기 경로](../../../services/core-control-plane/src/fdai/delivery/azure/resource_health_collection.py), [주장 변환 결과](../../../services/core-control-plane/src/fdai_core_service/semantic_assurance_claims.py), [Operator 표현](../../../services/operator-service/src/fdai_operator_service/families/conversation/presentation_artifact_v2.py) | [계약 및 FunctionType 테스트](../../../services/core-control-plane/tests/core/ontology_platform/test_resource_health_queries.py), [Azure 읽기 경로 테스트](../../../services/core-control-plane/tests/delivery/azure/test_resource_health_collection.py), [주장 테스트](../../../services/core-control-plane/tests/test_semantic_assurance_projection.py), [표현 테스트](../../../services/operator-service/tests/test_presentation_artifact_v2.py) |
| 타입이 지정된 관계 대화 보증 | 결정론적 의미 facet 복구, 정확한 Rule 선언과 다중 pair LinkType 계획, 병합된 증적 계보, 제한된 검증 완료 온톨로지 경로 및 현재 인스턴스 신원으로 가장하지 않는 스키마 주장을 제공합니다. 서비스 담당 관계는 완전하고 가려지지 않으며 세대에 고정된 인스턴스 경로를 단일 복합 읽기 권한으로 사용하고, 지원되지 않거나 비어 있는 매핑은 계속 보류합니다. 장애가 바인딩되지 않은 변경 상관관계 요청은 기존에 검토된 관계 또는 변경 활동 의도, 정확한 `approved_windows`, `target_resources`, `service_paths` facet, 검토된 비인과 facet, 그리고 `change`, `changes`, `change_records`, `incident` 앵커 중 하나가 있을 때 검토된 `compare/windowed` 프레임을 유지하고 관계 또는 인과 근거 없이 보류합니다. 이 보류는 인과관계를 주장할 수 없으므로 모델이 비인과 facet을 생략해도 지원되지 않는 일반 관계 응답으로 바뀌지 않습니다. 검토된 스키마 수준 object-type 및 link-type 대상은 해당 프레임을 보존할 수 있지만 인스턴스 신원을 확립하지 않으며, 구체 대상이나 추가 facet이 있으면 이 보류를 우회합니다. | [관계 플래너](../../../services/core-control-plane/src/fdai/core/conversation/semantic_relationship_planning.py), [인스턴스 경로 핸들러](../../../services/core-control-plane/src/fdai/core/ontology_platform/query_source_handlers.py), [frame 검사](../../../services/core-control-plane/src/fdai/core/conversation/semantic_planning_frame_checks.py), [보증 변환 결과](../../../services/core-control-plane/src/fdai_core_service/semantic_assurance_projection.py), [답변 변환 결과](../../../services/core-control-plane/src/fdai_core_service/semantic_relationship_projection.py) | [의미 계획 테스트](../../../services/core-control-plane/tests/conversation/test_semantic_planning_tier_routing.py), [인스턴스 경로 테스트](../../../services/core-control-plane/tests/core/ontology_platform/test_investigation_query_nodes.py), [보증 테스트](../../../services/core-control-plane/tests/test_semantic_assurance_projection.py), [답변 테스트](../../../services/core-control-plane/tests/test_semantic_turn_processor.py) |
| Kubernetes Resource 이벤트 이력 | 출처에 근거한 정확한 대상 계획, 실패 시 차단하는 정확한 identity 개수 검사, 증적에 결속된 정확한 child UID 필터 또는 명시적인 정확한 클러스터 범위의 제한된 Kubernetes Event 읽기, lease 기반 불투명 cursor 수집, indexed append-only 보존, 정규화한 이벤트 시각, 내용 기반 근거, 제한 사항을 보여주는 이중 언어 답변, 독립적인 Azure/Kubernetes 기능군 라우팅, 명시적인 불완전 결과, 원시 메시지와 원인, 변경 또는 실행 권한 없음 | [의미 플래너](../../../services/core-control-plane/src/fdai/core/conversation/semantic_resource_event_planning.py), [FunctionType](../../../services/core-control-plane/src/fdai/core/ontology_platform/resource_event_queries.py), [Kubernetes 읽기 경로](../../../services/core-control-plane/src/fdai/delivery/kubernetes_resource_event_history.py), [기능군 라우터](../../../services/core-control-plane/src/fdai/delivery/resource_event_history.py), [런타임 연결](../../../services/core-control-plane/src/fdai/runtime/resource_event_providers.py), [답변 변환 결과](../../../services/core-control-plane/src/fdai_core_service/semantic_turn_processor.py) | [의미 계획 테스트](../../../services/core-control-plane/tests/conversation/test_semantic_planning.py), [Kubernetes 어댑터 테스트](../../../services/core-control-plane/tests/delivery/test_kubernetes_resource_event_history.py), [라우터 테스트](../../../services/core-control-plane/tests/delivery/test_resource_event_history.py), [FunctionType 테스트](../../../services/core-control-plane/tests/core/ontology_platform/test_resource_event_queries.py), [답변 테스트](../../../services/core-control-plane/tests/test_semantic_turn_processor.py), [런타임 테스트](../../../services/core-control-plane/tests/runtime/test_resource_health_provider.py) |
| 정확 Pod 진단 | 보안이 적용된 정확 Pod UID, 제한된 종료 lookback, 신선하고 완전하며 충돌과 synthetic 값이 없는 provider 상태 메타데이터, UID로 필터한 라이프사이클 이유, 내용 없는 로그 근거, 원인 또는 실행 권한 없음 | [진단 FunctionType](../../../services/core-control-plane/src/fdai/core/ontology_platform/kubernetes_pod_diagnosis_queries.py), [진단 reducer](../../../services/core-control-plane/src/fdai/core/ontology_platform/kubernetes_pod_diagnosis_evidence.py) | [진단 query 검사](../../../services/core-control-plane/tests/core/ontology_platform/test_kubernetes_pod_diagnosis_queries.py), [진단 reducer 검사](../../../services/core-control-plane/tests/core/ontology_platform/test_kubernetes_pod_diagnosis_evidence.py) |
| 컨트롤 루프와 decisioning | Event 정규화, 계층 라우팅, 정확한 Rego allow/deny 평가 증적, quality, risk, 승인, 실행 coordination, 복구 및 감사 | [코어](../../../services/core-control-plane/src/fdai/core/) | [코어 테스트](../../../services/core-control-plane/tests/core/) |
| CAF/WAF/WARA 프레임워크 카탈로그 및 준비 상태 | 고정된 자문 프레임워크 정의, WAF 컨트롤 59개 전체 체크리스트, WARA/APRL 수명 주기 레코드 456개 전체, 범위와 타입이 지정된 근거, 매니페스트 기반 완전성 검사, 권한이 없는 온톨로지 변환 결과, 범위가 제한되고 출처를 표시하는 Operator 읽기 | [프레임워크 로더](../../../services/core-control-plane/src/fdai/rule_catalog/schema/framework_catalog.py), [WARA 가져오기 도구](../../../scripts/catalog/import_wara_aprl.py), [준비 상태 구성](../../../services/core-control-plane/src/fdai/composition/readiness_catalog.py), [프레임워크 변환 결과](../../../services/core-control-plane/src/fdai/core/ontology_platform/framework_projection.py), [Operator 변환 결과](../../../services/operator-service/src/fdai_operator_service/family_adapters.py) | [프레임워크 카탈로그](../../../services/core-control-plane/tests/rule_catalog/test_framework_catalog.py), [WARA 가져오기 도구](../../../services/core-control-plane/tests/rule_catalog/test_wara_import.py), [준비 상태](../../../services/core-control-plane/tests/composition/test_readiness_catalog.py), [온톨로지 변환 결과](../../../services/core-control-plane/tests/core/ontology_platform/test_framework_projection.py), [Operator 워크플로](../../../services/operator-service/tests/test_operator_workflow_family.py) 테스트 |
| 계획된 변경의 그래프 근거 | Forseti가 기존 권한 상한을 유지하기 전에 인증, 릴리스 일치, 최신성, 완전성, 충돌, 합성, 미래 시점 및 잘림 상태를 독립적으로 다시 계산하는 정확한 기준 시점 그래프 증적 | [영향 평가](../../../services/core-control-plane/src/fdai/core/impact_analysis/change_assessment.py)와 [Forseti](../../../services/core-control-plane/src/fdai/agents/forseti.py) | [영향 테스트](../../../services/core-control-plane/tests/core/impact_analysis/test_change_assessment.py)와 [에이전트 체인 테스트](../../../services/core-control-plane/tests/agents/test_change_management_chain.py) |
| 단계 4 측정 작업 | 전용 비실행기 신원, 비밀 참조 및 값이 없을 수 있는 루트 출력을 사용하는 기본 비활성 상태의 범위가 제한된 Container Apps 작업 세 개 | [측정 모듈](../../../infra/modules/measurement-runners/)과 [루트 조립](../../../infra/main.tf) | [Terraform 계획 테스트](../../../infra/modules/measurement-runners/tests/jobs.tftest.hcl)와 [루트 계약 테스트](../../../tests/integration/infra/test_measurement_runner_jobs.py) |
| 단계 4 측정 정책 러너 | 비활성 패턴 쓰기 전 완전한 시간 홀드아웃, 짝지은 모델 비용 및 품질 검토 권고, T0/T1/T2 예산, 처리량, 백분위수 감사, 명시적 사용 불가 상태 및 승격이나 실행 권한이 없는 영속 중복 및 재시작 수렴 | [Core 집약기](../../../services/core-control-plane/src/fdai/core/measurement/), [홀드아웃 게이트](../../../services/core-control-plane/src/fdai/delivery/measurement/holdout.py), [측정 정책 러너](../../../services/core-control-plane/src/fdai/delivery/measurement/measured_policy.py), [CLI 조립](../../../services/core-control-plane/src/fdai/delivery/measurement_runner_cli.py) | [Core 측정 테스트](../../../services/core-control-plane/tests/core/measurement/), [전달 테스트](../../../services/core-control-plane/tests/delivery/measurement/), [러너 테스트](../../../services/core-control-plane/tests/measurement/test_runners.py) |
| 프로바이더 관계 D2-D4 수명 주기 | 고정된 스키마 입력, 비활성 명시적 orientation 후보, 완전한 엔드포인트 정본 변환 결과, 전이 참조 전용 재구축 무효화, 재현 가능한 간선, 탐색 및 영향 범위 비교, 정확한 롤백 포인터, 변경할 수 없는 서로 다른 검토자의 제안 이력 | [후보 세대](../../../services/core-control-plane/src/fdai/delivery/provider_schema_relationship_generation.py), [검토 원장](../../../services/core-control-plane/src/fdai/delivery/provider_schema_relationship_ledger.py), [완전 세대 변환 결과](../../../services/core-control-plane/src/fdai/delivery/azure/generation_relationships.py), [D4 비교](../../../services/core-control-plane/src/fdai/core/ontology_platform/direction_shadow/) | [세대 및 원장 테스트](../../../services/core-control-plane/tests/delivery/), [정본 고정본 테스트](../../../services/core-control-plane/tests/delivery/test_inventory_relationship_verifier.py), [D4 테스트](../../../services/core-control-plane/tests/core/ontology_platform/direction_shadow/) |
| 의사 결정 근거 검증 | 버전이 지정된 인증, 근거, 완전성, 충돌 및 최신성 정책 증명, 내용 기반 묶음, 유효 구간과 폐기를 고려한 검증기 선택, 예상된 검증기, 유효성 검사, 시간 초과, 조회 및 전송 실패를 범위가 제한된 차단 결과로 변환하면서 작업 취소는 그대로 전달하는 준비 상태 검사, 검증된 근거를 정확한 후속 의사 결정 입력에 연결하는 수명이 짧고 권한이 없는 승인 결과, `config/decision-boundary-inventory.json`에 등록된 모든 긍정적 의사 결정 경계, 즉 각 전체 입력 다이제스트와 범위, 목적 및 출처 리비전에 맞는 현재 승인 결과가 있어야만 긍정적인 결과를 허용하는 ChatOps qualification, 채팅 정책 단계 승격, Rubric 모드 승격, 현재 사례 T1 재사용, 운영 승격, 보안 온톨로지 쿼리 소비, 운영 컨텍스트 상태 근거와 스냅샷(bypass closure는 제공자가 바인딩되었지만 필수가 아닐 때만 SHADOW_ONLY를 강제하며, 제공자가 없으면 그래프 기반 상한이 적용됨), 분석기 신원 및 상태 대상 선택, 시작 준비 상태, 운영 준비 상태, 인과 종결, 효과 모델 활성화와 멱등 재적용, 작업 흐름 게이트, 영속 작업 흐름 승인 및 작업 흐름 결과 수락, 검토된 의사 결정 표면을 정확히 고정하고 누락된 경계, 실행되지 않거나 결과가 폐기된 승인 검사, 잘못된 모듈의 평가기 및 인벤토리에 없는 소스 경계를 차단하는 완전 인벤토리 커버리지 가드, 공유 증적과 묶음 다이제스트가 없으면 적용 모드 권한에는 사용할 수 없는 읽기 전용 기존 승격 증적, 자격 증명 보존과 실행 권한이 없는 Managed Identity 인증 Azure 원본 읽기 | [검증 계약](../../../packages/service-contracts/src/fdai_service_contracts/decision_evidence_verification.py), [검증기 프로바이더 seam](../../../services/core-control-plane/src/fdai/shared/providers/decision_evidence_verifier.py), [준비 상태 게이트](../../../services/core-control-plane/src/fdai/core/readiness/decision_evidence.py), [시작 조정기](../../../services/core-control-plane/src/fdai/core/readiness/coordinator.py), [운영 준비 상태 서비스](../../../services/core-control-plane/src/fdai/composition/readiness.py), [qualification 축약기](../../../services/core-control-plane/src/fdai/core/conversation_assurance/quality_qualification.py), [채팅 정책 승격](../../../services/core-control-plane/src/fdai/core/conversation_assurance/promotion.py), [승격 평가기](../../../services/core-control-plane/src/fdai/core/measurement/operational_promotion.py), [쿼리 권한](../../../services/core-control-plane/src/fdai/core/ontology_platform/query_receipt_authority.py), [상태 묶음](../../../services/core-control-plane/src/fdai/core/operational_context/evidence_bundle.py), [컨텍스트 스냅샷 materializer](../../../services/core-control-plane/src/fdai/core/operational_context/materializer.py), [분석기 대상 해석기](../../../services/core-control-plane/src/fdai/delivery/analyzer_targets.py), [인과 종결](../../../services/core-control-plane/src/fdai/core/rca/hypothesis.py), [효과 모델 활성화](../../../services/core-control-plane/src/fdai/core/assurance_twin/model_promotion.py), [작업 흐름 게이트 해석기](../../../services/core-control-plane/src/fdai/core/workflow/gate_resolver.py), [작업 흐름 승인 근거](../../../services/core-control-plane/src/fdai/core/workflow/approval_admission.py), [작업 흐름 결과 원장](../../../services/core-control-plane/src/fdai/core/workflow/outcome_verification.py), [경계 인벤토리](../../../config/decision-boundary-inventory.json), [커버리지 가드](../../../scripts/quality/architecture/check-decision-boundary-coverage.py), [Azure 어댑터](../../../services/core-control-plane/src/fdai/delivery/azure/decision_evidence.py) | [계약 테스트](../../../packages/service-contracts/tests/test_decision_evidence_verification.py), [준비 상태 테스트](../../../services/core-control-plane/tests/core/readiness/test_decision_evidence.py), [시작 조정기 테스트](../../../services/core-control-plane/tests/core/readiness/test_startup_coordinator.py), [운영 준비 상태 테스트](../../../services/core-control-plane/tests/composition/test_readiness_service.py), [qualification 및 채팅 정책 테스트](../../../services/core-control-plane/tests/core/conversation_assurance/), [승격 테스트](../../../services/core-control-plane/tests/core/measurement/test_operational_promotion.py), [쿼리 권한 테스트](../../../services/core-control-plane/tests/core/ontology_platform/test_query_receipt_authority.py), [상태 묶음 및 스냅샷 테스트](../../../services/core-control-plane/tests/core/operational_context/), [분석기 대상 테스트](../../../services/core-control-plane/tests/delivery/test_analyzer_targets.py), [인과 종결 테스트](../../../services/core-control-plane/tests/core/rca/test_hypothesis.py), [효과 모델 활성화 테스트](../../../services/core-control-plane/tests/assurance_twin/test_model_promotion.py), [작업 흐름 게이트 및 결과 테스트](../../../services/core-control-plane/tests/core/workflow/), [커버리지 가드 테스트](../../../tests/integration/scripts/test_decision_boundary_coverage.py), [Azure 어댑터 테스트](../../../services/core-control-plane/tests/delivery/azure/test_decision_evidence.py) |
| A3-E 수명 주기 영속성 | Core가 계산한 변경할 수 없는 개정 번호, 정확한 대상을 지정하며 재사용할 수 없는 승인과 검증된 근거 결속, 인증된 승인/갱신/폐기 명령, 기능군별 해시 체인 전이, 단조로운 fencing, 다시 만들 수 있는 변환 결과, 원자적 PostgreSQL 감사, 최신 전이에 결속된 스냅샷 읽기 및 연결되지 않은 실패 시 차단 주 저장소 fence 검사 | [개정 번호 신원](../../../services/core-control-plane/src/fdai/core/standing_authority/lifecycle_revision.py), [수명 주기](../../../services/core-control-plane/src/fdai/core/standing_authority/lifecycle.py), [fence 가드](../../../services/core-control-plane/src/fdai/core/standing_authority/fence.py), [프로바이더 seam](../../../services/core-control-plane/src/fdai/shared/providers/standing_authority.py), [PostgreSQL 어댑터](../../../services/core-control-plane/src/fdai/delivery/persistence/postgres_standing_authority.py), [마이그레이션](../../../service-migrations/branches/core-control-plane/versions/20260829_core_standing_authority_lifecycle.py) | [상시 권한 테스트](../../../services/core-control-plane/tests/core/standing_authority/), [영속성 테스트](../../../services/core-control-plane/tests/persistence/test_postgres_standing_authority.py) |
| ARB 관찰 추적 | 명시적인 소유자, ID, 기한, 중복, 재시작, 충돌, 권한 없음 검사와 종료된 observer 성능 저하 근거 보존을 포함해 고정된 Huginn, Muninn, 전문 에이전트, Forseti, Saga 경계를 런타임에 연결된 재생 가능한 관찰 경로로 변환합니다. | [관찰 루프](../../../services/core-control-plane/src/fdai/core/architecture_review/observation_loop.py), [변환 결과](../../../services/core-control-plane/src/fdai/core/architecture_review/projection.py) | [아키텍처 검토 테스트](../../../services/core-control-plane/tests/core/architecture_review/) |
| 발행기로 한정된 모델 해석 | 이전 버전과 호환되는 catalog 및 quota seam, SKU 한정 Azure 용량 조회, stable version 전달, version이 있는 preference 대체 경로, GA version 없이 판단 보류된 선택적 기능의 경로 억제 | [resolver schema](../../../services/core-control-plane/src/fdai/rule_catalog/schema/llm_resolver.py), [배포 변환 결과](../../../services/core-control-plane/src/fdai/rule_catalog/schema/llm_endpoint_selection.py), [resolver CLI](../../../services/core-control-plane/src/fdai/rule_catalog/schema/llm_resolver_cli.py), [Azure 조회](../../../services/core-control-plane/src/fdai/delivery/azure/llm/resolver_queries.py) | [resolver 테스트](../../../services/core-control-plane/tests/rule_catalog/schema/test_llm_resolver.py), [narrator 테스트](../../../services/core-control-plane/tests/rule_catalog/schema/test_narrator_collection.py), [Azure 조회 테스트](../../../services/core-control-plane/tests/delivery/azure/llm/test_resolver_queries.py) |
| 모델 경계 privacy 최소화 | 타입이 지정된 사전 최소화 증적, 프로바이더 전송 전 결정론적 민감정보 제거, 그리고 판단 권한을 바꾸지 않으면서 안전하지 않은 모델 또는 임베딩 페이로드를 실패 시 보류하는 동작 | [model_trace.py](../../../services/core-control-plane/src/fdai/delivery/azure/llm/model_trace.py), [Azure LLM 어댑터](../../../services/core-control-plane/src/fdai/delivery/azure/llm/) | [model trace 테스트](../../../services/core-control-plane/tests/delivery/azure/llm/test_model_trace.py), [어댑터 테스트](../../../services/core-control-plane/tests/delivery/azure/llm/test_adapters.py), [mixed-model cross-check 테스트](../../../services/core-control-plane/tests/quality_gate/test_mixed_model_cross_check.py) |
| 예약된 Core Job 이름 | 유효한 기존 이름은 Job별로 유지하고 Azure 32자 제한을 넘을 때 환경 범위 축약 형식을 사용합니다. | [compute 모듈](../../../infra/modules/compute/container-apps/), [root 조립](../../../infra/main.tf) | [Job 명명 테스트](../../../tests/integration/infra/test_container_app_job_names.py) |
| 영속 scheduler Job 진입점 | 포기된 claim 조정, 구성된 ingress 토픽으로의 Event Bus 발행, 중복 억제, 민감정보가 없는 재시도 출력 및 실행 권한 없음이 적용된 범위가 제한된 PostgreSQL 기반 scheduler 실행 | [scheduler CLI](../../../services/core-control-plane/src/fdai/delivery/scheduler_tick_cli.py), [scheduler 서비스](../../../services/core-control-plane/src/fdai/core/scheduler/service.py), [PostgreSQL 어댑터](../../../services/core-control-plane/src/fdai/delivery/persistence/) | [scheduler CLI 테스트](../../../services/core-control-plane/tests/delivery/test_scheduler_tick_cli.py), [scheduler 테스트](../../../services/core-control-plane/tests/core/scheduler/), [영속성 테스트](../../../services/core-control-plane/tests/persistence/) |
| 실행 가능한 DB-DR 작업 | 전달 계층이 소유하는 Azure PostgreSQL 특정 시점 복원, 범위가 제한된 결정적 테이블 비교, 롤백되는 읽기/쓰기 smoke, 정리, 영속 검증기 감사 및 전용 비실행기 신원 | [DB-DR CLI](../../../services/core-control-plane/src/fdai/delivery/db_dr_drill_cli.py), [Azure 복원 어댑터](../../../services/core-control-plane/src/fdai/delivery/azure/db_dr_restore.py), [PostgreSQL 검사](../../../services/core-control-plane/src/fdai/delivery/db_dr_postgres.py), [프로바이더 중립 검증기](../../../services/core-control-plane/src/fdai/core/verticals/resilience/db_dr_verifier.py) | [전달 테스트](../../../services/core-control-plane/tests/delivery/), [검증기 테스트](../../../services/core-control-plane/tests/verticals/test_db_dr_verifier.py), [인프라 계약 테스트](../../../tests/integration/infra/test_scheduler_db_dr_jobs.py) |
| 컨트롤 플레인 지역 복구 shadow 경로 | 실제 공급자를 변경하지 않고 예상 epoch 차단, 검증된 단일 writer 상태, 범위가 제한된 근거 증적, 다음 작업 전 중단 동작을 적용하는 공급자 중립적인 순서 기반 failover 및 failback 예행 연습 | [shadow 복구](../../../services/core-control-plane/src/fdai/core/verticals/resilience/shadow_recovery.py), [복구 공급자 계약](../../../services/core-control-plane/src/fdai/shared/providers/control_plane_recovery.py) | [shadow 복구 테스트](../../../services/core-control-plane/tests/core/verticals/test_recovery_plan_shadow.py), [복구 계획 테스트](../../../services/core-control-plane/tests/core/verticals/test_recovery_plan.py), [복구 조정기 테스트](../../../services/core-control-plane/tests/core/verticals/test_recovery_coordinator.py) |
| 환각 루브릭 승격 | 짝지은 불변 기준선/처리군 근거, 신뢰도를 고려한 준비 판정, 독립 검토 결속, 엄격한 매니페스트 검증 및 승격 권한이 없는 ActionType별 실패 시 차단 루브릭 모드 해석 | [루브릭 승격 core](../../../services/core-control-plane/src/fdai/core/quality_gate/promotion.py) 및 [매니페스트 어댑터](../../../services/core-control-plane/src/fdai/delivery/measurement/rubric_promotion_evidence.py) | [루브릭 승격 테스트](../../../services/core-control-plane/tests/core/quality_gate/test_rubric_promotion.py), [어댑터 테스트](../../../services/core-control-plane/tests/delivery/test_rubric_promotion_evidence.py) 및 [조립 테스트](../../../services/core-control-plane/tests/composition/test_rubric_promotion_binding.py) |
| MSCP 응답 결과 변환과 고정 전체 루프 종결 | 리소스 참조 대신 대상 다이제스트를 저장하고, 계약이 표현할 수 없는 관측(창을 벗어났거나 아직 기록되지 않았거나 전달 완료 전인 관측)을 발송 도중 오류로 만들지 않고 `unscorable`로 보류하며, 실행이나 promote 권한을 갖지 않는 strict shadow `ResponseOutcome` 변환. 제품에 포함된 shadow executor 위에서 실제 제어 루프를 실행하고 독립적이고 권위 있는 효과 관측에서만 종결하는 고정 SRE 전체 루프 재생이 이를 검증합니다 | [응답 결과 변환](../../../services/core-control-plane/src/fdai/core/mscp_profile/response_outcome.py)과 [효과 검증](../../../services/core-control-plane/src/fdai/core/mscp_profile/effect_verification.py) | [변환 테스트](../../../services/core-control-plane/tests/core/mscp_profile/test_response_outcome.py)와 [고정 전체 루프 재생](../../../services/core-control-plane/tests/scenarios/test_v2026_07_replay.py) |
| MSCP 효과 준비 상태 | 정확한 후보 묶음과 기한이 포함된 재시작 안전 예상 효과 레코드, compare-and-set 관측 lease, 오래된 개정 번호 및 소유권 차단, 기한순 worker 복구, 영속 verified/mismatch/hold 결과, 프로바이더 실패 격리, 후보별 검토 메트릭과 95% 신뢰도 하한, 무관용 guard 미비점, 즉시 demotion을 지원하는 기본 shadow 검토 프로파일 수명 주기, 재시도 또는 승인 fan-out이 없는 전체 범위 제한 실패 라우팅, 추가 전용 감사 전이 및 실행, 승격 또는 활성화 권한 없음 | [대기 효과 저장소](../../../services/core-control-plane/src/fdai/core/mscp_profile/pending_effect_store.py), [관측 worker](../../../services/core-control-plane/src/fdai/core/mscp_profile/observation_worker.py), [준비 상태 검증기](../../../services/core-control-plane/src/fdai/core/mscp_profile/readiness.py), [프로파일 수명 주기](../../../services/core-control-plane/src/fdai/core/mscp_profile/profile_lifecycle.py), [실패 정책](../../../services/core-control-plane/src/fdai/core/mscp_profile/failure_policy.py) | [대기 효과 테스트](../../../services/core-control-plane/tests/core/mscp_profile/test_pending_effect_store.py), [worker 테스트](../../../services/core-control-plane/tests/core/mscp_profile/test_observation_worker.py), [준비 상태 테스트](../../../services/core-control-plane/tests/core/mscp_profile/test_readiness.py), [수명 주기 테스트](../../../services/core-control-plane/tests/core/mscp_profile/test_profile_lifecycle.py), [실패 테스트](../../../services/core-control-plane/tests/core/mscp_profile/test_failure_policy.py) |
| 실행 권한 부여 | 프로바이더 중립적인 요구 사항 결과, 비어 있지 않은 결정 집합의 최소 권한 축소, 정규 요청 및 인벤토리 연결, 모호한 ID 또는 연결되지 않은 권한 부여 제안 거부 | [execution_authorization](../../../services/core-control-plane/src/fdai/core/execution_authorization/) | [실행 권한 부여 테스트](../../../services/core-control-plane/tests/core/execution_authorization/) |
| 온톨로지 안전성 platform | 카탈로그에서 로드한 Interface 및 FunctionType 선언을 포함하는 exact 의미 release, release-aware 조회 profile 및 함수 등록, principal 범위로 한정된 매니페스트, 검증된 Resource와 ResourceType 분류, 범용/temporal 조회 algebra, bitemporal 토폴로지/차이, 범위가 제한된 blast-radius 차이, authoritative inventory rebuild pointer 및 서로 다른 검토자와 회귀 증적에 결속된 catalog PR 제안을 포함하는 immutable direction-generation shadow comparison, 검토된 메트릭 개념, topology-aware causal 결합, 값의 평균 처리나 권한 확대가 없는 교차 출처 변환 상태 및 텔레메트리 판정, Resource별 최신성 메타데이터가 완전한 그래프 읽기, 다이제스트로 차단된 지속형 운영 모델 replay 복구, 프로덕션 쓰기 권한이 없는 근거 기반 읽기 및 copy-on-write scenario branch, 별도의 planner-function 및 operational-plan lineage와 안전하게 닫히도록 문서화된 인자, 근거, 대상 및 효과 검증 계약이 있는 변경 계획, compact typed effect-reconciliation event, 인증된 독립 observer binding 및 lease-fenced 영속 terminal outbox 전달 | [ontology_platform](../../../services/core-control-plane/src/fdai/core/ontology_platform/) | [온톨로지 platform 테스트](../../../services/core-control-plane/tests/core/ontology_platform/) |
| 온톨로지 구조 모델 | 정확한 ResourceType 아이덴티티, 검토된 ResourceClass 집계, 검토된 Property 의미 및 capability Interface, 직접 링크 역할과 의미 특성, 탐색형 관계 탐색, 순서가 있는 형식화된 경로, 제한을 보존하는 그래프 표현 | [소유 설계](ontology-structural-model-ko.md), [온톨로지 계약](../../../services/core-control-plane/src/fdai/shared/contracts/models/ontology.py), [카탈로그 변환 결과](../../../services/core-control-plane/src/fdai/core/ontology_platform/catalog_projection.py), [쿼리 platform](../../../services/core-control-plane/src/fdai/core/ontology_platform/) | [온톨로지 platform 테스트](../../../services/core-control-plane/tests/core/ontology_platform/), [카탈로그 테스트](../../../services/core-control-plane/tests/rule_catalog/), [Console 그래프 테스트](../../../console/src/components/ontology-graph.model.test.ts) |
| 운영 인스턴스 근거 adapter | 인증된 exact-endpoint runtime-call observation, principal-safe PostgreSQL role 근거, 명시적 unavailable source 상태, action authority 없이 inventory single writer를 통과하는 검증된 pre-promotion 보강 | [runtime-call telemetry](../../../services/core-control-plane/src/fdai/core/ontology_platform/runtime_call_telemetry.py), [PostgreSQL role 근거](../../../services/core-control-plane/src/fdai/core/ontology_platform/postgres_role_evidence.py), [inventory binding](../../../services/core-control-plane/src/fdai/delivery/runtime_call_inventory.py) | [runtime-call telemetry 테스트](../../../services/core-control-plane/tests/core/ontology_platform/test_runtime_call_telemetry.py), [PostgreSQL role 근거 테스트](../../../services/core-control-plane/tests/core/ontology_platform/test_postgres_role_evidence.py), [inventory binding 테스트](../../../services/core-control-plane/tests/delivery/test_runtime_call_inventory.py) |
| Kubernetes 워크로드 근거 | 허용 목록에 있는 Deployment 및 Pod 관측, 정확한 대상 선택, 독립적으로 검증된 2단계 소유권 근거, 검토된 불변 Pod 재시작 이력 메트릭, 근본 원인 또는 실행 권한을 주장하지 않는 최신성 및 충돌 인식 rollout, 같은 UID 재시작, 서로 다른 UID 교체 및 내용 없는 정확한 Pod 진단 축약기를 제공합니다. 교체 근거는 클러스터, 네임스페이스, 워크로드 개정, 수명 주기 순서, 범위가 지정된 종료, 양의 컨테이너와 replica 상태 및 완전한 desired-replica 이력을 연결하며 모호한 후보는 재생 가능하게 유지합니다. 진단은 보안이 적용된 정확한 Pod UID 하나를 범위가 제한된 수명 주기 및 로그 본문을 보존하지 않는 근거와 결합하고 명시적인 출처 공백을 유지합니다. 조회 연결은 누락된 과거 관측을 추론하지 않고 영속 수명 주기 수집을 기다립니다. | [Kubernetes 인벤토리 source](../../../services/core-control-plane/src/fdai/delivery/kubernetes_api_inventory.py), [rollout 조회](../../../services/core-control-plane/src/fdai/core/ontology_platform/kubernetes_rollout_queries.py), [Pod 복구 조회](../../../services/core-control-plane/src/fdai/core/ontology_platform/kubernetes_pod_recovery_queries.py), [Pod 교체 축약기](../../../services/core-control-plane/src/fdai/core/ontology_platform/kubernetes_pod_replacement_evidence.py), [Pod 진단 조회](../../../services/core-control-plane/src/fdai/core/ontology_platform/kubernetes_pod_diagnosis_queries.py), [내용 없는 로그 어댑터](../../../services/core-control-plane/src/fdai/delivery/kubernetes_pod_log_evidence.py), [의미 플래너](../../../services/core-control-plane/src/fdai/core/conversation/) | [인벤토리 source 테스트](../../../services/core-control-plane/tests/delivery/test_kubernetes_api_inventory.py), [워크로드 축약기 및 조회 테스트](../../../services/core-control-plane/tests/core/ontology_platform/), [로그 어댑터 테스트](../../../services/core-control-plane/tests/delivery/test_kubernetes_pod_log_evidence.py), [플래너 테스트](../../../services/core-control-plane/tests/conversation/), [조립 테스트](../../../services/core-control-plane/tests/composition/) |
| 지속형 운영 인스턴스 그래프 | 검증된 source policy, adaptive collection, event/delta/snapshot convergence, 로컬/배포 analyzer 일정 관리 동등성, 모호한 전송을 조정 대기로 유지하는 한 번만 게시되는 analyzer 발견 사항, 명시적 근거 원본에서 바인딩되는 타입 지정 Kubernetes Pod 수명 주기 발견 사항, 현재 상태, 실패 이력, 복구, 근거 공백을 분리해 유지하고 최신성 예산을 넘긴 상태를 철회하는 한정된 Pod 수명 주기 프로젝션, principal-safe health, typed semantic rollup, content-addressed archive lifecycle, 5개 결과를 갖는 graph refresh 결정, 관계를 진술할 수 있는 스냅샷만 게이팅하는 관계 커버리지, 안전한 부분 live-evidence write-through, action authority가 없는 typed 대표 competency | [소유 설계](continuous-operational-instance-graph-ko.md), [감사 계약](../../../config/continuous-operational-instance-graph-audit.json), [analyzer CLI](../../../services/core-control-plane/src/fdai/delivery/analyzer_tick_cli.py), [analyzer 실행기](../../../services/core-control-plane/src/fdai/delivery/analyzer_tick.py), [게시 계약](../../../services/core-control-plane/src/fdai/shared/providers/event_bus.py), [게시 원장](../../../services/core-control-plane/src/fdai/delivery/persistence/postgres_analyzer_publication.py), [Pod 수명 주기 analyzer](../../../services/core-control-plane/src/fdai/core/investigation/kubernetes_pod.py), [Pod 근거 바인딩](../../../services/core-control-plane/src/fdai/delivery/pod_evidence_binding.py), [Pod 수명 주기 프로젝션 축약기](../../../services/core-control-plane/src/fdai/core/readiness/detection_lifecycle.py), [Pod 수명 주기 프로젝션 상태](../../../services/core-control-plane/src/fdai/delivery/detection_lifecycle_state.py), [Operator 수명 주기 프로젝션](../../../services/operator-service/src/fdai_operator_service/detection_lifecycle_projection.py), [로컬 analyzer 작업](../../../scripts/deployment/local/run-analyzer-loop.sh), [rollup core](../../../services/core-control-plane/src/fdai/core/ontology_platform/semantic_rollup.py), [archive core](../../../services/core-control-plane/src/fdai/core/ontology_platform/archive_manifest.py), [graph refresh](../../../services/core-control-plane/src/fdai/core/ontology_platform/graph_evidence_refresh.py), [투영 커버리지](../../../services/core-control-plane/src/fdai/delivery/persistence/postgres_ontology.py), [competency](../../../services/core-control-plane/src/fdai/core/ontology_platform/operational_instance_competency.py), [inventory adapter](../../../services/core-control-plane/src/fdai/delivery/inventory_rollup.py), [live evidence](../../../services/core-control-plane/src/fdai/delivery/inventory_live_evidence.py), [archive persistence](../../../services/core-control-plane/src/fdai/delivery/persistence/postgres_operational_archive.py), [Core migration](../../../service-migrations/branches/core-control-plane/versions/20260822_core_operational_archive.py) | [analyzer 테스트](../../../services/core-control-plane/tests/delivery/test_analyzer_tick.py), [게시 원장 테스트](../../../services/core-control-plane/tests/delivery/test_analyzer_publication_ledger.py), [Pod 시나리오 테스트](../../../services/core-control-plane/tests/delivery/test_analyzer_tick_pod_scenario.py), [Pod 수명 주기 축약기 테스트](../../../services/core-control-plane/tests/core/readiness/test_detection_lifecycle.py), [Pod 수명 주기 프로젝션 테스트](../../../services/operator-service/tests/test_detection_lifecycle_projection.py), [Pod 수명 주기 종단 간 테스트](../../../tests/integration/test_pod_lifecycle_detection_e2e.py), [감사 테스트](../../../tests/integration/scripts/test_continuous_operational_instance_graph_audit.py), [refresh 테스트](../../../services/core-control-plane/tests/core/ontology_platform/test_graph_evidence_refresh.py), [competency 테스트](../../../services/core-control-plane/tests/core/ontology_platform/test_operational_instance_competency.py), [live-evidence 테스트](../../../services/core-control-plane/tests/delivery/test_inventory_live_evidence.py), [rollup 테스트](../../../services/core-control-plane/tests/core/ontology_platform/test_semantic_rollup.py), [archive 테스트](../../../services/core-control-plane/tests/core/ontology_platform/test_archive_manifest.py), [purge 테스트](../../../services/core-control-plane/tests/delivery/test_operational_archive_purge.py), [cross-lane 테스트](../../../tests/integration/test_operational_instance_retention.py) |
| 온톨로지 선언 워크벤치 변환 결과 | Exact-release 선언 상세, 토폴로지 기반 종속 항목, 정제된 ObjectType 근거 상태, 보존 release 호환성, 역할/용도 redaction 및 변경 권한이 없는 결정론적 개정 번호 | [ontology_declaration_projection.py](../../../services/core-control-plane/src/fdai/delivery/ontology_declaration_projection.py), [ontology_dependents_projection.py](../../../services/core-control-plane/src/fdai/delivery/ontology_dependents_projection.py), [ontology_evidence_health_projection.py](../../../services/core-control-plane/src/fdai/delivery/ontology_evidence_health_projection.py), [ontology_release_diff_projection.py](../../../services/core-control-plane/src/fdai/delivery/ontology_release_diff_projection.py) | [delivery 변환 결과 테스트](../../../services/core-control-plane/tests/delivery/), [catalog materializer 테스트](../../../tests/integration/scripts/test_materialize_authoritative_catalogs.py) |
| OI-12 운영 인증 | Exact-release 7축 집계 snapshot, 읽기 전용 PostgreSQL 수집, signed storage growth, 명시적인 unavailable 근거, 범위가 제한된 로컬 rollup/archive/restore exercise 및 권한이 없는 증적 발행 | [인증 계약](../../../services/core-control-plane/src/fdai/core/ontology_platform/operational_instance_certification.py), [인증 reducer](../../../services/core-control-plane/src/fdai/delivery/operational_instance_certification.py), [PostgreSQL source](../../../services/core-control-plane/src/fdai/delivery/operational_instance_certification_postgres.py), [archive exercise](../../../services/core-control-plane/src/fdai/delivery/operational_instance_certification_archive.py), [인증 CLI](../../../services/core-control-plane/src/fdai/delivery/operational_instance_certification_cli.py) | [계약 테스트](../../../services/core-control-plane/tests/core/ontology_platform/test_operational_instance_certification.py), [delivery 테스트](../../../services/core-control-plane/tests/delivery/test_operational_instance_certification.py), [archive exercise 테스트](../../../services/core-control-plane/tests/delivery/test_operational_instance_certification_archive.py) |
| 의미 대화 계획 수립 | 매니페스트 로드 전 compact T1 social/operation preflight, 모든 비직접 결과를 위한 Whole-turn 기능 인식 스키마 제안, 후속 프레임 제안보다 먼저 적용하는 canonical typed judgment, 서버가 소유한 프레임/계획 신원, principal-manifest 검증, 비동기 검증된 실행, 근거가 필요 없는 타입 지정 직접 응답, 내용이 없는 계층/구성/신뢰도/지연 시간/결과 및 판단 보류 텔레메트리, 전체 최종 처리 결과, 결정론적 의도 그래프, exact-command 호환성 전환, 선언 기반의 범위가 제한된 질문 집합 생성, 인식 상태 완결성 release 증적, 정확한 서비스-Resource 범위와 실패 시 차단되는 Resource 상태 근거를 사용하는 타입 기반 네트워크 대 애플리케이션 지연 조사, 발화가 이미 지목한 대상을 되묻지 않도록 출력 계열과 무관하게 동작하는 정확한 Resource 신원 해소 및 실행 권한이 없는 연속 커버리지 게이트 | [대화](../../../services/core-control-plane/src/fdai/core/conversation/), [의미 판단 텔레메트리](../../../services/core-control-plane/src/fdai/core/conversation/semantic_judgment_telemetry.py), [S3 프레임 정규화](../../../services/core-control-plane/src/fdai/core/conversation/semantic_planning_frame_normalization.py), [대상 후보 계획](../../../services/core-control-plane/src/fdai/core/conversation/semantic_target_candidate_planning.py), [조사 플래너](../../../services/core-control-plane/src/fdai/core/conversation/semantic_investigation_planning.py) | [대화 테스트](../../../services/core-control-plane/tests/conversation/) |
| 영속 백그라운드 작업 인계 | 프로덕션 실행기 연결 없이 임차 기간으로 보호되는 분리 읽기 레코드, 원자적 최종 발신함, progress-before-terminal 전달을 보장하는 트랜잭션형 Core-to-Operator snapshot 및 progress outbox 점유, Operator 소유 변환 결과 수집, 단일 기록 완료 감사 표시 | [background_task](../../../services/core-control-plane/src/fdai/core/background_task/), [projection 게시자](../../../services/core-control-plane/src/fdai_core_service/background_task_projection.py), [projection feed](../../../services/core-control-plane/src/fdai/delivery/persistence/postgres_background_task_projection_feed.py), [완료 감사 어댑터](../../../services/core-control-plane/src/fdai/delivery/persistence/background_task_completion_audit.py) | [백그라운드 작업 테스트](../../../services/core-control-plane/tests/core/background_task/), [runtime 테스트](../../../services/core-control-plane/tests/runtime/test_read_investigation_runtime.py), [완료 감사 테스트](../../../services/core-control-plane/tests/persistence/test_background_task_completion_audit.py) |
| Rule 의미 세대 종결 | 타입 기반 활성화 명령 및 최종 결과, 정확한 대상 증적과 예상 이전 세대 compare-and-swap, 프로바이더 접근 전 replay 차단, 원자적 StateStore 결과/outbox 영속성, lease 차단, 재시도 예약, 손상 거부 및 정책 또는 실행 권한이 없는 broker 확인 기반 발행 상태 | [rule_semantic_generation](../../../services/core-control-plane/src/fdai/core/rule_semantic_generation/) | [Rule 의미 세대 테스트](../../../services/core-control-plane/tests/core/rule_semantic_generation/) |
| 온톨로지 의미 세대 | 프로바이더 중립적이고 범위가 제한된 순서 보장 문서 매니페스트, 자체 검증 가능한 세대 ID, 후보 전용 구체적인 인덱스, 영속 PostgreSQL 저장, 예상 이전 세대 활성화 compare-and-swap, full/incremental 선언 및 deployment-object 문서, 독립적인 검증 증적, stale detection 및 롤백 | [catalog_search 프로바이더](../../../services/core-control-plane/src/fdai/shared/providers/catalog_search.py) 및 [catalog_search 전달](../../../services/core-control-plane/src/fdai/delivery/catalog_search/) | [카탈로그 검색 테스트](../../../services/core-control-plane/tests/delivery/catalog_search/) |
| 메트릭, VM 프로세스 및 MySQL 압력 근거 연결 | 별칭 없는 검토된 메트릭 개념, 정확한 ObjectSet에서 파생한 label 선택기, 어떤 계획도 보호된 근거를 모델이 작성한 리터럴로 대체하지 못하도록 객체 값을 받는 모든 FunctionType 입력에 적용한 dependency-only 근거 연결, 관측된 0을 프로바이더 공백과 구분하는 정확한 `MetricProvider` 구간, 범위가 제한된 VM 프로세스별 CPU 레코드, 원인 또는 실행 권한이 없는 staged MySQL 포화 대 수요 근거 | [metric_window.py](../../../services/core-control-plane/src/fdai/delivery/metric_window.py), [metric_semantic_catalog.py](../../../services/core-control-plane/src/fdai/runtime/metric_semantic_catalog.py), [VM 프로세스 계약](../../../services/core-control-plane/src/fdai/core/ontology_platform/vm_process_evidence.py), [Azure Monitor Perf 어댑터](../../../services/core-control-plane/src/fdai/delivery/azure/vm_process_evidence.py), [MySQL 압력 근거](../../../services/core-control-plane/src/fdai/core/ontology_platform/mysql_pressure_evidence.py) | [메트릭 의미 카탈로그 테스트](../../../services/core-control-plane/tests/runtime/test_metric_semantic_catalog.py), [VM 프로세스 계약 테스트](../../../services/core-control-plane/tests/core/ontology_platform/test_vm_process_evidence.py), [Azure 어댑터 테스트](../../../services/core-control-plane/tests/delivery/azure/test_vm_process_evidence.py), [MySQL 압력 테스트](../../../services/core-control-plane/tests/core/ontology_platform/test_mysql_pressure_evidence.py) |
| 운영 가설 루프 | 완전한 graph Dynamic 근거 연결, 근거 하한을 고려한 계획 선택, 기한이 제한된 독립 궤적 종결, 일반 exact-plan 실행에서 시작하는 감독되는 타입 기반 효과 조정, 독립 VM Scale Set 관측을 위한 배포 소유 Ed25519 인증, 권한이 없는 exact kinetic proposal handoff, 과거 단일 참조 읽기와 새로운 복수 참조 전용 쓰기를 지원하는 변경 불가능한 다중 효과 운영 계보 및 Owner 사람 승인을 거치는 graph-model pointer 승격 | [graph 근거](../../../services/core-control-plane/src/fdai/delivery/azure/graph_dynamic_evidence.py), [종결](../../../services/core-control-plane/src/fdai/core/assurance_twin/graph_closure.py), [조정](../../../services/core-control-plane/src/fdai/delivery/reconciliation_runtime.py), [서명 관측 맥락](../../../services/core-control-plane/src/fdai/delivery/azure/observation_context.py), [런타임 관측 연결](../../../services/core-control-plane/src/fdai/runtime/observation_evidence.py), [일반 요청 producer](../../../services/core-control-plane/src/fdai/delivery/reconciliation_request.py), [kinetic proposal producer](../../../services/core-control-plane/src/fdai/delivery/kinetic_proposal.py), [Forseti binding](../../../services/core-control-plane/src/fdai/agents/forseti.py), [계보](../../../services/core-control-plane/src/fdai/core/operational_planning/hypothesis_lineage.py) 및 [승격](../../../services/core-control-plane/src/fdai/delivery/graph_model_promotion.py) | [graph 근거 테스트](../../../services/core-control-plane/tests/delivery/azure/test_graph_dynamic_evidence.py), [종결 테스트](../../../services/core-control-plane/tests/assurance_twin/test_graph_closure.py), [조정 테스트](../../../services/core-control-plane/tests/delivery/test_reconciliation_runtime.py), [서명 맥락 테스트](../../../services/core-control-plane/tests/delivery/azure/test_observation_context.py), [런타임 연결 테스트](../../../services/core-control-plane/tests/runtime/test_observation_evidence.py), [kinetic proposal 테스트](../../../services/core-control-plane/tests/delivery/test_kinetic_proposal.py), [Forseti 테스트](../../../services/core-control-plane/tests/agents/test_decision_case_e2e.py), [계보 테스트](../../../services/core-control-plane/tests/core/operational_planning/test_hypothesis_lineage.py) 및 [승격 테스트](../../../services/core-control-plane/tests/delivery/test_graph_model_promotion.py) |
| 운영 학습 전달 | 릴리스에 고정된 적격 결과 사례, 범위가 제한된 이벤트 버스 후보 게시, 독립 부정 검토, 내용 기반 주소가 지정된 비활성 초안 게시, 검토자 principal을 대소문자 구분 없이 비교한 뒤에야 영속 승격 레지스트리를 승인할 수 있는 검토된 재생 권한 | [적격 결과 및 검토](../../../services/core-control-plane/src/fdai/core/operational_learning/), [O3 검증기 및 게시자](../../../services/core-control-plane/src/fdai/delivery/gitops_pr/), [O3 런타임 연결](../../../services/core-control-plane/src/fdai/runtime/operational_catalog_review.py), [권위 있는 레지스트리](../../../services/core-control-plane/src/fdai/delivery/persistence/state_store_action_promotion.py), [O7 근거](../../../services/core-control-plane/src/fdai/delivery/measurement/operational_promotion_evidence.py) | [통제된 루프 테스트](../../../services/core-control-plane/tests/agents/test_governed_learning_loop.py), [O3 전달 테스트](../../../services/core-control-plane/tests/delivery/test_gitops_catalog_validator.py), [O3 런타임 테스트](../../../services/core-control-plane/tests/runtime/test_operational_catalog_review.py), [O7 근거 테스트](../../../services/core-control-plane/tests/delivery/test_operational_promotion_evidence.py) |
| 자율 규칙 발견 주기 | 범위가 제한된 시간 구간 ID, 관측부터 통합까지의 완전한 보존, 영속 다이제스트를 다시 검증하는 동시 복제본 사이의 종료 상태 전용 재생, 독립 모델 계열 재승인, 권한을 포함한 중첩 후보 필드의 재귀적 거부, 임계값 기반 재정의 감사 수집, 재정의 인식 감사 메트릭, 중복 없는 사람 shadow 검토, 후보가 승격 대상이 되기 전에 정책 위반 탈출을 잊지 않는 범위 제한 dwell 근거 | [발견 주기](../../../services/core-control-plane/src/fdai/core/operational_learning/discovery_cycle.py), [계약](../../../services/core-control-plane/src/fdai/core/operational_learning/discovery_contracts.py), [재정의 신호](../../../services/core-control-plane/src/fdai/core/operational_learning/override_signals.py), [영속 기록](../../../services/core-control-plane/src/fdai/core/operational_learning/discovery_persistence.py), [shadow dwell](../../../services/core-control-plane/src/fdai/core/operational_learning/shadow_dwell.py) | [주기 테스트](../../../services/core-control-plane/tests/core/operational_learning/test_discovery_cycle.py), [재정의 신호 테스트](../../../services/core-control-plane/tests/core/operational_learning/test_override_signals.py), [shadow dwell 테스트](../../../services/core-control-plane/tests/core/operational_learning/test_shadow_dwell.py), [사람 검토 테스트](../../../services/core-control-plane/tests/agents/test_discovery_shadow_review.py) |
| 운영 준비 인계 | 타입이 지정된 소유권 이전 수집, Forseti가 책임지는 읽기 전용 검토, 재생 시 중복을 막는 보고서 전달, 승인 권한과 실행 권한이 없는 근거 기반 shadow 조치 | [준비성 조립](../../../services/core-control-plane/src/fdai/composition/readiness.py), [런타임 소비자](../../../services/core-control-plane/src/fdai/runtime/consumers.py), [작업 연결](../../../services/core-control-plane/src/fdai/runtime/bootstrap_tasks.py) | [런타임 수집 테스트](../../../services/core-control-plane/tests/runtime/test_operational_readiness_ingest.py), [준비성 서비스 테스트](../../../services/core-control-plane/tests/composition/test_readiness_service.py), [조치 테스트](../../../services/core-control-plane/tests/core/readiness/test_remediation.py) |
| Outcome Assurance 변환 결과 계약 | 읽기 전용 타입 범위, 기간, 준비 상태, 귀속, 결과, 가드, 근거 변환 결과와 최신 권위 관측 correction 축소, 해결되지 않은 분모 이벤트를 보존하는 명시적 finalized 이벤트 귀속 및 결정론적 JSON 재현 디코딩 | [outcome_assurance.py](../../../services/core-control-plane/src/fdai/core/measurement/outcome_assurance.py)와 [measurement 패키지](../../../services/core-control-plane/src/fdai/core/measurement/__init__.py) | [Outcome Assurance 테스트](../../../services/core-control-plane/tests/core/measurement/test_outcome_assurance.py) |
| 통제된 기준선 및 처리 코호트 주장 | 비합성 기준선 및 처리 코호트의 결정론적 실패 시 차단 적격 판정. 필수 성공 지표 전체, 임계값 0 가드 전체, 고정 시나리오 집합의 실제 콘텐츠 다이제스트, 표본 30개 하한을 고정한 신뢰 버전 관리 저장소 정책으로 평가하며, 호출자가 제공한 변경 불가능한 40자 또는 64자 16진수 커밋 개정 하나, 갈래별로 서로 다른 보고서와 출처 다이제스트, 절대값을 포함한 신뢰 구간, 완전성과 출처 참조에 연결합니다. 평가 대상 갈래 사실은 모두 정규 해시로 계산하며, 적격 판정에는 그 해시에 결속한 갈래별 승인과 증적 다이제스트 전체에 결속한 코호트 수준 승인이 함께 필요합니다. 두 승인 모두 주입된 신뢰 공급자나 별도로 검증한 증명 묶음에서만 얻으며 산출물에서 얻은 승인은 인정하지 않고, 산출물의 반입 출처 역시 신뢰할 수 있는 반입 채널이 전달하는 평가기 매개변수입니다 | [주장 정책](../../../services/core-control-plane/src/fdai/core/measurement/cohort_claim_policy.py)과 [신뢰 구성](../../../config/sre-cohort-claim-policy.json), [코호트 계약](../../../packages/service-contracts/src/fdai_service_contracts/baseline_cohort.py), [승인 연결](../../../services/core-control-plane/src/fdai/core/measurement/baseline_cohort_claim.py), [증적 가져오기](../../../tools/cohort_receipt.py), [기준선 실행기](../../../tools/baseline_run.py) | [정책 테스트](../../../services/core-control-plane/tests/core/measurement/test_cohort_claim_policy.py), [코호트 계약 테스트](../../../packages/service-contracts/tests/test_baseline_cohort.py), [주장 테스트](../../../services/core-control-plane/tests/core/measurement/test_baseline_cohort_claim.py), [기준선 실행기 테스트](../../../services/core-control-plane/tests/tools/test_baseline_runner.py) |
| 아키텍처 검토 | 매니페스트 준비 상태, 수락된 차단 항목 계약, 공급자 기반 근거 증명, 결정론적 최신성 검사를 위한 주입식 UTC 평가 시계, 독립적으로 기록된 승인을 포함하는 내용 기반 no-execution-authority Decision 증적, 제어 전용 Process 변환 결과, exact 검증 스냅샷 그래프 근거 및 목표 15개 에이전트 검토 루프 | [아키텍처 검토 코어](../../../services/core-control-plane/src/fdai/core/architecture_review/), [변경 평가](../../../services/core-control-plane/src/fdai/core/impact_analysis/change_assessment.py), [소유자 색인](architecture-review-board-ko.md), [온톨로지 에이전트 루프](architecture-review/ontology-agent-loop-ko.md), [근거 권한 계약](architecture-review/evidence-and-authority-ko.md), [전달 계획](architecture-review/delivery-plan-ko.md) | [아키텍처 검토 테스트](../../../services/core-control-plane/tests/core/architecture_review/), [변경 평가 테스트](../../../services/core-control-plane/tests/core/impact_analysis/test_change_assessment.py), [준비 상태 검사기 테스트](../../../tests/integration/scripts/test_check_arb_readiness.py) |
| 운영자 SRE 명령 경로 | 운영자 문제 대응 요청 하나를 단일 correlation 아래에서 Incident 하나와 멱등 타입 ActionProposal 하나에 연결하고 권위 있는 Incident, Trace, Process, Approval 링크를 반환합니다 | [sre_request.py](../../../services/core-control-plane/src/fdai/core/incident/sre_request.py), [operator_request.py](../../../services/core-control-plane/src/fdai/shared/providers/operator_request.py) | [SRE 요청 테스트](../../../services/core-control-plane/tests/core/incident/test_sre_request.py) |
| 에이전트 pantheon | 고정 에이전트 15개와 타입이 지정된 이벤트 런타임 | [에이전트](../../../services/core-control-plane/src/fdai/agents/) | [에이전트 테스트](../../../services/core-control-plane/tests/agents/) |
| 조립 | Exact-release 의미 조회 assembly, request-role 실행기 factory, 짝지은 rubric receipt source/verifier binding 및 호출 범위의 불투명 상관관계를 사용하는 리소스 상태 활동 게시를 포함한 프로바이더/런타임 의존성 주입 | [조립](../../../services/core-control-plane/src/fdai/composition/) | [조립 테스트](../../../services/core-control-plane/tests/composition/) |
| Core 어댑터 | Core에 남은 프로바이더, 영속성, 알림 및 platform 어댑터입니다. T2 캐시 영속성 경계는 최소 권한 데이터베이스 함수를 통해 정확한 카탈로그 파티션, TTL 읽기, 승격 및 롤백 상태, 원자적 로테이션 증적을 소유합니다. 레거시 인벤토리는 `ALTER TABLE ... RENAME TO`를 추적하여 파티션 이름 변경(예: `t2_cache_default`에서 `t2_cache_legacy_default`로)이 소유권 검증 및 스키마 핑거프린팅에서 head 기준 유효 테이블 이름으로 나타나도록 합니다. 공개 웹 결과는 Azure 어댑터가 반환하기 전에 답변 구간을 exact source digest 및 권한 없는 실행 증적에 연결합니다. | [전달](../../../services/core-control-plane/src/fdai/delivery/) 및 [Core 서비스 마이그레이션](../../../service-migrations/branches/core-control-plane/) | [전달 테스트](../../../services/core-control-plane/tests/delivery/), [T2 캐시 영속성 테스트](../../../services/core-control-plane/tests/persistence/test_postgres_t2_cache.py) 및 [서비스 마이그레이션 테스트](../../../tests/integration/services/test_service_migration_inventory.py) |
| 운영 이력 lifecycle Job | Shadow 일정 관리, 범위가 제한된 PostgreSQL partition 근거, 비공개 Blob archive 검증, restore sampling, hold 평가, 저장소 압력 보고, 증적 gate 기반 purge 및 PostgreSQL resource 종속성이 없는 versionless Key Vault secret URI | [operational_history_lifecycle_runner.py](../../../services/core-control-plane/src/fdai/delivery/operational_history_lifecycle_runner.py), [PostgreSQL repository](../../../services/core-control-plane/src/fdai/delivery/persistence/postgres_operational_history_lifecycle_runner.py) 및 [독립 target Terraform Job](../../../infra/operational_history_lifecycle_job.tf) | [runner 검사](../../../services/core-control-plane/tests/delivery/test_operational_history_lifecycle_runner.py) 및 [인프라 계약](../../../tests/integration/infra/test_operational_history_lifecycle_job.py) |
| Rule 카탈로그 프로파일 바인딩 | 관리되는 `FDAI_PROFILE_ID`를 시작 시 한 번 해석해 T0 색인과 워크플로 guard 검증이 함께 읽는 불변 Rule 튜플로 만들고, 선택과 등급 조정을 차단 기본으로 처리하며, 테넌트 값이 없는 시작 진단을 남깁니다 | [rule_profile.py](../../../services/core-control-plane/src/fdai/runtime/rule_profile.py) | [Rule 프로파일 테스트](../../../services/core-control-plane/tests/runtime/test_rule_profile.py) |
| 런타임 | 불변 시작 계획, 타입이 지정된 active-runtime 조립, 지속형 operating-model 구독, ControlLoop가 ontology store를 노출한 뒤 연결되는 effect reconciliation, 집중된 메시징, Incident, 의미, 리소스 소유권 및 작업 hook 경계, 명시적 종료 순서, process-critical 상태 및 감사 쓰기와 authority-critical 전체 체인 증명을 분리하는 준비 상태, 작업 감독을 포함하는 Core 프로세스 수명 주기 | [런타임](../../../services/core-control-plane/src/fdai/runtime/), [bootstrap_plan.py](../../../services/core-control-plane/src/fdai/runtime/bootstrap_plan.py), [bootstrap_core.py](../../../services/core-control-plane/src/fdai/runtime/bootstrap_core.py), [bootstrap_resources.py](../../../services/core-control-plane/src/fdai/runtime/bootstrap_resources.py), [bootstrap_messaging.py](../../../services/core-control-plane/src/fdai/runtime/bootstrap_messaging.py), [bootstrap_incidents.py](../../../services/core-control-plane/src/fdai/runtime/bootstrap_incidents.py), [bootstrap_semantics.py](../../../services/core-control-plane/src/fdai/runtime/bootstrap_semantics.py) 및 [bootstrap_task_hooks.py](../../../services/core-control-plane/src/fdai/runtime/bootstrap_task_hooks.py) | [런타임 테스트](../../../services/core-control-plane/tests/runtime/), [부팅 계획 테스트](../../../services/core-control-plane/tests/runtime/test_bootstrap_plan.py), [메시징 테스트](../../../services/core-control-plane/tests/runtime/test_bootstrap_messaging.py), [Incident 테스트](../../../services/core-control-plane/tests/runtime/test_bootstrap_incidents.py) 및 [종료 테스트](../../../services/core-control-plane/tests/runtime/test_bootstrap_shutdown.py) |
| Core 계약과 프로바이더 경계 | Core 전용 타입, 프로바이더 프로토콜, 구성, 스트리밍 및 텔레메트리 | [shared](../../../services/core-control-plane/src/fdai/shared/) | [shared 테스트](../../../services/core-control-plane/tests/shared/) |
| Rule 카탈로그 파이프라인 | 카탈로그 스키마 로딩, 대소문자를 정규화한 관리 범위, 유한한 매개 변수 완화 범위, 검토된 기준선 제어 집합 해석, 수집, 내용 기반 주소가 지정된 스냅샷 미러링, 멱등 초안 검토 게시, 검증, 정제 및 승격 지원 | [rule_catalog](../../../services/core-control-plane/src/fdai/rule_catalog/) 및 [수집 전달](../../../services/core-control-plane/src/fdai/delivery/rule_catalog_delivery.py) | [Rule 카탈로그 테스트](../../../services/core-control-plane/tests/rule_catalog/) 및 [수집 전달 테스트](../../../services/core-control-plane/tests/delivery/test_rule_catalog_delivery.py) |
| 검토된 Property 의미 커버리지 | 룰이 평가하는 참조 대비 검토된 Property 의미의 측정 커버리지, 선언된 프로바이더 경로의 근거 규칙, 회귀 방지 하한, 결정론적 우선순위 백로그 | [check-property-semantic-coverage.py](../../../scripts/quality/architecture/check-property-semantic-coverage.py) 및 [property-semantics.yaml](../../../rule-catalog/vocabulary/property-semantics.yaml) | [커버리지 게이트 테스트](../../../tests/integration/scripts/test_property_semantic_coverage.py) |
| Core 서비스 항목 지점 | Core 분포 시작과 서비스 조립 | [fdai_core_service](../../../services/core-control-plane/src/fdai_core_service/) | [Core 패키지 테스트](../../../services/core-control-plane/tests/) |

Inventory 관계 수렴은 지속형 운영 인스턴스 그래프가 소유합니다. 검토된 provider parent가 일반
containment를 shadow하고 snapshot 및 ontology store가 cardinality를 강제하며 inventory
ontology projector는 graph 교체와 정확한 세대의 매니페스트 및 상태 마커를 하나의 PostgreSQL
트랜잭션으로 커밋합니다. 판테온 적용 모드는 고정된 에이전트 역할 분리를 유지하면서 해결된
자율성 상한, 권한이 있고 만료되는 승인, Saga 소유의 실행 전 receipt, 안정적인 멱등성 예약,
소유자가 fencing된 리소스 claim, 분산 리소스 lock을 Thor의 실행기 호출 전에 결합합니다.
재시작 시 모호한 실행은 명시적인 조정 또는 rollback 전까지 `execution_unknown`으로 유지됩니다.
Resource
ObjectSet receipt는 결과가 0개인 read를 포함해 source generation 및 completeness를 query
truncation과 독립적으로 보존합니다.
관계 traversal은 root_object_types 필터 없이 root_ids를 전달하여 상위 entity-resolution
노드가 resolve한 교차 유형 루트가 저장소에 도달하고, `_filter_graph`가 이후 대상 selector
유형으로 결과를 좁힙니다.
Principal 범위 운영 근거 읽기는 기존의 범위가 제한된 응답을 통해 증적으로 검증된 Context
메타데이터를 연결하며 변경 또는 실행 권한을 추가하지 않습니다.
Detection 변환 결과도 출처에서 파생된 Forecast 및 Pattern 객체만 노출하며 보류된 관계는
카탈로그를 복원하기 전에 정확한 엔드포인트 신원을 요구합니다.
해당 영속화 메서드는 기존 온톨로지 인스턴스 저장소 경계에서 멱등성을 유지합니다.
분석기 실행은 명시적인 장소에서 버스 보안을 선택하고 배포된 5분 tick 상한을 로컬 루프와
단일 실행에 동일하게 적용합니다.
프로바이더 중립 관측 판정은 서로 다른 프로바이더가 동일하게 보고한 속성만 보존하고 승자를
선택하지 않은 채 모든 경합 필드를 기록합니다.
독립 프로바이더 비교는 범위가 제한된 정확한 대상 세대의 모든 정규 프로바이더에 주입된
검증기를 요구합니다.
Context 읽기는 인증된 principal 범위 증적을 연결하고 Forecast 및 Pattern 생산자는 원자적
영속화와 인증된 생산자 증명을 사용합니다.
보안 쿼리 증적 검증은 표지만 바꾼 다이제스트를 신뢰하지 않고 다이제스트에 포함된 전체 발급
증적에서 완전성을 다시 파생합니다.
Context 근거 읽기는 범위가 제한된 근거 묶음을 만들기 전에 응답 묶음 바이트를 예약합니다.
Direction-shadow 승격은 비교 양쪽이 정확한 release 신원을 고정하지 않으면 제안 전용 상태를
벗어날 수 없습니다.
Direct API 승격 어댑터는 변경이 발생하지 않은 재시도 가능 실패를 보고할 수 있습니다. 실행기는
안정적인 재시도 기회를 소비하지 않고 실패한 최종 시도를 기록합니다.
운영 Context 응답은 정확한 읽기 요청에 다시 연결되며 토폴로지 재생은 완전한 근거를 보고하기
전에 정규 출처 증적 다이제스트를 요구합니다.
Context 스냅샷은 요청의 카탈로그 리비전과도 일치해야 하며 응답 바이트 예산은 반환되는 묶음
신원 필드를 포함합니다.
각 근거 경로의 출처 참조는 동일한 보안 객체의 속성에서 독립적으로 다시 계산한 값과 정확히
일치해야 하므로 연결되지 않았거나 위조된 출처 참조는 projection 전에 차단됩니다.
같은 변환은 독립적으로 검증된 `runtime_calls` edge를 양방향으로 보존하며 서비스 간 상호 호출을
방향 충돌로 취급하지 않습니다.
Context 변환 결과는 증적 발급을 인증하고, 출처 세대와 검증 계보를 포함한 전체 링크 관측
메타데이터를 비교하며, 번들과 메타데이터를 하나의 바이트 예산으로 제한합니다.

Bounded ARM compute overlay는 검토된 parent 및 attachment mapping을 통해 VMSS VM과 NIC child
collection을 소유합니다. Console instance presentation은 role assignment를 생략하고 선택한
non-scope root의 immediate Resource Group 하나만 유지하며 provider relationship을 추가하지 않고
evidence-backed AKS managed group, VMSS, VM, NIC hierarchy를 렌더링합니다.

Safety-core 커버리지 하한은 Core 패키지 안의 결정론적 계층과 risk 게이트에 적용됩니다. 해당
테스트는 Core 소유 테스트 트리에 유지합니다.

온톨로지 조회 실행은 런타임에서 exact release, 매니페스트, 역할 및 용도를 다시 검사합니다.
범위가 제한된 의존성 wave는 노드 기한에 큐 wait를 포함하고 in-flight 취소를 전파하며
차단된 descendant를 건너뜁니다. 안정적인 핸들러 타입, 값 및 런타임 실패는
`capability_failed`로 유지됩니다. 구조화된 진단에는 `node_kind`와 `failure_type`만 허용하며,
예외 본문, 인자, 노드 식별자, 프로바이더 페이로드 또는 운영자 데이터는 포함하지 않습니다.
조립은 범위가 제한된 secured ObjectSet 증적을 발급하고 source-derived 네트워크 및 Pod
텔레메트리 함수를 exact release에 등록합니다. 함수 dependency는 발급된 content 다이제스트만
해석합니다. Exact-id ObjectSet은 고정된 indexed batch를 사용하며 result 상한을 판단할 수 있으면
중단합니다. `catalog.search_rules` 함수는 해당 exact release와 프로바이더 중립적이고 범위가
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
제안 두 개를 만듭니다. 조립은 해석된 narrator 또는 `t1.judge` 후보를 T1 플래너로 연결하고
`t2.reasoner.primary` 후보는 별도의 선택적 escalation 어댑터에 유지합니다. Core는 T1 제안을
사용할 수 없거나 결정론적 스키마, 매니페스트, 구성 또는 계획 검증을 통과하지 못한 경우에만 T2를
호출합니다. 각 제안은 기본 90초 예산을 가지며, 범위가 제한된 `Retry-After` 지연이 이 예산 안에
들어올 때 제한된 후보 하나를 최대 한 번 재시도합니다. 조립은 권위 있는 프로바이더가 연결된
핸들러만 노출합니다. 스키마로 검증된 `cause` facet은 후보 primary intent가
`query.resource_current_state`여도 current-state 빠른 경로가 구조화된 인과 계획을 대체하지
못하게 합니다. 누락된 exact-Resource slowness 조사는 부정되지 않고 대상 identifier 밖에 있는
검토된 인과, 증상, 시작 span, 경쟁 change event 부재, 정확한 manifest path, 등록된 metric
concept로만 완성합니다. Dependency-latency와 traffic-load 근거는 모두 검증된 relationship path를
사용하며 불완전한 입력은 판단 보류 상태로 유지합니다. 누락된 outer `Resource` type은 충돌하는
canonical type 없이 frame target과 정확히 일치하는 스키마 검증 `resource` target 하나에서만
복원합니다. 입력 없는 recovery 진단은 고정된 실패
precondition 이름과 개수만 기록하며 운영자 text, target 값, source-span text, model payload 또는
provider data를 남기지 않습니다. 부분 causal hold는 검증된 각 hypothesis ID를 `unresolved`로
표시하며 실행하지 않은 evidence를 supported 또는 refuted conclusion으로 승격하지 않습니다.
Metric comparison이 완료되면 같은 hold가 측정 변화를 보존하고 합성된 unresolved hypothesis
요약에는 evidence를 연결하지 않습니다. 공개
프레임 제안은 Core가 서버 소유 다이제스트를 다시 만들기 전에 shared wire 식별자 제약을
적용합니다. 구조화된 진단은 계획 단계, 후보 인덱스, 실패 클래스 및 입력을 포함하지 않는
검증 위치만 기록하며 운영자 텍스트와 프로바이더 상세는 제외합니다. 공개
조립 파사드는 Azure 전용 모델 및 카탈로그 연결을 `semantic_query_azure_composition.py`에 위임하면서
강제 적용되는 800줄 한도 아래를 유지합니다. 모듈 계약은 패키지 배치 게이트가 강제하는
`composition`, `seam` 및 `container` 기준점을 보존합니다. 검증된 `llm.mode` 문자열은 다른 LLM
연결기와 동일하게 값 비교로 Azure 의미 조립을 선택합니다.
ObjectSet 핸들러는 각 요청 역할에 맞게 다시 만들어지므로 읽기 담당이 Owner 가시성을 상속하지 않고
Owner도 읽기 담당으로 조용히 축소되지 않습니다. 모델, release, 저장소 또는 전송 계층 선행 조건이 없으면
암시적 `runtime=None` 대신 명시적 startup-readiness 실패로 유지됩니다.
Continuous 커버리지 증적은 결정론적 고정본 structural 검증과 운영 준비 상태를
분리합니다. 외부에서 생성된 `cross_service_e2e` 또는 `live_assurance` 질문 증적만
`production_ready`를 설정할 수 있으며 committed `deterministic_fixture`는 false로 유지합니다.
운영 커버리지 증적은 다이제스트 계산 전에 근거, 평가 및 최신성 시각을 UTC로 정규화하므로
서비스 표준 시간대가 달라도 같은 절대 시각은 하나의 재생 신원을 유지합니다.
Azure Monitor 경보 정규화도 Event 및 멱등성 신원을 만들기 전에 같은 UTC 규칙을 적용하므로
오프셋 표현만 다른 프로바이더 재시도가 중복 인시던트 신호가 되지 않습니다.
Azure 구성은 메트릭 프로바이더가 연결된 경우에만 검토된 `azure-monitor` 실제 영향 탐색
매니페스트를 컴파일합니다. 컨트롤 루프는 실행 권한을 평가하기 전에 작업 대상을 측정하고 기록된
관찰을 기존 상한에 전달합니다. 어댑터는 스키마 최대값 안에서 매니페스트 시간 제한을 적용하며,
근거가 누락되거나 시간 초과, 실패, 활성 또는 과부하 상태이면 권한을 낮출 수만 있습니다. 감사
기록은 Azure를 다시 조회하지 않고 재생할 수 있도록 정제된 사유와 스칼라 메트릭을 보존합니다.
Knowledge 검색은 pgvector 경계에서 유한하지 않은 임베딩을 차단하고 메모리 참조 구현에서는
유한하지 않은 유사도를 0으로 처리하여 잘못된 모델 출력에서도 결정적 순위를 유지합니다.
대화 사전 검사는 social narration 전에 직접 응답 profile의 범위를 확인하며, 너무 큰 입력은
운영 맥락을 노출하거나 모델을 호출하지 않고 보류합니다.
런타임 초기화는 의미 준비 상태와 버티컬 workload-identity construction을 기존 수명 주기 및
연결 보조 로직에 위임하여 기본 조립 루트를 검토된 fanout 상한 아래로 유지합니다. Thin
초기화 래퍼는 injected identity-builder 테스트 및 포크 경계를 보존합니다.
운영 가설 루프는 service 또는 agent를 추가하지 않습니다. 완전한 graph prerequisite는
composition에서 연결됩니다. 일반 실행은 일치하는 기존 exact V2 plan에서만 effect-reconciliation
request를 생성하고 broker 발행 전에 영속 outbox에 commit합니다. 누락된 observation 또는 발행
failure는 held 또는 pending evidence로 남으며 executor outcome을 다시 쓰지 않습니다. Model pointer
변경은 기존 governance ActionType, risk, Owner 승인, Thor execution, rollback 및 Saga audit 경로
안에 유지됩니다.
[계보 producer](../../../services/core-control-plane/src/fdai/core/operational_planning/hypothesis_lineage.py)와
[컨트롤 루프 sink](../../../services/core-control-plane/src/fdai/core/control_loop/_execution.py)는
권위 있는 계획 기록, 완료된 실행기 결과, 일치하는 독립적이고 채점 가능한 관측이 모두 있을
때만 단일 효과 episode 하나를 제출합니다. 변환 결과 기록 실패는 실행기 결과를 변경하지 않으며,
이 producer는 누락된 결과를 날조하는 대신 복수 효과를 거부합니다. focused 계보 및 컨트롤 루프
shadow 테스트가 두 경계를 고정합니다.

수직 영역 간 중재는 권고 표기가 아니라 목표 효과를 읽습니다.
[의사결정 사례 도메인](../../../services/core-control-plane/src/fdai/core/decision_case/domain.py)은
한 영역이 산출한 ActionType, 부호가 있는 목표 효과, 그리고 두 값을 읽어 온 표준 계보를
전달하는 고정 `DomainOptionEvidence` 계약과, 두 영역이 동일한 통제 목표에서 서로 반대
부호의 효용을 가질 때만 충돌을 보고하는 순수 관계 `conflicting_objective_effects`를
소유합니다.
[Forseti 수용 지점](../../../services/core-control-plane/src/fdai/agents/_framework/forseti_decision_helpers.py)은
이 근거를 한정된 엄격 파서로 수용하고 계보가 합성 전문가 표식뿐인 페이로드를 거부하므로,
의사결정 사례와 종결 판정에 도달하는 선택지 참조는 기여한 재생이 실제로 산출한 값입니다.
가용성 이음매는 실행 상태 점검이 소유합니다.
[`runtime_health`](../../../services/core-control-plane/src/fdai/agents/_framework/runtime_health.py)가
도달 불가 에이전트 집합을 한 번만 도출해 구성 시점에 탐침으로 결속하므로, Forseti는 프레임워크에
에이전트를 들여오지 않고도 소유자가 응답할 수 없는 중재를 종결 HIL 판정으로 닫습니다.

## 독립 서비스 지도

| 서비스 | 패키지 responsibility | 패키지 지도 |
|---------|------------------------|-------------|
| 환경 모델 바인딩 | 권한이 없는 공유 정책 계약, 정확한 제안-정책 결합, 3-way-CAS Settings projection, 고유한 기능 신원, 정확한 GA 및 TPM/PTU 해석, 범위가 제한된 공급자 읽기, Core 전용 attested runtime binding, healthy active-revision CAS, 정책 결속 exact 적용 및 독립 공급자 readback | [공유 계약](../../../packages/service-contracts/src/fdai_service_contracts/model_binding.py), [해석기 스키마](../../../services/core-control-plane/src/fdai/rule_catalog/schema/model_binding_policy.py), [제안 검증기](../../../scripts/deployment/azure/model_binding_proposal.py), [projection workflow](../../../.github/workflows/model-settings-projection.yml), [projection materializer](../../../scripts/deployment/local/materialize-authoritative-settings.py), [service guard](../../../scripts/deployment/service/guard_plan.py), [계획 검증기](../../../scripts/deployment/azure/verify-deployment-plan.py), [active revision 검증기](../../../scripts/deployment/azure/verify_active_core_revision.py), [공급자 readback](../../../scripts/deployment/azure/verify_model_deployments.py), [Operator IAM 어댑터](../../../services/operator-service/src/fdai_operator_service/postgres_iam.py), [Console 편집기](../../../console/src/routes/settings-model-binding-policy.tsx) |
| Operator 서비스 | 인증된 경로 계열, 범위가 제한된 인증 모듈을 통한 loopback 전용 로컬 Azure CLI 세션 초기화, 영속 의미 브리지, 정규화된 직접 Psycopg 연결, 정확한 릴리스 읽기, 소유자 범위 백그라운드 작업, 실행 권한이 없는 principal 범위 Process 상태 및 원자적 전환 제안 수락 | [인증 경계](../../../services/operator-service/src/fdai_operator_service/auth.py), [로컬 인증](../../../services/operator-service/src/fdai_operator_service/local_auth.py), [DSN 정규화](../../../services/operator-service/src/fdai_operator_service/postgres_dsn.py), [운영 경로 계열](../../../services/operator-service/src/fdai_operator_service/families/operations/), [워크플로 계열](../../../services/operator-service/src/fdai_operator_service/families/workflow/), [Process 변환 결과](../../../services/operator-service/src/fdai_operator_service/process_transition_projection.py), [승인 변환 결과](../../../services/operator-service/src/fdai_operator_service/process_approval_projection.py), [재시도 수락](../../../services/operator-service/src/fdai_operator_service/process_retry_admission.py), [백그라운드 작업 변환 결과](../../../services/operator-service/src/fdai_operator_service/families/conversation/background_tasks.py), [런타임 변환 결과 읽기 구성요소](../../../services/operator-service/src/fdai_operator_service/runtime_projection_reader.py), [PostgreSQL 계열 저장소](../../../services/operator-service/src/fdai_operator_service/postgres_family_store.py), [어댑터](../../../services/operator-service/src/fdai_operator_service/adapters/), [스트리밍](../../../services/operator-service/src/fdai_operator_service/streaming/) 및 [composition.py](../../../services/operator-service/src/fdai_operator_service/composition.py) |
| FDAI Console 백그라운드 작업 점검 | 엄격한 소유자 범위 작업/진행 상황 decoder, 이중 언어 목록 및 선택 상세 표현, 생성, 취소, 재시도 또는 실행 컨트롤이 없는 명시적 새로 고침 | [경로](../../../console/src/routes/background-tasks.tsx), [decoder](../../../console/src/routes/background-tasks.model.ts), [decoder 테스트](../../../console/src/routes/background-tasks.model.test.ts) |
| FDAI Console Process 컨트롤 | 엄격한 principal 범위 Process 및 전환 디코더, 현지화된 현재 단계 요구 사항, 리비전 결속 재개/취소/재시도 요청, 명시적인 성공 아님 수락 | [컨트롤 디코더](../../../console/src/routes/processes.control.ts), [컨트롤 패널](../../../console/src/routes/process-control-panel.tsx), [요청 클라이언트](../../../console/src/routes/processes.transitions.ts), [브라우저 계약](../../../console/tests/e2e/workflow-process-transitions.spec.ts) |
| FDAI Console 온톨로지 워크벤치 | Exact 선언 경로, 엄격한 변환 결과 decoder, 근거/종속 항목/release 구역, localized 검증 상태 및 실행 control이 없는 스냅샷 결속 영향/map 표현 | [ObjectType 워크벤치](../../../console/src/routes/ontology-object-type-detail.tsx), [영향 경로](../../../console/src/routes/blast-radius.tsx), [영향 decoder](../../../console/src/routes/blast-radius.model.ts), [온톨로지 계약](../../../console/src/routes/ontology.types.ts) |
| FDAI Console 지역화 카탈로그 | 공유 셸, 인시던트 및 알림 레이블은 기본 이중 언어 카탈로그에 둡니다. 경로별 Teams 통합 및 선택적 Cost Governance 레이블은 지연 로드되는 경로 카탈로그에 유지하므로 전문 지침이 진입 번들 예산을 사용하거나 패키지를 활성화하지 않습니다. 기본 카탈로그를 변경하면 question bank 다이제스트를 다시 생성합니다. | [기본 영어 카탈로그](../../../console/src/i18n/messages.en.json), [기본 한국어 카탈로그](../../../console/src/i18n/messages.ko.json), [경로 카탈로그](../../../console/src/routes/i18n/) |
| FDAI Console 경로 로드 | 이름이 지정된 경로 내보내기는 하나의 형식 안전 지연 로드 어댑터를 사용하고, 공유 경로 모듈은 하나의 로더를 재사용합니다. 진입 번들 검사는 필요한 지연 로드 경계를 확인하고 경로 격리를 약화하지 않으면서 원시 크기와 gzip 예산을 모두 적용합니다. | [패널 레지스트리](../../../console/src/panels.tsx), [진입 번들 검사](../../../console/scripts/check-entry-bundle.mjs) |
| FDAI Console Dashboard v2 | 별도 리소스 중심 `/dashboard-v2` 경로, 표시량이 제한된 허니콤, 하나의 활성 미리 보기, 유형 자동완성, 인벤토리 조회 결과 디코딩을 제공합니다. 기존 대시보드와 Cost Governance 경로는 유지합니다. 실제 콘솔 화면 구현은 완료했으며 인벤토리 전체 조회 계약과 인증된 런타임 검증은 별도로 남아 있습니다. | [경로](../../../console/src/routes/dashboard-v2.tsx), [디코더](../../../console/src/routes/dashboard-v2.model.ts), [브라우저 검사](../../../console/tests/e2e/dashboard-v2.spec.ts), [적용 기록](../../roadmap-implementation/interfaces/console-operations.md) |
| 네트워크 토폴로지 시각화 | 공유 네트워크 어휘, 작성된 정적 다이어그램 계약, 관측 전용 Console 포커스 및 경로 표현, 실행 권한이 없는 정제된 내보내기 | [공유 어휘](../../../packages/network-topology-contracts/), [다이어그램 컴파일러](../../../tools/architecture-diagrams/), [Console 아키텍처 컴포넌트](../../../console/src/components/), [소유 설계](../interfaces/network-topology-visualization-ko.md) |
| 문서 인제스트 API | 업로드 접수, API 소유 전이, 통제된 미리 보기 권한 확인, 펜스가 적용된 커넥터 상태 | [패키지](../../../services/document-ingestion-api/src/fdai_ingestion_api_service/) |
| 문서 처리 워커 | 영속 문서 처리, 프로세스로 격리된 한국어 및 영어 OCR, 다시 시작해도 안전한 보호 철회 정리 | [패키지](../../../services/document-processing-worker/src/fdai_document_worker_service/), [로컬 OCR](../../../services/document-processing-worker/src/fdai_document_worker_service/adapters/local_ocr.py), [공급자 정책 계약](../../../packages/service-contracts/src/fdai_service_contracts/document_ocr.py) |
| Isolated 실행기 | Thor 소유 명령 처리, 프로바이더 효과, 증적 및 실행기 어댑터 | [패키지](../../../services/isolated-executor/src/fdai_executor_service/) |

이 패키지는 `fdai-service-contracts`에만 의존하며 다른 서비스 구현은 가져오지 않습니다.
로컬 조립은 서비스 소유 클라이언트 수명 주기와 loopback 어댑터를 연결합니다. 따라서 Operator 의미
브리지, 인제스트 게시자, 문서 워커 consumer 및 Isolated 실행기는 배포된 어댑터와 동일한 logical
topic, 멱등성, 준비 상태 및 증적 경계를 보존합니다.
Operator IAM 조립은 집중된
[`iam_composition.py`](../../../services/operator-service/src/fdai_operator_service/iam_composition.py)
경계 뒤에 둡니다. 따라서 채널 검증, 영속 HIL 전달 및 데이터베이스 어댑터가 최상위 서비스 조립의
의존성 fanout을 넓히지 않습니다.
문서 워커는 신뢰할 수 없는 압축 해제가 장기 실행 서비스를 종료하지 못하도록 native PDF를
리소스 상한이 있는 별도 프로세스에서 구문 분석합니다.
양방향 IPC는 하나의 단조 기한 아래 범위가 제한된 데몬 스레드에서 실행되며 상위 프로세스는
텍스트를 수락하기 전에 반환된 페이지 및 문자 상한을 다시 검증합니다.

## Shared 계약 SDK

[fdai_service_contracts](../../../packages/service-contracts/src/fdai_service_contracts/)는 프로세스가
공유하는 versioned wire 서술자, codec, 호환성 검사, 준비 상태 기록, 문서 계약,
운영자 계약 및 실행기 계약을 소유합니다. 서비스 조립, 프로바이더 구현,
데이터베이스 접근 또는 business 작업 흐름은 포함하지 않습니다.
`IncidentPageProjection`은 일반 `PageProjection` wire 형태를 안정적으로 유지하면서 Incident
roster page와 같은 스냅샷의 결과 metric을 하나의 읽기 전용 Operator 계약으로 연결합니다.
선택적 `incident_number`는 현재 UTC 월을 기준으로 할당되는 표시 전용 참조이며, 정규 Incident와
correlation 신원은 변경되지 않습니다.

Shared SDK는 Core/Operator 경계에서 사용하는 no-authority ontology-query 기록도 소유합니다.
의미 problem 프레임, 범위가 제한된 조회 DAG, 의도 그래프, 작업 증적 및 structural 커버리지 증적입니다.
프로바이더 클라이언트, 온톨로지 저장소, 플래너 모델 또는 실행 핸들러는 포함하지 않습니다.

대화형 대화 계획은 기능을 선택하기 전에 스키마로 검증된 의미 판단을 한 번 사용합니다. 이 판단이
principal 범위 매니페스트에 있는 컬렉션 범위 Resource 상태, Resource Health 또는 Service Health
함수를 모호하지 않은 의미로 수락하면 Core는 두 번째 프레임 모델 요청을 보내지 않고 프레임을 결정론적으로
만들고 검증합니다. Operator bridge는 변환 결과를 수락하기 전에 계속 요청을 영속화합니다. 요청 누락은
범위가 제한된 가시성 경합으로 재시도할 수 있지만 영구적인 변환 결과 신원 충돌은 consumer group을
반복해서 재조정하지 않고 한 번 격리합니다. 모델 시간에는 완료된 의미 판단, 프레임, 계획 호출을 모두
포함하며 전체 턴 시간은 더 넓은 지연 시간 권위로 유지합니다.
함수 의존성은 결정 권한과 표현 권한을 분리합니다. 결정에 사용하려면 독립적인 근거 승인이 필요하며,
`Bragi`의 `operations-review` 읽기는 역할, 목적, release, 증적 및 구체화가 일치하는 정확한
프로세스 발급 ObjectSet만 재사용할 수 있습니다.
또한 Core에서 Operator 화면으로 범위가 제한된 인벤토리 검사, 온톨로지 변환 및 현재 상태 읽기 근거를
전달하는 버전이 지정된 no-authority 운영 활동 기록을 소유합니다. 이 기록은 논리적 에이전트 소유권과
생산 프로세스를 분리하고 `execution_authority=false`를 고정합니다.

기존 Operator/Core 묶음의 버전 1.2는 범위가 제한된 semantic-turn 요청 하나와 근거에 묶인 최종
결과 하나를 추가합니다. 요청은 인증된 역할, 세션 정렬, 용도, 기한 및 멱등성을
pin합니다. Answered 결과에는 exact release, 매니페스트, 계획, 실행 증적 및 근거 참조가
필요합니다. SDK는 해당 필드를 폐기하는 대신 의미 downgrade to N-1을 거부합니다. 런타임
게시와 consumption은 service-owned 구현으로 유지되며, Operator bridge는 서로 다른 최종
projection topic과 progress topic을 감독합니다.

Operator continuation 조회는 `request_id`로 결합하기 전에 결과 후보를 정확한 세션으로,
요청 후보를 정확한 outbox namespace와 principal로 제한하여 materialize합니다. 범위가 제한된
후보 집합은 lineage 검사를 유지하면서 PostgreSQL 조인이 관련 없는 `state_kv` 행으로 확장되지
않게 합니다.

Semantic-turn 요청은 opaque server-issued token과 함께 타입이 지정된 화면 또는 리소스 그룹
선택을 보존합니다. Operator는 Core가 `query.contextual_resources`를 위해 정확한
`Resource.id` 범위를 컴파일하기 전에 인증된 principal, 일반 소문자 role 범위, purpose,
정확한 release, source generation, completeness 및 id 집합에 대해 token을 조회하고 선택
다이제스트를 다시 계산합니다.
클라이언트가 위조하거나 다시 계산한 id, 재시작 후 사라진 token 또는 범위 불일치는 principal
컬렉션으로 대체하지 않고 타입이 지정된 사용 불가 결과가 됩니다. 어떤 context 필드도 승인
또는 실행 권한을 부여하지 않습니다.
명시적 발화 조건식은 token의 집합과 교집합하며, 불완전한 object-only contextual 표는
answered claim이 되지 않고 semantic turn을 hold합니다.
이 hold는 contextual resource plan에만 적용합니다. 범위가 제한된 다른 query table은 명시적
잘림 상태와 함께 계속 반환됩니다.
Operator instance projection은 인증된 principal과 활성 generation에서 token을 발급하며,
잘린 projection은 신원을 완전히 생략합니다.
Contextual FunctionType은 불투명한 선택 token을 스칼라 스키마 입력으로 전달하고 객체 값인
조회 결과는 의존성 전용으로 유지합니다. 따라서 연결되지 않은 model node는 specialized
read를 호출할 수 없습니다.
공유 범위 digest는 소문자 일반 역할(`reader`, `contributor`, `approver`, `owner`)만 사용하고
`BreakGlass`는 거부합니다. 정확한 id 조건식은 최대 128개씩 batch로 조회하고, 이러한 객체
전용 읽기에서는 관계 구체화와 관계 완전성 검사를 생략합니다.
Wire 계약은 보수적인 512개 id context envelope를 허용하고
일반 ObjectSet과 store 상한은 1,000개로 유지합니다.
Context 계약은 incident, screen 및 resource-group 신원을 혼합하는 입력을 거부하며, 정확한
선택 읽기는 source-generation receipt를 보존합니다.
같은 512개 상한을 Operator/Core schema가 함께 적용하므로 과도한 client context는
planning에 들어갈 수 없습니다.
범위가 제한된 semantic query JSON envelope는 512개 id 선택에 맞게 크기를 확보하면서도
일반 output의 기존 행 및 byte 상한은 제거하지 않습니다.

SDK는 두 semantic channel이 하나의 physical Event Hub를 공유할 때 사용하는 logical-topic marker와
결정론적 consumer-group 파생 규칙도 소유합니다. Core와 Operator는 서로 다른 adapter, codec,
identity, logical topic 및 offset group을 유지하며 상대 서비스 구현을 가져오지 않습니다. 같은 계약은
targeted Terraform 상태가 새 output을 아직 materialize하지 않았을 때 사용하는 canonical physical-topic
기본값도 제공합니다.

SDK는 `notification-delivery-receipt` wire 스키마와 canonical 논리 토픽도 소유합니다.
Operator는 기존 multiplex 물리 토픽을 통해 관찰을 인증하고 게시하며, Core만 이미 수락된 전달에
관찰을 적용합니다. 이 계약은 알림 대상이나 실행 권한을 부여하지 않습니다.

SDK는 WARA shadow 평가 토픽과 Operator 소비자 그룹 ID도 소유합니다. Core는 권한이 없는 평가
결과를 이 토픽으로 발행하고 독립 Operator 서비스는 활성 컨트롤 전체가 정확히 포함됐는지 검증한
뒤 읽기 변환 결과를 교체합니다. 공유 계약에는 wire ID만 있으며 어느 서비스에도 공급자 읽기 또는
실행 권한을 부여하지 않습니다.

또한 SDK는 실행 장소 계약을 소유합니다. `FDAI_EXECUTION_VENUE`를 해석하는 유일한 resolver와
장소가 선택하는 기능 플래그 표 하나입니다. 모든 프로세스가 같은 변수를 해석하고 독립 서비스는
core 컨트롤 플레인을 import할 수 없으므로 특정 서비스가 아니라 여기에 둡니다.
`fdai/runtime/venue.py`는 이를 다시 내보내기만 하고 자체 바인딩을 선언하지 않습니다.

서비스 분포 5개는 deployable `0.1.2` 이미지를 N-1, `0.1.3`을 N으로 사용합니다. 기존 contract-set
`1.0.0`/`1.1.0` 매트릭스는 프로세스 간 호환성 경계로 유지합니다.
내용 기반 주소를 가진 실제 운영 근거는 exact 서비스와 관측 종류도 연결하고 `observed=true`를
요구합니다. 다이제스트를 다시 계산해도 관측하지 않은 점유는 실제 운영 증적이 될 수 없습니다.

패키지 테스트 트리는 SDK 행동을 검증합니다. 서비스 간 N/N-1 및 토폴로지 검사는
[루트 통합 테스트](../../../tests/integration/)에 유지합니다.
배포 가능한 서비스 이미지는 고정된 Alpine Python, OpenSSL 및 SQLite baseline을 공유합니다.
문서 worker는 자신이 소유한 Tesseract 언어 데이터와 OCR runtime 의존성만 추가합니다.

## 기타 저장소 소유자

| 경로 | Responsibility |
|------|----------------|
| [evaluation-sdk/](../../../evaluation-sdk/) | 패키지 범위 CI로 보존하는 휴면 독립 evaluation 계약과 실행기입니다. |
| [benchmarks/](../../../benchmarks/) | 휴면 외부 실행 장치 driver 패키지와 명시적 독립 CyberGym shadow 실행기입니다. |
| [eval/golden-dataset/](../../../eval/golden-dataset/) | 로캘 중립 온톨로지 탐색 및 답변 oracle을 갖춘 이중 언어 cloud-operations 의미 질문입니다. 생성된 question-bank 아티팩트는 10개의 소스 파일에 대해 콘텐츠 주소로 지정됩니다. |
| [services/core-control-plane/src/fdai/delivery/golden_question_dataset.py](../../../services/core-control-plane/src/fdai/delivery/golden_question_dataset.py) | 저장소 golden dataset의 범위가 제한된 loader와 결정론적 typed-observation adapter입니다. Semantic 축이 누락되면 release evidence 전에 인증에 실패합니다. |
| [extensions/](../../../extensions/) | 선택적 독립 패키지 기능입니다. |
| [rule-catalog/](../../../rule-catalog/) | Catalog-as-code 데이터입니다. |
| [policies/](../../../policies/) | OPA/Rego policy-as-code입니다. |
| [콘솔/](../../../console/) | 지식 원본 및 거버넌스 적용 문서 업로드 경로, 지역화된 가이드 서랍, 검증된 Manual Studio 카탈로그 경계를 포함하는 얇은 운영자 SPA입니다. |
| [tools/manual-studio/](../../../tools/manual-studio/) | 독립 정적 가이드 라이브러리, HTML 슬라이드 뷰어, 저장소에 안전한 미디어 출처 계보 및 집중 프로토타입 검사를 제공합니다. |
| [teams_workflow_binding.py](../../../services/operator-service/src/fdai_operator_service/teams_workflow_binding.py) | 로컬의 암호화된 루프백 상태와 배포 환경의 버전이 지정된 단일 Key Vault 시크릿을 사용하는 프로바이더 중립 Teams 엔드포인트 영속화입니다. |
| [cli/](../../../cli/) | Operator command-line 클라이언트입니다. |
| [scripts/agent/design_context.py](../../../scripts/agent/design_context.py) | Design 맥락 읽기를 기록하고 dirty 편집 경로를 예약하며, framework 및 constitution 편집의 stale 맥락을 hard-block하고, commit 범위와 파괴적 Git을 보호하며, repository-wide 검증을 명시적인 integration 또는 release 경계로 라우팅합니다. |

## 관련 문서

| 알아볼 내용 | 문서 |
|-------------|------|
| 물리 서비스 및 패키지 소유권 | [다중 서비스 저장소 레이아웃](multi-service-repository-layout-ko.md) |
| 모듈 경계와 의존성 주입 | [프로젝트 구조](project-structure-ko.md) |
| 대화 및 온톨로지 조회 구현 순서 | [온톨로지 조회 커버리지 구현 계획](../interfaces/ontology-query-coverage-implementation-plan-ko.md) |
| IS 작업 패키지와 local-first 순서 | [서비스 분해 실행 계획](service-decomposition-execution-plan-ko.md) |
| 서비스 승격, 데이터 소유권 및 롤백 게이트 | [서비스 승격과 데이터 소유권](service-graduation-and-ownership-ko.md) |
| Control-loop 권한 | [아키텍처 instructions](../../../.github/instructions/architecture.instructions.md) |
| 에이전트 역할과 권한 | [에이전트 Pantheon](../agents/agent-pantheon-ko.md) |
