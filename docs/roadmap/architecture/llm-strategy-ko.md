---
title: LLM 전략(LLM Strategy)
translation_of: llm-strategy.md
translation_source_sha: 0cdcd039a0200ed893104abe5339abba268df047
translation_revised: 2026-08-28
---
# LLM 전략(LLM Strategy)
이 설계는 LLM을 **덜 사용**합니다. 모델은 **T2** 대체 경로이며 T0와 T1이 사례를 해결하지 못했을 때만 사용합니다. 결정론적 검증이 승인하기 전에는 모델 출력을 실행에 사용하지 않습니다. 실행 자격은 검증이 부여하며 **모델은 부여하지 않습니다**. 이 문서는 [architecture.instructions.md](../../../.github/instructions/architecture.instructions.md)의 tier 및 quality-gate 규칙과 [security-and-identity-ko.md](security-and-identity-ko.md)의 위협 모델을 확장합니다.
> 가용성, 가격, 미리 보기 상태가 바뀌므로 채택 시 모델 권장 사항을 확인하세요. 구체 모델은 가정이 아니라 시나리오 세트에서 측정한 비용과 품질로 선택합니다.
## 구현 상태
### 구현 범위
| 영역 | 상태 | 근거 | 참고 |
|------|------|------|------|
| 기능 레지스트리, 해석 및 프로비저닝 평가 | implemented | `rule-catalog/llm-registry.yaml`; `rule_catalog/schema/llm_resolver.py`; `provisioning_assessment.py`; 집중 resolver 테스트 | 기능과 모델 대응, 명시적 용량 단위, 혼합 발행기 불변식 및 실패 시 차단 준비 상태를 실행할 수 있습니다. |
| 발행기 한정 Foundry 카탈로그 검색 | implemented | `delivery/azure/llm/resolver_queries.py`; 집중 resolver 및 adapter 검사 | 선택적 발행기 인식 경계는 OpenAI, Anthropic 및 MistralAI 계열을 구분하고 안정된 AIServices 버전을 읽으며 기존 adapter의 계열 전용 대체 경로를 보존합니다. Partner 배포 및 endpoint routing은 미완료 상태입니다. |
| 환경 모델 바인딩 정책 및 PTU 계획 | implemented | `fdai_service_contracts/model_binding.py`; `model_binding_policy.py`; Operator IAM 바인딩 경로 및 PostgreSQL 어댑터; `model_binding_proposal.py`; `model-settings-projection.yml`; Console 모델 편집기; 보호된 배포 워크플로; 집중 계약, 해석기, Operator, Console 및 Terraform 검사 | Owner는 모든 T1/T2 기능에 리비전이 있는 `auto`, `pinned` 또는 `hil-only` 의도를 저장할 수 있습니다. 보호된 runner는 권한이 없는 정확한 계획 제안 하나를 현재 정책과 결합한 후 PTU와 정확한 모델 버전을 평가합니다. 별도 3-way CAS는 runtime Settings를 바꾸지 않고 정제된 모델 Settings projection을 복원합니다. Console과 Operator에는 공급자 변경 또는 실행 권한이 없습니다. |
| 후보 전용 의미 판단 및 계획 | implemented | `core/conversation/semantic_judgment.py`; `core/conversation/semantic_planning.py`; `composition/wire_semantic_query.py`; Azure 의미 어댑터; 집중 판단 및 계획 테스트 | 범위가 제한된 T1 판단은 같은 바인딩에서 잘못된 스키마 출력을 다시 시도한 후 선택적으로 T2로 전환합니다. 수락된 의미는 계획에 사용될 수 있지만 실행 권한을 부여하지 않습니다. |
| T2 교차 검사, 검증기, 근거 확인, 신뢰도 및 rubric | implemented | `core/quality_gate/`; `delivery/azure/llm/rubric.py`; 집중 quality 게이트 및 Azure 어댑터 테스트 | 필수 4개 경로와 선택적 감산 rubric이 있습니다. 근거가 없거나 잘못되면 거부, 판단 보류 또는 사람 검토로 결과를 낮춥니다. |
| 에스컬레이션 정책과 같은 발행기 primary 지연 시간 라우팅 | implemented | `core/quality_gate/escalation_ladder.py`; `delivery/azure/llm/latency_routed_cross_check.py`; `composition/wire_llm.py`; 집중 라우팅 테스트 | 에스컬레이션 단계는 권한을 갖지 않으며 지연 시간 선택은 secondary 발행기로 넘어갈 수 없습니다. 별도의 범위 제한 제안자 대체 경로는 등록된 secondary 제안자를 호출할 수 있지만, 해당 후보도 같은 quality 게이트로 다시 들어갑니다. |
| T2 제안자 장애 조치, 영속 복구 근거 및 통제된 경로 선택 | implemented | `core/tiers/t2_reasoning/recovery.py`; `runtime/t2_{recovery,route_registry}.py`; `ops.switch-t2-proposer-route`; 집중 런타임 및 판테온 체인 테스트 | 실제 제안자 시도마다 예산을 예약하고 민감정보가 제거된 영속 근거를 발행합니다. 최종 소진은 Thor가 경로 변경을 영속화하기 전에 사람 승인으로 이동하며, Vidar는 실패한 변경만 복원합니다. 이 문서에는 통제된 배포 복구 캠페인이 보존되어 있지 않습니다. |
| 모델 수명 주기 만료 검토 메커니즘 | implemented | `model_lifecycle_review.py`; `model_lifecycle_reconciler.py` 제안 스키마 v3; 집중 수명 주기 및 Key Vault 출처 테스트 | 제안은 정확한 출처 다이제스트와 영향 기능을 결합합니다. 만료된 미병합 검토는 매핑을 바꾸지 않고 권한 없는 보류를 만듭니다. 직접 Key Vault 출처 어댑터가 있지만 시작 로드, PR 수명주기 관측, 결정 영속화 및 런타임 보류 적용은 열려 있습니다. |
| 운영 모델 근거와 강제 적용 승격 | in-progress | `core/measurement/model_tracking.py`; [목표와 메트릭](goals-and-metrics-ko.md#구현-상태) | 측정과 승격 계약이 있지만 모든 활성 T1/T2 기능의 보존된 실제 운영 집단은 이 문서에서 입증되지 않습니다. |
| 주간 모델 조정기와 검토된 교체 흐름 | in-progress | `.github/workflows/model-lifecycle-reconcile.yml`; `scripts/deployment/azure/model_lifecycle_reconciler.py`; 집중 수명 주기 및 보호된 workflow 테스트 | 제안 전용 경로는 모델 계열, 발행자, 상태, SKU, 용량 단위, 용량 값을 비교하고 정제된 근거를 만듭니다. 공급자 실패 시 판단을 보류하며, 활성화 권한이 없는 멱등적 초안을 열 수 있습니다. 만료된 제안을 평가하거나 런타임 보류 상태로 연결하는 경로가 없고, 통제된 실행 증적도 보존되어 있지 않습니다. |
### 구현 이력
| 날짜 | 상태 | 변경 | 근거 | 남은 작업 |
|------|------|------|------|-----------|
| 2026-08-28 | implemented | Azure OpenAI 및 AIServices 모델에 대해 이전 버전과 호환되는 발행기 한정 카탈로그 검색과 안정된 partner 버전 조회를 추가했습니다. | `current change`; 집중 resolver 검사(`46 passed`); Ruff 및 strict mypy. | Partner registry preference를 활성화하기 전에 발행기 인식 Terraform account, 배포 format, private endpoint 및 runtime endpoint binding을 추가해야 합니다. |
| 2026-08-14 | in-progress | 이전 이력을 재구성하지 않고 구현 원장을 도입했으며 quality 게이트 상태를 현재 resolver, rubric, 에스컬레이션 및 지연 시간 라우팅 코드에 맞췄습니다. | `current change`; 위의 레지스트리, quality 게이트, Azure 어댑터, 조립 및 측정 경로입니다. | 운영 모델 근거를 보존하고 통제된 조정기 흐름을 구현합니다. |
| 2026-08-19 | implemented | 실제 모델 해석을 보호된 계획에 연결하고, 정확한 전체 및 배포 매니페스트를 계획 메타데이터에 봉인했으며, 적용 시 같은 JSON과 SHA를 복원하고, 제안 전용 주간 수명 주기 조정기를 추가했습니다. | `current change`; 집중 모델 수명 주기, 계획 검증기, Operator 서술기, Terraform 및 권한 workflow 검사. | 통제된 조정기 실행을 한 번 보존하고, 레지스트리나 배포를 바꾸기 전에 모든 교체 초안을 별도로 검토합니다. |
| 2026-08-21 | implemented | 기존 `GlobalStandard` 1K TPM 임베딩 배포와 검토된 `Standard` 200K TPM 후보를 변경 없음으로 잘못 분류한 문제를 수정했습니다. 수명 주기 제안은 이제 SKU와 유효 용량을 포함합니다. 보호된 계획은 정확한 주소, 모델 계열, 계정 연결, 기존 SKU/용량, 목표 SKU/용량, 교체 작업이 모두 일치할 때만 이 전환을 허용합니다. | `current change`; `model_lifecycle_reconciler.py`; `deploy-dev.yml`; 집중 수명 주기 검사 5개와 파괴적 계획 검사 2개 통과. | 정확한 보호 계획만 적용하고 교체와 런타임 연결을 검증한 뒤 적용 증적을 보존하고 수렴 후 범위가 제한된 이행 승인을 제거합니다. |
| 2026-08-23 | implemented | 후보 전용 의미 판단을 읽기 전용 의미 계획에 연결하고, 선택적 T2 전환 전에 같은 바인딩에서 최대 3회의 스키마 복구를 시도하며, 액션 자세와 액션 주체의 정합성을 적용했습니다. | `current change`; `semantic_judgment.py`; `semantic_planning.py`; `wire_semantic_query.py`; 집중 의미 판단, 어댑터, 티어 라우팅 및 조립 검사. | 보존된 실제 운영 shadow 집단에 스키마 복구 시도, 복구, 전환 및 계획 처리 결과 측정을 추가합니다. |
| 2026-08-23 | implemented | 제공된 T2 제안자 복구 계약을 이 소유 문서에 기록했습니다. 범위가 제한된 시도는 Huginn 유입 전에 민감정보가 제거된 증적을 영속화합니다. 최종 소진은 Heimdall이 축약하고 Forseti가 판정하며, 승인된 경로 변경은 Thor, 추가 전용 감사 및 상관관계로 제한된 Vidar 롤백을 사용합니다. 복구된 시도는 관측으로 남고 새 승인을 열지 않습니다. | 커밋 `68f0d4014`와 `e96416ce1`; `recovery.py`; `t2_recovery.py`; `t2_route_registry.py`; `test_{t2_recovery,t2_route_registry}.py`; `test_t2_recovery_chain.py`. | 재시작 복구, 소진에서 승인으로의 전환, 경로 변경, 실패한 검증의 롤백, 오래된 롤백 거부 및 새 승인 없는 복구를 입증하는 정확한 개정 번호의 통제된 캠페인을 보존합니다. |
| 2026-08-23 | in-progress | 소스와 workflow 검토에서 제안 만료가 영향받는 기능을 사람 검토로 낮추지 않는다는 점을 확인해 수명 주기 범위를 바로잡았습니다. 예약 workflow는 제안 전용으로 유지되며 보존된 실행이 없습니다. | `current change`; `.github/workflows/model-lifecycle-reconcile.yml`; `scripts/deployment/azure/model_lifecycle_reconciler.py`; 집중 수명 주기 계약 테스트. | 권위 있는 런타임 모델 소스에 만료-보류 경로를 구현한 뒤 보호된 예약 실행을 한 번 보존하고 모든 교체 초안을 별도로 검토합니다. |
| 2026-08-23 | implemented | 로컬에서 실행 가능한 만료 검토 범위를 추가했습니다. 수명 주기 제안 v3는 정본 출처 모델 다이제스트와 영향 기능을 기록합니다. 순수 평가기는 해당 정확한 출처의 만료된 미병합 제안만 보류하고 늦은 병합 근거를 거부합니다. Operator 소유 비동기 Key Vault 출처는 공식 Azure vault origin과 audience, 정확한 secret 신원, 크기, JSON 깊이, 활성화 및 만료 상태, 전체 마감, secret-safe 오류와 표현을 검증합니다. | `current change`; 집중 수명 주기 및 Key Vault 테스트; 15회의 비평 및 하드닝 라운드는 검증된 Medium 이상 결함 없이 종료됐습니다. | 비동기 출처 로드와 신뢰할 수 있는 PR 수명주기 관측을 시작 과정에 연결하고, 결정을 영속화 및 검증한 뒤 모델 매핑을 바꾸지 않고 기능 바인딩 전에 보류를 적용합니다. |
| 2026-08-24 | implemented | 모든 T1/T2 기능에 리비전이 있는 환경 바인딩 초안, 완전한 후보 단위의 TPM/PTU 대체 선택, 정확한 GA 버전 봉인, Owner 전용 평가 및 계획 요청, 활성 산출물 다이제스트 차단, Terraform 버전 고정을 추가했습니다. | `current change`; 공통 정책, 해석기, Azure 조회, Operator IAM, Console 모델, 보호된 워크플로 및 Terraform 경로; 완료 보고서에 기록된 집중 검사. | 이 경로를 validated로 분류하기 전에 보호된 PTU 계획, 적용, 롤백 증적과 적용 후 독립 바인딩 검증을 보존합니다. |
| 2026-08-24 | implemented | 의도적으로 사용할 수 없는 secondary 발행기로 인해 일반 완전성 게이트가 Terraform 전에 중단되는 것을 실제 평가에서 확인한 뒤, 모델 바인딩 전용 보호 배포 모드를 추가했습니다. 범위가 제한된 `plan-model-*` 및 `apply-model-*` 요청 ID는 환경 정책과 보호 요청을 요구하고 Azure OpenAI 모듈만 대상으로 삼으며 봉인된 Cognitive deployment 변경만 허용합니다. 또한 교체 버전, SKU, 용량을 resolved artifact와 대조합니다. | [이슈 #270](https://github.com/dotnetpower/fdai/issues/270); `deploy-dev.yml`; `test_model_resolution_lifecycle.py`; 집중 보호 workflow 검사 60개, YAML 구문 분석 및 Ruff 통과. | 이 경로를 validated로 분류하기 전에 정확한 PTU 계획, 적용, 독립 런타임 검증 및 역방향 계획 롤백을 실행합니다. |
| 2026-08-24 | implemented | 보호 작업 종류와 모델 정책 환경, 리비전, 다이제스트, 활성 산출물 제한을 변경할 수 없는 계획 메타데이터에 결속했습니다. Exact 적용은 다른 작업 종류 또는 환경을 거부하고, 중복된 resolved 기능은 재생에 실패하며, 독립 management-plane readback은 배포된 모델 계열, 버전, SKU, 용량, 프로비저닝 상태를 비교한 뒤 민감정보가 제거된 증적을 기록합니다. | [이슈 #270](https://github.com/dotnetpower/fdai/issues/270); `verify-deployment-plan.py`; `verify_model_deployments.py`; 보호 workflow 및 resolver 검사 107개 통과; Ruff, strict mypy 및 YAML 구문 분석 통과; 비평 10회 뒤 검증된 미해결 결함은 Low 이하만 남았습니다. | 정확한 PTU 계획 및 적용과 역방향 계획 롤백 증적을 보존한 뒤 Core와 Operator가 봉인된 런타임 다이제스트를 사용하는지 검증합니다. |
| 2026-08-24 | implemented | YAML 들여쓰기로 모델 전용 범위 검사가 monitoring script 안에 포함된 문제를 수정해 실행 가능한 workflow 단계로 복원하고, 사용 중단 중인 출처 모델 계열은 정확히 봉인된 GA 모델 계열, 버전, SKU 및 PTU 용량으로만 이동하도록 허용했습니다. 출처 모델, SKU, 용량, 배포 이름 및 계정 연결 검증은 유지합니다. | [이슈 #270](https://github.com/dotnetpower/fdai/issues/270); 실행형 workflow 단계 및 합성 교체 검사; 집중 모델 검사 45개와 embedded Python block 17개 통과. | 정확한 보호 PTU 계획, 적용, 독립 readback, 런타임 바인딩 및 역방향 계획 롤백 증적을 실행하고 보존합니다. |
| 2026-08-24 | implemented | 첫 보호 PTU 계획의 Model Capacities 요청이 adapter의 고정 30초 제한을 초과해 Terraform 전에 중단된 뒤 범위가 제한된 Azure CLI resolver deadline을 추가했습니다. CLI는 5-300초를 허용하고 catalog, permission, quota 및 PTU 질의에 같은 제한을 사용하며 보호 workflow는 90초를 선택합니다. | [이슈 #270](https://github.com/dotnetpower/fdai/issues/270); 실패한 계획 `32749593774`; 집중 resolver 및 workflow 검사 62개, strict mypy 및 embedded Python 검사 17개 통과. | 새 deadline으로 보호 계획을 다시 실행하며 공급자가 다시 초과하면 새 근거 없이 재시도하지 않습니다. |
| 2026-08-25 | implemented | 변경 가능한 Terraform 입력 CAS를 정확한 healthy active Core revision, digest-pinned image, 검증된 resolved-model attestation 및 runtime model digest로 대체했습니다. 별도 Core 전용 service transition이 모델 계획 전에 attested artifact를 결속하며 exact 적용은 같은 revision, image 및 model digest를 다시 관측합니다. | [이슈 #270](https://github.com/dotnetpower/fdai/issues/270); active-runtime 및 attestation 검증기, 보호된 service guard 및 plan bundle, 통합 모델/service 검사 249개 통과. | Core binding transition을 적용한 뒤 PTU 계획, 적용, readback 및 역방향 계획 롤백 증적을 보존합니다. |
| 2026-08-25 | implemented | 변경 가능한 repository 모델 정책 입력을 정확한 Operator 계획 제안 하나를 가져오는 보호된 runner 경로로 대체했습니다. 읽기 전용 결합은 모델 해석 전에 제안, 요청, 정책, 환경, 리비전, 활성 산출물 및 권한 제한을 검증합니다. | `current change`; `model_binding_proposal.py`; `deploy-dev.yml`; 집중 제안, 요청, 수명 주기 및 workflow 검사. | 통제된 제안-계획 증적 하나를 보존한 뒤 exact 적용, 독립 readback 및 롤백 근거를 완료합니다. |
| 2026-08-25 | implemented | 누락된 deployed 모델 Settings projection을 위한 보호된 producer를 추가했습니다. Repository 산출물, 활성 Core runtime 및 서명된 image attestation 다이제스트가 일치할 때 model projection만 기록한 뒤 환경과 다이제스트를 다시 읽습니다. | `current change`; `model-settings-projection.yml`; `materialize-authoritative-settings.py`; 집중 projection 및 workflow 검사. | Owner 초안과 계획 제안을 제출하기 전에 통제된 projection 증적 하나를 보존합니다. |
| 2026-08-25 | implemented | Key Vault URI heredoc에 YAML 들여쓰기가 남아 실행할 수 없던 protected 모델 Settings producer shell을 복구했습니다. Workflow는 migration secret을 읽기 전에 anchored Bash 표현식으로 같은 공식 vault origin을 검증합니다. | `current change`; `model-settings-projection.yml`; 집중 workflow 및 privileged CI 계약 45개 통과; `actionlint` 통과 | Owner 초안과 계획 제안을 제출하기 전에 통제된 projection 증적 하나를 보존합니다. |
### 남은 작업
- [ ] [목표와 메트릭](goals-and-metrics-ko.md#남은-작업)과 [Agent Pantheon 구현 계획](../agents/agent-pantheon-implementation-ko.md#남은-작업)의 실제 운영 KPI 선행 조건을 충족한 뒤, 활성화된 모든 T1/T2 기능에 대해 모델 신원, 비용, 지연 시간, 스키마 복구 시도와 복구 결과, 전환, 계획 처리 결과, 불일치, 근거 확인, 검증기, rubric, 결과 및 가드 근거가 포함된 고정된 실제 운영 shadow 집단을 보존합니다.
- [ ] 범위가 제한된 시도 예산, 재시작 후 영속 증적 전달, 최종 소진에서 사람 승인으로의 전환, 감사된 경로 변경, 상관관계로 제한된 롤백 및 새 승인 없는 복구를 입증하는 통제된 T2 복구 캠페인을 보존합니다.
- [ ] 구현된 만료 미병합 평가기와 직접 Key Vault 출처 어댑터를 비동기 시작 소유자를 통해 연결합니다. 신뢰할 수 있는 PR 수명주기 관측, 제안 및 결정 다이제스트 검증, 영속화, 바인딩 전 기능 보류를 추가합니다. 영향받는 기능이 모델 매핑을 바꾸지 않고 사람 검토로 이동함을 입증한 뒤, 사용 중단 또는 모델 계열 표류가 정제된 초안 PR만 만드는 통제된 예약 실행 증적을 보존합니다. 시작 및 출처 계약은 [Narrator 라우팅 및 지연 시간](../interfaces/narrator-routing-and-latency-ko.md#남은-작업)이 소유합니다.
- [ ] 선택적 rubric, 에스컬레이션 호출 또는 primary pool 행동은 고정된 재현과 독립 검토 후 [권위 있는 ActionType 레지스트리](../decisioning/action-ontology-ko.md#33-governance)를 통해서만 승격하며 누락된 바인딩은 실패 시 차단을 유지합니다.
- [ ] 프로비저닝된 SKU를 평가하고 정확한 모델 버전과 PTU 용량을 봉인하며 승인된 계획을 적용하고 런타임 바인딩을 독립 검증한 뒤 롤백을 연습하는 보호된 환경 정책 캠페인 하나를 보존합니다. Console 또는 Operator ID에는 공급자 변경 권한을 부여하지 않습니다.
## 모델 티어
커버리지 수치는 **측정된 베이스라인에 대해 검증할 목표**
([goals-and-metrics-ko.md](goals-and-metrics-ko.md)) 이지 보장이 아님. 이들은 하나의 이벤트
스트림을 분할하므로 T0+T1+T2는 ~100%; T0 (~70-80%) 는
[architecture.instructions.md](../../../.github/instructions/architecture.instructions.md) 에
문서화.

| 티어 | 역할 | 모델 클래스 | 커버리지 목표 | 비용 프로파일 |
|------|------|-------------|-------------|-------------|
| **T0** | 결정론 엔진 | **모델 없음** | ~70-80% | 토큰 0 |
| **T1** | 유사도 + 경량 판단 | **임베딩 모델** + **소형/저렴 LLM** | ~15-20% | 매우 낮음 |
| **T2** | 신규/모호 케이스에 대한 추론 | **프론티어 LLM (2+ 독립)** | ~5-10% | 최고; mixed-model 교차 검사 필수 |

### 티어 경계

- 결정론 판정을 산출하는 규칙 없고 케이스가 신규는 아닐 때 **T0 → T1**.
- T1이 **abstain** 할 때만 **T1 → T2**: 정확한 규칙 매칭 없음, 이전 해결된 인시던트에 대한
  임베딩 유사도가 설정 스코어 임계 아래, 적용 가능한 학습된 액션 없음.
- 유사도 임계와 abstain 조건은 **설정** , 하드코딩 아님.
## T1 - 경량 티어

- **임베딩**: 작은 임베딩 모델이 인시던트를 벡터화하고 과거 패턴과 대응시킵니다. 비용 효율이 높은 호스팅 모델을 우선 사용하고, 데이터 잔류지나 비용이 요구하면 로컬 sentence-transformer를
  사용합니다([데이터 프라이버시](#data-privacy-and-residency) 참조). 벡터는 상태 옆에 저장합니다(예: pgvector).
- **후보 전용 의미 판단**: 소형 지시 모델이 범위가 제한된 문맥과 주체 범위로 제한된 기능을 사용해 타입이 지정된 의도, 대상, 요청 정보, 신뢰도, 모호성 및 액션 자세를 제안합니다.
  스키마가 잘못되면 범위가 제한되고 민감정보가 제거된 복구 정보만 전달하며 같은 바인딩에서 최대 3회 시도한 후 선택적으로 T2 바인딩으로 전환합니다. 호출자는 전환을 비활성화할 수 있습니다.
- **검증된 계획 입력**: 수락된 판단은 신뢰할 수 없는 입력 묶음 안에서 의미 계획으로 전달됩니다. 결정론적 코드는 `advise_only`를 `action_subject: none`으로 정규화하고, `draft_only`에는 타입이 지정된
  주체를 요구하며, 결과 프레임과 계획을 검증합니다. 어느 모델도 권한이나 실행 자격을 부여하지 않습니다.
- 목표: 프론티어 왕복 없이 이벤트의 ~15-20% 흡수.
## T2 - 추론 티어 (Quality 게이트 필수)

T2는 신규 또는 모호 케이스만 처리(~5-10%). 그 출력은 실행 전 quality 게이트 통과해야 함.
모델은 **후보를 생성** ; 결정론 검증기가 자격을 결정.

- **Mixed-model 교차 검사**: 같은 판단에 대해 **2개 이상 독립 모델** 실행. 독립은 진짜 별개
  프로바이더/가중치 - 같은 base 모델을 서비스하는 두 엔드포인트는 **세지 않음** , correlated
  에러가 검사 무력화.
  - **합의 조건식**: 합의는 자유 텍스트가 아니라 **정규화 구조화 액션** (대상 리소스, 작업,
    파라미터) 에 대해. 정본 액션 객체를 문자열 아이덴티티가 아니라 의미 등가로 비교.
  - **N 모델과 정족수**: N ≥ 3 인 경우 설정된 정족수(예: majority) 요구; 정족수 없음 → escalate.
    2-of-2 동점(불일치) 는 HIL로 escalate, 절대 auto-resolve 아님.
  - **비용 컨트롤**: **cascade** 선호 - 더 저렴한 reasoner 먼저 실행하고 self-consistency나
    grounding 신호가 약할 때만 두 번째 호출 - 그래서 전체 N-모델 동시 확산은 진짜 어려운 케이스에만
    지출.
  - **출처 이력 (재현성)**: 결정은 **각 모델의 투표**
    (`QualityDecision.model_votes`: `model_id`, 제안 액션 타입, agreed)를 - 단순 동의
    카운트가 아니라 - 기록해, T2 판정을 추가 전용 감사 에서 재구성할 수 있게 한다(로그가
    약속하는 재생 속성).
- **검증기**: 어떤 모델과도 독립적인 **결정론** 검사가 후보 액션을 policy-as-code와 what-if/
  예행 실행에 대해 재검증 후 execution-eligible. 검증기 - 모델 텍스트 아님 - 가 권위.
- **Grounding (RAG)**: 판단을 정당화하는 규칙/정책/문서 인용 강제, **각 인용 항목이 규칙 카탈로그
  에 존재하고 실제로 주장을 지지하는지 검증**(fabricated 인용 방어). Ungrounded 시 **abstain**.
- **임계 게이팅**: 스키마, 정책, what-if, 보안-스캔 검사가 모두 통과해야 하고 계산된 **신뢰도**
  가 임계 통과해야 함. 신뢰도는 검증기와 교차-검사 신호(합의, grounding 유효성, 역사적 성공)
  에서 파생 - **절대 모델의 self-reported 신뢰도가 아님** , 신뢰할 수 없음. 임계 아래는 HIL로
  라우팅.

### 결과 시맨틱

- **조건을 충족한** - 모든 게이트 통과; 리스크 게이트로.
- **abstain** - 근거에 기반한, 지지된 답 없음; 자율 액션 없음, HIL로 라우팅.
- **disagree/escalate** - 모델이 정족수 실패; HIL로 라우팅.
- **거부** - 검증기 또는 정책이 후보 거부; no-op, 감사됨.

네 개 모두 타입된, 감사된 결과; **조건을 충족한** 만 실행으로 진행 가능.

![결과 시맨틱. 주요 단계는 novel or ambiguous case, mixed-model pool: 2+ independent models, quorum agreement?, escalate to HIL, deterministic verifier: policy-as-code and what-if, deny: no-op, audited, grounded and citations valid?, abstain to HIL, confidence over threshold?, execution-eligible to risk gate입니다.](../../diagrams/generated/fdai-roadmap-architecture-llm-strategy-01.ko.svg)

### 루브릭 게이트 (환각 필터)

선택적인 다섯 번째 축이 후보의 추론을 고정된 기준(충실도, 근거-행동 정합성, 완전성,
일관성)으로 채점하고 최저 점수를 `min()`으로 confidence에 반영합니다. **감산 전용**이므로
루브릭은 자격을 낮출 수는 있어도 절대 높일 수 없습니다. Shadow 우선으로 도입하며(promotion
게이트를 충족할 때까지 판정 후 기록만), 평가기 오류 시 HIL로 fail-closed 처리합니다. 판정자는
제안자와 다른 publisher여야 합니다(모델이 자기 답을 채점할 수 없습니다). 전체 설계는
[hallucination-rubric-gate.md](../decisioning/hallucination-rubric-gate-ko.md)를 참고하세요.

## 프롬프트 인젝션 방어

이벤트 페이로드와 도구 출력은 **신뢰할 수 없는** 이며 직접 또는 간접 프롬프트 인젝션 운반 가능
([security-and-identity-ko.md](security-and-identity-ko.md)).

- 모든 페이로드와 도구-출력 텍스트를 **지시가 아니라 데이터** 로 취급; 모델은 거기 임베드된 지시를
  따르면 안 됨. 프롬프트에서 신뢰할 수 없는 구간을 delimit하고 격리.
- **간접 인젝션**: 도구/RAG에서 반환된 출력이 모델에 재공급 - 같은 격리 적용, retrieved 텍스트가
  액션 계약을 변경하지 못하게.
- **검증기와 정책 재검사가 권위** ; 오직 "sound"만 승인되고 결정론 검사를 실패하는 후보는 거부.
- 어떤 모델 호출 **전에** 시크릿과 식별자 redact - 인젝션이 생성 출력으로 exfiltrate 못하도록.

## 데이터 프라이버시와 잔류지

- **최소화와 redact**: 모델 호출 전 프롬프트에서 시크릿, 연결 문자열, 어떤 고객/테넌트/구독
  식별자도 제거; 필요한 최소 페이로드 전송.
- **잔류지 라우팅**: 민감 이벤트를 설정으로 로컬/in-region 모델(예: 로컬 임베딩) 로 라우팅;
  제한된 데이터를 외부 엔드포인트로 보내지 않음.
- **No-train / 보존**: 제출된 프롬프트에 대한 **no-training** 보장과 최소 보존 있는
  엔드포인트 선호; 기능별 선택된 자세를 구성에 기록.

## 프로바이더 추상화

- 모든 모델 호출은 `shared/` 의 **프로바이더 중립적인 클라이언트** 를 통해 감 - 모델이 `core/tiers`
  를 만지지 않고 스왑 가능.
- 모델을 하드코딩 이름이 아니라 기능으로 설정: `t1.embedding`, `t1.judge`, `t1.vision`,
  `t2.reasoner.primary`, `t2.reasoner.secondary`, `t2.rca`.
- **클라이언트 계약**: 요청 시간 초과, 구조화/JSON-schema 출력, 토큰 회계, 재현 가능 설정
  (지원되는 곳에서 temperature 0 + 고정 시드) 강제 - 그래서 교차 검사와 리플레이가 비교 가능.
- **버전된 매핑**: 기능→구체-모델 매핑은 버전됨; 결정에 사용된 정확한 모델 ID와 구성
  버전은 리플레이를 위해 감사 로그에 기록.
- Azure OpenAI, 다른 Azure Foundry 모델, 또는 서드파티 엔드포인트로 순전히 구성으로 라우팅,
  코어를 CSP-중립 유지.

### Heterogeneous 엔드포인트 및 게이트웨이 계약

FDAI는 모델 기능, 프로바이더, 경로, wire 프로토콜, authentication, 용량을 서로 분리된
필드로 해석합니다. 따라서 T1/T2 코어 계약을 변경하지 않고 Azure OpenAI direct,
Azure API 관리(APIM)을 경유하는 Azure OpenAI, APIM을 경유하는 OpenAI-compatible
자체 호스팅 GPU 모델을 사용할 수 있습니다.

`resolved-models.json`은 선택적 `endpoint_bindings`를 포함합니다. 검증된 각 연결은 다음을
선언합니다.

- **프로바이더 및 경로:** `azure-openai` 또는 `self-hosted`를 `direct` 또는 `apim-gateway`와
  독립적으로 선언합니다.
- **Wire 프로토콜:** Azure 배포 경로(`azure-openai`) 또는 요청 본문 모델 id를 사용하는
  `/v1` 경로(`openai-v1`)를 선언합니다.
- **Authentication:** Entra 대상 또는 자격 증명 참조를 선언합니다. 현재 런타임 T1/T2
  연결은 Entra를 요구하며 지원되지 않는 auth 종류는 direct 엔드포인트 대체 경로 대신 시작을
  차단합니다.
- **용량:** 하나의 양수 값과 함께 `tpm`, `ptu`, `gpu`를 선언합니다. PTU와 GPU 값은 TPM처럼
  변환하지 않습니다.
- **Feature 및 출처 이력:** 스트리밍, embeddings, 구조화된 출력, 도구 calling, 발견
  출처, resource-reference 다이제스트, 검증 시간을 포함합니다.

엔드포인트 URL과 자격 증명은 운영자 변환 결과에 serialize하지 않습니다. 연결은 opaque
`endpoint_ref`를 저장하고 조립 루트가 protected 배포 구성에서 HTTPS URL로
해석합니다. 해석기가 주입되지 않은 연결은 시작에 실패합니다. 임베딩, 제안자,
기본 및 보조 교차 검증, 비평자, Judge, RCA, 서술기 경로가 같은 request-target 빌더를
사용합니다. `endpoint_bindings`가 없는 이전 방식 파일은 direct Azure OpenAI 경로를 유지합니다.

APIM은 경로 및 거버넌스 경계이며 모델 발행기가 아닙니다. Mixed-model quality 게이트는
게이트웨이 뒤의 발행기와 계열을 계속 비교합니다. 기본과 보조 기능은 같은 APIM
hostname을 사용해도 별도 연결을 유지하며 same-publisher 쌍은 계속 잘못된입니다.

자체 호스팅 엔드포인트는 virtual 네트워크 검사 또는 `/v1/models`만 신뢰해 discover하지 않습니다.
Publisher-keyed domain-separated Ed25519 등록
(`fdai.model-endpoint-registration.v1`)을 통해 후보 집합에 들어옵니다. 잘못된 서명은
parse 전에 차단합니다. 등록된 GPU 모델이 shadow 모드를 벗어나기 전 기능 탐색과 quality
재생이 계속 필요합니다.

프로비저닝된 용량 발견은 Azure 모델 Capacities 관리 API를 사용합니다. 실제 운영 해석기는
regional 카탈로그에서 최신 generally available 모델 버전을 먼저 선택한 뒤 모델 format, 계열,
버전으로 subscription-scoped 용량 엔드포인트를 조회합니다. 응답을 지역 및 프로비저닝된
SKU로 필터하고 범위가 제한된 `management.azure.com` 페이지 나누기만 따라가며 `availableCapacity`를 PTU로
사용합니다. 카탈로그 버전 누락, malformed 응답, 신뢰할 수 없는 next 링크, 서비스 용량 부족은
`hil-only`로 실패 시 차단 처리합니다.

APIM 경로는 `x-fdai-model-backend`, `x-fdai-capacity-unit`, `x-fdai-spillover` 응답 헤더를
반환해야 합니다. T2 제안자 및 교차 검증 클라이언트는 근거가 누락되거나 malformed이면 성공
응답도 거부합니다. 수락된 근거는 영속 model-health 싱크를 통해 민감정보가 제거된 `selected`
전이를 덧붙이기하고 실제 백엔드, TPM/PTU/GPU 단위, spillover 결정, 연결 id를 기록합니다.
엔드포인트 URL, APIM 요청 id, 프로바이더 오류 텍스트는 저장하지 않습니다.

`infra/modules/llm/apim-ai-gateway`의 선택적 Terraform 패키지는 기존 APIM 인스턴스에 하나의
기능을 연결합니다. FDAI 호출자의 Entra 대상을 검증하고 managed 신원으로 APIM을 두
Azure OpenAI 백엔드에 인증하며 첫 요청을 PTU로 보내고 HTTP 429에서 same-family Standard
배포로 정확히 한 번 재시도한 뒤 mandatory 근거 헤더를 발행합니다. APIM 서비스는
생성하지 않습니다. 루트 조립은 모듈을 기본 비활성화된으로 유지하므로 minimum-cost day-zero
인벤토리는 변경되지 않습니다.

`fdai-model-endpoint-discovery`는 protected management-plane 병합 명령입니다. Strict 구성은
예상 Azure OpenAI 계정/배포 및 APIM API/백엔드를 나열하며 엔드포인트 URL 또는 자격 증명
값을 받지 않습니다. Azure 출처는 계정 종류, 배포 준비 상태, 모델 계열/버전,
SKU, TPM/PTU 용량을 검증합니다. APIM 출처는 API, 두 백엔드 id, managed-identity 정책,
HTTP 429 전환, 모든 FDAI 근거 헤더를 검증합니다. 중복 기능 경로는 출력 전에
실패합니다. Command는 검증된 연결을 기존 `resolved-models.json`에 atomic mode-`0600` 쓰기로
병합하고 `--force` 없이 overwrite하지 않습니다.

Signed 자체 호스팅 등록은 injected `Ed25519SignedRegistrationSource`를 통해 같은 출처
집계 경로를 사용합니다. 따라서 raw GPU 엔드포인트는 범용 Azure 발견 구성에 들어가지
않고 발행기 키가 등록 문서 parse 전에 필요합니다.

## 모델 프로비저닝과 라이프사이클

모델 가용성, 버전, 폐기는 지속 shift. 모델 id 하드코딩은 rot 보장. 아래 프로비저닝 모델은 기능→구체-모델 매핑을 **부트스트랩에서 자동, 업데이트 시 리뷰** 로 유지, 다른 어떤 변경
처럼 모델 변경이 shadow-before-enforce 원칙을 통해 흐르도록.

### 기능 바인딩 정책

`rule-catalog/llm-registry.yaml`은 상류 기본값을 정의합니다. 리전 또는 프로비저닝된 처리량
(PTU) 제약으로 더 좁은 바인딩이 필요하면 Owner가 T1 또는 T2 기능별 리비전 환경 정책을
제출할 수 있습니다. 정책은 런타임 스위치가 아니라 거버넌스 초안입니다. Operator API는
의도를 저장하고 검토된 보호 계획만 활성 산출물을 교체할 수 있습니다.

| 선택 모드 | 해석기 동작 | 실패 동작 |
|-----------|------------|----------|
| `auto` | 완전한 레지스트리 후보를 순서대로 평가합니다. | 다음 후보를 평가하고 없으면 `hil-only`로 유지합니다. |
| `pinned` | 요청한 발행기, 계열, SKU 및 용량만 평가합니다. | 사람 검토로 유지하며 다른 계열로 대체하지 않습니다. |
| `hil-only` | 기능에 모델을 바인딩하지 않습니다. | 종속 결정을 사람 검토로 유지합니다. |

```yaml
capability: t2.reasoner.primary
selection_mode: pinned
publisher: OpenAI
family: gpt-4o
sku: GlobalProvisionedManaged
capacity: { unit: ptu, value: 30 }
```

- **환경 범위:** 정책은 사용자나 대화가 아니라 하나의 배포 환경에 적용됩니다.
- **정확한 계획:** 평가는 호환 GA 버전을 선택하고 보호 계획은 해당 버전, SKU, 용량,
  정책 다이제스트 및 활성 산출물 다이제스트를 적용까지 고정합니다.
- **후보 완결성:** `auto`는 발행기-계열-버전-SKU-용량 후보를 완전하게 평가합니다.
- **용량 단위:** Standard SKU는 TPM, 프로비저닝된 SKU는 변환 없는 PTU를 사용합니다.
- **T2 쌍 원자성:** 보류 상태가 아니면 primary와 secondary는 서로 다른 발행기여야 합니다.
- **Console 권한 없음:** 초안, 평가 및 계획 요청은 공급자를 변경하지 않습니다. 보호된 모델 계획은 하나의 요청 ID로 정확한 Operator 제안과 정책 다이제스트를 식별합니다. Runner는 PostgreSQL을 변경하지 않고 읽으며 오래되었거나 권한을 포함한 상태를 차단합니다.
- **독립 도구:** 검색, RCA, rubric, escalation 및 tool calling은 별도 게이트를 유지합니다.

### 부트스트랩 Provisioner

`azd up` 또는 동등한 절차에서 resolver는 레지스트리와 승인된 환경 정책을 결합하고 Azure
OpenAI / Foundry 카탈로그 및 용량 표면을 조회하여 **구체 기능당 하나의 배포**를
프로비저닝합니다. 가상 `t1.vision`은 일치하는 narrator 배포를 재사용하며 Key Vault와 감사가
해석된 매핑을 보존합니다. Azure delivery는 `(publisher, family)` 쌍을 보고하고 허용된
OpenAI/AIServices format을 매핑하며 두 값을 안정된 버전 키로 사용합니다. 계열 전용 adapter는
호환되며 partner 활성화는 발행기 인식 인프라와 endpoint binding을 기다립니다.

배포자가 `Cognitive Services Contributor` 를 갖지 않을 때, 선호 계열이 리전에 없을 때,
`capacity_tpm` 쿼터가 부족할 때, mixed-model 불변식을 만족할 수 없을 때의 **배포자-권한 게이트
전체 표** 는
[dev-and-deploy-parity-ko.md § 배포자-스코프 LLM 프로비저닝](../deployment/dev-and-deploy-parity-ko.md#배포자-스코프-llm-프로비저닝)
에서 저술; 이 섹션은 happy-path 형태만 보여줌.

![부트스트랩 Provisioner. 주요 단계는 Terraform / Bicep: azd up, Azure OpenAI or Foundry resource, resolver, llm-registry.yaml, query catalog: / available families + versions in region, for each capability: / first preference available, capability를 hil-only로 표시 / completeness impact 보고, create deployment / with TPM or PTU capacity, verify mixed-model invariant: / primary.publisher ≠ secondary.publisher, FAIL, write resolved-models.json to Key Vault / + audit entry입니다.](../../diagrams/generated/fdai-roadmap-architecture-llm-strategy-02.ko.svg)

**부트스트랩 불변식 (MUST)**
- 누락된 역할, 선호 계열 부재, zero 할당량 같은 환경 실패는 영향을 받은 기능을
  `hil-only`로 표시하고 계속합니다. 프로비저닝 평가가 이 성능 저하를 표시하며
  배포는 `--assess-fail-on critical`로 차단하도록 선택할 수 있습니다.
- 두 T2 reasoner가 명시적 `hil-only` 모드 밖에서 모두 해석되면
  `t2.reasoner.primary.publisher`와 `t2.reasoner.secondary.publisher`는 달라야 합니다.
  Same-publisher 쌍은 hard 해석기 오류입니다.
- Resolved 매핑은 기능당 `{deployment, family, version, publisher}` 를 기록하여 감사
  로그가 어떤 케이스를 결정한 정확한 모델을 이름 지을 수 있음.

### 프로비저닝 완결성 게이트

해석기는 프로비저닝 불가능한 기능을 `hil-only`로 강등시키고 계속한다 -
하나의 누락된 계열 때문에 전체 부트스트랩을 막지 않으므로 **부분 배포가
조용하다**: `resolved-models.json`이 T1 쌍 + `t2.reasoner.primary`만 담고 있는데
레지스트리는 보조 reasoner, 비평자, RCA reasoner, 에스컬레이션 상한까지
선언할 수 있다. 그러면 조립 루트는 조용히 forced-disagree 교차 검증으로
대체 경로 하고 모든 T2 케이스가 HIL로 라우팅되며, reasoning 계층이 사실상 꺼졌다는
신호가 배포 시점에 없다.

[`assess_provisioning`](../../../services/core-control-plane/src/fdai/rule_catalog/schema/provisioning_assessment.py)
이 그 공백을 닫는다. 권위 `llm-registry.yaml`(의도)과 `resolved-models.json`(실제)
을 비교해 결정론적 `ProvisioningReport`를 반환한다:

- 선언된 각 기능을 `resolved` / `capacity-reduced` / `hil-only` / `missing`
  으로 분류하고 `core` / `quorum` / `optional`로 태깅하며, 부재 시 런타임 영향을 명시;
- `quorum_ok`는 mixed-model T2 교차 검증이 형성 가능한지(두 reasoner 가용 + 다른
  발행기) 보고 - `hil-only` 모드에서는 기대하지 않음;
- `ProvisioningSeverity`가 `ok`(전부 resolved), `degraded`(선택적 기능만
  누락 - 토론 / RCA / 에스컬레이션 / 평가 기준 off는 허용), `critical`(코어 기능
  누락 또는 정족수 미형성 - T2가 사실상 off)로 롤업.

배포 파이프라인은 심각도로 게이팅하고 리포트를 감사 로그에 기록(`critical` 시 A2
운영 알림)하므로, 반쪽만 프로비저닝된 reasoning 계층이 런타임 HIL storm으로 숨지
않고 `azd up` 시점에 보인다.

부트스트랩 CLI가 이를 직접 노출한다: `fdai-llm-resolver --assess-fail-on critical`
은 평가를 stderr에 출력(`critical` 시 `A2 alert:` 라인)하고 non-zero로 종료하므로,
CI 배포 단계가 모든 T2 케이스를 조용히 HIL로 보내는 reasoning 계층을 배포하기 전에
차단한다. 기본값 `--assess-fail-on none`은 하위호환을 위해 report-only로 유지된다.

### 런타임 해석

코어 코드는 기능 계약에만 의존. `resolved-models.json` 은 시작 시 Key Vault에서 로드;
stale 참조(배포 삭제 또는 404) 는 다른 기능이 아니라 **HIL로 fail-close**.

```python
# core/tiers/t2-reasoning/reasoner.py (illustrative)
primary   = client.for_capability("t2.reasoner.primary")
secondary = client.for_capability("t2.reasoner.secondary")
cand_a = primary.chat(...)
cand_b = secondary.chat(...)
if not agree(cand_a, cand_b):
    escalated = client.for_capability("t2.reasoner.escalated")   # cost-capped
    return arbitrate(cand_a, cand_b, escalated.chat(...))
return quorum_result(cand_a, cand_b)
```

- `core/` 에 모델 id가 나타나지 않음.
- 누락 배포는 장애로 취급: 요청은 HIL로 라우팅되고 운영 알림 발행(A2, [channels-and-notifications-ko.md](../interfaces/channels-and-notifications-ko.md#3-categories-a1a4)
  에 따라). 다른 기능로의 조용한 스위치는 금지.

### 에스컬레이션 단계 구조 정책

위의 `if not agree(...): escalated = ...` 스텝은 하드코딩된 분기가 아니라
**정책 결정**이다. [`core/quality_gate/escalation_ladder.py`](../../../services/core-control-plane/src/fdai/core/quality_gate/escalation_ladder.py)
(`decide_escalation`)에 순수·결정론 함수로 구현되며, 형제
[`debate_router`](../../../services/core-control-plane/src/fdai/core/quality_gate/debate_router.py)를 그대로
미러링한다: 고정된 `EscalationLadderConfig` + "더 강한 모델로 올라갈까,
멈추고 HIL로 라우팅할까?"에 답하는 stateless 함수. 정책을 먼저 단독으로 -
라이브 배선 전에 테스트·감사 가능하게 - 출하하는 것은 debate-router
delta-2a -> delta-2b 순서를 따른다. `QualityGate`는 `EscalationLadderConfig`가
배선되면 결정을 **shadow**(`QualityDecision.escalation_route` /
`escalation_reason`, 그리고 읽은 `self_consistency` stability,
`quality_decision_audit_fields`로 표면화)로 기록한다 - 측정만 하고 행동은 안 함;
escalated 모델을 실제 호출하는 것은 다음 강제 적용 스텝. `on_self_consistency_below`
트리거는 조립 루트의 self-consistency cascade가 후보에 얹은
`action_stability` 신호를 읽는다 - 게이트는 모델을 직접 샘플링하지 않는다(샘플러의
"cascade 트리거는 조립 관심사" 계약).

어떤 트리거도 단계 구조를 오르기 전에 검증된 온톨로지, 룰 또는 deterministic-evidence 개선의 trusted
개수가 필요합니다. 기본 최소는 10입니다. 개수는 모델 후보가 아니라 orchestration에서 오며,
개수와 구성된 최소 모두 `escalation_metadata`에 기록됩니다. 개수가 없으면 0으로 기본 설정되어
`ontology_improvement_budget_remaining`으로 안전하게 중단됩니다. 영속 case-history orchestration이
개수를 공급하고 별도 승격이 호출을 활성화할 때까지 shadow 관측으로 유지됩니다.

단계 구조 rung(`EscalationTier`)은 레지스트리 기능과 일대일:
`PRIMARY` -> `SECONDARY` -> `ESCALATED`. `decide_escalation`은 `ESCALATE`
(다음 더 강한 reasoner를 tiebreaker로 소비) 또는 `STOP`(호출자가 미해결 케이스를
HIL로 라우팅)을 반환하며, 다음 하드닝 불변식을 지킨다:

- **단계 구조는 실행 자격을 절대 부여하지 않는다.** *더 강한 모델을 쓸지*만
  결정한다. escalated 모델의 제안도 신뢰할 수 없는 이며 같은 quality 게이트(검증기 +
  grounding + 정족수)로 재진입한다; disagreement는 단계 구조를 오른다고 auto-resolve
  되지 않으며 - 결정론 검증기가 유일한 권위로 남는다.
- **실패 시 차단.** `escalated_available=False`(`t2.reasoner.escalated`를 해석
  하지 않은 포크)는 `STOP`을 반환하며, precedence에서 deny-list보다 위.
- **Cost-bounded.** 한 번의 호출은 최대 한 rung만 오르고 `ESCALATED` 천장을
  넘지 않는다; `enabled=False`는 비용 spike용 killswitch.
- **Ontology-first.** 구성된 트리거가 있어도 trusted validated-improvement 개수가
  `minimum_ontology_improvement_attempts`에 도달하기 전에는 중단됩니다.
- **Triggers.** `cross_check_disagreement`(주 트리거, 레지스트리의
  `invocation: on_disagreement` 반영) + 선택적 `on_self_consistency_below`
  임계값(self-consistency 샘플러가 흔들리는 제안자를 보고하면 nominal agreement
  에서도 escalate). ActionType별 `never`/`always` 리스트로 튜닝하며 거부가 allow
  우선.

Resolved 모델 계열은 배포 별칭과 별도로 각 T2 어댑터에 전달됩니다. GPT-5 및 o-series
채팅 계열은 `max_completion_tokens`를 보내고 custom `temperature`를 생략합니다. Classic 채팅
계열은 `max_tokens`와 `temperature`를 유지합니다. 이 규칙은 기본 latency-pool 구성원을 포함한
RCA, 제안자 및 교차 검증 요청에 동일하게 적용되므로 friendly 배포 별칭이 잘못된 wire
필드를 선택할 수 없습니다.

### Narrator 라우팅 및 지연 시간

Narrator 배포 선택, 멀티모달 탐색, 사용자별 선호 설정, TTFT, 웹 검색 풀 및 런타임
전달 결정은 [Narrator 라우팅 and 지연 시간](../interfaces/narrator-routing-and-latency-ko.md)가
소유합니다. T2 quality-gate 배정은 system-governed 상태를 유지하며 same-publisher T2 기본
예외는 아래에 이어집니다.

### T2 기본 라우팅 및 통제된 복구

T2는 서로 다른 두 복구 범위를 사용합니다. 호출별 지연 시간 라우팅은
`t2.reasoner.primary` 슬롯 안의 배포 중 하나를 선택합니다. 요청 간 제안자 복구는 통제된 액션
파이프라인을 통해서만 선호하는 등록 제안자 경로를 바꿉니다. 어느 범위도 모델 출력에 권한을
부여하거나 mixed-model quality 게이트를 약화하지 않습니다.

- **동일 발행기 지연 시간 풀:** 모든 primary 풀 배포는 하나의 발행기를 공유하고, 그 발행기는
  `t2.reasoner.secondary`와 달라야 합니다. 지연 시간 라우팅은 primary 슬롯에만 적용되고,
  secondary 교차 검사, Critic, Judge 및 에스컬레이션 단계는 고정된 역할을 유지합니다. 리졸버는
  발행기가 섞인 풀을 거부합니다. `llm.t2_primary_latency_routing`은 기본값이 `true`이며 후보가
  두 개 이상일 때만 활성화되고, 후보가 하나이면 해당 primary를 그대로 사용합니다.
- **범위가 제한된 호출 내 선택:** 라우터는 선택한 배포를 기록하고, 프로바이더 오류 텍스트 없이
  실패를 분류하며, 범위가 제한된 cooldown을 적용하고, 남은 동일 발행기 배포를 각각 최대 한 번
  시도합니다. 교차 검사의 secondary를 지연 시간 primary로 대체하지 않습니다.
  `ModelHealthTransitionSink`는 선택, 비정상 및 복구된 배포 상태를 영속화합니다. 이 기록의 실패는
  실패한 모델 호출을 성공으로 바꾸거나 이미 성공한 제안을 차단하지 않습니다.
- **예산이 적용된 제안자 대체 경로:** `BoundedFailoverT2Proposer`는 실제 호출 전에 공유 T2 예산을
  예약하고 등록된 `primary` 및 `secondary` 제안자 경로를 각각 최대 한 번 시도합니다. 모든 후보는
  신뢰할 수 없는 상태로 같은 검증기, 근거 확인, 교차 검사 및 리스크 게이트에 다시 들어갑니다.
  예산 소진이나 전체 후보 실패는 더 약한 판단을 반환하지 않습니다.
- **영속 근거:** 각 시도는 경로 역할, 시도 번호, 상태, 실패 등급, 최종 상태 및 복구 상태를 담되
  끝점이나 예외 텍스트는 제외한 `T2AttemptReceipt`를 발행합니다. 런타임은 Huginn 유입 전에 증적과
  감사 항목을 저장하고, 전달되지 않은 증적을 다시 보내며, 프로바이더 호출을 재생하지 않고 범위가
  제한된 이전 실패를 구체화할 수 있습니다.
- **통제된 경로 변경:** 복구 증적은 정보로만 남습니다. 최종 후보 소진만 Heimdall 이상과 Forseti의
  `ops.switch-t2-proposer-route` `hil` 결정이 됩니다. Var가 승인을 운반하고, Thor가 멱등 CAS 경로
  변경을 수행하며, Saga가 감사 체인을 보존하고, Vidar가 실패한 상관관계의 변경만 복원합니다.
  오래된 롤백은 더 최신 경로 개정을 덮어쓸 수 없습니다. ActionType은 shadow 우선이며 강제 적용된
  전환 전에 사람 승인이 필요합니다.
- **읽기 전용 가시성:** 경로 상태와 증적은 재시작 후에도 유지됩니다. Operator 변환 결과는 모델
  상태와 민감정보가 제거된 복구 상세를 표시할 수 있지만 경로 변경, cooldown 해제, 승인 또는
  배포 승격을 수행할 수 없습니다.

조립은 구성된 제안자가 해당 프로토콜을 노출할 때만 관측기와 선택기를 연결합니다. 그렇지 않으면
기존 단일 경로 동작을 유지합니다.

### 조정기 작업

계획된 주간 작업은 더 선호되는 새 계열, 60일 안의 사용 중단, 측정된 용량 또는 품질 표류를 감시합니다. 범위가 제한된 이슈 또는 초안 PR과 A2 알림만 만들며 실제 매핑을 바꾸지 않습니다.
제안 스키마 v2는 모델 계열, 발행자, 상태뿐 아니라 SKU와 유효 용량 단위/값도 비교하므로 제자리 확장이나 교체를 변경 없음으로 잘못 분류하지 않습니다.
병합되지 않은 교체가 만료되면 기능을 사람 검토로 낮추고, 승인된 레지스트리 변경도 Owner 검토와 고정 시나리오 shadow 재현을 통과해야 합니다.

### Mixed-Model 계열 전략

Quality 게이트는 두 독립 모델 계열 필요. 포크가 실제로 얻는 쌍은 부트스트랩 시점 선택:

| 모드 | 보조 위치 | 언제 선택 |
|------|--------------|-----------|
| `azure-foundry` (기본) | Azure AI Foundry 모델 카탈로그를 통해 서비스되는 Anthropic / Mistral / Cohere 모델 | 리전과 컴플라이언스가 비-OpenAI Foundry 모델 허용; 단일 청구 표면 |
| `external` | 직접 서드파티 엔드포인트를 통한 보조(Anthropic API 등) | 필요 계열이 리전의 Foundry에서 이용 불가 |
| `hil-only` | 보조 프로비저닝 안 됨; 모든 T2 케이스가 HIL로 라우팅 | 포크가 두 번째 계열을 얻을 수 없음(일시); 명시적 명시적 선택 |

선택된 모드는 구성 값 (`llm.mixed_model_mode`); 부트스트랩 해석기가 이를 읽고 그에 따라
불변식 강제. 나중에 모드 스위치는 런타임 토글이 아니라 거버넌스 PR.

### 포크 vs 상류 분리

상류는 기능 이름, 스키마, 기본 선호, resolver 행동, mixed-model 불변식 및 범용 Azure IaC를
소유합니다. 포크는 지원되는 구성과 DI 경계로 지역, compliance, 비용, 일정, 알림, 리소스 및
해석된 모델 값을 제공합니다.

## Rule-to-Decision 조회 파이프라인

[모델 티어](#모델-티어) 의 티어 백분율은 의도적인 **계층 조회 파이프라인** 의 *결과* : 들어오는
이벤트가 저렴-비싼 레이어를 traverse하고, 프론티어 LLM(L5) 은 모든 저렴 레이어가 abstain할 때만
도달. 파이프라인은 타입된 **온톨로지** 에 빌드: 규칙, 리소스, 신호, 액션이 온톨로지 엔티티,
매칭은 텍스트-유사도 추측이 아니라 결정론 그래프 탐색.

온톨로지 프레이밍은 이전 AGI 온톨로지 설계(cardinality-aware 링크 있는 타입 객체, `required_
interfaces` 와 `submission_criteria` 통해 액션에 통합된 함수) 로부터 object-type / link-type
/ action-type 분리를 차용, CSP 리소스와 규칙에 적용. 이것이 모든 규칙에 결정론 전달 경로와
모든 재사용에 정본, hashable 서명을 부여.

### 온톨로지 기반

저수준 rule-dispatch 기반은 네 **ObjectType**으로 시작하며 [FDAI 운영 온톨로지](operating-ontology-ko.md)가 서비스, 목표, 결정, 효과 의미를 소유함.
확장 가능한 레지스트리는 프로세스, 대화, ReviewCase 같은 product 객체와 ResourceType, SignalType, Property, ActionType 같은 meta 객체를 일급으로 둠.
선언은 `rule-catalog/vocabulary/`에 있고 런타임 인스턴스는 shared 온톨로지 저장소를 사용함.

| ObjectType | 의미 | 백업 |
|------------|------|------|
| `Resource` | 거버넌스 아래의 대상(Azure 리소스; CSP-중립 스키마, 프로바이더 어댑터가 채움) | `shared/providers/` |
| `Rule` | 의도 있는 결정론 컨트롤(`applies_to`, `evaluates`, `remediates`) | `rule-catalog/` |
| `Signal` | 타입된 관찰(Activity Log 라인, 표류 차이, 비용 이상, canary 결과) - `event-ingest` 에 진입하는 기본형 | `shared/contracts/event` |
| `Finding` | 시점의 리소스에 대한 규칙 매칭, 컨텍스트와 심각도 포함 | 런타임에 파생; 감사 저장소에 지속 |

meta ObjectType은 LinkType 엔드포인트를 정직하게 만듦. `applies_to`는 `ResourceType`,
`triggered_by`는 `SignalType`, `evaluates`는 `Property`, `remediates`는 `ActionType`을 대상으로
함. 해당 카탈로그를 직접 읽는 배포에서는 런타임 인스턴스가 0개일 수 있지만, 선언 자체가
ActionType을 Rule로 모델링하는 엔드포인트 별칭을 방지함.

shipped ObjectType, LinkType, ActionType 선언은 모두 evidence-governed임. 출처 URL과
resolved 선언 버전을 인용하고 license와 수집 시간을 기록하며 로더가 검증하는
정본 내용 해시를 운반함. 출처 이력이 없거나 stale이면 카탈로그 조립을 차단함.

관계는 cardinality 메타데이터 있는 **타입된 LinkType** - 그래서 탐색은 스캔이 아니라
O(인덱스 조회). 각 선언은 `is_transitive`, `is_causal`, `temporal_order` 플래그도 함께
운반하므로 탐색 엔진이 재귀 확장이 안전한 시점과 쿼리가 시간을 존중해야 하는 시점을
알 수 있음. 시간 LinkType은 대상 ObjectType의 정렬 가능한 속성으로 해석해야 하는
`order_by_property`도 선언함. 인스턴스 저장소는 모든 링크 쓰기 전에 cardinality를 강제하고,
`is_transitive`가 true일 때만 같은 LinkType을 반복해서 순회하며, 시간 링크를 대상 속성
순서로 반환함. 이 값들은 시각화 힌트가 아니라 런타임 불변식임.

| LinkType | Cardinality | Transitive | 의미 |
|----------|-------------|:---------:|------|
| `applies_to` | Rule → ResourceType (M:M) | - | 규칙이 매칭할 수 있는 리소스 타입 |
| `triggered_by` | Rule → SignalType (M:M) | - | 규칙 평가를 유발하는 신호 |
| `evaluates` | Rule → Property (M:M) | - | 규칙이 읽는 리소스 속성 |
| `remediates` | Rule → ActionType (M:1) | - | 매칭 시 규칙이 제안하는 온톨로지 액션 |
| `resource_of` | 신호 → Resource (M:1) | - | 신호가 관한 리소스 |
| `overrides` | 재정의 → Rule (M:1) | - | 재정의가 이 규칙 대상([rule-governance-ko.md](../rules-and-detection/rule-governance-ko.md#override) 참조) |
| `causes` / `prevents` | Rule → 결과 (M:M, causal) | - | T2가 추론할 수 있는 causal 메타데이터(드묾) |
| `precedes` / `follows` | 발견 사항 → 발견 사항 (M:M, temporal) | - | 하나의 인시던트에 대한 관련 발견 사항 상관관계 |
| `contains` | Resource -> Resource (1:M, 부모 -> 자식) | ✓ | 소유/스코프 포함: 구독 -> resource-group -> 리소스, VNet -> 서브넷, 클러스터 -> node-pool입니다. 재귀 탐색은 저장된 parent-to-child direction을 따릅니다. [인벤토리 어댑터](csp-neutrality-ko.md#5-인벤토리-계약--리소스-그래프)가 채웁니다. |
| `attached_to` | Resource → Resource (M:1) | - | 수명 결합 첨부: NIC→VM, disk→VM, private-endpoint→대상. 부모 삭제 시 자식이 깨짐. |
| `depends_on` | Resource → Resource (M:M) | - | 정상 동작에 필요한 논리적 참조: ContainerApp→Key-Vault / ACR / Postgres, managed-identity→앱. 끊긴 엣지는 대상 이 아니라 dependent 를 degrade. |
| `peered_with` | Resource ↔ Resource (M:M, symmetric) | - | Independently supported directed 기록 두 개로 표현하는 네트워크 peer이며 기록 하나는 reverse를 imply하지 않습니다. |
| `routes_to` | Resource → Resource (M:1) | - | UDR next 홉 같은 directed 트래픽 경로 또는 참조이며 absence는 unreachable을 입증하지 않습니다. |

탐색은 방향적이고 캐시됨; 타입 `R` 의 `Resource` 에 대한 타입 `T` 의 `Signal` 은 두 인덱스
교집합을 통해 `triggered_by ∋ T` 및 `applies_to ∋ R` 인 정확한 규칙 세트로 해결 - 텍스트 검색
없음, 모델 호출 없음.

Resource→Resource 링크(`contains`, `attached_to`, `depends_on`, `peered_with`, `routes_to`)는
risk-gate가 [risk-classification-ko.md](../decisioning/risk-classification-ko.md)의 3-값
enum 대신 *실제* 영향 범위 를 계산할 수 있게 하고, T2 가 대상 리소스 주변 **depth-2 이웃
서브그래프** 를 프롬프트로 받을 수 있게 하는 것 - 벌거벗은 리소스 id 가 아니라 근거 있고
인용 가능한 컨텍스트. 권위 있는 출처 는
[인벤토리 계약](csp-neutrality-ko.md#5-인벤토리-계약--리소스-그래프); `core/` 는 절대 클라우드
SDK 로 조회하지 않음. 새 링크 종류는 어댑터가 발행 하기 전에
`shared/contracts/ontology/link-type.json` 에 먼저 추가해야 함 - 미인식 `ResourceType` 과
동일하게, 미인식 링크는 자동 등록이 아니라 이슈 오픈 (self-extending 온톨로지,
[포크 확장](#포크-확장-self-extending-온톨로지) 참조).

런타임 ObjectType 속성과 LinkType 속성은 정본 JSON 데이터여야 함. 대응 키는
문자열이고, 숫자는 finite이며, datetime은 timezone-aware이고 RFC 3339 UTC로 정규화됨.
지원하지 않는 Python 객체는 쓰기 경계에서 거부함. in-memory와 PostgreSQL 저장소가
같은 정규화를 적용하므로 재생은 선택한 어댑터에 따라 달라지지 않음.

### 구체적인 Rule 의미 규칙

제공되는 Rule은 와일드카드 온톨로지 관계를 사용하지 않습니다. `triggered_by`는 검토된
`SignalType`을 참조하고, `evaluates`는 정본 `Property` ID를 참조하며,
`implemented_by_policy`는 Rule을 1급 `PolicyArtifact`에 연결합니다. 범위가 제한된 OPA AST
동기화 도구는 카탈로그를 구성하기 전에 Rego 패키지 ID와 속성 읽기를 검증합니다.

원시 이벤트는 `vocabulary/signal-types.yaml`을 통해 해석됩니다. 정확한 pattern 일치는 전문화된
형식을 선택하고, 일치하지 않는 이벤트는 검토된 단일 구성 기준선 형식을 선택합니다. 의미
수집은 후보 Rule의 순위를 매길 수 있지만 정확한 ID와 그래프 링크가 전달 및 근거 확인의
권위로 유지됩니다.

### 온톨로지 아티팩트로서의 규칙

[rule-catalog-collection-ko.md](../rules-and-detection/rule-catalog-collection-ko.md)의 Rule 스키마 v2는
파이프라인이 전달하는 온톨로지 필드를 운반함. 이전 `applies_to` scope-map 의미는
`scope_predicates`로 이행하며 모든 전달 필드는 로드 시 CI로 검증함.

```yaml
# rule-catalog/rules/example.yaml (illustrative fragment; full schema in rule-catalog-collection.md)
id: object-storage.public-access.deny
version: 1.2.0
source: authored
severity: high
category: security
resource_type: object-storage
check_logic: <opa-package-ref>            # 결정론 평가기
remediation: <action-ref>                 # 온톨로지 ActionType 인스턴스 가리킴

# ── ontology fields (new; CI-validated) ──
applies_to:    [object-storage]
triggered_by:  [property.public_access.changed, config.public_access.enabled]
evaluates:     [object-storage.public_access]
scope_predicates: {}                         # 선택 labels/tags/scope filter
remediates:    remediate.disable-public-access
required_interfaces: [Evaluable, Remediable]   # submission_criteria enforced at load
submission_criteria:
  - kind: resource_type_registered
    value: object-storage
provenance: { ... }
```

`required_interfaces` 와 `submission_criteria` 는 참조된 온톨로지 설계의 같은
Functions-plus-Interfaces 패턴 따름: 규칙은 인터페이스 계약이 런타임 객체에서 충족될 때만
dispatchable, 스키마 레지스트리에 대해 `applies_to` / `triggered_by` 가 해결될 수 없는 규칙을
CI가 거부.

`resource_type`은 기존 정책과 교정 코드가 사용하는 정본 단일 대상으로
유지하며 `applies_to`에 반드시 포함해야 함. `scope_predicates`는 이전 라벨/tag 범위 지도를
담아 타입 축과 혼동되지 않게 함. 업스트림 출처가 더 좁은 메타데이터를 제공하지 않을 때만 기존
및 신규 수집 룰을 `triggered_by: ["*"]`, `evaluates: ["*"]`로 backfill함. 와일드카드는 명시적
catch-all이지 추론된 신호가 아님. TrustRouter와 T0는 같은 `applies_to` x (`triggered_by` exact
또는 `*`) 교집합을 사용함.

### 파이프라인 스테이지와 ActionType (구분되는 개념)

이 시스템에서 "액션" 이라 불리는 두 가지는 **혼동 금지**:

- **PipelineStage** - 계층적 조회에서 결정이 이뤄진 위치. **감사 어휘** 이지 스키마 아티팩트가
  아님. 모든 audit-log 엔트리는 `pipeline_stage` 필드를 기록해서 결정 경로가 종단 간 로
  재구성 가능. `remediate` 제외 모든 스테이지는 실행기 관점에서 읽기 전용 (CSP 변경
  없음).
- **ActionType** - 롤백 계약 있는 **CSP-중립 변경 카테고리**. `shared/contracts/ontology/action-type.json`
  에 선언; 인스턴스(예: `remediate.disable-public-access`) 는 카탈로그에 존재하며 규칙의
  `remediates` 필드에서 참조됨. 이게 스키마 아티팩트.

`remediate` 만이 둘을 커플링: PipelineStage(실행기 스텝) 이면서 그 출력이 Resource에
적용되는 ActionType **인스턴스**. `escalate` / `abstain` / `deny` 는 ActionType을 절대
발동하지 않는 종단 스테이지.

**PipelineStage 어휘** (`audit_log.pipeline_stage` 에 기록):

| PipelineStage | 레이어 | 비용 | 전제조건 | 종단? |
|---------------|--------|------|---------|:---:|
| `L1_evaluate` | L1 (T0) | 순수 함수, 인메모리 OPA/Rego | 규칙의 `applies_to` 가 Resource와 매칭; `check_logic` 컴파일 | - |
| `L1_simulate` (what-if) | L1 (T0) | 선언적 상태에 대한 순수 함수 | 리소스 상태 스냅샷 이용 가능 | - |
| `L2_reuse` | L2 | O(1) 인덱스 선택 | 학습된-액션 저장소의 `(signature, rule_id, catalog_version)` 적중 | - |
| `L3_similarity` | L3 (T1) | 임베딩 1 + pgvector kNN | 이웃의 컨텍스트 호환성 검사 통과 | - |
| `L4_cache_hit` | L4 | O(1) 키 조회 | TTL과 카탈로그/모델 버전 내 서명 매칭 | - |
| `L5_reason` | L5 (T2) | 프론티어 LLM (기본 + 보조; 불일치 시 escalated) | quality-gate가 권위 | - |
| `remediate` | risk-gate ⇒ 실행기 ⇒ 전달 | ActionType 인스턴스를 Resource에 적용 | policy-as-code 검증기 통과; 모든 ActionType 전제조건 성립 | - |
| `escalate` | risk-gate ⇒ ChatOps | HIL 요청 | 어떤 저렴 레이어도 케이스 해결 못함 | ✓ |
| `abstain` | 어떤 레이어 | 감사된 no-op | grounding 없음 또는 검증기 abstain | ✓ |
| `deny` | 어떤 레이어 | 감사된 no-op | risk-classification이 액션 차단 | ✓ |

`L5_reason` 만 LLM 호출. 다른 모든 스테이지는 결정론이며 마이크로초-밀리초에 실행.

### ActionType 계약

**ActionType** ([스키마](../../../services/core-control-plane/src/fdai/shared/contracts/ontology/action-type.json)) 는
하나의 CSP-중립 변경 카테고리와 그 카테고리의 모든 인스턴스에 대한 안전 불변식을 선언.
`preconditions` / `stop_conditions` / `blast_radius` / `description` 을 제외한 모든 필드는
필수.

- `name` - 안정 id (예: `remediate.disable-public-access`).
- `operation` - 아래 enum의 CSP-중립 동사.
- `interfaces` - 실행기 가 지켜야 하는 런타임 계약; risk-gate 는 이 집합으로 feature 벡터
  구성.
- `rollback_contract` - 인스턴스를 되돌리는 방법. **`none` 은 유효 값 아님**; 모든 ActionType 은
  최선 노력 라도 undo 경로를 선언해야 함. 정말로 되돌릴 수 없는 변경 은
  `irreversible: true` (아래) 를 설정하고 risk-classification 이 HIL+정족수 으로 라우팅 -
  롤백 을 침묵시키는 방식이 아님.
- `irreversible` - 액션 이전 상태가 완전히 복원 불가능할 때만 true (예: soft-delete 된 리소스의
  `purge`). Rollback_contract 은 여전히 필수이며 최선 노력 복구를 기술.
- `default_mode` - 모든 업스트림 ActionType은 반드시 `shadow`로 출시합니다. 강제 적용로의
  승격은 승격 게이트 통과 후 별도 통제된 액션으로 수행합니다.
- `promotion_gate` - 어사인먼트가 shadow-mode ActionType 을 강제 적용 로 승격시키기 전에 고정
  시나리오 세트에서 통과해야 할 측정 기준 (`min_shadow_days`, `min_samples`, `min_accuracy`,
  `max_policy_escapes`). Rule 배정 는 이 값을 tighten 만 가능, loosen 불가.
- `preconditions[]` - 액션이 risk-gate 에 도달하기 **전에** T0 검증기 가 결정론적으로 평가하는
  검사. 실패하는 전제조건은 abstain, 부분 적용 절대 금지.
- `stop_conditions[]` - 적용 **도중 또는 이후에** 실행기 가 결정론적으로 평가하는 조건. 참
  값이 하나라도 나오면 자동 halt + `rollback_contract` 로 롤백 트리거.
- `blast_radius` - risk-gate 가 이 ActionType 인스턴스의 blast-radius 분류 차원을 계산하는
  방법. `static_enum` 은 고정 버킷; `graph_derived` 는 Resource → Resource 링크 (기본:
  `contains` + 역방향 `depends_on`, 깊이 2) 를 walk 하여 영향받는 Resource 수를 개수. 인스턴스가
  `max_affected_resources` 초과 시 abstain + escalate. 실제 탐색 구현은 risk-gate 와
  함께 P2 에 랜딩; P1 은 선언만 기록.

#### 연산 동사

`operation` enum 은 CSP-중립. 각 동사 는 고정 의미를 가지므로 규칙 저자와 프로바이더 어댑터가
의도를 합의.

| 동사 | 의미 | 기본 롤백 |
|------|-----|---------------|
| `create` | 새 Resource 프로비저닝 | `pr_revert` (같은 PR에서 destroy) |
| `update` | in-place 속성 변경 (non-destructive) | `pr_revert` (차이 에 이전 속성값) |
| `delete` | CSP 수준 Resource 제거 | `snapshot_restore` (삭제 전 스냅샷) |
| `disable` | 삭제 없이 끄기 | `state_forward_only` via `enable` |
| `enable` | `disable` 의 역 | `state_forward_only` via `disable` |
| `tag` | 메타데이터 전용 변경 | `pr_revert` |
| `drop` | DB-DDL 제거 (스키마 / 객체) | `pitr` |
| `purge` | soft-delete 후 hard-delete; `irreversible: true` | 최선 노력 `snapshot_restore` |
| `scale` | 개수 / SKU 조정 | 이전 spec 으로 `pr_revert` |
| `restart` | in-place 프로세스/파드 bounce | 프로바이더 계약에 따라 `scripted` 또는 `state_forward_only` |
| `failover` | 관리형 장애 조치 트리거; `RequiresMaintenanceWindow` | `scripted` (failback) |
| `rotate` | 시크릿 / 인증서 로테이션 | `snapshot_restore` (이전 버전 유지) |
| `revert` | 이전 액션 인스턴스의 명시적 롤백 | revert PR 자체에 `pr_revert` |
| `attach` | Resource → Resource 링크 생성 (PE→대상, MI→App, disk→VM) | `state_forward_only` via `detach` |
| `detach` | 그런 링크 제거 | `state_forward_only` via `attach` |
| `quarantine` | 삭제 없는 네트워크/정책 격리 | `state_forward_only` (격리 정책 해제) |

#### Interface

ActionType 의 `interfaces` 집합은 실행기 가 지켜야 하는 런타임 계약을 명명. 인터페이스 누락은
"뭐든 허용" 이 아님 - risk-gate 는 인터페이스 집합이 그 `operation` 의 안전 불변식 요건을 커버하지 못하는 ActionType 을 자동 실행하지 않음.

| Interface | 의미 |
|-----------|-----|
| `ControlPlane` | CSP 메타데이터/설정만 건드림 (사용자 데이터 절대 안 건드림). Auto 후보의 기준선. |
| `DataPlaneMutating` | 사용자 데이터 건드림. **영향 범위 무관하게 기본 HIL**. |
| `IdempotentByKey` | 동일 멱등성 키로 재시도 안전; 실행기 의 dedup 이 이 키 사용. |
| `RateLimited` | 버킷 상한(per-resource, per-tier, global) 준수 필수; 오버플로우는 HIL 로 degrade. |
| `RequiresInventoryFresh` | 대상 Resource 의 인벤토리 레코드가 `freshness_ttl` 초과 stale 이면 실행 금지. 유령 리소스 액션 방지 - 인벤토리 계약 ([csp-neutrality-ko.md § 5](csp-neutrality-ko.md#5-인벤토리-계약--리소스-그래프)) 이 최신성 커서 공급. |
| `GraphTraversalRequired` | blast-radius 계산이 Resource → Resource 링크 (`contains` / `attached_to` / `depends_on`) 트래버설에 의존. 그래프 없으면 ActionType abstain. |
| `CrossResource` | 여러 Resource 를 변경; 실행기 가 deadlock-free 결정론적 순서로 N 개 per-resource 락 획득. |
| `AsymmetricRollback` | 롤백 경로 가 정확한 역이 아님 (예: PITR 이 Δ-data 유실). auto → HIL demotion 강제; 다른 차원 무관하게 auto 선택 안 됨. |
| `RequiresMaintenanceWindow` | 승인된 구간 안에서만 실행 (P3 chaos / DR). 구간 스케줄러 없으면 abstain, 그냥 실행 금지. |

### 계층 조회 파이프라인

![계층 조회 파이프라인. 주요 단계는 Signal arrives, L0. event-ingest / normalize + dedup + correlate into incident, no-op, audited, L1. T0 rule match / ontology traversal: applies_to ∩ triggered_by / run each rule's evaluate action (OPA/Rego, in-memory), risk-gate, L2. Learned-action lookup / (signature, rule_id, catalog_version) → verified action, L3. Embedding similarity (T1) / 1 embedding call → pgvector kNN / reuse neighbor.action iff cos > threshold and context compatible, L4. T2 result cache / signature includes catalog_version + model_config_version + mode, L5. T2 cascade / primary → agree? → done / disagree? → escalated / quality-gate authoritative, writeback: promote verified outcome / into L2 (learned action) + L4 (result cache)입니다.](../../diagrams/generated/fdai-roadmap-architecture-llm-strategy-03.ko.svg)

**예상 적중 분포** (설계 목표, [goals-and-metrics-ko.md](goals-and-metrics-ko.md) 에 따라 측정
대상):

| 레이어 | 적중당 비용 | 들어오는 이벤트의 설계 비율 |
|--------|-----------|--------------------------|
| L0 dedup / correlate | µs | N 이벤트 → 1 인시던트로 접힘(압축, 커버리지 수치 아님) |
| L1 T0 | µs, 인메모리 | ~70-80% |
| L2 learned-action | ms, 인덱스 선택 | L5 결과가 아래로 distill되면서 시간에 걸쳐 성장 |
| L3 임베딩 유사도 | 임베딩 1 + kNN | T1 ~15-20% 밴드의 나머지 |
| L4 T2 캐시 | O(1) 키 | 미해결이지만 최근 케이스의 반복 흡수 |
| L5 T2 cascade | 프론티어 LLM | **~5-10%만** - 실제 토큰 지출 |

두 구조적 결과:

- **LLM 사용은 시간에 걸쳐 감소** , 증가 아님. 모든 L5 검증된 결과가 L2에 writeback, 그래서 지난
  주 전체 T2 cascade가 든 반복 케이스는 이번 주 해시 조회. 이것이 "LLM을 덜 쓴다" 원칙 뒤의
  구체 메커니즘.
- **규칙 변경이 올바른 행을 자동으로 무효화** (아래 참조). 수동 캐시 bust 없음; stale 재사용은
  승격이나 강등에서 살아남지 않음.

### 서명 구성

L2와 L4를 키하는 서명은 온톨로지-타입된 필드에 대한 정본 해시 - 기록과 재사용이 문자열-
유사가 아니라 semantics-aware.

```text
signature = sha256(
  Signal.type,
  canonical(Signal.params),                # sorted, redacted, typed
  Resource.type,
  canonical(Resource.props),               # only props referenced by evaluates
  Rule.id, Rule.version,
  Catalog.version,
  Model.config.version,                    # L4 only; L2 omits (model-independent reuse)
  Mode                                     # shadow | enforce
)
```

- **민감정보 제거가 해시 전 실행** - 그래서 시크릿이 절대 서명에 진입 못함.
- **`evaluates` 에 명명된 속성만** 참여, 그래서 관련 없는 리소스 churn이 재사용을 무효화하지 않음.
- **카탈로그 / 모델 버전 bump** 와 **shadow ↔ 강제 적용 전이** 는 새 서명 강제, 별도 cache-flush
  스텝 없이 [비용 통제 수단](#비용-컨트롤cost-controls) 의 무효화 규칙 적용 보장.

### 재사용 감사 (모든 레이어, 적중 포함)

자율성은 결정 - 재사용으로 생산된 것 포함 - 이 완전히 귀속 가능함을 요구. 모든 레이어가 감사
엔트리 씀:

- `layer` (L1..L5)
- 발동한 `rule_id` 와 `rule_version`
- `signature` 와 매칭 방법(정확 적중 / cos 유사도 + 스코어 / 캐시 age)
- `reused_from`: 결과가 재사용된 audit_id로의 back-reference (L2/L4)
- `mode` (shadow / 강제 적용) 와 결과 risk-gate 결정

Resolvable `reused_from` 없는 재사용은 결함 - 감사 체인은 원래 그것을 검증한 L5 결과로 어떤
결정에서든 walkable하고 유효한 규칙/모델 버전으로 forward해야 함.

### 포크 확장 (self-extending 온톨로지)

온톨로지는 **코어에서 도메인-비종속** 이며 **포크별 확장 가능**합니다. 포크는 자체 패키지에
`ObjectType`과 `LinkType` 카탈로그 항목을 추가하고 해당 정의를 따르는 기록을 발행하는
프로바이더를 연결합니다. `core/`나 업스트림 계약 패키지는 편집하지 않습니다.
- 새 `Resource` 하위타입은 검토된 카탈로그 항목으로 등록하고 파이프라인을 자동 상속 -
  `evaluate`, `reuse`, `similarity` 가 `core/` 의 코드 변경 없이 그들 위에서 작동.
- 새 `LinkType` (예: 포크-특이 causal 관계) 은 자체 cardinality, transitivity, 추론 메타데이터
  선언; 미사용 링크는 inert 유지.
- 새 `ActionType` (예: 포크-특이 딜리버리 어댑터) 은 자체 `required_interfaces` 와
  `submission_criteria` 선언; 미등록 액션을 참조하는 규칙은 런타임이 아니라 카탈로그 로드에서
  실패.
- Autoprovisioning: 신호에서 관찰된 인식되지 않은 ResourceType은 이슈 오픈(절대 auto-register
  아님), 그래서 온톨로지는 표류가 아니라 리뷰로 확장.

### 온톨로지 저장 레이아웃

전체 저장소, 스키마, 부트/리로드 설계는
[rule-lookup-ontology-storage-ko.md](rule-lookup-ontology-storage-ko.md)에서 관리합니다.

## 비용 컨트롤(비용 통제 수단)

- **정규화된 이벤트 서명 + 규칙 카탈로그 버전 + 모델-config 버전 + shadow/강제 적용 모드** 를
  포함하는 서명으로 T1/T2 결과 **캐시**. 이것이 캐시를 변경에 걸쳐 정확하게 함: 카탈로그나
  모델-config bump가 stale 엔트리 무효화.
- **무효화**: TTL 적용, 규칙-카탈로그 승격 시 무효화; 신선한 평가가 HIL로 보낼 케이스에 **절대**
  `auto` 결과를 서비스하지 않음, shadow-mode 결과를 enforce-mode 결정 충족에 절대 재사용하지
  않음.
- **예산 가드**: 티어별 토큰 예산과 비율 한도; 초과분은 HIL로 강등, 게이트 없는 auto-action
  이 되지 않음.
- **프로바이더 실패 처리**: 시간 초과, rate-limit, 장애 시 **실패 시 차단** - 범위가 제한된 백오프로 재시도하고 보조 프로바이더로 대체 경로한 뒤 circuit 차단기로 HIL 강등.
  실제 제안자 후보마다 shared 예산에서 호출 하나를 reserve하며 정제된 시도 증적에는 경로 역할, 실패 등급, 상태, 추적 신원만 유지합니다.
  최종 exhaustion은 Huginn, Heimdall, Forseti로 전달되어 실제 HIL ActionRun을 만들고 복구 성공은 관측으로만 남아 새 승인을 열지 않습니다. 절대 무한 재시도하거나 검증되지 않은 후보를 auto-execute하지 않음.
- **Outcome-Driven 토큰 Economics**: 모델 호출, 토큰, 지연 시간, 비용을 최소화하면서 검증된 운영 가치를 최대화합니다. 원문 문서를 모든 판단에서 RAG로 직접 검색하기 전에 출처가 연결된 온톨로지 사실과 T0/T1 reuse를 사용합니다. 남은 사례에는 최소 근거에 기반한 맥락과 충분함이 입증된 가장 작은 모델을 제공하고, 모호성이나 위험에는 원문 검색, 더 강한 모델, 교차 검증, 사람 승인을 사용합니다. 정확도, 근거 품질, 안전성은 비용보다 우선하는 제약입니다.

## T1 개선(정제)

부하를 아래-티어로 계속 shift하려면 ("LLM을 덜 쓴다" 레버), T1은 시간에 걸쳐 강화 가능 - 평가할
옵션, 커밋 아님:

- **학습된-액션 재사용**: 검증된 T2 결과를 T1이 매칭할 수 있는 학습된 액션으로 승격.
- **정제 / fine-tuning**: 수용된, 검증된 T2 판단을 소형 T1 모델로 distill하여 커버리지
  올림.
- **제약**: 훈련 데이터와 fine-tuned 아티팩트는 **고객-비종속** 이어야 하고 상류에 절대 커밋되지
  않고 하류 포크에 유지
  ([generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md)).
  Distilled 모델은 게이트에 대해 아무것도 변경하지 않음: 그 출력도 여전히 검증기 통과.

## 품질 측정(Quality 측정)

- **평가 실행 장치**: 예상 판정이 있는 버전된 golden 시나리오 세트; 모델은 승격 전 리플레이로
  오프라인 스코어링, per-model, per-tier 점수표 생산.
- **Hallucination 비율**: 생성된 후보 중 인용이 grounding-validity 검사 실패하거나 검증기가
  액션 거부한 것의 비율로 측정, 샘플링되고 주기적 human-labeled - 모델의 self-report 아님.
- 모델별, 티어별 정확도와 hallucination 비율 추적; **회귀는 승격을 자동 블록** (shadow→강제 적용이
  shadow에 유지) [security-and-identity-ko.md](security-and-identity-ko.md) 에 따라.
- Mixed-model 불일치 비율은 모니터되는 신호; 상승하는 비율은 표류 또는 나쁜 모델 플래그. 이들은
  [goals-and-metrics-ko.md](goals-and-metrics-ko.md) 의 KPI에 공급.

## 열림 Decisions

각각 시나리오 세트에서 **측정된 비용/quality** 로 결정, 가정 아님.

- [ ] 포크-측 레지스트리 오버라이드: 특정 포크가 리전과 컴플라이언스 자세에 대해
      `rule-catalog/llm-registry.yaml` 에 어떤 선호를 pin하는가.
- [ ] 기본 **mixed-model 계열 전략** (`azure-foundry` vs `external` vs `hil-only`) - 상류는
      셋 다 제공; 각 포크가 부트스트랩에서 하나 선택.
- [ ] 조정기 주기와 Azure OpenAI / Foundry의 구체 폐기-피드 소스(주간이 기본 권장).
- [ ] 임베딩 모델: hosted vs 로컬(데이터 잔류지, 비용).
- [ ] Mixed-model의 정족수 크기 / N과 불일치-escalation 정책.
- [ ] 버티컬별 신뢰-임계 값(복원력, 변경 안전성, 비용 거버넌스).
- [ ] 이벤트 클래스별 민감정보 제거 ruleset과 잔류지 라우팅.
- [ ] 캐시 TTL과 카탈로그-버전 무효화 트리거.
- [ ] T2 결과를 T1으로 distill할지, 그리고 포크-측 훈련 파이프라인.
