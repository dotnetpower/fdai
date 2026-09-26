---
translation_of: project-structure-dependency-injection.md
translation_source_sha: a595aed1faf57fc9046e19b0164830dcc5736d4b
translation_revised: 2026-09-26
---

# 프로젝트 구조 의존성 주입

이 문서는 upstream 및 downstream 구현에서 지원하는 의존성 주입 경계와 구성 경계를 담당합니다. 상위 문서는 리포지토리와 모듈 소유권 지도를 유지합니다.

## 설계 개요

이 문서는 [project-structure-ko.md](project-structure-ko.md)에 포함되어 있던 상세 계약을 그대로 보존하는 집중 소유 문서입니다.

## 의존성 주입을 통한 커스터마이제이션

업스트림은 범용 인터페이스와 동작하는 기본 구현을 제공합니다. 포크는 `core/`를 편집하거나
복사하지 않고 자체 조립 루트에서 의존성을 주입해 구성을 변경합니다.
[포크 모델](../../../.github/instructions/generic-scope.instructions.md)을 참조하세요. [알림 과다 수신 관리](../operations/alert-noise-governance-ko.md)는 제한적 조회기, 독립 근거, 기존 Workflow/Process 조정, GitOps 전달, 원본 작성자 통제 및 효과 중계를 연결합니다. 공유 알림 코덱은 온톨로지 쿼리 한도를 늘리지 않고 비공개 근거 크기를 제한하며, 순수 평가 함수는 불완전한 라우팅을 보고서 완전성에도 반영합니다. 공유 시계열 스키마는 완전하고 균일한 관측량과 사례별 탐지 결과를 고정합니다. Core는 평가 구간/주기 중 한 축을 비교하고 전달 계층은 고정된 출처 기록을 인증하며 지원되는 Azure Terraform 기간 필드만 생성합니다. Operator 요청 이력은 자체 접수를 정확한 서명 결과와 연결하며 공유 제안 상세는 Core 테이블에 접근하거나 승인/결과 권한을 만들지 않고 기준선과 재생 지표를 결속합니다. 팩터리는 처리 구조만 제공하며 독립 권한이나 수신자/효과 증적을 만들지 않습니다. 운영 도입에는 아직 충족해야 할 조건이 있습니다.

> **포크 유지관리자**: 절차적 walkthrough는
> [downstream-fork-guide-ko.md](../fork-and-sequencing/downstream-fork-guide-ko.md)에서 시작. 이 섹션은
> 그 가이드가 operational 화하는 경계 카탈로그입니다.

- **조립 루트**: `core/` 는 `shared/` 의 CSP-중립 인터페이스에만 의존합니다.
  얇은 조립 루트(`core/` 밖)가 시작 시 구체 구현을 바인딩합니다. `core/` 는 절대 구체
  어댑터를 new-up 하지 않고 의존성을 주입받습니다. 상류 기본 바인더는
  [`fdai.composition.default_container`](../../../services/core-control-plane/src/fdai/composition/__init__.py) 이며,
  포크의 엔트리 포인트는 해당 바인딩을 감싸거나 교체하는 자체 팩토리를 호출합니다.
  구체 어댑터 클래스(예: `PackageResourceSchemaRegistry`, `JsonSchemaContractValidator`)
  는 공개 서브-패키지에서 re-export **되지 않습니다**; 해당 서브모듈에서 직접, 그리고
  조립 루트에서만 가져오기 되어야 하므로 `core/` 가 실수로 구체에 의존할 수 없습니다.
  선택적 확장 배포판은 자체 팩터리, 리소스 로더, 준비 상태 형식, 어댑터를 위한 검토된
  권한 중립 facade를 노출할 수 있습니다. 구성에서만 이 facade를 가져오며 Core에서는 가져오지
  않습니다. 공개 검색 가능성은 가용성, 활성화, 접근, 승인, promotion 또는 실행 권한을
  부여하지 않습니다.
- **구성 기반 연결**: 설정이 각 구현을 선택합니다. `bind_configuration_drift`는 선택적 `ConfigurationDriftReportSink`를 받습니다. 런타임은 Core가 소유한 `StateStoreConfigurationBaselineSink`를 주입하여 완료된 근거를 반환 전에 기록하며, 프로바이더 조회나 검토 권한 또는 서비스를 추가하지 않습니다.
  `composition/wire_distiller.py`는 exact-version 엔드포인트 세 개와 replay-identical 프롬프트 하나로 review-only `Distiller`를 atomic하게 연결합니다. 협의체 기록이 없으면 사용하지 않는 엔드포인트 값을 검증하지 않고 abstention을 유지합니다. 부분 기록은 실행 T2 변경 없이 시작을 실패시킵니다.
  범용 드롭 디렉터리 `ManualSource`는 크기 상한을 넘은 경로를 메타데이터 전용 검토 대기 후보로 유지하므로 읽기 한도가 잘못된 삭제 신호를 만들 수 없습니다. 마이그레이션이 소유한 `operator_forecast_retention` 보안 장벽 뷰는 Core 사례 이력의 삭제 집계만 Operator에 제공합니다. 원시 사례와 문서 내용, 채널 권한, 런타임 DDL 권한은 바뀌지 않습니다. Operator 전달 진단은 기존 서비스 소유 테이블에서 기록된 차단기 모드를 읽으며, System Knowledge는 런타임이나 에스컬레이션 권한을 바꾸지 않고 변경된 설계 원본의 검증값을 다시 생성합니다.
- **상류의 기본 구현**: 메인 저장소는 모든 경계에 대해 동작하는 범용 기본 구현을 제공하여
  독립 실행 가능합니다. 포크는 필요한 경계만 교체합니다.
- **인스턴스 후보 조회**: `build_semantic_query_runtime(instance_candidate_query=...)`와 Azure 조립 함수는 신뢰할 수 있는 `InstanceCandidateQuery`를 받습니다. 조립 모듈은 정확한 release에 소스 기반 Function과 전체 객체 읽기 집합이 있는지 확인합니다. 기본 초기화는 임베딩 공간과 모델 버전 식별자가 명시된 경우에만 격리된 StateStore/벡터/그래프 런타임을 제공합니다. 인증된 principal과 그룹 클레임으로 접수 범위를 결정하며 조회 접수는 임베딩을 호출하거나 생성을 기다리지 않습니다. 감독되는 30초 조정 주기는 영속적인 에이전트 소유 준비·원본 변경 무효화 이벤트를 게시하고, 종결 감사가 있는 캐시만 복원하며 접수는 5분 뒤 만료됩니다. 활성 범위 8개와 주기별 기한으로 작업량을 제한합니다. 의미 순위 검색은 실제 자격 검증 전까지 사용 불가 상태입니다. 정확한 ID 조회는 현재 그래프의 인가를 거치며 전체 목록이나 실행 권한을 뜻하지 않습니다. 후보 전용 표시와 실제 검증 근거는 [조회 원장](../../roadmap-implementation/interfaces/ontology-query-coverage-implementation-plan.md)에서 계속 추적합니다.
- **적응형 대화**: `build_semantic_query_runtime(adaptive_service=...)`에는 `AdaptiveModel`과 `AdaptivePolicy`를 주입한 `AdaptiveConversationService`를 전달할 수 있습니다. 고정 역할, 독립 검토, 프로바이더의 공통 사용량 제한 및 검증된 근거 조회기는 그대로 필요합니다. 검증된 의미 계획은 동기 planner thread와 비동기 Azure provider 작업 전체에 취소 전용 model-call scope를 연결합니다. 따라서 요청 취소는 일반 후보 fallback을 변경하지 않고 provider 작업을 중지하고 회수합니다. `semantic_runtime_cancellation.py`는 이 스레드 취소 브리지를 소유하고 `semantic_planning_preflight_router.py`는 하나의 `plan()` 호출에 대한 preflight 기반 direct-response 라우팅을 소유하며, 두 모듈 모두 공개 import나 읽기 전용 권한을 바꾸지 않고 강제된 LOC 제한 아래로 유지됩니다. 전체 의미 판단은 selector 순서를 유지하는 32 KiB 후보 전용 기능 변환 결과를 사용합니다. 대상 없는 선언 종류 목록을 위한 정확한 타입 지정 가시성 및 현재 범위 특성 조합은 명시적인 `visible`, `current_scope`, `list` 특성이 있는 단수 종류와 명시적인 `visible`, `current_scope` 특성이 있는 복수 종류를 포함하며 principal 매니페스트를 결정론적으로 컴파일합니다. 원시 발화 토큰으로 이 경로를 선택하지 않습니다. 검증된 preflight Resource 컬렉션 필터는 서술자 축소나 요약 계획보다 먼저 검토된 value group에 결속되므로 선택적 상태 필터가 있어도 알 수 없는 타입은 형식화된 명확화만 만들 수 있습니다. 수락되지 않은 Resource 이벤트 이력 제안은 다음 frame 모델의 context만 축소할 수 있으며 제안 수락, frame-plan 검증, 근거 허용, 읽기 전용 권한은 바뀌지 않습니다. 이 경계에서 운영 의도 map 비교는 명시적인 bool을 반환합니다. 컬렉션 Resource 상태 계획과 상태 사실 해석은 결정론적 Core 온톨로지 플랫폼이 계속 소유하며 표현 계층은 검증된 행만 사용합니다. 대상이 없는 최근 Resource 변경은 추가 전용 관측 journal을 사용하는 별도의 서버 범위 FunctionType으로 처리합니다. 조립 과정은 PostgreSQL 조회기와 정확한 이벤트 ID 수신 fence를 주입합니다. Snapshot에 포함된 이벤트는 현재 상태를 변경하지 않는 이력 전용 journal append를 사용하므로 동일한 범위 제한 journal이 최종 수신을 입증합니다. 검토된 ARG change-feed와 Event Grid Resource 변경 출처 ID만 프로바이더 변경 검증을 충족할 수 있습니다. Core는 프로바이더 변경을 운영 상태 전이와 구분합니다. 의미 조회기는 인벤토리 수집과 동일한 `FDAI_INVENTORY_SCOPES` parser로 서버 범위를 확인하며, `AZURE_SUBSCRIPTION_ID`는 기존 단일 범위 fallback으로만 유지합니다.
- **엄격한 의미 스키마**: 프로바이더 호환 의미 제안 스키마는 지원되지 않는 길이 키워드를 제거할 때도 대안 및 미해결 용어 각각 최대 8개라는 한도와 필수 단일 명확화 질문에 대한 설명을 유지합니다. 결정론적 서버 검증이 계속 최종 권위를 가지며 잘못된 제안은 읽기 또는 실행 권한 없이 안전하게 차단됩니다.
- **일반 후보 재검증**: 일반 지식과 비슷하지만 검증된 one-shot 경로에 적합하지 않은 preflight 후보는 완전한 타입 지정 운영 판단으로 다시 들어갑니다. preflight 레이블이 넓다는 이유만으로 판단을 보류하지 않으며 두 번째 판단도 일반 계획 및 근거 검사를 통과하기 전에는 읽기 또는 실행 권한을 부여하지 않습니다.
- **논리 서비스 조회 소유권**: `semantic_logical_service_frame.py`는 정확한 frame 또는 명확화 frame을 소유하고 `semantic_logical_service_planning.py`만 승인된 BusinessService 또는 Workload의 id, 이름, alias를 typed 워크로드 및 Resource 경로로 컴파일합니다. 모델 계획, 프로바이더 이름, 태그 또는 레이블로 이 서버 소유 읽기를 대체할 수 없으며 표현 계층은 실행 권한이 없는 검증된 행만 사용합니다. 생성된 System Knowledge 카탈로그는 이 설계 문구를 색인할 수 있지만 런타임 인스턴스 또는 조회 권한을 부여하지 않습니다.
- **현재 T1 reuse 근거**: `CurrentReuseVerifier`는 변경할 수 없는 operational 사례를 위해 fresh 리소스, 토폴로지, 그래프, 소유자, 정책, 예행 실행, 안전성 사실을 수집합니다. Azure 캐시 최신성은
  범위가 제한된 age와 future skew를 사용해 현재 evaluation 시계 기준으로 평가하므로 이벤트 직전의 recent
  캐시는 통과할 수 있지만 historical 재생이 stale 근거를 되살릴 수는 없습니다. Learned 서명은
  정본 매개변수와 완전한 operational-case 맥락을 연결합니다. Growth 및 pgvector 조회/쓰기
  경계는 데이터베이스 I/O 전에 non-finite 임베딩 값을 거부합니다. Approximate pgvector 검색이 요청한 결과 제한을 채우지 못하면 후보를 반환하기 전에 exact sequential scan으로 다시 시도합니다. 검증기는 실행 권한을
  부여하지 않습니다. 연결이 없으면 operational reuse는 abstain하고 이전 방식 pattern은 계속됩니다.
  Pantheon 조립은 `OperatingPatternCompiler`를 inject할 수 있으며 Norns는 타입이 지정된 learning을
  serialize하고 Mimir 검토 전에 범위가 제한된 제안 backpressure를 적용합니다.
- **Causal 및 Dynamic 런타임 근거**: `TemporalCausalEvidenceProvider`는 범위가 제한된 pre-cutoff series와 그래프 사실을 제공하고 `DynamicSimulationRequestProvider`는 최대 32개 current-state 가지를 제공합니다. `CausalHypothesisProjection`은 Forseti-owned이며 모델 grade는 `EffectModelCausalEvidenceVerifier`를 요구합니다. Dynamic 모델은 시뮬레이션 스냅샷 이후 결과를 사용할 수 없고 현재 스냅샷은 evaluation-clock 최신성을 사용합니다. Pure simulator도 조정기 밖에서 모델 기준 시점 또는 finite-arithmetic 위반을 거부합니다. 연결이 없으면 shadow 경로가 비활성화됩니다.
- **Operational 승격 권한**: `OperationalPromotionReceiptVerifier`와
  `OperationalPromotionUnitVerifier`가 변경할 수 없는 근거를 해석합니다. 운영 레지스트리는
  이 연결 없이는 shadow를 유지하며 raw scalar 메트릭은 test-only 이전 방식 고정본 모드입니다.
  Promotion-state 새로 고침 실패는 stale 적용을 재사용하지 않고 unified system-health 상한을 낮춥니다. 의사 결정 근거 승인은 로컬에서 StateStore를 사용하고 배포 환경에서 읽기 전용 불변 Blob 기록을 사용합니다. 보호된 정책은 권위, 목적, 출처 개정, 검증기 분리 및 만료를 고정하며, 근거가 없거나 잘못되면 실행 또는 승격 권한을 부여하지 않습니다. 개발 `remediate.tag-add@1.1.0` 연결은 공유 실행기 대상 계약으로 범위가 제한된 논리 Resource ID 하나를 확인하고 change identity, 권한 부여 및 승격 경계가 모두 있을 때만 gateway에 도달합니다. Gateway는 태그 전용 변경, snapshot rollback, reader identity 기반 실제 상태 확인을 소유하며, 런타임은 승격 registry나 Console 권한을 바꾸지 않고 이를 MSCP 독립 효과 관찰자로 제공합니다.
- **Operational catalog 검토 및 측정**: `DeterministicCatalogValidator`는 고정 시나리오 디렉터리에서
  제공된 Rule loader, shadow evaluator, regression gate를 재사용합니다.
  `GitOpsCatalogReviewPublisher`는 내용 기반 주소가 지정된 비활성 검토 package만 게시합니다.
  `operational-promotion` 작업은 상태 변경 없이 exact-digest 근거를 저장하고, `cohort_observation_import`는 산출물이 선언한 군, 리비전, 프로토콜, 승인 또는 권한을 받지 않습니다.
  보호된 workflow가 묶음당 관측값을 1,000개로 제한하고 중복 JSON 키를 차단하며 각 관측 다이제스트를 묶음과 exporter workflow에 연결한 뒤 멱등 재생을 검증합니다. 신뢰할 수 있는 제품 중립 출처 레지스트리는 군의 각 필수 측정값을 저장소 내부의 일반 exporter workflow 하나와 고정 출처 식별자에 배정합니다. 반입기는 해당 식별자를 주입하고 인벤토리는 일치하는 출처 계보만 다시 계수합니다. 제품 어댑터는 배정된 workflow 뒤에 유지되며, 연결이 없거나 불완전하거나 중복되거나 두 군이 공유하면 경로를 차단합니다.
  `CostPromotionReviewStore`는 하나의 exact Cost Governance 대상 검토를 위한 권한 중립 경계입니다. 업스트림 PostgreSQL 어댑터와 Core 서비스 migration이 append-only 저장을 소유하며, 보호된 workflow는 각 기록 전에 하나의 attested campaign과 활성 pin을 검증합니다. 이 저장소는 package activation, ActionType 또는 Workflow mode, promotion 레지스트리를 갱신할 수 없습니다.
  안정적인 요청 재생은 원래 payload와 정규화 열을 검증하고 요청 소유 내용 및 보존 기간만 비교한 뒤 원래 시각을 담은 검토를 반환합니다.
- **Governed action 및 probe 전달**: `GovernedGovernancePrPublisher`는 retire 및 exemption
  순수 writer를 기존 write-once PR adapter에 연결하고 replay 가능한 open-to-merge 또는
  종단 증적을 저장합니다. Retirement loader는 병합된 retirement artifact를 active rule
  index에서 projection하고 exemption은 canonical JSON schema를 사용합니다. 예외 수명 주기
  조정기는 기존 `EventBus` 경계를 사용해 정확한 예외 개정과 배정이 연결된
  `governance.reapply-rule-assignment` 제안을 게시합니다. 연결이 없으면 보류하며 브로커
  수락은 최종 증적이 아닙니다.
  `LiveBlastProbeAdapter`는 배포가 제공하는 `BlastSignalSource`와 `ProbeFailureStreakSource`
  구현을 연결하며, 소스가 없거나 실패하면 Axis E를 낮추고 권한을 부여하지 않습니다.
  Runtime 조립은 retired-rule projection을 모든 downstream rule map에 전달하고 HIL/direct
  경로 전에 영속 promotion-attestation store를 연결합니다.
  HIL resume은 현재 active map에서만 rule을 resolve하며 catalog retirement 또는
  reload 뒤에는 serialized parked rule body를 신뢰하지 않습니다.
- **독립 효과 관측**: 영속 kinetic artifact 저장소가 exact-plan source입니다.
  `StateStoreExecutedActionObservationStore`는 검증기가 승인한 Heimdall 관측만 받습니다.
  `effect_evidence_bridge.py`는 검증된 증적만 matched로 옮기며 실패 또는 미상 결과는 registry 접근 없이 현재 승인을 요구하는 연결되지 않은 `StateStoreShadowReversionWriter`로 ActionType 하나를 복귀해야 합니다.
- **Azure operational 근거**: `bind_azure_operational_evidence`는 strict promoted-inventory 스냅샷 읽기 담당, 현재 안전성 평가기, 구성된 Azure 메트릭, 범위가 제한된 가지 estimator, effect-model 읽기 담당을 조립합니다. Temporal 어댑터는 근거 hashing 전에 non-finite 메트릭 값을 거부합니다. 부분 연결은 컨테이너 construction에서 실패합니다.
- **대시보드 가용성 변환**: `shared/telemetry/dashboard_status.py`는 프로바이더와 도메인
  리듀서가 생성한 뒤의 정규화된 메트릭 관측을 사용합니다. 프로바이더 I/O를 수행하지 않으며
  어떤 권한도 부여하지 않습니다. Phase 0 서술자는 소스가 연결된 패널의 예상 생산자와 최신성
  구간을 지정합니다. 누락되거나 오래되었거나 충돌하거나 일치하지 않거나 미래 시점이거나 합성인
  라이브 관측은 숫자 대체값 없이 사용 불가로 표시됩니다.
- **변경 안전성 권한 전 근거**: `core/control_loop/change_safety_evidence.py`는
  `Container.change_safety_evidence_provider`를 통해 주입된 프로바이더 하나를 받고 Activity
  Log 감지기는 `Container.change_safety_detector`를 통해 별도로 주입됩니다. 대역 외
  발견 사항의 경우 컨트롤 루프는 Action 생성 후 실행 권한 및 risk-gate 전에 정확한 표류 및
  what-if 레코드를 결합합니다. 근거가 없거나 유효하지 않으면 발견 사항을 억제하지 않고
  보류합니다. 프로바이더는 관측된 영향 개수만 채울 수 있으며 권한을 부여하거나 독립 작업 후
  검증을 충족할 수 없습니다.
- **Principal 범위 operational 근거**: `OperationalEvidenceSource`와
  `OperationalEvidencePrincipalContextProvider`는 하나의 쌍으로 바인딩됩니다. Core는 기존
  semantic 변환 결과가 Operator로 전달되기 전에 범위가 제한된 번들과 증적으로 검증된 Context
  메타데이터를 승인합니다. 쌍이 없으면 기존 응답을 유지하고 일부만 바인딩되면 컨테이너 구성에
  실패합니다. 두 경계 모두 변경 또는 실행 권한을 부여하지 않습니다.

### 기능 번들

검증된 번들, 확장, trusted-artifact, 스킬 공개 및 철회 수명 주기는 [기능 번들 수명 주기](capability-bundle-lifecycle-ko.md)에서 소유합니다. 프롬프트 공개 예산은 저장된 Markdown 본문만이 아니라 trusted XML wrapper를 포함한 완전한 렌더링 스킬 또는 bundle 레이어에 적용됩니다. turn별 Operator Memory 조립은 독립적인 Resource Group 및 Resource 범위를 동시에 읽고 두 읽기가 완료된 뒤 결정론적 계층 순서를 보존합니다. 콘텐츠가 없는 조립 로그는 렌더링된 프롬프트나 memory 본문을 기록하지 않고 전체, Operator Memory, 스킬 공개 시간을 분리합니다.

### 주입 가능한 Seams

Operator의 영속 발신함 facade는 별도 래퍼 없이 테스트 맥락 브리지를 재노출합니다.
import를 모아도 작업 정체성, 문서 수집, 출처 소유권, 구성 의존성 상한은 유지합니다.

아래 **CSP-중립성 계약** 으로 표시된 여덟 경계는 [csp-neutrality-ko.md](csp-neutrality-ko.md)의 와이어 수준 계약을 구현합니다. `core/` 는 인터페이스만 봅니다; 포크 또는 미래의 비-Azure
단계 는 `core/` 를 편집하지 않고 조립 루트 에서 새 구현을 등록합니다.

| 경계 | 인터페이스 (`shared/`) | 계약 | 기본 (상류) | 포크 오버라이드 예시 |
|------|-----------------------|-----|-------------|---------------------|
| 예측 및 테스트 맥락과 파생 사례 수명 주기 | `ForecastContextProvider`; `TestContextSource` (Core); `CaseHistoryDerivedDataStore` | 정확한 범위, 대상, 시각과 독립 검증 근거. 파생 정리가 끝나야 원본 삭제를 완료하며 실행 권한은 없음 | 정규화된 이력 수집, 의미 초안, 인증된 맥락 명령, Saga가 감사한 적용 결과, Thor 실행 직전 검사, 승인된 Pattern 조회, 실제 라이브러리 DSN을 쓰는 원본 삭제 보호형 T1 벡터 정리를 연결함. 독립 증적 발급, Operator 작업 화면, 다른 후속 사본 정리는 미완료임 | 거버넌스를 따르는 출처 및 검증 증적 공급자와 삭제를 보호하는 사례 저장 어댑터 |
| 제한된 워커 계획 | `core/task_worker/`의 `TaskWorkerPlanningProvider`와 추가형 준비 호출 및 복구 가능 저장소 계약 | 한 번의 호출 전에 토큰/비용 예약을 영속화하고 측정된 사용량이나 미확인 사용량, 원자적 종료 이벤트를 보존합니다. 에이전트 또는 실행 권한은 없습니다. | 명시적으로 활성화한 Core의 `runtime/task_workers.py`가 Azure 계획, 단일 소유자 PostgreSQL 복구, 정확한 대상의 저장된 인벤토리 읽기를 연결합니다. [범위와 선행 조건](../agents/bounded-task-workers-ko.md#운영-구성) | 범위, 예산, 실패 시 사용량 기록을 유지하는 읽기 전용 준비 호출 프로바이더와 복구 가능 저장소 주입 |
| Event 버스 | `EventBus` (Kafka 프로듀서/컨슈머) | **CSP-중립성 계약** - [이벤트버스](csp-neutrality-ko.md#1-이벤트버스-계약--kafka-와이어-프로토콜) | SASL/OAUTHBEARER (Entra 토큰 소스) 를 사용하는 librdkafka 기반 클라이언트 | AWS IAM SigV4 인증, GCP IAM 인증, Confluent SASL/PLAIN, 자체 호스팅 Kafka mTLS |
| 런타임 | `RuntimeAdapter` (OCI + Knative 호환 매니페스트 렌더링) | **CSP-중립성 계약** - [런타임](csp-neutrality-ko.md#2-런타임-계약--oci-이미지--knative-호환-매니페스트) | Container Apps IaC 렌더러 (Bicep/Terraform) | Cloud 실행 YAML, App 실행기 서비스, 어떤 K8s 위의 Knative 서비스 |
| 시크릿 & 구성 | `SecretProvider` / `ConfigProvider` | **CSP-중립성 계약** - [시크릿](csp-neutrality-ko.md#3-시크릿-계약--환경변수--k8s-secret) | env + Container Apps KV-reference 브릿지 | ESO + Key Vault / AWS Secrets Manager / GCP 시크릿 Manager / HashiCorp Vault |
| 워크로드 신원 | `WorkloadIdentity` (audience-scoped OIDC 토큰) | **CSP-중립성 계약** - [워크로드 아이덴티티](csp-neutrality-ko.md#4-워크로드-아이덴티티-계약--oidc-토큰) | user-assigned Managed Identity (IMDS → Entra 토큰) | IRSA, GCP 워크로드 신원 Federation, SPIFFE/SPIRE SVID |
| 인벤토리 | `Inventory` 및 `InventorySnapshotStore` (CSP-중립 배치, 변경할 수 없는 후보 staging, atomic 활성 포인터) | **CSP-중립성 계약** - [인벤토리](csp-neutrality-ko.md#5-인벤토리-계약--리소스-그래프) | 전용 읽기 전용 MI의 scheduled Azure 수집기: ARG full-scan, direct ARM-list 대체 경로, 서명된 declarative 복구, PostgreSQL last-known-good 변환 결과; Core-owned 이행은 관찰된 `peered_with` 및 검증된 `runtime_calls` 링크와 여러 valid `attached_to` 기준점을 허용 | 포크가 커버리지, 권한, 관계 cardinality 및 atomic-promotion 의미 규칙을 유지하면서 다른 ordered 출처를 주입 |
| 메트릭 인제스트 | `MetricProvider` | **CSP-중립성 계약** - [메트릭](csp-neutrality-ko.md#6-metric-query-계약---csp-neutral-sample-iterator) | `NoopMetricProvider` 또는 Azure Monitor Logs 연결 | CloudWatch, Prometheus, Datadog 또는 다른 정규화된 메트릭 어댑터 |
| 로그 인제스트 | `LogQueryProvider`, `TelemetryEvidenceProvider` | **CSP-중립성 계약** - [로그](csp-neutrality-ko.md#7-log-query-계약---structured-log-records). 내용 기반 주소가 지정된 `TelemetryEvidenceNeed` 하나가 검토된 recipe, 정확한 대상, 기준 시점 및 예산을 지정합니다. 프로바이더는 원시 행이나 조회 텍스트 없이 범위가 제한된 완전성과 비용을 반환합니다. | `NoopLogQueryProvider`; 구성된 Azure 어댑터는 이벤트 시각 인벤토리 신원을 해석하고 최대 3개의 Diagnostic Settings 또는 작업 영역 기반 Application Insights 목적지를 발견한 후 명시적인 정적 대체 경로 하나를 추가해 정확한 범위의 KQL을 실행합니다. RCA는 이 원격 측정 경로에서 범위가 제한된 fact token과 불투명한 인용만 모델에 전달합니다. 적응형 어댑터는 고정 recipe 카탈로그만 컴파일하며 완전한 연결을 사용할 수 있으면 shadow Process를 활성화합니다. | Loki, Elasticsearch, CloudWatch Logs 또는 다른 구조화된 로그 어댑터입니다. 다른 읽기 전용 recipe 실행기는 recipe id, 출처 처리 결과, 취소 및 증적 계보를 보존해야 합니다. |
| 추적 인제스트 | `TraceQueryProvider` | **CSP-중립성 계약** - [추적](csp-neutrality-ko.md#8-trace-query-계약---distributed-trace-spans) | `NoopTraceQueryProvider`; 구성된 Azure 어댑터는 정확한 이벤트 시각 작업 영역 경로를 공유하고 Application Insights 요청 및 의존성을 변환합니다. Core는 항목과 참조가 제한되고 표준화되며 정확한 토폴로지, 시나리오, 구간, 관측 시각 및 최대 24시간의 양수 근거 유효 기간에 결속된 독립 인용 계측, 수집기 또는 헤더 전파 신호 하나가 일치할 때만 추적 연속성 원인을 구분할 수 있습니다. 잘못된 신뢰도 구성은 근거 평가 전에 실패하며 결합 인용이 100개를 넘으면 판단을 보류합니다. 홉 순서 발견은 감지기가 문제가 있는 홉을 식별할 때까지 판단을 보류하며, 소유권 근거가 없는 경계는 원인 영역을 `unknown`으로 유지하고, 근거 신뢰도는 T1 상한을 적용한 후 기본 `0.5` 하한을 통과해야 합니다. | Tempo, Jaeger, Honeycomb 또는 다른 구간 어댑터 |
| Cloud 프로바이더 | 프로바이더 클라이언트 | (위 여덟 경계를 사용) | 참조/범용 Azure 어댑터 | 특정 CSP 어댑터 |
| **Saga 이슈 인계** | `fdai.agents` facade의 `IssueTrackerAdapter`와 추가형 `IdempotentIssueTrackerAdapter`, 런타임 `StateStore` 저널 | - | `StateStoreIssueTrackerAdapter`는 이슈 상태와 정확한 작업 결과를 CAS로 영속화하고 실제 처리와 시작 복원에 하나의 결정론적 변환 결과 한도를 적용하며 종료를 발생 댓글 밖에 기록하고 consumer 시작 전에 복원합니다. `InMemoryGithubIssueAdapter`는 타입이 지정된 런타임 인계의 테스트 전용입니다. | 프로바이더 측에서 작업 ID와 내용을 원자적으로 결속하고 결과를 영속적으로 복구하는 `create_or_comment_once`를 구현합니다. 기존 어댑터는 직접 에스컬레이션에 계속 사용할 수 있지만 추가형 경계가 없으면 타입이 지정된 인계는 실패 시 차단됩니다. |
| **스키마 출처** | `SchemaRegistry` (원시 JSON 스키마 로더) | - | `PackageResourceSchemaRegistry` (패키지 내장 스키마) | 원격 schema-registry 어댑터; 내용 해시 로 핀된 스냅샷 |
| **경계 검증** | `ContractValidator` / `EventValidator` (실패 시 차단 입력 검사) | - | `JsonSchemaContractValidator` + `JsonSchemaEventValidator` (draft-2020-12) | 포크가 `core/` 편집 없이 도메인 특이 체크(예: 소스 허용 목록) 추가 가능 |
| **액션 precondition 근거** | `core/risk_gate/preconditions.py`의 `PreconditionEvaluator`; RiskGate가 consume하는 indexed `PreconditionEvaluation` 기록 | - | `GovernedPreconditionEvaluator`가 정본 이벤트 근거를 결합하고, `StateStoreOpenActionEvidenceProvider`가 Thor의 영속 active-run 인덱스를 읽으며, `OntologyChangeWindowEvidenceProvider`가 범위가 제한된 구간 조회를 수행합니다. 활성 행이 없거나 malformed이면 충돌로 처리하고, 프로바이더가 없으면 조건은 해결되지 않은 상태로 남기며, 잘리거나 malformed인 구간은 inactive 상태로 유지합니다. | 모든 조건 인덱스와 근거가 권한을 유지하거나 낮추기만 한다는 규칙을 보존하면서 읽기 전용 상태 변환 결과를 교체합니다. |
| **아키텍처 검토 근거** | `core/architecture_review/readiness.py`의 `ProductionEvidenceProvider`, 선택적 `Container.architecture_review_evidence_provider` 연결 | - | 기본 unbound이므로 메타데이터만 있는 운영 준비 상태는 계속 차단됩니다. | `dataclasses.replace`로 URI, 범위, 개정, 관측 시간 및 승인자 권한을 인증하는 통제된 bounded-body 공급자를 주입하며 결정 또는 실행 권한은 부여하지 않습니다. |
| **관리형 trajectory 데이터셋** | `shared/providers/trajectory.py`의 변경할 수 없는 감사 / 대화 / 도구 / 승인 / 결과 스냅샷 프로토콜, `TrajectoryAccessAuthorizer`, `TrajectoryDatasetStore`; `core/trajectory/`의 `TrajectoryJoinService`, `TrajectoryDatasetAdminService` | - | Deny-by-default 허용 목록 authorizer, in-memory 메타데이터 저장소, 결정론적 JSONL 내보내기 도구, PostgreSQL 메타데이터/격리 구역 어댑터, Owner-only GET 변환 결과, offline 검증기 | authorization-before-materialization, 범위가 제한된 excerpt, 체크섬, 보존/legal 보류, reviewed-only Norns intake를 유지하며 policy-backed 범위 권한 확인과 변경할 수 없는 출처 읽기 담당을 주입 ([설계](../interfaces/governed-trajectory-datasets-ko.md)) |
| Rule / 정책 출처 | rule-catalog + `policies/` 로더, `RuleIndex`, `CatalogIndexLifecycle` | - | 잠금으로 보호되는 원자적 current/N-1 전달 인덱스를 사용하는 번들 범용 규칙. 다이제스트 tombstone이 제거된 버전의 충돌을 차단합니다. | 고객 규칙 세트 / 임계값 |
| **Rule 수집 근거 전달** | `rule_catalog/pipeline/`의 `RuleCatalogSnapshotStore`와 `CollectionReviewPublisher` | - | 선택적 Azure Blob 내용 기반 주소 미러와 초안 전용 GitOps 검토 게시자. 실시간 카탈로그 경로나 병합 권한 없음 | 다이제스트 검증, 원격 멱등성, 검토 전용 게시, 카탈로그 활성화 권한 없음 규칙을 유지하면서 저장소 또는 pull request 호스트 교체 |
| **기능 번들 런타임** | `core/capability_catalog/`의 `CapabilityRuntime` + `CapabilityBundle` 및 trust-verified `ExtensionManager`; `core/tools/`의 가산 `StaticToolRegistry` / `CompositeToolRegistry`; `composition/`의 `install_capability_bundle(...)` | - | 포크 연결이 없는 기본 발견 카탈로그, 확장은 비활성화된 상태로 설치 | 검토된 reasoning-tool 메타데이터와 프로바이더를 추가하거나 기능을 기존 `ActionType` / `Workflow`에 연결; 중복 id, 다이제스트, trust, 호환성, 매니페스트 동등성, 모든 참조를 activation 전에 검증 |
| **기능 라이선싱** | `core/licensing/`의 `LicenseVerifier`, `LicenseEntitlementAuthority`, 토큰 계약 및 현재 시각 기준 해석, `delivery/trust/ed25519.py`의 패키지된 `Ed25519LicenseVerifier`, `core/executor/`의 `LicenseGatedThorExecutionPort` | - | 배포되는 런타임은 예상 신원을 `fdai-upstream`으로 고정하고 경과 UTC 시간 30일을 넘는 서명 기간을 거부하며, 토큰이 없거나 잘못되거나 만료되거나 잘못 연결된 배포를 관찰 전용으로 유지합니다. 로컬 소스 checkout은 소유자 전용 비공개 키가 패키지 공개 키와 일치할 때만 전체 카탈로그를 사용합니다. | 배포판은 조립 단계에서 예상 신원을 제공하고 Key Vault 또는 동등한 시크릿 참조로 서명 토큰을 주입합니다. 모든 Thor 경로는 승격, RBAC, 위험, 승인, 안전장치, 감사 실패 시 거부 또는 효과 검증을 대체하지 않고 가용성을 다시 검사합니다. ([설계](../fork-and-sequencing/capability-licensing-ko.md)) |
| **맥락 선택 정책** | `core/working_context/`의 `ContextSelectionPolicy`, 필수 불변식 래퍼, revision-safe 권한, shadow 실행기, 재생, 근거 저장소; `CapabilityRuntime`의 `context_selection_policy` 참조 | - | 불변 `deterministic-tiered-v1@1.0.0`, 후보 설치는 비활성화된, 영속 근거는 `StateStore` 재사용 | 조립에서 검토된 정책 구현을 등록하고 exact id/버전을 `CapabilityRuntime`으로 연결하며, 범위가 제한된 shadow 측정 후 근거 구간과 롤백 대상으로만 promote ([설계](../decisioning/context-selection-policy-ko.md)) |
| **브라우저 근거** | `shared/providers/browser_evidence.py`의 `BrowserEvidenceProvider`, 출처 정책, 수집 요청, 산출물 저장소, 보관 싱크, `core/browser_evidence/`의 정책 및 서비스, `fdai-service-contracts`의 v1 호환 및 v2 작업 공간 DTO | - | 기본 unbound, 선택적 isolated Playwright 전달 어댑터, PostgreSQL 산출물, 추가 전용 보관, 근거 작업 흐름 단계, 호환되는 GET-only 메타데이터, 변경을 고려하는 페이로드 없는 조사 작업 공간, v2 Operator 테스트 4개마다 정확히 하나인 서비스 테스트 모음 담당자 | 서버가 소유한 정확한 정책과 실행기 신원이 없는 restricted-egress 런타임을 연결하며 내용은 신뢰되지 않은 shadow-only 상태로 유지합니다. 허용된 식별정보는 식별정보가 없는 보류 집계와 분리하며 Console 필터는 수집 또는 작업 권한이 되지 않습니다. ([설계](../interfaces/browser-evidence-ko.md)) |
| **MSCP 효과 관측** | `core/mscp_profile/`의 `ExpectedEffectProvider`, `IndependentEffectObserver`; 변경할 수 없는 `Container`의 선택적 쌍 | - | 기본 unbound, headless 런타임이 완전한 쌍을 ControlLoop로 전달해 predict -> 전달 -> observe -> shadow-audit 순서 유지 | `dataclasses.replace`로 두 collaborator를 함께 연결, 일부 연결은 fail fast, shadow 결과는 자율성을 높이지 않음 ([설계](mscp-operational-profile-ko.md)) |
| **타입이 지정된 외부 RPC** | `core/rpc/`의 `RpcRegistry`, `RpcMethod`, 범위, 멱등성 계약, `delivery/rpc/`의 범위가 제한된 HTTP 클라이언트/경로, 결정론적 Python stub codegen, `build_production_rpc_app(...)` | - | 컨트롤 플레인은 RPC 경로를 mount하지 않으며 명시적 선택 standalone 앱이 built-in 도구 발견과 PostgreSQL hashed 점유를 연결 | 포크가 identity-aware authorizer와 명시적 additional 메서드를 제공합니다. Side-effect 메서드는 영속 멱등성 점유가 필요하고 실행기를 직접 호출하지 않고 타입이 지정된 제안을 제출합니다. |
| **온톨로지 ObjectType / LinkType / InterfaceType** | `services/core-control-plane/src/fdai/rule_catalog/schema/`의 실패 시 차단 ObjectType, LinkType, InterfaceType 및 명시적 Interface 구현 로더 | - | `rule-catalog/vocabulary/{object-types,link-types,interface-types,interface-implementations}/` 아래의 shipped 선언을 대응하는 변경할 수 없는 `Container.ontology_*` 튜플로 부하합니다. Interface 연결은 compile되어 exact 런타임 release에 pin됩니다. | 포크는 fork-local vocabulary 디렉터리에 추가 YAML을 제공하고 조립 루트에서 두 루트를 부하하며 combined Interface 연결을 compile한 뒤 concatenated 튜플을 `dataclasses.replace`로 전달합니다. 중복 이름과 dangling 연결은 fail-close합니다. 자세한 절차는 [downstream-fork-seam-recipes-ko.md § 5.8a](../fork-and-sequencing/downstream-fork-seam-recipes-ko.md#58a-ontology-object-type--link-type-additions). |
| **네트워크 조회 증적 검증** | `services/core-control-plane/src/fdai/core/ontology_platform/network_path.py`의 `NetworkQueryReceiptVerifier`와 조립이 소유한 opaque 검증 맥락 하나 | - | Unbound 상태이며 증적 발급자와 검증기 없이는 `query.network_path_segments`를 인증된 운영 함수로 등록할 수 없습니다. | Secured 증적 역할, singleton 용도, exact 온톨로지 release, projected-result 다이제스트 및 `FunctionInvocationContext`를 인증하는 issuer-backed 검증기를 inject합니다. Opaque 맥락은 함수 인자에 포함되지 않으며 검증은 실행 권한을 부여하지 않습니다. |
| **Runtime-call 근거 변환** | `services/core-control-plane/src/fdai/{core/ontology_platform,delivery}/`의 `RuntimeCallObservation`, `RuntimeCallTelemetryProducer`, `RuntimeCallInventoryEnricher` | - | 예약 인벤토리 작업이 기존 single-writer enrichment 경계를 연결하며, 인증된 source가 정확한 caller 및 target Resource id를 제공할 때까지 edge를 추가하지 않고 `telemetry_source_unavailable`을 기록합니다. AKS Pod 로그 근거는 별도의 내용 없는 읽기 경로를 사용하며 출처 revision, 프로바이더 기준 시점 및 구간 범위를 독립적으로 연결하기 전까지 불완전 상태로 유지됩니다. AKS 결정론적 축약기는 인과관계와 실행 권한을 거짓으로 고정한 Forseti 소유 T0 근거 증적을 생성합니다. | Exact-release, active-generation, scope, freshness, independent-verifier, no-authority 검사를 보존하면서 권위 있는 telemetry source를 주입합니다. |
| **작업 흐름 카탈로그 (프로세스 자동화)** | `services/core-control-plane/src/fdai/rule_catalog/schema/workflow.py`의 `load_workflow_catalog(root, *, schema_registry, action_type_names, rule_ids=...)`; `services/core-control-plane/src/fdai/core/workflow/`의 `compile_workflow(...)` | - | `rule-catalog/workflows/` 아래 shadow-first 작업 흐름입니다. 각 액션 단계는 `ActionType`을 cross-reference하고 근거/컨트롤 단계는 전용 타입이 지정된 계약을 사용합니다. | 포크는 자체 `fork/workflows/` 디렉토리에 작업 흐름 YAML을 추가로 로드해 concatenate한 ActionType / 룰 집합과 함께 `dataclasses.replace(container, workflows=...)`로 주입합니다. 두 루트 간 `name` 중복은 실패 시 차단됩니다. 자세한 내용은 [(4[56])](../decisioning/process-automation-ko.md)을 참고하세요. |
| **복구 시도 및 디스패치** | `core/workflow/`의 `recovery_attempt.py`, `recovery_effect_claim.py`, `recovery_terminalization.py`, `recovery_coordinator*.py` 계열(`recovery_coordinator.py`가 경로 순서를 소유하고 `_models`, `_records`, `_support`, `_binding`, `_dispatch`, `_effect`, `_release`, `_terminalization`이 각각 한 단계를 소유), `recovery_effect_ingress.py`; `core/executor/`의 `hold_dispatch_fence.py`; `shared/providers/automation_hold_state.py`의 `AutomationHoldStateReader`와 `HoldReleaseAuthorizationReader`; `delivery/persistence/`의 `workflow_recovery.py`; `delivery/`의 `workflow_recovery_observation_handler.py`; `agents/_framework/`의 `heimdall_huginn_projection.py` | - | 영속적 복구 시도 신원 결속, 배타적인 compare-and-set 사전 디스패치 청구 하나, 별도 승인/안전장치 증적, 신원 분리가 적용된 권위 있는 효과 완료 주장, 비정상 종료에 안전한 최종 Process/Saga outbox, 논리 대상 잠금 내부의 권한 부여 결속 디스패치 fence, 독립적인 사후 효과 관측을 위한 버전이 지정된 타입 안전 관측자 경로 수집 지점 하나. 이 수집 지점은 Heimdall이 소유한 `object.recovery-effect-observation` 토픽만 읽습니다. 외부 관측은 Huginn이 `object.event`로 정규화하고, Heimdall이 `heimdall_huginn_projection.py`로 선언된 필드를 자신의 토픽에 투영합니다. 이 모듈은 투영 로직을 `heimdall.py` 밖에 두며 어떤 권한도 부여하지 않습니다. 런타임은 복구 승인 저널, Workflow 결과 기록기를 감싼 확정 안전장치 번들 보존, 독립 효과 관측 저널, 관측자 그룹 관측 수집 지점을 연결합니다 | 새 모듈은 기존 자동화 보류, 승인 저널, 복구 승인 계약을 사용하며 새로운 실행 권한이나 프로바이더 연결을 도입하지 않습니다. 포크는 각 읽기 및 기록 seam을 교체할 수 있지만 영속성이 승인이나 효과 검증 권한을 부여하게 만들 수는 없습니다. [#652, #656, #658, #640](../decisioning/process-automation-ko.md) 참조. |
| **경로 교차 안전장치 증적 및 독립 효과 관측** | `core/executor/`의 `execution_provenance.py`, `safeguard_dispatch_validation.py`, `effect_observation.py`, `effect_observation_ledger.py`, `effect_observation_codec.py`, `effect_observation_source.py`; `delivery/persistence/`의 `postgres_effect_observation.py`; `delivery/azure/`의 `vm_power_state_effect_source.py`; `delivery/github/`의 `effect_state_source.py` | - | 영속 안전장치 디스패치 증적은 신원 스키마 1.1.0에서 실행 경로, 오케스트레이션 출처(`core`, `workflow`), 실행 장소(`core`, `isolated_executor`)를 결속하며 출처 필드 이전의 1.0.0 레코드도 그대로 읽고 다이제스트를 검증할 수 있습니다. 독립 효과 관측은 정확한 번들, Action, 대상, 원본 개정, 근거 레코드, 실행기 증적에 결속된 별도의 추가 전용 증적이며 근거 구간, 최신성, 확정성, 완전성, 충돌, 합성 여부, 영향 억제 범위로 판정합니다. `verified`만 효과를 종결합니다. `missing`, `stale`, `conflicting`, `censored`, `unavailable`은 새 효과를 승인하지 않는 하나의 미상 보류이며 `failed`는 7개 안전장치와 현재 사람 승인을 다시 명시하는 비활성 `GovernedRecoveryRequest`만 낼 수 있습니다. 읽을 수 없거나 도달할 수 없거나 표현할 수 없는 원본은 버리지 않고 보류로 보존하며 보존된 관측이 없는 전달은 효과 부재가 아니라 `missing`으로 읽습니다. 관측자, 실행기, 원본 신원은 서로 달라야 하며 모든 증적은 실행, 싱크 커밋, 잠금 해제, 승격 권한을 false로 고정합니다. | 포크는 관측 원본 경계나 추가 전용 저장소를 교체할 수 있지만 관측이 실행, 싱크, 해제, 승격 권한을 부여하게 하거나 약한 관측을 `verified`로 확대할 수는 없습니다. [#633](../decisioning/execution-model-ko.md)을 참조하세요. |
| **통제된 Python 작업** | `shared/providers/`의 `PythonTaskAuthor`, `PythonTaskArtifactStore`, `VmTaskTargetResolver`, `VmTaskRunner` | - | 로컬 템플릿 작성자 + in-memory 산출물/대상 + 계획 수립 실행기; 운영은 변경할 수 없는 산출물을 Postgres에 저장하고 활성 인벤토리에서 대상을 해석하며 headless 실행기가 Azure Managed Run Command를 연결 | 포크는 내용 해시, declared 기능, 멱등성, non-executing Operator API 계획, 타입이 지정된 제안 전달을 유지하면서 다른 작성자, 산출물 저장소, 대상 해석기, compute 실행기를 제공. [(4[56]) § 4.5](../decisioning/workflow-control-loop-integration-ko.md#45-governed-python-task-및-cron-schedule) 참조. |
| **통제된 샌드박스 프로파일** | `core/sandbox/`의 `SandboxProfileCatalog`, `VmTaskSandboxCatalog`, `ToolSandboxCatalog`, `DocumentConverterSandboxCatalog`; `shared/providers/`의 `DocumentConverter` | - | 프로파일이 없는 명령, VM-task, 도구, converter 요청은 실패 시 차단합니다. Profiled 래퍼는 구체적인 어댑터 직전에 기능, 모드, 접미사, 시간 초과, 인자/입력/출력 바이트, workspace/네트워크 상한을 적용합니다. | 포크는 각 어댑터 연결과 함께 명시적 서버가 소유한 프로파일을 제공합니다. 프로바이더 계약 뒤에서 converter 또는 alternate 실행기를 구현할 수 있지만 호스트 경로, executable, 자격 증명 또는 더 넓은 요청 권한을 노출하지 않습니다. [(4[56]) § 4.6](../decisioning/workflow-control-loop-integration-ko.md#46-governed-command-및-shell-artifact) 참조. |
| **통제된 실행 백엔드** | `shared/providers/execution_backend.py`의 `ExecutionBackend`와 `ExecutionSubmissionLedger`; `core/execution_backend/`의 프로파일 intersection 및 조정기; `composition/`의 `bind_execution_backends(...)` | - | 프로파일은 비활성화된 상태로 로드되고 기존 샌드박스 검증이 먼저 실행됩니다. PostgreSQL은 멱등적 수명 주기 시도를 저장하고 bubblewrap 및 VM 어댑터는 기존 동작을 보존하며 Azure Container Apps 작업은 pre-provisioned pinned 템플릿만 시작합니다. | 조립에서 서버가 소유한 프로파일과 구체적인 어댑터를 제공합니다. 연결은 워크로드, 자격 증명, 네트워크, workspace 접근, 한도, 지역, 범위를 추가하지 않고 낮출 수만 있습니다. 충족 여부, 승인, 롤백, 감사 결정을 소유하지 않습니다. [execution-backends-ko.md](../interfaces/execution-backends-ko.md)를 참조하세요. |
| **통제된 명령, 셸 작업 및 코드 workspace** | `shared/providers/`의 `CommandRunner`, `CommandPlan`, `ShellTaskChecker`, `ShellTaskSpec`, `CodeWorkspaceProvider`, `CodePatchSet`; `core/tools/` 및 `core/python_task/`의 `CommandCatalog`, 기본값 명령 spec, 셸 structural 검증, workspace patch 검증 | - | `RecordingCommandRunner`, `BashSyntaxChecker`, 명시적 선택 `BubblewrapCommandRunner`, copy-on-write `GitCodeWorkspaceProvider`, 타입이 지정된 `azure.resource.list`, `azure.group.list`, `azure.vm.list`, `azure.vm.status` 읽기용 명시적 선택 `AzureCliCommandRunner`; 로컬 VM 인벤토리는 `az vm list --show-details`를 사용합니다. 생성된 Python은 `process`를 거부하고 셸 산출물은 validate하지만 실행하지 않으며 업스트림 앱은 기본적으로 실제 운영 실행기를 연결하지 않습니다. | 포크는 credential-free 로컬 실행기와 비공개 workspace 프로바이더 또는 credentialed Azure 읽기 브로커를 연결할 수 있습니다. 서버가 소유한 범위 및 신원, 결정론적 argv 렌더링, raw 명령 문자열 금지, stale-file 해시 검사, 멱등성, 출력 한계, `tool_call` / `direct_api` / `run_runbook` 경로 분리를 유지해야 합니다. [(4[56]) § 4.6](../decisioning/workflow-control-loop-integration-ko.md#46-governed-command-및-shell-artifact) 참조. |
| **인시던트 확인** | `core/incident/proposal_store.py`의 `IncidentProposalStore` | - | 로컬 개발용 범위가 제한된 `InMemoryIncidentProposalStore`; 운영의 `PostgresIncidentProposalStore`는 복제본 간 atomic consume 사용 | 같은 principal/세션 연결, 만료, atomic single-consumer 의미 규칙을 보존하는 영속 저장소만 주입 |
| **인시던트 알림 전달** | `DurableIncidentLifecycleNotifier`로 감싼 `IncidentLifecycleNotifier`; atomic 점유/완전한/release용 `IncidentNotificationDeliveryStore` | - | 로컬은 in-memory 점유, 운영은 임차 기간이 있는 PostgreSQL row-lock 점유; 알림 매트릭스 + HIL 에스컬레이션 대체 경로 | `ChannelRegistry`에 Teams, Slack, 이메일, 웹훅, pager 어댑터를 연결하고 고정된 `audit_id`, single-claimer 의미 규칙, 임차 기간 복구, 시작 재생 유지 |
| 전달 어댑터 | 전달 인터페이스 | - | `gitops-pr` / `chatops` | 다른 PR 호스트 / 채팅 채널 |
| Risk 채점 & thresholds | risk-gate 구성 | - | 범용 임계값 | 고객 리스크 정책 |
| 모델 프로바이더 | 모델 클라이언트 (기능별) | - | 설정된 기본 엔드포인트 | 고객 승인 모델 |
| **Assurance Twin 의미 컴파일러** | `Container`를 통해 주입하는 `NlQueryCompiler` 및 `AssuranceTwinDiscoverySink` | - | 명시적인 `semantic_model_unavailable`, 발견 인계는 사용 불가를 보고 | 정확한 입력 다이제스트, 컴파일러 개정, 근거 참조, 결과 한계, 읽기 전용 검증, 원시 질문 및 변경 권한 없음 조건을 보존하는 스키마 제한 컴파일러와 비활성 발견 sink 주입 |
| **실시간 아웃바운드 스트림** | `SseSink` (비동기 publish + async-iterator 구독, SSE 페이로드) | - | `InMemorySseSink` (테스트/데브); HTTP `text/event-stream` 어댑터는 콘솔 읽기 전용 표면과 함께 랜딩 | 양방향 표면이 필요하면 WebSocket 어댑터로 교체; 헤드리스 관찰기는 웹훅 전용. `shared/streaming/SseBroadcaster` 가 `EventBus` 토픽을 채널로 릴레이. |
| **파이프라인 스테이지 발행자** | `StagePublisher` (`shared/providers/stage_publisher.py`) 의 `emit(StageEvent)` | - | `NullStagePublisher` (기본 - 스테이지 코드가 관찰 사이드이펙트 없이 실행되도록 유지) | 인프로세스 데브 / 단일 레플리카: `SseSinkStagePublisher` 가 `SseSink` 로 바로 동시 확산. 멀티 레플리카 프로덕션: `EventBusStagePublisher` 가 Kafka 토픽(기본 `fdai.pipeline.stages`) 에 발행하고 기존 `SseBroadcaster` 가 모든 레플리카가 소비하는 SSE 채널로 릴레이. 파이프라인 스테이지 (`event_ingest`, `trust_router`, T0/T1/T2, `risk_gate`, `executor`, `audit`) 가 프로토콜을 받도록 backward-compat - 업스트림 기본은 아무 것도 발행 하지 않음. |
| **콘솔 읽기 패널** | `ReadPanel` (`delivery/operator_api/panels.py`) | - | 코어 라우트만 (`/audit`, `/kpi`, `/hil-queue`); `ExampleFinOpsPanel` 은 참조용으로 제공되지만 UI 최소화를 위해 **미등록** | 포크가 `OperatorApiConfig.extra_panels` (각각 GET 전용 라우트로 래핑, 빌드 시 경로 검증) + 콘솔 `panels.tsx` 레지스트리 항목으로 버티컬 대시보드(FinOps 비용, 드리프트 보드, DR 드릴 이력) 추가 |
| **T2 결정론적 검증 근거** | `Container.t2_deterministic_evidence_verifiers`를 통해 주입하는 `DeterministicEvidenceVerifier` 구현 | - | 런타임은 명시적인 사용 불가 `what_if` 및 `security` 검증기를 연결하므로 권위 있는 생산자 두 개 없이는 T2가 적격이 될 수 없습니다. | 시뮬레이션 엔진과 보안 스캐너 구현을 버전 있고 후보에 연결된 레코드와 함께 모두 주입합니다. 부분 연결, 오래되거나 충돌하는 근거, 합성 라이브 근거, 범위가 제한되지 않았거나 중복된 근거 메타데이터는 계속 보류합니다. |
| **LLM 계량(metering)** | `MeteringSink` / `MeteringReader` (`core/metering/sink.py`); `MeteringEmitter`가 명시적인 `control_plane` 또는 `operator_chat` 범위와 함께 프로바이더가 측정한 `usage`를 기록 | - | 단일 프로세스 dev 실행 장치는 하나의 `InMemoryMeteringSink`를 공유합니다. T1, T2, 서술기 어댑터가 측정된 토큰을 발행합니다. 두 Azure 조립 분기는 같은 sink와 가격표를 Conversation Assurance에 전달합니다. 독립적인 Operator 서비스는 `GET /kpi/llm-cost`를 유지하고 SELECT-only 역할로 영속 `llm_invocation` 행을 읽으며 상세를 제한하되 token-only 집계는 정확하게 유지합니다. Interactive 로컬은 준비된 권위 있는 입력에서 정제된 인벤토리와 Settings 변환 결과를 별도로 materialize합니다. | 설정된 가격은 내부 예산 컨트롤에 남고 프로바이더 지출로 변환 결과되지 않으며, 누락된 프로바이더는 synthetic 대신 사용 불가 상태를 유지합니다. |
| **Infra 모듈** | `infra/modules/<seam>/` (Terraform 서브-모듈, `var.<seam>_kind` 로 선택) | - | Container Apps + PostgreSQL Flex + Event Hubs Kafka + Key Vault + Log Analytics | [csp-neutrality-ko.md § 승인된 대안 Azure 구현](csp-neutrality-ko.md#승인된-대안-azure-구현approved-alternative-azure-implementations) 에 따라 다른 서브-모듈 선택; 모듈의 출력 계약은 고정 유지 |

모든 경계가 주입되는 인터페이스이므로 고객 추가나 두 번째 클라우드는 구현 등록 문제입니다 -
위의 엄격한 단방향 의존 방향이 보존됩니다.

**동시성 자세**: `EventBus`, `StateStore`, `SecretProvider`, `WorkloadIdentity`, `Inventory`,
`MetricProvider`, `LogQueryProvider`, `TraceQueryProvider` 같은 I/O-bearing 프로바이더 프로토콜은
**기본 비동기**입니다. 구체 구현을 sync로 강제하면 이벤트 루프를 블록합니다.
**CPU / 시작 경계** - `SchemaRegistry`, `ContractValidator` / `EventValidator`,
`ConfigProvider` - 은 **sync 유지**: 시작 시 한 번 실행되거나, I/O 없는 순수 CPU 경계
검증이므로 비동기 래퍼는 노이즈만 추가합니다. 테스트는 `pytest-asyncio` + `asyncio_mode =
"auto"` 로 실행되어 평범한 `비동기 def test_...` 가 per-test 마커 없이 동작합니다. `InvestigationCoordinator`는 기본적으로 직렬 실행하며 요청 순서와 대상별 오류 격리를 보존합니다. 예약 Analyzer 조립은 동시 대상 평가 상한을 4로 명시합니다.

공유 `MetricProviderError` 계약은 범위가 제한된 실패 메타데이터를 소유합니다. Azure 전송 계층이 실패를 분류하고 Analyzer가 식별자를 제거합니다.
[메트릭 진단 계약](aks-diagnostic-evidence-plane-ko.md#안전한-메트릭-실패-진단)은 기존 공급자와 빈 결과의 동작을 유지하며, 실패 시 안전한 쪽으로 처리를 중단합니다.

시작 준비 상태의 프로바이더 중립 실행 예산, 탐색 시간 제한 및 파생 근거 수명은 `core/readiness`가
소유합니다. 런타임은 범위가 제한된 새로 고침을 예약하고 기존 만료 시점에 처리를 닫으며, Thor가
privileged I/O 전에 확인하는 실제 상한을 제공합니다. 어느 계층도 배포 권한을 높일 수 없습니다.
조정기는 영속화와 전환 발행 전에 축약된 전체 보고서를 공유 의사 결정 근거 승인 결과에
연결합니다. 승인 결과가 없거나 일치하지 않으면 차단되지 않은 보고서를 `DEGRADED`로 바꾸고 모든
기능을 최대 `SHADOW`로 제한하므로, 검증되지 않은 배포 권한을 주장하지 않으면서 읽기 전용 처리를
계속할 수 있습니다.

[에이전트 판테온 구현 계획](../agents/agent-pantheon-implementation-ko.md#범위가-제한된-공유-상태)이 공유 `StateStore`의 범위 제한 제거 및 재생 의미 체계를 소유합니다.

## 관련 문서

| 알아볼 내용 | 문서 |
|-------------|------|
| 상위 설계 | [프로젝트 구조](project-structure-ko.md) |
| 제공 상태 및 남은 작업 | [구현 원장](../../roadmap-implementation/architecture/project-structure-dependency-injection.md) |
