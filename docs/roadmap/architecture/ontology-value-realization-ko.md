---
title: Ontology Value Realization
translation_of: ontology-value-realization.md
translation_source_sha: ec7ed7a4acbf87a932f878c5497570944770f631
translation_revised: 2026-11-09
---
# 온톨로지 가치 실현

이 문서는 FDAI가 온톨로지에 근거한 추론을 측정된 운영 가치로 바꾸는 방법을 정의합니다. 온톨로지와 워크플로우 시스템의 현재 수준에 대한 냉정한 평가, 작업 범위를 정하는 결정, 통제된 안전성과 입증된 성과 사이의 격차를 메우는 단계를 기록합니다. 에이전트, 권한, 두 번째 의사결정 파이프라인은 추가하지 않습니다.

> **범위:** 여기서 가치는 측정된 운영 단위입니다. 시간, 통화가 명시된 비용, 건수를 뜻합니다. 매출 귀속, CRM, 고객 분석은 [Outcome Assurance](outcome-assurance-ko.md#비목표)의 비목표와 같이 범위 밖입니다. 단위를 비즈니스 수치로 환산하는 일은 배포 측 결정입니다.
>
> **권한 경계:** 모든 산출물은 읽기 모델 또는 게이트 입력입니다. 온톨로지 판독은 게이트를 닫아 둘 수만 있고 실행 권한을 줄 수 없습니다. 가치 주장은 승인, 승격, 실행을 하지 않습니다.

## 한눈에 보는 설계

FDAI는 이미 개체, 관계, 시간, 근거를 타입이 있는 온톨로지에 근거시키고 모든 액션을 승인, 감사, 효과 검증으로 통제합니다. 남은 격차는 가치 입증입니다. 워크플로우가 온톨로지 추론을 거의 사용하지 않고, 대부분의 추론 엔진은 테스트에서만 실행되며, 근거는 대부분 fixture 기반이고, 주장한 개선을 기준선과 비교해 정산하는 원장이 없습니다. 아래 단계는 이 격차를 순서대로 메우며 각 단계에는 관찰 가능한 종료 조건이 있습니다.

## 평가

평가는 저장소를 객체와 링크, 함수, writeback이 있는 통제된 액션, 의사결정 애플리케이션, what-if 시나리오, 측정된 피드백 루프를 갖춘 온톨로지 중심 운영 플랫폼의 공개된 패턴과 비교합니다. 소스, 카탈로그, 원장을 정적으로 검토한 결과이며 라이브 검증은 하지 않았습니다. 표는 VR1 이전의 상태를 기록하며 이후 변경은 [구현 원장](../../roadmap-implementation/architecture/ontology-value-realization.md)에 기록합니다.

| 영역 | 관찰된 상태 | 평가 |
|------|-------------|------|
| 온톨로지 구조 | ObjectType 89개, LinkType 127개, 인터페이스 타입 7개, 모든 사실에 유효 시간과 출처가 있습니다. | 강함 |
| 함수 | 카탈로그에 선언된 FunctionType 1개와 `operational_function_types`가 등록하는 소스 파생 읽기 FunctionType 약 40개가 있습니다. 모두 읽기 전용 근거 조회입니다. 워크플로우를 위한 판단, 점수, 예측을 계산하는 함수는 없습니다. | 근거 조회는 넓고 판단 함수는 없음 |
| 인과 추론 | 카탈로그에는 인과 메커니즘이 12개 선언되어 있습니다(`causal-mechanisms.yaml`). 별도의 55개 시나리오 인과, 예측, 영향 엔진이 `CatalogCausalGradeBridge`로 연결되어 있습니다. | 반박 읽기와 연결됨 |
| 비즈니스 계층 | `BusinessService`는 식별, 중요도, 소유를 가집니다. 목표는 서비스에 연결됩니다. | 영향이 서열형이며 측정값이 아님 |
| 워크플로우 | 카탈로그 워크플로우 16개가 모두 `shadow`입니다. 2개 워크플로우(`blast-radius-gated-service-restart`, `change-risk-gated-scale-in`)가 `ontology-function:` 게이트를 사용합니다. | 초기 온톨로지 함수 게이트 연결됨 |
| 액션 도달 범위 | ActionType 58개 중 직접 executor 바인딩이 있는 것은 약 10개, PR 기반 shadow가 23개, 바인딩이 없는 것이 9개입니다. | 대부분 제안 수준 |
| 근거의 현실성 | 역량 영수증은 `deterministic_fixture`, 검색 평가는 합성 데이터, typed selection은 shadow, 외부 벤치마크 하네스는 휴면 상태입니다. | 라이브 정확도 주장을 뒷받침하지 못함 |
| 가치 측정 | 비용 효과 정산, MTTR, DORA, cohort 주장은 부품으로 존재합니다. 주장한 개선을 정산하는 워크플로우 단위 원장은 없습니다. | 부품은 있으나 루프는 닫히지 않음 |
| 데이터 범위 | Azure Resource Manager와 Kubernetes입니다. 고객 시스템 어댑터는 남은 작업입니다. | 달성 가능한 가치의 한계 |

강점은 거버넌스이고 약점은 입증된 추론과 가치입니다. FDAI는 3단계가 독립 관측으로 주장을 정산하기 전에는 비즈니스 가치를 주장하지 않아야 합니다.

## 결정

아래 결정으로 범위를 고정해 추가 합의 없이 단계를 진행할 수 있게 합니다.

1. **가치 루프 3개.** Resilience(재사용 가능한 AKS 상거래 시나리오의 MTTR), Cost Governance(기존 정산을 통한 실현 절감), Change Safety(기준선 대비 리드 타임, 변경 실패율, 롤백률)입니다.
2. **매출이 아니라 단위.** 가치 주장은 초, 단일 통화의 비용 금액, 건수를 기록합니다. 업스트림 저장소는 금액 환산 비율을 보관하지 않습니다.
3. **기준선 대비 보수적 값.** 기준선과 처리군은 같은 시나리오 집합 버전을 쓰고, 처리군은 기간이 끝난 뒤 관측하며, 보고 값은 95% 구간의 보수적 경계입니다.
4. **독립성.** executor 출력은 근거가 되지 않습니다. 정책 이탈은 주장한 모든 가치를 차단합니다.
5. **fixture는 테스트 전용.** fixture는 계약을 증명할 수 있지만 측정된 성과를 증명할 수 없습니다. 측정 주장은 배포 저장소에 보관된 정제된 리플레이 또는 라이브 cohort를 사용합니다.
6. **제한된 도입.** 한 번에 측정된 프로세스 하나를 승격하며, 게이트 증거가 생기기 전에는 shadow 기본값을 유지합니다.

## 단계

### VR0 - 가치 주장 원장

- 타입이 있는 가치 주장, cohort, 정산 계약을 정의합니다.
- 완전하고 독립적이며 범위가 일치하고 표본 하한을 넘는 cohort로만 주장을 정산합니다.
- 주장에 워크플로우, 버전, 목표, 근거 참조를 기록합니다.

### VR1 - 온톨로지를 아는 워크플로우

- `ontology-function:<function>` 게이트 참조로 온톨로지 함수 판독을 읽는 게이트를 추가합니다. 완전하고 최신이며 영수증이 있고 함수가 정확히 일치하는 결과일 때만 열립니다.
- 폭발 반경, 변경 위험, 지연 비용에 대한 판단 함수를 추가합니다. 각각 결정론적이고 읽기 전용이며 리플레이할 수 있어야 합니다. 비용 지연은 게이트가 없는 순위 신호입니다. 비용 임계값은 FinOps가 담당할 비즈니스 결정이기 때문입니다.
- 반증 읽기가 있는 인과 메커니즘 카탈로그를 늘리고 기존 엔진을 같은 근거 규칙 뒤에 연결합니다.
- 카탈로그 워크플로우 2개 이상을 shadow에서 온톨로지 함수 게이트에 바인딩합니다.
- 읽기 전용 근거 reader로 판단 함수를 런타임 온톨로지 그래프, provider가 관측한 변경 피드, 관측된 비용에 바인딩합니다. 잘렸거나 오래되었거나 합성이거나 충돌하거나 관측되지 않은 원본은 게이트를 닫고, 검토된 구성은 임계값을 선택하며 근거는 선택하지 않습니다.
- 온톨로지 네이티브 워크플로우 기본 요소(`core/workflow/ontology_native.py`: `ObjectSetWorkflowInput`, `ForEachObjectSetRunner`, 영수증 바인딩 `${step.<id>.output.<field>}` 치환, `evaluate_ontology_decision_branch`, `OntologyConditionTriggerEvaluator`, `OntologyOwnershipApprovalResolver`), 고도화 판단 함수와 머클 DAG 합성 실행기(`core/ontology_platform/advanced_decision_functions.py`: `decision.slo_exhaustion_eta`, `decision.change_collision`, `decision.recovery_feasibility`, `decision.spof_exposure`, `OntologyFunctionDagRunner`), FinOps 가치 모델링(`core/ontology_platform/finops_value_modeling.py`: `CostObservationOntologyProjector`, `decision.budget_burn_risk`, `score_business_service_criticality`, `filter_safe_sizing_recommendations`, `evaluate_unit_economics`), 시나리오 브랜치 디지털 트윈 시뮬레이션(`core/ontology_platform/digital_twin_simulation.py`: `simulate_workflow_on_scenario_branch`, `compare_counterfactual_options`, `build_workflow_topology_preview`, `validate_chaos_spof_recovery_readiness`)을 제공합니다.
- T2 추론을 화이트리스트 판단 도구, shadow 워크플로우 컴파일러, 실시간 RCA 가설 필터, 기권 시 근거 수집 계획, 승인권자 브리핑 패키지(`core/ontology_platform/aip_agent_integration.py`)와 연결합니다.

### VR2 - 실데이터 근거

- 검토된 라벨과 분리된 holdout이 있는 정제된 사고 cohort를 보관합니다.
- 근본 원인 top-1과 top-3 정확도, 올바른 기권, 잘못된 액션 비율, 근거 확보 시간을 보고합니다.
- 동등성 절차로 Azure SRE Agent와 비교합니다.
- 라이브 모델은 명시적으로 요청할 때만 실행합니다.

### VR3 - 루프 닫기

- 가치 루프마다 워크플로우 하나를 일반 게이트로 승격합니다. 실제 executor 바인딩, 스테이징 동등성(`verify_action_staging_parity`), Wave 5 확장 안전 제어(`WorkflowScaleSafetyController`), 독립 효과 검증이 필요합니다.
- 루프마다 독립 관측으로 가치 주장 하나를 자동 정산(`PostWindowValueClaimAutoSettler`)하고 동등성을 벤치마크(`evaluate_sre_agent_parity_cohort`)합니다.
- 기대 효과와 관측 효과의 차이를 운영 학습으로 환류(`recalibrate_option_utility_from_settlement`)합니다.

### VR4 - 소비와 도달 범위

- 추천 액션, 근거, 불확실성, 기대 효과, 승인 제어를 보여 주고 게이트 없는 `decision.cost_of_delay` 순위 신호로 정렬하는 운영자 의사결정 큐(`core/decision_case/decision_queue.py`, `core/ontology_platform/enterprise_governance_bridges.py`)와 Console Decision Inbox(`build_decision_inbox_view_model`), 워크플로우별 `ValueClaim` 드릴다운 뷰(`build_workflow_value_claim_drilldowns`)를 추가합니다.
- 벤더 중립 배포 및 서비스 카탈로그 브리지(`DeploymentAndServiceCatalogBridge`), ITSM 변경 창·온콜 교대조 및 티켓 감사 매핑 브리지(`EnterpriseGovernanceOntologyBridge`)를 추가합니다. 특정 비 Azure 외부 벤더 어댑터는 개별 명시적 승인 후 추가합니다.
- 워크플로우, 비즈니스 시나리오, 원자적 규칙, 프레임워크 컨트롤(WAF/CAF/WARA/MCSB), 모범 사례, 베이스라인, 프로브, 그리고 클라우드 도메인 아키텍처 지식(예: AKS 네트워크 정책 종류 등)에 대한 자연어 질문이 실행 권한 없는 인용 기반 `QueryTable` 행을 반환하도록 읽기 전용 시맨틱 쿼리 함수 5종(`catalog.search_workflows`, `catalog.search_business_scenarios`, `catalog.search_rules_and_controls`, `catalog.resolve_governance_chain`, `catalog.search_cloud_reference`, `core/ontology_platform/catalog_knowledge_queries.py` 및 `config/cloud-reference-corpus.yaml`)을 `build_semantic_query_runtime`에 바인딩합니다.
- 데이터 연결, 가치 주장 선언, 기준선, shadow, 승격 순서의 도입 플레이북을 게시합니다.

## 유스케이스 온보딩 플레이북

1. **데이터 연결.** 활성 인벤토리 스냅샷(`Resource`), 서비스 카탈로그(`BusinessService`, `Workload`, `implemented_by`), provider 변경 피드, `RecoveryPlan` 레코드를 런타임 온톨로지 인스턴스 그래프에 바인딩합니다.
2. **가치 주장 선언.** 워크플로우 참조, 목표 참조, 지표 이름, 단위(`duration_seconds`, 통화가 있는 `cost_amount`, `count`), 개선 방향, 시나리오 집합 버전, 기간 경계, 최소 표본 하한을 담은 `ValueClaimDeclaration`을 선언합니다.
3. **기준선 확보.** 처리군을 활성화하기 전에 동결된 시나리오 집합 버전에 대해 `ObservationLane.INDEPENDENT_OBSERVATION`의 완전한 `CohortRole.BASELINE` cohort를 수집합니다.
4. **shadow 검증.** `config/workflow-ontology-gates.yaml` 게이트(`decision.blast_radius`, `decision.change_risk`) 뒤에서 워크플로우를 `shadow` 모드로 실행하고, `CatalogCausalGradeBridge`와 `evaluate_disjoint_causal_holdout`으로 인과 가설을 검증하며, `decision.cost_of_delay` 순위 신호를 사용해 `DecisionQueueProjection`에서 우선순위를 검토합니다.
5. **승격과 정산.** 정책 이탈 0건으로 승격 게이트를 통과한 뒤 루프당 워크플로우 하나를 승격하고, 기간 종료 후 독립 관측에서 `CohortRole.TREATMENT` cohort를 수집해 `settle_and_publish_value_claims`로 95% 보수적 경계를 `StateStoreValueClaimLedger`와 Outcome Assurance에 기록합니다.

## 성공 지표

| 지표 | 시작점 | VR3 종료 목표 |
|------|--------|---------------|
| 온톨로지 함수 결과를 소비하는 워크플로우 | 0 | 2개 이상 |
| 소스 파생 판단 함수 | 0 | 3개 이상 |
| 연결된 인과 메커니즘 | 1 | 8개 이상 |
| 보관된 holdout의 근본 원인 정확도 | 없음 | 구간과 함께 보고 |
| 승격된 워크플로우 | 0 | 3개 |
| 독립 정산된 가치 주장 | 0 | 루프당 1개 |
| 정책 이탈 | 0 | 0 |

## 비목표

- 매출, 고객, 제품 분석.
- 복합 가치 점수 또는 성숙도 점수.
- 온톨로지 판독이나 가치 주장에서 나오는 권한.
- 업스트림 저장소의 고객 데이터, 테넌트 값, 금액 환산 비율.

## 관련 문서

| 알아볼 내용 | 문서 |
|-------------|------|
| 구현 현황과 남은 작업 | [구현 원장](../../roadmap-implementation/architecture/ontology-value-realization.md) |
| 결과 projection과 비목표 | [outcome-assurance-ko.md](outcome-assurance-ko.md) |
| 온톨로지 계층과 권한 | [operating-ontology-ko.md](operating-ontology-ko.md) |
| 워크플로우 전달 Wave | [customer-workflow-automation-plan-ko.md](../decisioning/customer-workflow-automation-plan-ko.md) |
| 워크플로우와 제어 루프 | [workflow-control-loop-integration-ko.md](../decisioning/workflow-control-loop-integration-ko.md) |
| 비즈니스 시나리오 | [aks-commerce-business-scenario-ko.md](../operations/aks-commerce-business-scenario-ko.md) |
