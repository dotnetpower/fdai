---
title: 에이전트 판테온 구현 계획
translation_of: agent-pantheon-implementation.md
translation_source_sha: 02c0aa4ef20a250d2466f08242f7e86ab1830ab2
translation_revised: 2026-09-20
---

# 에이전트 판테온 구현 계획

이 문서는 고정된 15개 에이전트 판테온의 구현을 조정합니다. 추가 전용 전달 원장, W0-W8
의존성 순서, 런타임 조립 계약을 한곳에 유지합니다. 에이전트 역할과 불변식은
[에이전트 판테온](agent-pantheon-ko.md)이 소유하고, 각 에이전트 간 작업 흐름은
[에이전트 작업 흐름 Shadow 롤아웃](agent-workflow-rollout-ko.md)에서 독립적으로 추적합니다.

> **범위:** 이 계획은 고객과 무관하며 Azure를 우선합니다. 포크는 지원되는 의존성 주입
> 경계를 통해 프로바이더와 전달 바인딩을 설정합니다. 에이전트 이름, 역할 바인딩 또는
> shadow 승격 경계를 변경하지 않습니다.

## 구현 상태

### 구현 범위

| 영역 | 상태 | 근거 | 참고 |
|------|------|------|------|
| W0-W1 문서, 온톨로지 및 프레임워크 기반 | implemented | [`test_framework_layout.py`](../../../services/core-control-plane/tests/agents/test_framework_layout.py), [`test_pantheon_doc_parity.py`](../../../services/core-control-plane/tests/agents/test_pantheon_doc_parity.py), [`test_topics.py`](../../../services/core-control-plane/tests/agents/test_topics.py) | 고정 레지스트리, 패키지 경계, 문서 일치 및 타입이 지정된 토픽 기반을 실행하고 검사할 수 있습니다. |
| W2-W6 거버넌스, 파이프라인, 인터페이스, 전문 에이전트, 인계 및 보안 메커니즘 | implemented | [`test_runtime_chain.py`](../../../services/core-control-plane/tests/agents/test_runtime_chain.py), [`test_thor_durable.py`](../../../services/core-control-plane/tests/agents/test_thor_durable.py), [`test_conversational_port.py`](../../../services/core-control-plane/tests/agents/test_conversational_port.py), [`test_prompt_deliberation.py`](../../../services/core-control-plane/tests/agents/test_prompt_deliberation.py) | 선택적 T2 종합 전의 T1 답변 평가를 포함한 범위가 제한된 메커니즘을 집중 합성 검사로 실행하지만 실제 운영 검증을 입증하지는 않습니다. |
| 영속 권한, 복구, 인계 및 학습 재생 | implemented | [`test_runtime.py`](../../../services/core-control-plane/tests/agents/test_runtime.py), [`test_wave2_governance.py`](../../../services/core-control-plane/tests/agents/test_wave2_governance.py), [`test_wave3_pipeline.py`](../../../services/core-control-plane/tests/agents/test_wave3_pipeline.py), [`test_bootstrap_config.py`](../../../services/core-control-plane/tests/runtime/test_bootstrap_config.py) | StateStore 기반 CAS, 점유 유효 기간, 검사 지점, 보낼 편지함 및 시작 복구 경로에는 재시작과 동시성 집중 검사 근거가 있습니다. 범위가 제한된 Low 심각도 복제본 간 및 작업 신원 잔여 문제 두 건은 아래에 열어 둡니다. |
| W7 에이전트 간 shadow 작업 흐름 메커니즘 | implemented | [`test_wave7_workflows.py`](../../../services/core-control-plane/tests/agents/test_wave7_workflows.py) | 작업 흐름에 실행 가능한 합성 shadow 추적이 있으며, enforce 작업 흐름을 기본값으로 사용하는 근거는 이 문서에 없습니다. |
| W8 KPI, 승격 및 성능 저하 메커니즘 | implemented | [`test_wave8_kpi_degradation.py`](../../../services/core-control-plane/tests/agents/test_wave8_kpi_degradation.py) | KPI 보고는 측정값과 사용 불가능한 근거를 구분하고, 근거가 없으면 승격을 차단하며, 주입된 성능 저하 훈련이 고정 판테온을 다룹니다. |
| W3 추적 연속성 근거 인계 | implemented | `huginn.py`; `heimdall.py`; `test_trace_continuity_chain.py` | sensing 경로는 허용 목록의 범위가 제한된 연속성 근거만 보존하고 역할, topic, 작업 권한을 바꾸지 않은 채 관측된 사유를 인시던트 후보 하나에 전달합니다. |
| 운영 활동 귀속 | implemented | `control_loop/_measurement.py`; `control_loop/_rca.py`; `agents/_framework/provider_adapters.py`; `delivery/{agent_activity,observation_campaign,startup_probe}.py`; Operator 활동 투영과 집중 테스트 | 기계 행위자와 책임지는 Pantheon 소유자를 구분합니다. 주기적 런타임 스냅샷은 활성 handler 상태를 보존하고 서로 독립적인 에이전트 레코드를 동시에 게시합니다. 인증된 버스 게시자만 `producer_principal`을 채우며, 소유자를 알 수 없는 기존 사용자 정의 source는 감사 근거로 유지하고 임의의 에이전트 활동으로 만들지 않습니다. |
| 최종 ActionRun 효과 관찰 경로 | implemented | [`executed_action_observation.py`](../../../services/core-control-plane/src/fdai/delivery/executed_action_observation.py), [`wire_azure_operational_evidence.py`](../../../services/core-control-plane/src/fdai/composition/wire_azure_operational_evidence.py), [`test_executed_action_observation.py`](../../../services/core-control-plane/tests/delivery/test_executed_action_observation.py) | Heimdall은 Thor의 최종 ActionRun을 소비하고 정확한 실행 전 아티팩트를 복원하며 검증기가 승인한 독립 관찰만 저장합니다. 배포가 소유하는 서명된 컨텍스트와 실제 종료 근거는 아직 필요합니다. |
| O7 운영 승격 근거 측정 | implemented | [`operational_promotion.py`](../../../services/core-control-plane/src/fdai/core/measurement/operational_promotion.py), [`operational_promotion_evidence.py`](../../../services/core-control-plane/src/fdai/delivery/measurement/operational_promotion_evidence.py), [`test_operational_promotion_evidence.py`](../../../services/core-control-plane/tests/delivery/test_operational_promotion_evidence.py) | 실행기는 매니페스트에 결합된 불변 배치를 소비하고 인과관계, 측정 단위, 재발 또는 정책 이탈 근거가 없으면 안전하게 차단합니다. 현재 완전한 실제 배치를 구체화하는 런타임 생산자는 없습니다. |
| 실제 운영 KPI 검증 및 실제 enforce 승격 | in-progress | [운영 학습 온톨로지](../rules-and-detection/operational-learning-ontology-ko.md), [목표와 메트릭](../architecture/goals-and-metrics-ko.md) | 측정 및 관찰 소비자는 있지만 완전하게 보존된 실제 shadow 코호트, 운영 승격 증적, 독립적인 검토 또는 실제 판테온 enforce 승격 근거는 없습니다. |

### 구현 이력

| 날짜 | 상태 | 변경 | 근거 | 남은 작업 |
|------|------|------|------|-----------|
| 2026-09-19 | implemented | Forseti의 운영자 RBAC에서 예제 principal 대체 동작을 제거했습니다. 이제 배포 정책이 없으면 운영자 작업 권한을 부여하지 않으며, 명시적으로 주입된 정책은 기존의 거부 및 보안 이벤트 동작을 유지합니다. 에이전트 역할, topic, 모델 정책 및 실행 권한은 바뀌지 않았습니다. | `current change`; `forseti.py`; 집중 RBAC 회귀 검사; Wave 3 및 프레임워크 레이아웃 검사; strict mypy와 Ruff. | 기존 실제 shadow 코호트와 함께 배포된 RBAC 판단 근거를 보존합니다. enforce 승격을 추론하지 않습니다. |
| 2026-09-17 | implemented | 통합 과정에서 strict typing 불일치가 드러난 기존 `ActionObservationHook`을 Heimdall의 명시적 공개 export에 복원했습니다. 역할, 토픽, 관측 동작 및 권한은 바뀌지 않았습니다. | `current change`; `heimdall.py`; 프레임워크 레이아웃 검사; 대상 strict mypy. | 운영 검증을 추론하지 않으며 기존 실제 효과 종료 작업을 유지합니다. |
| 2026-09-16 | implemented | 주기적 런타임 스냅샷이 활성 handler 상태를 보존하고 서로 독립적인 에이전트 레코드 15개를 동시에 게시하도록 했습니다. 느린 Event Hubs 왕복 하나가 모든 새로 고침을 직렬로 지연하지 않습니다. 역할, topic, 판단 및 권한은 바뀌지 않았습니다. | `current change`; `delivery/agent_activity.py`; `runtime/bootstrap_pantheon.py`; 에이전트 활동, 런타임 종료, 인벤토리, 분석기 및 관측 집중 검사 260개 통과, strict mypy와 Ruff 통과. | 배포된 활동 근거를 보존합니다. 초기 전체 인벤토리 Rule 평가와 현재 점검 결과 요약은 [이슈 #1199](https://github.com/dotnetpower/fdai/issues/1199)에서 추적합니다. |
| 2026-09-15 | implemented | 예측 기반 구현의 CI 등록 누락을 보완하고 Mimir 컨텍스트 처리, Muninn Pattern 읽기, Heimdall 이력 수신, Forseti 준비 상태 기록을 전용 framework 보조 모듈로 옮겼습니다. 역할, 소유 토픽, 제한된 대기 시간, 권한은 바뀌지 않았습니다. | `current change`; [PR #1029](https://github.com/dotnetpower/fdai/pull/1029); 분리 경로 집중 검사 234개, 근거 허용 경로 검사 316개, 구조 회귀 검사 55개, 실제 루프백 PostgreSQL 검사 3개, strict mypy와 Ruff 통과. | 보호된 CI와 병합은 대기 중이며 예측 후속 작업은 이슈 #1021부터 #1026에 남아 있습니다. |
| 2026-09-15 | implemented | Rebase 뒤 Var의 공개 대기 티켓 유형을 보호된 main과 일치시키고 기존 배정 검토 바인딩을 집중 배정 작업 흐름 helper로 이동했습니다. | `current change`; 레이아웃, 배정 및 Wave 3 집중 검사 125개 통과, strict mypy, Ruff 및 enforced LOC 통과. | 승인, 배정, 역할 또는 권한 동작은 바뀌지 않았으며 기록된 Low 심각도 잔여 문제를 해결합니다. |
| 2026-09-15 | implemented | 보호된 main으로 rebase한 뒤 Var shadow 검토 레코드, 범위 제한 티켓 제거 및 차단 시도 중복 제거를 집중 티켓 신원 helper로 이동했습니다. | `current change`; Wave 3, 런타임 및 정족수 검사 193개 통과, strict mypy, Ruff, 에이전트 가져오기 및 enforced LOC 통과, Var 800줄. | 승인 동작이나 권한은 바뀌지 않았으며 기록된 Low 심각도 잔여 문제 두 건을 해결합니다. |
| 2026-09-15 | implemented | 수명 주기 순위로 오래된 쓰기를 억제하기 전에, 그리고 Thor가 멱등성을 예약하거나 리소스를 점유하기 전에 활성 영속 ActionRun 신원을 검증하도록 했습니다. 상관관계를 공유하는 peer generation은 실행 전에 실패하며 정규 활성 실행을 복구 화면에서 숨길 수 없습니다. | `current change`; 활성 행 및 복제본 간 충돌 회귀 검사, LOC 상한 아래로 provider 점유 시간 helper 추출. | 기록된 Low 심각도 잔여 문제 두 건을 해결합니다. |
| 2026-09-15 | withdrawn | 독립 검토에서 결정, 전달 순서, 삭제 및 리소스 점유 경쟁을 발견해 상관관계 재사용 generation 교체를 철회했습니다. 이제 Thor, Var 및 영속 어댑터는 상관관계마다 변경할 수 없는 ActionRun 신원 하나를 결속하고 서로 다른 모든 generation을 거부합니다. 정확히 같은 generation 재생만 멱등성을 유지합니다. | `current change`; 실제 및 영속 재사용 거부, 기존 tombstone, 해제된 점유, 오래된 권한 및 shadow 일부 정족수 재시작 회귀 검사 300개 통과. | 기록된 Low 심각도 잔여 문제 두 건을 해결합니다. |
| 2026-09-15 | implemented | 비활성 Thor tombstone에 이전 액션 멱등성 generation을 보존하고 서로 다른 generation에서만 행을 CAS로 교체하도록 했습니다. 재사용한 상관관계도 완료된 실행을 되살리지 않고 새 shadow HIL 실행을 영속화합니다. | `current change`; 오래된 generation 억제, tombstone 교체 및 상관관계 재사용 일부 정족수 재시작 회귀 검사 통과. | 기록된 Low 심각도 잔여 문제 두 건을 해결합니다. |
| 2026-09-15 | implemented | Var가 영속 복구를 사용할 때 프로덕션 shadow 모드에서도 Thor ActionRun을 영속화해 미완료 정족수와 정확히 일치하는 실행이 두 번째 승인 전에 함께 복원되도록 했습니다. | `current change`; 일부 정족수 shadow 재시작, 런타임 및 bootstrap 검사 137개 통과, strict mypy 및 Ruff 통과. | 기록된 Low 심각도 잔여 문제 두 건을 해결합니다. |
| 2026-09-15 | implemented | Var 승인과 Vidar 롤백을 수명 주기 동안 안정적인 ActionRun 다이제스트 하나에 결속하고 영속 레코드를 해당 신원으로 범위화했으며, Thor가 실행이나 점유 해제 전에 오래된 권한 메시지를 거부하도록 했습니다. | `current change`; 권한 신원, 상관관계 재사용, 롤백 및 전체 에이전트 검사, strict mypy, Ruff, 에이전트 가져오기 및 LOC 게이트 통과. | Shadow 모드에서 일치하는 Thor ActionRun을 영속화한 뒤 기록된 Low 심각도 잔여 문제 두 건을 해결합니다. |
| 2026-09-15 | implemented | Vidar가 성공을 기록하기 전에 범위가 제한되고 공백이 아닌 롤백 증적을 정규화하도록 했습니다. 영속 종결 codec은 비어 있거나 비정규적인 증적을 차단하고 Thor도 공백인 성공 페이로드에서 리소스 점유를 독립적으로 유지합니다. | `current change`; Wave 3, T2 복구 체인 및 Thor 내구성 검사 161개 통과, strict mypy 및 Ruff 통과. | 롤백 증적 완전성의 소스 작업은 남아 있지 않으며 Low 심각도 잔여 문제 세 건은 계속 열려 있습니다. |
| 2026-09-15 | implemented | 비활성 지문 후보를 제안됨으로 표시하기 전에 대기열에 추가해 Norns 포화 복구를 재시도 가능한 상태로 유지했습니다. 용량 실패가 게시하지 않은 후보를 전달 완료로 보이게 할 수 없습니다. | `current change`; 집중 포화 재현과 Norns 내구성, 커버리지 및 런타임 검사 162개 통과, strict mypy 및 Ruff 통과. | 에이전트 역할이나 권한을 넓히지 않고 기록된 Low 심각도 잔여 문제 세 건을 해결합니다. |
| 2026-09-15 | implemented | 기존 판테온 및 프로젝트 구조 문서가 크기 상한에 도달해 구현된 T1/T2, Var, Vidar, Saga, Norns, Bragi 재생 계약을 이 집중 런타임 소유 문서로 통합했습니다. | `current change`; 캠페인 안전 검사 1,372개, 환경 의존 PostgreSQL 건너뜀 1개가 포함된 Cost Governance 격리 검사 170개, strict mypy, Ruff 및 구조/문서 게이트. | 에이전트 역할이나 권한을 넓히지 않고 기록된 Low 심각도 잔여 문제 두 건을 해결합니다. |
| 2026-09-15 | implemented | 런타임 동작을 바꾸지 않고 최종 CI 호환성을 복구했습니다. 검증된 실행 결과 분류를 집중 모듈로 옮기고, 평가 기준 테스트 후보를 신뢰된 대상에 결속하고, Norns를 `object.issue`를 통해 검증하고, 자연어 의미 체계 검출기가 정규 enum 검증을 잘못 분류하지 않도록 Var의 잠금된 비공개 판단 도우미 이름을 바꿨습니다. | `current change`; 집중 ControlLoop 패키지, 평가 기준 및 tier 테스트, Norns, Var, framework layout, semantic routing, Ruff, strict mypy, LOC, 번역 및 설계 검사. | 기록된 Low 심각도 잔여 문제 두 건은 유지됩니다. 역할, topic, 승인, 실행 또는 승격 권한은 바뀌지 않았습니다. |
| 2026-09-14 | implemented | 활동 귀속 변경에서 관련 없는 ActionRun fingerprint 필드를 제거해 영속 및 복구 식별자를 그대로 유지했습니다. | `current change`; 전체 mypy와 집중 Thor 내구성 및 복구 회귀 테스트. | 정확히 병합된 개정 번호의 배포 감사 및 활동 근거를 보존합니다. |
| 2026-09-14 | implemented | 운영 활동 귀속을 기계 행위자, 책임 `owner_agent`, 인증된 `producer_principal`로 분리했습니다. 컨트롤 루프 측정은 Heimdall, RCA는 Forseti, 시작 감사는 Saga, 관측 캠페인은 선언된 소유자에 귀속하며 Saga 감사 미러는 감사 대상 주체를 바꾸지 않고 Saga를 기록합니다. | `current change`; 서비스 계약, 컨트롤 루프, provider adapter, 관측 캠페인, 시작 probe, 파이프라인 및 Operator 투영 테스트. | 정확히 병합된 개정 번호의 배포 감사 및 활동 근거를 보존합니다. 역할, topic 또는 실행 권한은 바뀌지 않았습니다. |
| 2026-08-13 | in-progress | W0-W8 전체 완료 주장을 독립적으로 근거를 확인할 수 있는 구현 영역으로 교체했습니다. | 현재 변경 | 검증 완료 또는 enforce 운영을 주장하기 전에 실제 근거를 수집하고 별도 검토를 거친 승격을 완료합니다. |
| 2026-08-14 | implemented | 선택적 대화 T2 종합을 범위가 제한된 T1 답변 신호의 결정론적 충돌 평가 결과에만 실행하도록 했습니다. | `current change`, 집중 숙의 테스트 36개 및 framework layout 검사 | 에스컬레이션하지 않는 분기와 충돌로 에스컬레이션하는 분기의 통제된 런타임 근거를 보존합니다. |
| 2026-08-17 | implemented | 범위가 제한된 Huginn-Heimdall 연속성 근거 인계를 추가하고 인시던트 후보에 인식된 관측 사유를 보존했습니다. | `current change`; 작업처럼 보이는 위조 입력을 제외한 집중 추적-인시던트 체인 통과. | 이슈 #142에서 추적하는 통제된 실시간 시나리오 근거를 보존합니다. |
| 2026-08-23 | implemented | 정확한 아티팩트 복원과 독립적으로 검증된 Azure 효과 수집을 사용하는 Heimdall의 타입 지정 최종 ActionRun 관찰 경로를 추가했습니다. | `current change`; 실행된 작업 관찰, Azure 수집기, 조립, 런타임 topic 및 판테온 일치 검사. | 배포가 소유하는 서명된 컨텍스트 발급자를 바인딩하고 통제된 실제 종료 증적을 보존합니다. |
| 2026-08-23 | implemented | O7 불변 근거 소비자, 매니페스트 결합 인과관계 및 측정 단위 검증기, 영속 증적 저장소와 선택적 측정 작업을 추가했습니다. | `current change`; 운영 승격 소스, 실행기, 영속성, CLI 및 Terraform 검사. | 통제된 실제 배치 생산자를 구현하고 승격 검토 전에 작업별 근거를 축적합니다. |
| 2026-08-24 | implemented | 에이전트 역할, topic 또는 권한을 바꾸지 않고 운영 가설 계보에 선택된 모든 예상 효과와 독립 결과를 보존했습니다. 단일 속성만 있는 저장 레코드는 하나의 효과로 읽을 수 있고, 모호한 이중 필드 레코드는 안전하게 차단됩니다. | `current change`; `hypothesis_lineage.py`; `ActionOption.yaml`; 집중 계보 및 competency 검사 15개 통과. | 남은 계보 생산자, 서명된 컨텍스트 및 실제 배치 선행조건을 완료합니다. |
| 2026-08-25 | implemented | Thor가 Verdict를 전달할 때와 사람 승인 직후에 실제 시작 준비 상태 권한 상한을 다시 확인하도록 했습니다. 저하되거나 만료되거나 실패한 새로 고침은 AgentSpec, topic, 판단, 승인, 감사 또는 롤백 소유권을 바꾸지 않고 새 실행과 대기 중 실행을 실행기 I/O 전에 shadow로 강제합니다. | `current change`; Thor 내구 auto, 승인 및 권한 프로바이더 실패 회귀 검사, Pantheon 레이아웃 및 import gate. | 배포된 degraded-shadow ActionRun 하나를 보존하고 privileged 실행기가 호출되지 않았음을 증명합니다. |

### 남은 작업

- [x] [운영 학습 온톨로지](../rules-and-detection/operational-learning-ontology-ko.md)에 기록된
  대로 일대다 `expects` 링크와 런타임 예상 효과 계보를 조정하고 선택된 효과마다 하나의 독립
  결과를 보존합니다.
- [ ] Saga 감사 및 `object.issue` 게시 검사 지점을 단조 증가 개정 번호 CAS로 전진시키고,
  복제본 두 개에서도 감사 추가와 게시가 각각 한 번임을 보이는 회귀 검사를 보존합니다.
- [ ] 각 이슈 작업 ID를 전역에서 지문 하나와 요청 다이제스트 하나에 결속하고, 다른 지문에서
  같은 ID를 재사용하면 실패 시 차단됨을 보이는 회귀 검사를 보존합니다.
- [ ] 남은 선행조건을 완료합니다. 배포가 소유하는 서명된 컨텍스트 발급자를 바인딩하고,
  Forseti가 소유하는 남은 인과관계 계보 속성을 보존하며, 실제 런타임 생산자를 구성하고,
  통제된 실제 배치 생산자를 구현합니다.
- [ ] 에이전트 역할, topic 소유권, 모델 정책 또는 작업 권한을 넓히지 않고 운영 의존성을
  대상으로 선언된 성능 저하 동작을 입증합니다.
- [ ] [이슈 #1199](https://github.com/dotnetpower/fdai/issues/1199)를 완료합니다. 전체 인벤토리에서
  내구성 있는 기준 평가 작업을 발행하고 Forseti 판단과 Saga 감사 소유권을 유지하며 근거 공백을
  0으로 추론하지 않는 현재 Rule 점검 결과 요약을 구체화합니다.
- [ ] 하나의 고정된 런타임, 카탈로그, ActionType, 작업 흐름 및 시나리오 집합 리비전에서
  보존된 실제 shadow 코호트를 대상으로 선언된 KPI 수집기를 실행합니다.
- [ ] 승격 후보마다 표본 수와 신뢰 구간을 포함한 권위 있는 결과, 재발, 롤백 및 정책 이탈
  0건 근거를 보존합니다.
- [ ] 판테온 enforce 운영을 사용하거나 보고하기 전에 독립적인 승격 검토를 완료하고 권위 있는
  승격 집합 증적을 기록합니다.

## 설계 개요

웨이브는 별도의 권위 원본이 아니라 의존성 순서를 설명합니다. 완료된 구현 상세는 현재
에이전트, 작업 흐름, 온톨로지 및 런타임 owner가 관리합니다. 이 문서는 조정 요약과 실제
프로세스에서 해당 owner를 연결하는 조립 규칙만 유지합니다.

| Wave | 범위가 제한된 결과 | 현재 owner |
|------|---------------------|------------|
| **W0** | 문서와 온톨로지 기반 | [에이전트 판테온](agent-pantheon-ko.md), [에이전트 작업 흐름](agent-workflows-ko.md) |
| **W1** | 에이전트 프레임워크, 고정 레지스트리, 토픽 및 two-port 골격 | [`agents/_framework/`](../../../services/core-control-plane/src/fdai/agents/_framework/) |
| **W2** | Saga, Mimir, Muninn 및 Norns 거버넌스 메커니즘 | [에이전트 판테온](agent-pantheon-ko.md) |
| **W3** | sensing, 판단, 위험, 롤백 및 shadow 실행 체인 | [에이전트 판테온](agent-pantheon-ko.md) |
| **W4** | 결정론 우선 대화와 중재 | [대화 숙의](conversational-deliberation-ko.md) |
| **W5** | 비용, 용량 및 복원력 전문 에이전트 | [에이전트 판테온](agent-pantheon-ko.md) |
| **W6** | 감사 가능한 인계와 보안 에스컬레이션 | [에이전트 판테온](agent-pantheon-ko.md) |
| **W7** | 독립적으로 승격하는 에이전트 간 작업 흐름 | [에이전트 작업 흐름 Shadow 롤아웃](agent-workflow-rollout-ko.md) |
| **W8** | KPI, 승격 및 성능 저하 근거 | [에이전트 판테온 KPI와 성능 저하 정책](agent-pantheon-ko.md#42-per-agent-kpi-성공과-성능-저하-신호) |

## 11. Wave 7 - Shadow 로 cross-agent workflows

롤아웃 순서, 작업 흐름별 shadow 게이트, 의존성 및 제외 범위는
[에이전트 작업 흐름 Shadow 롤아웃](agent-workflow-rollout-ko.md)이 소유합니다. 각 작업 흐름은
독립적으로 검토하며 이 wave에서는 어떤 작업 흐름도 enforce로 승격하지 않습니다.

## 런타임 조립 계약

`PantheonRuntime`은 고정된 에이전트 집합의 조립 경계입니다. 구현은
`services/core-control-plane/src/fdai/agents/_framework/runtime.py`에 있으며
`services/core-control-plane/src/fdai/runtime/bootstrap_pantheon.py`에서 조립합니다.

### 영속 권한과 재생

이 런타임 계약은 [에이전트 판테온](agent-pantheon-ko.md)의 고정 역할 경계를 보존합니다.
재시작 및 동시성 안전을 제공하지만 다른 에이전트에 판단, 승인, 실행, 감사, 복구 또는 게시
권한을 부여하지 않습니다.

#### Tier, 승인 및 명령 신원

- 권한 상한은 액션을 실제 시작 T0, T1 또는 T2 tier로 평가합니다. 대체 경로 액션은 T0
  권한을 물려받을 수 없습니다.
- 라우팅은 중첩된 `resource.type`, 중첩된 `resource.resource_type`, 기존 평면 형태 순서로
  추측 없이 해석합니다. T1은 잘못된 재사용 신원, 횟수, 신뢰도 및 유사도 근거를 차단합니다.
- T2는 대상, 리소스 유형, 인용 및 ActionType을 신뢰된 라우팅 컨텍스트에 결속합니다. 인용된
  라우팅 규칙 중 정확히 하나가 `remediates` 또는 `alternatives`로 ActionType을 허용하며,
  같은 규칙이 위험, 사람 승인 및 실행 렌더링까지 이어집니다. 카탈로그에 선언된
  `alternatives`는 의미 유사도보다 먼저 적용하는 결정론적 근거 확인 자료입니다.
- 혼합 모델 합의에는 서로 다른 범위 제한 정규 모델 신원이 필요합니다. 서로 다른 래퍼로
  감싼 모델 하나가 자체 정족수를 충족할 수 없습니다.
- Var는 원본 ActionRun 멱등성 키를 보존하고 정규화된 각 principal 결정을 감사가 포함된
  StateStore 비교 후 교환(CAS) 집계에 결합합니다. 동시 복제본은 변경할 수 없는 같은 결정
  집합에서 정족수를 계산합니다.
- Var는 티켓을 제거하기 전에 최종 승인 하나와 게시 검사 지점을 저장합니다. 시작 처리는 정확한
  대기 필드를 조회하고 소비자가 시작되기 전에 종결 집계를 완료한 뒤 저장된 최종 페이로드를
  다시 게시하므로 사람에게 같은 결정을 다시 요구하지 않습니다.
- Thor는 상관관계, 액션 ID와 유형, 리소스, 액션 멱등성, 매개변수, 정족수, 시작 주체, 롤백
  계약, 판정 및 작업 흐름 계보에 수명 주기 동안 안정적인 ActionRun 신원 하나를 기록합니다.
  Thor는 멱등성이나 리소스를 점유하기 전에 초기 영속 ActionRun을 대기 중 상관관계 점유로
  원자적으로 생성합니다. 첫 영속 수명 주기 게시는 이를 활성 상태로 승격합니다. 리소스
  경합이 발생하면 재시도할 수 있도록 유지하지만 재시작 복구에서는 제외합니다. 대기
  중에는 정규 신원만 권위가 있으므로 재시도는 승격 전에 shadow 상태 같은 실시간 비신원
  필드를 갱신합니다. 활성 행과 종결 tombstone은 정규 신원 다이제스트를 보존하므로 정확히
  같은 재생만 행을 복구할 수 있습니다. 중복 디스패치는 해당 상관관계만 읽고 복제본 간
  재시작 복구 탐색을 실행하거나 관련 없는 리소스 점유를 변경하지 않습니다. Thor는 동일한
  활성 재생을 반환할 때 다른 복제본의 실행이나 로컬 뮤텍스를 캐시하지 않습니다.
  이전 버전 tombstone은 비어 있지 않은 멱등성 generation이 일치할 때만 완료로
  처리합니다. Var는 결정 및 최종 레코드를 이 신원으로 범위화하고 명시적 액션 필드와 함께
  전달하며, Thor는 오래된 승인을 실행 전에 거부합니다. Thor와 Var는 상관관계도 이 신원에
  결속하므로 다른 멱등성 generation이 같은 상관관계를 재사용할 수 없습니다.

#### 롤백 점유와 종결 재생

- Vidar는 프로바이더 복구 전에 상관관계와 정규 롤백 명령 다이제스트를 소유자 토큰 및 범위가
  제한된 점유 유효 기간과 함께 점유합니다. 하나의 안정적인 효과 필드 허용 목록이 실행기 입력과
  다이제스트를 모두 정의합니다. 매개변수, 액션 신원, 작업 흐름 계보 및 롤백 데이터는 포함하고
  다시 생성되는 `terminal_at` 같은 전달 메타데이터는 제외합니다.
- 경합하는 복제본은 유효한 점유를 변경하지 않고 재시도 가능한 처리기 실패를 발생시킵니다.
  검증된 만료 뒤의 재처리는 모호한 점유를 `execution_unknown`으로 닫고, 개정 번호 CAS는 늦은
  소유자의 완료를 차단합니다.
- 프로세스 내부 및 영속 재생은 전체 명령 다이제스트를 검증합니다. 종결 재생은 schema, 개정
  번호, 소유자 토큰, 점유 유효 기간, 범위 제한 신원, 상태, 메모 및 증적도 검증합니다. 성공한
  롤백은 정규화되고 공백이 아니며 범위가 제한된 `rollback_ref`를 제공해야 합니다. Thor도
  리소스 점유를 해제하기 전에 같은 증적 경계를 독립적으로 검증합니다.
- Vidar는 점유, 종결 및 게시 레코드를 같은 ActionRun 신원으로 범위화하고 액션 유형, 리소스,
  롤백 계약과 함께 전달합니다. Thor는 오래되었거나 일치하지 않는 롤백을 무시하고 현재 실행과
  점유를 그대로 유지합니다.

#### 영속 인계와 학습

- Saga는 외부 변경 전에 각 에스컬레이션을 런타임 StateStore에서 점유합니다. 타입 지정 인계는
  안정적인 작업 ID 하나를 정확한 이슈 내용에 결속하는 추가형
  `IdempotentIssueTrackerAdapter`를 사용합니다. 기존 `IssueTrackerAdapter` 구현은 직접
  에스컬레이션에 계속 사용할 수 있습니다.
- 배포되는 `StateStoreIssueTrackerAdapter`는 이슈 상태와 정확한 작업 결과를 CAS로 영속화하고
  소비자가 시작되기 전에 범위 제한 실제 변환 결과를 복원합니다. 실제 프로바이더 재정의는
  프로바이더 측에서 같은 영속성을 제공하며 `InMemoryGithubIssueAdapter`는 타입 지정 런타임
  인계의 테스트에만 사용합니다.
- Saga는 변경, 감사, 게시 및 완료 검사 지점을 기록합니다. `object.issue`를 게시한 뒤에만
  완료를 기록합니다. 버스가 없으면 이전 검사 지점을 대기 상태로 유지하고 재시도 가능한 실패를
  발생시킵니다. 종료 정보는 범위가 제한된 발생 댓글 목록 밖에 두고 CAS 전에 검증합니다.
- Norns는 인계 멱등성 키를 점유하고 대기 작업을 영속 지문 횟수에 CAS로 적용하며, 게시 또는
  결정론적 보류가 전달 완료를 표시할 때까지 각 후보를 유지합니다. 시작 처리는 정확한 대기 필드를
  범위가 제한된 항목 하나씩 조회합니다. 차단된 선두 항목은 복구를 멈추지만 다음으로 성공한
  flush는 그 뒤의 영속 후보를 계속 처리합니다. 용량을 검증하고 후보를 추가한 뒤에만 지문을
  제안됨 집합에 넣으므로 포화 복구도 다시 시도할 수 있습니다.

> **현재 제한 사항:** 동시 Saga 복제본은 작업에 결속된 외부 변경 한 번 뒤에도 감사 및 이슈
> 게시 이벤트를 중복 추가할 수 있습니다. 하류 게시 멱등성과 Norns 중복 제거가 영향을
> 제한합니다. 배포되는 이슈 어댑터도 작업 ID 결속을 지문 하나의 범위에서만 확인합니다. Saga의
> 별도 영속 인계 점유가 배포되는 타입 지정 호출자의 위험을 완화합니다.

#### 범위가 제한된 공유 상태

`StateStore`는 `delete_states_beyond(prefix, retain_newest)` 제거 연산 하나를 노출합니다.
`read_states`와 같은 순서로 변환 결과 한도를 넘는 가장 오래된 행을 제거합니다. 키 하나를
지정할 수 없으므로 권위 있는 기록이나 감사 항목을 지울 수 없습니다. Var 복구가 영속이면
프로덕션은 shadow 및 enforce 모드 모두에서 Thor 저장소도 제공하므로 미완료 정족수와 해당
ActionRun이 함께 재개됩니다. 적용 모드 조립은 여전히 명시적인 `thor_state_store`,
`vidar_state_store`, `var_state_store` 바인딩을 모두 요구하며, 하나라도 없으면 프로세스 로컬
승인 또는 롤백 상태를 사용하기 전에 시작을 차단합니다. 비활성 Thor 행은 안정적인 멱등성
generation을 유지합니다. 같은 generation은 계속 억제하고 다른 generation은 실패 시
차단합니다. Generation을 알 수 없는 기존 tombstone도 재사용 권한을 부여하지 않습니다. 활성
행은 리소스 점유, 수명 주기 순위 억제 또는 실행 전에 검증합니다. 해제된 리소스 점유는
상관관계, 멱등성 키 및 액션 지문이 모두 같아야 완료된 같은 실행으로 인정합니다.

### 대화형 액션 재진입

Bragi는 `object.event`의 단독 쓰기 담당인 `Huginn.ingest`에 연결된 `proposal_sink`를 사용하며
변경 토픽을 게시하지 않습니다. 제안은 운영자를 `initiator_principal`로 포함하고 추적 가능한
상관관계 ID를 반환하며 실행하지 않고 타입 지정 파이프라인 진행만 렌더링합니다. Forseti와 Thor는
시작 주체를 보존하고 Var는 자기 승인을 차단합니다. 진입 RBAC는 `Contributor` 미만의 액션
요청을 차단합니다. Huginn은 `event_type == "operator_request"`일 때만 운영자 제안 필드를
수락하고 `operator_initiated`를 엄격한 Boolean으로 처리하므로 외부 신호가 운영자 액션을
위조할 수 없습니다.

### 조립과 수명 주기

- `PantheonRuntime.build(provider, raw_event_topic)`는 활성 에이전트를 인스턴스화하고 하나의
  `EventBusBridge`를 바인딩하며, 에이전트별 소비자 그룹에서 선언된 각 구독을 등록합니다.
- 원시 유입은 별도의 판테온 소비자 그룹을 사용하며 Huginn을 통해 진입합니다. 기본 컨트롤
  루프의 레코드를 가로채거나 해당 루프의 의존성이 되지 않은 채 나란히 실행합니다.
- `run()`은 소비자 실패를 격리하고 범위가 제한된 일시적 실패를 재시작하며 정상 형제 소비자를
  계속 실행합니다. 종료 시간도 제한됩니다.
- 런타임은 기본적으로 활성화된 shadow입니다. `FDAI_START_PANTHEON=0`으로 비활성화하며,
  소비자 조립이 없으면 in-memory 대체품을 만들지 않고 명시적으로 건너뜁니다.
- 별도 검토된 승격이 enforce를 활성화하기 전까지 Thor는 `enforce=False`를 유지합니다. Enforce
  조립에는 영속 Saga 감사 바인딩과 진행 중 ActionRun의 영속 저장소가 필요합니다.
- Vertical 간 중재에서는 헌법의 hard constraint가 부적격 선택지를 먼저 제거한 다음 Odin이
  남은 soft objective의 순위를 결정합니다.

### 구성 및 관측 경계

| 경계 | 계약 |
|------|------|
| `consumer_group_prefix` | 환경별로 소비자 그룹을 격리합니다. |
| `disabled_agents` | 선택적 에이전트를 바인딩과 구독에서 제거하며 Saga와 Vidar는 비활성화할 수 없습니다. |
| `saga` | enforce 운영에 필요한 추가 전용 영속 감사를 제공합니다. |
| `thor_state_store` | 최종 상태가 아닌 ActionRun을 재구성하고 재시작 후 리소스 잠금을 보존합니다. |
| `vidar_state_store` | 롤백 점유, 소유자 점유 유효 기간, 차단 개정 번호 및 종결 증적을 영속화합니다. |
| `var_state_store` | 승인 결정, 최종 페이로드 및 게시 검사 지점을 영속화합니다. |
| `muninn_state_store` | Muninn 변환 결과, Saga 이슈 상태 및 Norns 인계 학습 복구를 지원합니다. |
| `payload_validator` | 프로바이더 경계에서 잘못된 게시를 거부합니다. |
| 소비자 재시작 제한 | 형제 소비자를 취소하지 않고 지수 백오프와 유한한 재시작 상한을 적용합니다. |
| `health()` | 브리지 메트릭, 에이전트와 소비자 상태, 사용할 수 없는 에이전트, 연속성 및 유효 enforce 상태를 보고합니다. |
| Shadow 관찰기 | 권위 있는 구독자의 레코드를 소비하지 않고 실행 예정 결정을 측정합니다. |
| `ShadowDivergenceLedger` | 승격 근거를 위해 상관관계 ID로 shadow 결정과 권위 있는 결정을 결합합니다. |
| `heimdall_action_observation_hook` | 정확한 최종 ActionRun 아티팩트를 복원하고 독립적으로 검증된 효과 관찰만 기록합니다. |
| 하트비트 | 설정된 주기로 범위가 제한된 상태 스냅샷을 발행합니다. |

### 이벤트 버스 불변식

- 토픽 소유권과 파티션 키는 공유 토픽 레지스트리를 사용합니다. 변경 토픽에는 비어 있지 않은
  리소스 키가 필요하며 잘못된 키는 게시 전에 차단됩니다.
- 게시 묶음은 생산자, 스키마, 상관관계 및 멱등성 메타데이터를 포함합니다. 소비자 측 소유권
  검사는 사칭 게시자를 핸들러에 전달하기 전에 dead-letter 처리합니다.
- 핸들러 재시도와 시간 제한은 범위가 제한됩니다. 순서가 있는 변경 스트림은 독성 레코드에서
  중단할 수 있으므로 나중 효과가 실패한 이전 효과를 앞지를 수 없습니다.
- DLQ redrive는 명시적 운영자 작업입니다. DLQ 쓰기 실패는 집계하며 정상 소비자와 격리합니다.
- `InMemoryBus`는 프로덕션 브리지와 동일한 묶음, 파티션, 시간 제한 및 실패 격리 계약을 따릅니다.
- 에이전트 게시는 `PantheonBus` 프로토콜을 사용하므로 런타임 조립에서 역할이나 권한 계약을
  바꾸지 않고 전달 어댑터를 교체할 수 있습니다.

## 거버넌스와 롤백

권위 있는 웨이브 간 규칙은 저장소 지침에서 관리합니다:

- 문서와 이중 언어 업데이트: [코딩 규칙](../../../.github/instructions/coding-conventions.instructions.md)과 [언어 정책](../../../.github/instructions/language.instructions.md)
- 고정 에이전트 역할과 권한: [에이전트 판테온 지침](../../../.github/instructions/agent-pantheon.instructions.md)
- 포크 커스터마이제이션: [고객 무관 범위](../../../.github/instructions/generic-scope.instructions.md)

범위가 제한된 각 웨이브는 독립적으로 되돌릴 수 있습니다. 새로 조립한 단계는 shadow에서
시작하며, 롤백은 권한을 부여하거나 과거 근거를 다시 쓰지 않은 채 이전 바인딩을 복원합니다.

## 관련 문서

| 학습 주제 | 읽기 |
|-----------|------|
| 고정 역할, 토픽, 작업 및 성능 저하 | [에이전트 판테온](agent-pantheon-ko.md) |
| 에이전트 간 작업 흐름 정의 | [에이전트 작업 흐름](agent-workflows-ko.md) |
| 작업 흐름별 롤아웃 순서와 근거 | [에이전트 작업 흐름 Shadow 롤아웃](agent-workflow-rollout-ko.md) |
| 런타임 소스 소유권 | [프로젝트 구조](../architecture/project-structure-ko.md) |
| KPI 측정과 승격 근거 | [목표와 메트릭](../architecture/goals-and-metrics-ko.md) |
| 지원되는 다운스트림 바인딩 | [다운스트림 포크 가이드](../fork-and-sequencing/downstream-fork-guide-ko.md) |
