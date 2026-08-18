---
title: 에이전트 판테온 구현 계획
translation_of: agent-pantheon-implementation.md
translation_source_sha: 22942c4f969bcbf1ec61835a08c4a0033b4688e3
translation_revised: 2026-08-19
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
| W7 에이전트 간 shadow 작업 흐름 메커니즘 | implemented | [`test_wave7_workflows.py`](../../../services/core-control-plane/tests/agents/test_wave7_workflows.py) | 작업 흐름에 실행 가능한 합성 shadow 추적이 있으며, enforce 작업 흐름을 기본값으로 사용하는 근거는 이 문서에 없습니다. |
| W8 KPI, 승격 및 성능 저하 메커니즘 | implemented | [`test_wave8_kpi_degradation.py`](../../../services/core-control-plane/tests/agents/test_wave8_kpi_degradation.py) | KPI 보고는 측정값과 사용 불가능한 근거를 구분하고, 근거가 없으면 승격을 차단하며, 주입된 성능 저하 훈련이 고정 판테온을 다룹니다. |
| W3 추적 연속성 근거 인계 | implemented | `huginn.py`; `heimdall.py`; `test_trace_continuity_chain.py` | sensing 경로는 허용 목록의 범위가 제한된 연속성 근거만 보존하고 역할, topic, 작업 권한을 바꾸지 않은 채 관측된 사유를 인시던트 후보 하나에 전달합니다. |
| 실제 운영 KPI 검증 및 실제 enforce 승격 | not-started | [목표와 메트릭](../architecture/goals-and-metrics-ko.md) | 이 계획에는 보존된 실제 shadow 표본 집합, 운영 승격 증적, 독립적인 검토 또는 실제 판테온 enforce 승격 근거가 없습니다. |

### 구현 이력

| 날짜 | 상태 | 변경 | 근거 | 남은 작업 |
|------|------|------|------|-----------|
| 2026-08-13 | in-progress | W0-W8 전체 완료 주장을 독립적으로 근거를 확인할 수 있는 구현 영역으로 교체했습니다. | 현재 변경 | 검증 완료 또는 enforce 운영을 주장하기 전에 실제 근거를 수집하고 별도 검토를 거친 승격을 완료합니다. |
| 2026-08-14 | implemented | 선택적 대화 T2 종합을 범위가 제한된 T1 답변 신호의 결정론적 충돌 평가 결과에만 실행하도록 했습니다. | `current change`, 집중 숙의 테스트 36개 및 framework layout 검사 | 에스컬레이션하지 않는 분기와 충돌로 에스컬레이션하는 분기의 통제된 런타임 근거를 보존합니다. |
| 2026-08-17 | implemented | 범위가 제한된 Huginn-Heimdall 연속성 근거 인계를 추가하고 인시던트 후보에 인식된 관측 사유를 보존했습니다. | `current change`; 작업처럼 보이는 위조 입력을 제외한 집중 추적-인시던트 체인 통과. | 이슈 #142에서 추적하는 통제된 실시간 시나리오 근거를 보존합니다. |

### 남은 작업

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
`services/core-control-plane/src/fdai/runtime/bootstrap.py`에서 조립합니다.

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
| `payload_validator` | 프로바이더 경계에서 잘못된 게시를 거부합니다. |
| 소비자 재시작 제한 | 형제 소비자를 취소하지 않고 지수 백오프와 유한한 재시작 상한을 적용합니다. |
| `health()` | 브리지 메트릭, 에이전트와 소비자 상태, 사용할 수 없는 에이전트, 연속성 및 유효 enforce 상태를 보고합니다. |
| Shadow 관찰기 | 권위 있는 구독자의 레코드를 소비하지 않고 실행 예정 결정을 측정합니다. |
| `ShadowDivergenceLedger` | 승격 근거를 위해 상관관계 ID로 shadow 결정과 권위 있는 결정을 결합합니다. |
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
