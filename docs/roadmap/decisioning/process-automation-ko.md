---
title: 프로세스 자동화(Process Automation)
translation_of: process-automation.md
translation_source_sha: a430f230bf837031e886ba22ad48721c35c13bd2
translation_revised: 2026-08-14
---

# 프로세스 자동화(프로세스 자동화)

프로세스 자동화는 다단계 비즈니스 프로세스를 1급, 온톨로지 연결, 거버넌스된
아티팩트로 바꾼다. 프로세스는 컨트롤 플레인을 우회하는 스크립트가 아니다. 이는
온톨로지 `ActionType` 호출의 선언적 시퀀스이며, 동일한 trust-routing 컨트롤
루프가 한 번에 한 스텝씩, 단일 교정 과 동일한 안전 불변식 아래에서
전달 한다.

이 문서는 [agent-workflows.md](../agents/agent-workflows-ko.md) 의 머신-리더블 대응물이다.
그 문서가 12개 cross-agent 워크플로를 산문과 시퀀스 다이어그램으로 기술한다면,
이 문서는 워크플로를 catalog-as-code 로 출시하고 shadow 모드로 실행하게 하는
카탈로그 스키마, 온톨로지 추가분, 런타임 배선을 정의한다.

> **범위.** 여기의 모든 것은 customer-agnostic 이다
> ([generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md)).
> 워크플로는 [`rule-catalog/action-types/`](../../../rule-catalog/action-types)
> 아래의 업스트림 `ActionType` 카탈로그만 참조하며, 새 변경 기본 요소 를
> 선언하지 않는다. 새 기능 가 필요한 프로세스는 먼저 업스트림 `ActionType`
> 문서 PR 을 열라는 신호다.

## 구현 상태

### 구현 범위

| 영역 | 상태 | 근거 | 참고 |
|------|------|------|------|
| 워크플로 카탈로그, 스키마 및 온톨로지 계약 | implemented | [`test_workflow_catalog.py`](../../../services/core-control-plane/tests/rule_catalog/test_workflow_catalog.py), [`Process.yaml`](../../../rule-catalog/vocabulary/object-types/Process.yaml) | 로더, 교차 참조, shadow 기본값 및 Process 어휘 검사가 구현되어 있습니다. |
| 런타임 저널, 변환 결과, 승인 및 명령 | implemented | [`test_orchestrator.py`](../../../services/core-control-plane/tests/core/workflow/test_orchestrator.py), [`test_projection.py`](../../../services/core-control-plane/tests/core/workflow/test_projection.py), [`test_workflow_approval.py`](../../../services/core-control-plane/tests/delivery/persistence/test_workflow_approval.py) | 영속 스냅샷, 추가 전용 이벤트, 승인, 재시도, 재개 및 취소 동작에 집중 테스트가 있습니다. |
| 보상 및 영속 자동화 hold | implemented | [`test_automation_hold.py`](../../../services/core-control-plane/tests/core/workflow/test_automation_hold.py), [`test_orchestrator.py`](../../../services/core-control-plane/tests/core/workflow/test_orchestrator.py), [`test_control_loop_authority.py`](../../../services/core-control-plane/tests/core/test_control_loop_authority.py), [`test_gate.py`](../../../services/core-control-plane/tests/core/risk_gate/test_gate.py) | 모든 불완전 보상 경로가 영속 대상 hold를 발행합니다. 재시작과 중복 전달에서도 hold를 유지하고 일반 정방향 전달을 차단하며, 일치하는 검증된 복구만 hold를 해제할 수 있습니다. |
| 저작 및 읽기 전용 Process 화면 | implemented | [`workflow-builder.chat.ts`](../../../console/src/routes/workflow-builder.chat.ts), [저작 화면](#8-저작-표면-콘솔-workflow-builder) | 콘솔은 실행 권한 없이 비공개 초안을 만들고 검증하며 Process 변환 결과를 조회할 수 있습니다. |
| 실패 시에만 실행되는 `on_failure` 분기 | implemented | [`runner.py`](../../../services/core-control-plane/src/fdai/core/runbook/runner.py), [`models.py`](../../../services/core-control-plane/src/fdai/core/runbook/models.py), [`test_runbook_runner.py`](../../../services/core-control-plane/tests/core/runbook/test_runbook_runner.py) | 선언된 대체 스텝은 성공 경로에서 `fallback_not_triggered` 로 건너뛰고, 자신을 가리키는 스텝이 실패했을 때만 실행되며, 무관한 스텝의 실패로는 발동하지 않고, 명시적 재개로는 여전히 진입할 수 있습니다. `Runbook` 은 이제 `Workflow` 계약과 같은 이유로 자기 참조 및 역방향 대체를 거부합니다. |
| 타입이 지정된 `SignalType` 트리거 참조 | not-started | [알려진 한계](#21-알려진-한계-p1), [`signal_type.py`](../../../services/core-control-plane/src/fdai/rule_catalog/schema/signal_type.py), [`signal-types.yaml`](../../../rule-catalog/vocabulary/signal-types.yaml) | 레지스트리는 관측 의미만 선언하지만 제공 워크플로 트리거는 요청 및 명령 이벤트를 가리킵니다. 레지스트리를 넓히면 T0 규칙 dispatch 해석도 바뀌므로, 로드 시점 교차 검사에는 온톨로지 승격이 먼저 필요합니다. |

### 구현 이력

| 날짜 | 상태 | 변경 | 근거 | 남은 작업 |
|------|------|------|------|-----------|
| 2026-08-14 | in-progress | 이전 출처 이력을 재구성하지 않고 구현 원장을 도입하고 남은 헌법상 보상 공백을 표시했습니다. | `current change`; 구현 범위 표의 현재 소스, 집중 테스트 및 추적성입니다. | 아래의 보상 hold 및 승격 종료 조건을 완료해야 합니다. |
| 2026-08-14 | implemented | 보상 실패, ledger 재시작, 중복 전달, 정방향 전달 차단 및 일치하는 복구 해제 전반에서 영속 자동화 hold를 검증하고 FDAI-CONST-009를 implemented로 기록했습니다. | `current change`; `test_automation_hold.py`, `test_orchestrator.py`, `test_control_loop_authority.py`, `test_gate.py`; 집중 검사 10개가 통과했습니다. | 아래의 독립 워크플로 승격 근거와 관련 없는 트리거 및 분기 작업은 계속 남아 있습니다. |
| 2026-08-14 | implemented | `on_failure` 분기를 실패 시에만 실행되도록 바꿔, 선언된 대체 스텝이 성공 경로에서 일반 정방향 스텝으로 실행되지 않게 했습니다. | `current change`; [`runner.py`](../../../services/core-control-plane/src/fdai/core/runbook/runner.py), [`test_runbook_runner.py`](../../../services/core-control-plane/tests/core/runbook/test_runbook_runner.py); 집중 runbook 및 workflow 검사 114개가 통과했습니다. | 로드 시점 교차 검사 전에 요청 및 명령 트리거를 포함하는 `SignalType` 어휘를 승격하고, 독립 워크플로 승격 근거를 보존해야 합니다. |

### 남은 작업

- [x] 누락, 실패 또는 채점 불가능한 보상에 대한 영속 대상 hold가 재시작과 중복 전달에서도
  유지되고 이후 정방향 전달을 차단하며, 일치하는 검증된 복구를 통해서만 해제되는 것을
  집중 hold, orchestrator, control-loop 및 risk-gate 테스트로 증명했습니다.
- [ ] 타입이 지정된 `SignalType` 트리거 참조를 추가하고 로드 시점에 교차 검사합니다. 이 작업은
  요청 및 명령 트리거를 포함하는 `SignalType` 어휘 승격에 가로막혀 있습니다. 제공 레지스트리는
  관측 의미만 선언하며, 이를 넓히면 T0 규칙 dispatch 해석도 함께 바뀝니다.
- [x] 실패 시에만 실행되는 `on_failure` 분기를 구현했으며, 성공 경로가 발동되지 않은 대체
  스텝을 건너뛰고, 무관한 실패는 그 대체를 발동하지 않으며, 명시적 재개는 여전히 거기로
  진입할 수 있음을 런타임 테스트로 입증합니다.
- [ ] 하나의 고정된 Workflow 및 ActionType 카탈로그 리비전에서 독립 효과 및 복구 종결을
  포함한 승격된 워크플로 시나리오를 보존합니다.

## 1. 혼동하면 안 되는 네 가지 개념

프로세스 자동화는 절대 혼동하면 안 되는 네 개념을 조합한다. 각각 단일 책임을
가진다.

| 개념 | 책임 | 백킹 |
|------|------|------|
| **ActionType** | 7개 안전조건(stop, 롤백, 영향 상한, 예행 실행, 잠금, 멱등성, 감사)을 가진 CSP-중립 변경 카테고리 | [`rule-catalog/action-types/`](../../../rule-catalog/action-types), [action-ontology.md](action-ontology-ko.md) |
| **작업 흐름** | 비즈니스 프로세스의 *선언*: 각각 하나의 `ActionType` 을 참조하는 스텝의 순서 리스트 + 트리거 + 승격 게이트 + 기본 모드 | [`rule-catalog/workflows/`](../../../rule-catalog/workflows), 아래 스키마 |
| **프로세스** | 실행 중 워크플로의 *런타임 인스턴스와 상태*: 현재 스텝, 대상 리소스, 진행한 발견 사항 | `Process` ObjectType (온톨로지) |
| **런북** | *실행 메커니즘*: 스텝 리스트를 걷고, `on_failure` 를 존중하며, 집계 감사 행 를 기록 | [`services/core-control-plane/src/fdai/core/runbook/`](../../../services/core-control-plane/src/fdai/core/runbook) |

분리가 중요합니다. `Workflow`는 *무엇*이 *언제* 실행되는지 선언하고 `Runbook`은 compiled
`Workflow`의 thin 실행기이며 `Process`는 한 번의 실행에 대한 audited 상태입니다. 변경
단계는 `ActionType`에 위임하여 안전성 불변식을 상속합니다. 읽기 전용 `evidence` 단계는 대신
`WorkflowEvidenceDispatcher`를 사용하고 액션 권한이 없으며 브라우저 근거가 사용 불가이면
실패 시 차단됩니다. ([설계](../interfaces/browser-evidence-ko.md))

## 2. 워크플로 카탈로그 스키마

워크플로는 [`rule-catalog/workflows/`](../../../rule-catalog/workflows) 아래의
catalog-as-code 이며, 로드 시
[`shared/contracts/workflow/schema.json`](../../../services/core-control-plane/src/fdai/shared/contracts/workflow/schema.json)
과 `Workflow` pydantic 모델에 대해 검증된다. `description` 과 `anti_scope` 를
제외한 모든 필드는 필수다.

```yaml
schema_version: "1.0.0"
name: cost-aware-remediation          # 안정 dotted id; audit 키
version: "1.0.0"
description: >-                        # <= 200 자, 영어, 마케팅 없음
  Attach a cost impact to every SRE remediation so the verdict reflects
  reliability and finance together.
trigger:
  kind: signal                         # signal | schedule
  signal_type: object.drift            # kind == signal 일 때 필수
  schedule: null                       # kind == schedule 일 때 RFC-5545 형태 cron
default_mode: shadow                   # NEW 워크플로는 shadow 기본값 MUST
promotion_gate:
  min_shadow_days: 14
  min_samples: 100
  min_accuracy: 0.95
  max_policy_escapes: 0
steps:
  - id: estimate_cost
    action_type_ref: remediate.right-size   # ActionType name 으로 resolve MUST
    guard_rule_ref: null                     # 스텝을 gate 하는 선택적 Rule id
    compensated_by: null                     # 이 스텝을 되돌리는 선택적 ActionType
    on_failure: null                         # 실패 시 실행할 선택적 step id
    params:                                  # 선택적 scalar 인자; 문자열은 템플릿 가능
      reason: "drift on ${event.resource_ref}"
  - id: apply_rightsize
    action_type_ref: remediate.right-size
    on_failure: null
anti_scope: >-                          # 선택적; 워크플로가 의도적으로 제외하는 것
  Not a budget enforcement path; it only annotates SRE actions with cost.
```

로더가 강제하는 필드 규칙:

- `name` 은 안정 dotted id (`^[a-z][a-z0-9_.-]{0,79}$`); 로더는 업스트림 과 모든
  포크 추가분에 걸쳐 이 값으로 dedupe 한다.
- `steps` 는 최소 하나; 단계 `id` 는 워크플로 내에서 유일하다.
- 모든 `action_type_ref` 는
  [`load_action_type_catalog`](../../../services/core-control-plane/src/fdai/rule_catalog/schema/action_type.py)
  의 등록된 `ActionType` 이름 으로 해석 MUST. 오타는 첫 전달 가 아니라
  로드 시 실패한다 - [`rule.py`](../../../services/core-control-plane/src/fdai/rule_catalog/schema/rule.py) 의
  `remediates` 링크가 쓰는 동일한 cross-reference 규율.
- `compensated_by` 는 설정 시 역시 `ActionType` 이름 으로 해석 MUST. 그 스텝의
  saga 롤백 액션이다 ([5절](#5-saga-보상saga-compensation) 참조).
- `on_failure` 는 설정 시 같은 워크플로 내 스텝 리스트에서 **뒤에 오는** 기존 단계
  `id` 를 참조 MUST (자기 자신이나 앞 스텝은 불가), 정확히
  [`Runbook`](../../../services/core-control-plane/src/fdai/core/runbook/models.py) 스텝처럼. 역방향 대체 경로 은
  러너가 이미 적용된 스텝을 재실행하게 만들므로 로드 시 거부된다.
- `guard_rule_ref` 는 설정 시 로드된 룰 카탈로그의 Rule id 로 해석 MUST.
  가드 는 스텝의 결정론적 "언제"다 - policy-as-code 술어이지, 모델 텍스트가
  아니다.
- 업스트림 워크플로는 `default_mode: shadow` MUST. `enforce` 로 출시되는
  워크플로는 업스트림 스키마 위반이다; 강제 적용 승격은 별도의 gated 거버넌스 PR.
- `params` 는 설정 시 스텝의 scalar (문자열 / number / boolean) 인자 맵이다.
  문자열 값은 `${event.resource_ref}` / `${event.trigger_ts}` /
  `${event.event_type}` 토큰을 담을 MAY 하며 오케스트레이터가 런타임에 트리거
  이벤트에서 치환한다; 알 수 없는 토큰은 verbatim 으로 남아 미해결 참조가 감사 에
  보인다. 해결된 params 는 `workflow.step` 감사 행 에 기록된다.

### 2.1 알려진 한계 (P1)

- **`signal_type` 는 자유 문자열이다.** 트리거 `signal_type` 은 signal-type
  레지스트리에 대해 cross-reference 되지 않으므로 (업스트림 에 아직 없음) 오타가
  로드 시 잡히지 않는다. `SignalType` 온톨로지 승격이 도착하기 전까지는 문서로
  취급하라.
- **`on_failure` 는 성공 경로에서도 실행된다.** 컴파일된 런북 러너는 선언된
  모든 스텝을 순서대로 걷는다; `on_failure` 대상은 성공 시에도 실행되는 일반
  스텝이며, 추가로 실패 시 대체 경로 으로도 실행된다. 조건부 분기가 구현되고 테스트되기
  전까지 `on_failure`가 null이 아닌 워크플로우는 강제 적용 승격 대상이 아니며 shadow에
  남아야 합니다. 제공 워크플로우는 이를 null로 두고 `compensated_by`를 사용합니다. 멱등
  대체 경로를 작성해도 승격 차단이 해제되지 않습니다.

> **해결됨.** 분기는 이제 실패 시에만 실행됩니다. 어떤 스텝의 `on_failure` 대상으로
> 지정된 스텝은 성공 경로에서 `fallback_not_triggered` 사유로 건너뛰며, 자신을
> 가리키는 스텝이 실패했을 때만 실행됩니다. 명시적 재개(`start_step_id`)는 여전히
> 대체 스텝으로 직접 진입할 수 있습니다.
> [`runner.py`](../../../services/core-control-plane/src/fdai/core/runbook/runner.py) 와
> [`test_runbook_runner.py`](../../../services/core-control-plane/tests/core/runbook/test_runbook_runner.py)
> 를 보세요.

### 2.2 정의, 소유권, 연결

카탈로그 문서와 운영자의 자동화 설정은 별도 기록다.

- **`WorkflowDefinition`**은 변경할 수 없는 content-hash 작업 흐름 문서다.
  `origin` (`upstream`, `tenant`, `user`), `visibility` (`global`, `team`,
  `private`), 수명 주기, 소유자, 출처 이력, 해석된 ActionType 버전,
  ActionType 카탈로그 다이제스트를 기록한다.
- **`WorkflowBinding`**은 인증된 principal 하나에 속하며, 보이는 정의를
  `deck_open`, `schedule`, `signal`에 연결한다. 예약 연결은 strict cron과
  IANA 표준 시간대가 필요하고 신호 연결은 신호 타입이 필요하다. 매개변수는
  scalar로 제한되며 새 액션을 정의할 수 없다.

콘솔은 정의를 **Built-in**, **Shared**, **Mine**으로 그룹화한다. Built-in은
업스트림 git 카탈로그에서 오고, Shared는 검토를 통과한 테넌트 카탈로그 산출물다.
Mine은 비공개 user 정의를 포함한다. **My automations**는 principal 연결을
별도로 표시하므로 새 트리거나 표준 시간대가 단계 그래프를 복제하지 않고 기존
정의를 재사용한다.

모든 액션 단계는 계속 ActionType 카탈로그를 통해 해석된다. 연결은 자율성을
높이거나 등록되지 않은 액션을 추가할 수 없다. 프로세스 시작 전 컴파일러는 작업 흐름
버전, 정의 해시, 해석된 ActionType 버전, 카탈로그 다이제스트를 pin하므로 재생이
현재 카탈로그에 의존하지 않는다. 비공개 정의의 공유 또는 승격은 in-place
가시성 토글이 아니라 검토된 거버넌스 흐름으로 유지한다.

## 3. 온톨로지 추가분

프로세스 자동화는 정확히 하나의 ObjectType 과 두 개의 LinkType 를 추가한다. 이는
감사 로그를 복제하지 않으면서 실행 중 프로세스를 그래프에서 traverse 가능하게
만드는 최소한의 정당한 확장이다.

### 3.1 `Process` ObjectType

[`rule-catalog/vocabulary/object-types/Process.yaml`](../../../rule-catalog/vocabulary/object-types/Process.yaml)
는 한 번의 워크플로 실행에 대한 런타임 상태를 선언한다. 모든 출시 built-in 처럼
`id` 로 키 한다.

| 속성 | 타입 | 의미 |
|------|------|------|
| `id` | 문자열 | `(workflow_ref, target_resource_id, trigger_ts)` 에서 파생한 멱등적 프로세스 id이며 재시도는 이를 재사용합니다. 저장된 모든 프로세스를 Operator API에서 조회할 수 있도록 1-200자의 URL-safe 영문자, 숫자, `_`, `.`, `:`, `-`만 사용합니다. |
| `workflow_ref` | 문자열 | 이 프로세스가 인스턴스화하는 `Workflow` 이름. |
| `workflow_version` | 문자열 | 이 실행에 선택된 불변 작업 흐름 버전. |
| `status` | 문자열 | `pending`, `running`, `waiting`, `compensating`, `compensated`, `succeeded`, `failed`, `cancelled`, `timed_out`. |
| `current_step` | 문자열 | 현재 진행 중 단계 id (최종 일 때 빈 값). |
| `target_resource_id` | 문자열 | 프로세스가 작동하는 주 Resource. |
| `started_at` | datetime | RFC 3339 UTC 시작 타임스탬프. |
| `updated_at` | datetime | 최근 커밋 전이 의 RFC 3339 UTC 타임스탬프. |
| `correlation_id` | 문자열 | 프로세스 저널, 감사 행, 변환 결과 이 공유하는 상관관계 id. |
| `revision` | 정수 | 권위 있는 스냅샷 의 optimistic 동시성 개정 번호. |

### 3.2 LinkType

| LinkType | 엔드포인트 | Cardinality | 플래그 | 의미 |
|----------|-----------|-------------|--------|------|
| `targets` | 프로세스 -> Resource | many_to_one | - | 프로세스가 작동하는 리소스; risk-gate 가 프로세스 대상에 대한 영향 범위 를 계산하게 한다. |
| `advances` | 프로세스 -> 발견 사항 | many_to_many | `temporal_order` | 프로세스가 진행한 순서 있는 발견 사항; 재생 를 위한 시간-존중 체인. |

비즈니스 핵심 링크 - 프로세스 스텝에서 `ActionType` 로 - 는 온톨로지 LinkType 가
아니다. `ActionType` 인스턴스는 카탈로그에 살고 이름 으로 cross-reference 되기
때문이며, 정확히 `remediates` 가 Rule 을 `ActionType` 로 해석 하는 방식이다.
워크플로 로더가 로드 시 그 연결을 강제한다; 온톨로지 LinkType 는 1급 객체 타입
간 런타임 그래프 엣지만 커버한다.

## 4. 컨트롤 루프 통합

집중 [워크플로 컨트롤 루프 통합](workflow-control-loop-integration-ko.md) 문서가 오케스트레이션,
catalog-root, 어댑터 라우팅, 저널, 명령 및 샌드박스 실행 세부 정보를 소유합니다.

## 5. saga 보상(saga 보상)

중간에 실패하는 다단계 프로세스는 이미 적용된 스텝을 되돌릴 수 있어야 MUST. 각
스텝은 그것을 되돌리는 `ActionType` 인 `compensated_by` 를 선언 MAY. 보상 계약은:

- 스텝 실패 시, 앞서 적용된 스텝들은 동일 파이프라인을 통해 그들의
  `compensated_by` 액션을 전달 하여 역순으로 보상된다.
- 보상 액션 자체가 `ActionType` 호출이므로 자기만의 롤백 계약 와 감사
  엔트리를 가진다 - 감사 없는 undo 는 없다.
- `compensated_by` 가 없고 non-reversible `ActionType` 인 스텝은 forward 전달을 중단하고
  정확한 부분 상태를 기록하며 복구를 HIL로 라우팅합니다. HIL은 부분 상태를
  사라지게 하지 않습니다.
- Applied 단계 이후 실패, 취소 또는 시간 초과는 정상 최종 상태 전에 reverse-
  의존성 보상을 시작합니다. 병렬 가지는 새 작업을 받지 않고 applied 증적을
  결합한 뒤 보상 순서를 계산합니다.
- 누락된, 실패한 또는 unscorable 보상은 `status=failed`,
  `recovery_incomplete=true`, 적용/보상 증적 및 영향 대상의 영속 자동화 보류로 끝납니다.
  읽기와 별도로 승인된 Vidar 복구만 보류를 통과할 수 있습니다. 검증된 full 보상은
  `status=compensated`를 사용할 수 있지만 부분 결과는 `succeeded`가 될 수 없습니다.

프로세스 오케스트레이터는 이제 선언된 보상을 타입이 지정된 유입으로 전달합니다. 전달 전에
보상 의도를 기록하고 제안 참조를 별도 보존하며 비정상 종료 후에도 같은 프로세스를
재개합니다. 제안 참조는 전달만 입증합니다. `WorkflowOutcomeVerifier`가 각 액션과
보상 증적을 독립적으로 검증해야 forward 단계가 완료되거나 프로세스가 `compensated`가
됩니다. 근거가 없거나 거부되거나 malformed이면 waiting 상태를 유지하거나
`recovery_incomplete`로 끝나며 성공이 되지 않습니다.

업스트림 headless 런타임과 운영 Operator API는 shared 영속 상태 저장소에
`StateStoreWorkflowOutcomeLedger`를 연결합니다. 컨트롤 루프는 강제 적용 액션과
`ResponseOutcome`의 실행 신원이 일치할 때만 변경할 수 없는 증적을 기록하며, 성공 증적에는
독립적으로 검증된 효과 근거도 필요합니다. 해석기는 제안 참조, 프로세스, 단계로
증적을 읽으므로 재개 시 호출자가 제공한 상태나 증적 맥락을 신뢰하지 않습니다. Shadow,
알 수 없음, 누락된, mismatched, unscorable 결과는 프로세스를 진행시킬 수 없습니다.

`StateStoreAutomationHoldLedger`는 recovery-incomplete 프로세스가 종료되기 전에 대상 다이제스트 기반
보류를 기록합니다. Headless 컨트롤 루프는 모든 ordinary 액션 전에 이 보류를 읽고 RiskGate는
`deny`를 반환합니다. 보류 읽기가 실패하거나 malformed여도 거부합니다. 읽기 경로는 이 변경
게이트를 사용하지 않습니다. 활성 보류를 소유한 프로세스와 작업 흐름 계보가 일치하는
`compensate_*` 액션만 일반 안전성 및 권한 확인 파이프라인에 다시 진입할 수 있으며 RiskGate는
이 복구를 사람 승인으로 제한합니다. 모든 보상 결과에는 계속 독립적인 효과
근거가 필요합니다. 모든 증적을 검증한 뒤 조정기는 `status=compensated`를 기록하기 전에
개정 번호 compare-and-set으로 일치하는 보류를 release합니다. release 충돌 또는 영속성
실패는 `recovery_incomplete`로 종료합니다. Released 보류는 이후 프로세스를 위해 다시 발행할 수
있으며 이전 프로세스는 새 보류를 release할 수 없습니다.

`ChangeWindowWorkflowGuardEvaluator`는 정확한 프로세스 대상과 evaluation 시간으로
`gate_ref: change-window.active`를 해석합니다. 다른 참조는 기존 가드 평가기에 delegate하므로
architecture-review 운영 게이트는 그대로 유지됩니다. 가드 해석은 실패 시 차단입니다: 오래된 평가 시점,
예외를 던지거나 사용할 수 없는 평가기, 불리언이 아닌 결과는 각각 단계를 차단하고 범위가 제한된
`guard_error`를 기록하며, 깨끗한 정책 차단은 `guard_error`를 null로 유지합니다.
Shipped `planned-vm-start-change`
작업 흐름은 활성 구간, Owner 정족수, `ops.start-vm`, 독립 결과 검증, 변경 요약,
`ops.deallocate-vm` 보상의 재사용 가능한 전체 pattern을 보여 줍니다. Versioned 작업 흐름
design이 이 ActionType들을 pin하며 런타임에서 arbitrary 변경을 선택하는 방식은 의도적으로
지원하지 않습니다.

공개 작업 흐름 실행 경로는 declared 매개변수 substitution에만 맥락을 사용합니다.
`requester.principal`은 항상 인증된 운영자로 교체하고 호출자가 제공한 `approval.*`,
`action.*`, `compensation.*`, `decision.*`, `parallel.*`, `requester.*`, `wait.*` 키는
거부합니다. 이 이름 공간은 서버가 소유한 프로세스 근거입니다. 공개 요청은 승인 정족수,
액션 성공, 복구 또는 control-step 진행 상황을 만들 수 없습니다.

새 `process.created` 이벤트는 해당 프로세스를 정확히 재개하는 데 필요한 최소 서버가 소유한
묶음을 포함합니다. Original 트리거 시간과 모드, `requester.principal`, 작업 흐름 매개변수
템플릿에서 참조한 맥락 키만 기록합니다. `x-fdai-redact` 인자에 사용되는 값은 제외하고
묶음을 불완전한으로 표시하므로 시크릿을 저장하는 대신 재개를 차단합니다.
`POST /workflows/{process_id}/resume`은 요청 본문을 허용하지 않습니다. 경로는 프로세스 스냅샷과
creation 이벤트를 다시 읽고 작업 흐름 이름 및 버전과 derived 프로세스 id를 검증한 뒤 original 대상,
상관관계, 트리거, 모드, safe 맥락을 재사용합니다. 기여자는 shadow 프로세스를 재개할 수
있습니다. 강제 적용 프로세스에는 계속 Owner와 현재 작업 흐름 강제 적용 허용 목록이 필요합니다. 근거가
누락된, 이전 방식, malformed, 민감정보가 제거된, version-mismatched 또는 identity-mismatched 상태이면 타입이 지정된 충돌을
반환하고 단계를 전달하지 않습니다.

`POST /workflows/{process_id}/cancel`도 요청 본문을 허용하지 않으며 같은 영속 묶음을
해석합니다. 기여자는 shadow 프로세스를 취소할 수 있고 강제 적용 프로세스에는 Owner가
필요합니다. 이 명령은 프로세스가 `pending` 또는 `waiting`일 때만
`process.cancellation-requested`를 기록합니다. `running` 프로세스는 in-flight 디스패처가 idle이라고
가정할 수 없으므로 `process_not_at_safe_boundary`를 반환합니다. Waiting 액션은 먼저 권위 있는
결과를 조정합니다. 실행기는 모든 새 단계를 차단하고 검증된 applied 단계는 기존 reverse
보상 경로로 진입합니다. Waiting 승인은 영속 Var 상태와 모든 HIL 자리를 닫으므로 늦은
승인이 취소된 프로세스를 되살릴 수 없습니다. Applied 단계가 없는 취소는 `cancelled`로
종료하고 applied 단계 이후 검증된 복구는 `compensated`로 종료합니다.

액션 전달 및 단계 저널 신원은 명시적인 긍정 `attempt`를 포함하며 호환성
기본값은 `1`입니다. `STEP_STARTED`, `ACTION_DISPATCHED`, 가지, waiting, 완료, 실패,
최종, 감사 id는 시도를 포함하고 `WorkflowActionDispatcher`는 타입이 지정된 제안 멱등성
키에 이를 사용합니다. 따라서 두 시도가 하나의 이벤트 또는 제안으로 합쳐지지 않습니다.

`POST /workflows/{process_id}/retry`는 `failed` 상태에서 새 시도를 시작하거나 최종 사유가
`approval_timed_out`인 경우에만 `timed_out` 상태에서 시작하며 본문을 받지 않습니다. 최종
시도에는 허용 목록에 포함된 effect-free 사유가 있어야 하며 액션 전달, 취소,
보상 근거가 없어야 합니다. Approval 근거는 최종 `approval_rejected` 또는
`approval_timed_out`에만 허용됩니다. 디스패처 exception은 로컬 전달 이벤트가 없어도
모호한하므로 `retry_requires_recovery`를 반환합니다. Shadow 재시도에는 기여자가 필요하고
강제 적용 재시도에는 Owner와 현재 강제 적용 허용 목록이 필요합니다. 서버가 소유한 시도 한도의
기본값은 3이며 호출자가 높일 수 없습니다.

작업 흐름 승인 상태와 HIL 자리 신원은 프로세스, 단계, 시도에 연결됩니다. 시도 1은
기존 영속 기록을 위해 이전 방식 키를 유지하고 이후 시도는 서로 다른 키를 사용합니다. 한 명의
거절은 전체 정족수 시도를 최종으로 만들고 모든 형제 자리를 닫으므로 late 승인이
거절과 경쟁할 수 없습니다. `approval_rejected` 또는 `approval_timed_out` 뒤 범위가 제한된 재시도는 새
시도용 fresh 자리만 만듭니다. 형제 보류 종결이 중단되어도 최종 작업 흐름 CAS가
권위 있는하므로 큐는 stale 또는 만료된 자리를 숨기고 다음 프로바이더 읽기가 physical 보류
상태를 복구합니다. 취소와 시간 초과는 exact 시도를 닫고 거절, 취소, 시간 초과는
서로를 덮어쓰지 않습니다. 작업 흐름 프로바이더가 시간 초과 terminalization을 소유하며 범용 HIL 만료
워커는 작업 흐름 자리를 건너뜁니다. Approval 결정은 영속 기한 전에만 수락됩니다. Late
결정이 먼저 개정 번호를 변경하면 실행기는 해당 시도를 다시 읽고 시간 초과 CAS를 재시도하므로
기한 뒤 완성된 정족수가 프로세스를 진행시키지 못합니다. 기한 전에 완성된 정족수는 프로세스
조정이 나중에 재개되어도 유효합니다. 콜백과 대화 승인 표면은
no-self-approval을 위해 정규화된 principal을 비교합니다. Approval 점유 CAS 재시도는 fixed
contention 한계 대신 변경할 수 없는 자리 정족수에 따라 확장됩니다.

작업 흐름 감사는 각 ActionType의 `x-fdai-redact` 경로를 사용합니다. 민감정보가 제거된 필드는
`[REDACTED]`로 표시되며 프로세스 저널에 들어가지 않습니다. 작업 흐름 런타임에는 시크릿 보관
프로바이더가 없으므로 resolved params에 민감정보가 제거된 필드가 있는 강제 적용 액션은 타입이 지정된 전달 전에
실패합니다. Secret-bearing 작업 흐름 단계는 값을 감사 또는 재생 상태에 저장하지 않고 공급할
전용 보관 경계가 생길 때까지 사용 불가 상태를 유지합니다.

ChangeWindow 평가는 온톨로지 vocabulary를 따릅니다. `reviewed`와 `active`는 effective 상태이고
`allow`, `maintenance`, `emergency`는 게이트를 허용하며 `freeze`, `quiet`는 차단합니다. Malformed,
out-of-range, 잘린 근거는 계속 차단됩니다.

## 6. 거버넌스

- **Shadow-first.** 모든 워크플로는 `default_mode: shadow` 로 출시된다: 각 스텝을
  변경 없이 judge-and-log 한다. 강제 적용 승격은 고정된 시나리오 세트에서
  워크플로의 `promotion_gate` 를 측정하는 명시적, 별도 리뷰된 거버넌스 PR 이다.
- **HIL 은 Var 통해, 감사 은 Saga 통해.** `ActionType` 이 HIL 로 라우팅되는
  스텝은 승인자 principal (Var) 을 거친다; 모든 최종 결과는 Saga 가 감사
  한다. 프로세스 자동화는 새 승인 이나 감사 표면을 추가하지 않는다.
- **Human 재정의 적용.** 스텝을 게이트 하는 룰에 대한 오퍼레이터 재정의 는
  재정의 스코프에서 그 스텝의 실행을 억제하며, 평가기 는 무엇을 했을지
  계속 기록해 발견 루프에 공급한다.
- **주입에 의한 포크 커스터마이즈.** 포크 는 자기 카탈로그 루트 아래 자기
  워크플로를 추가하고 동일 로더 경계 을 통해 등록한다; `core/` 를 편집하지 않는다.

### 6.1 승인자 할당(승인자 배정)

HIL 로 라우팅되는 워크플로 스텝은 "누가 승인하고, 어떻게 도달하는가"에 대한 구체적
답이 필요하다. 프로세스 자동화는 새 승인 표면을 추가하지 않는다;
[`WorkflowApprovalPlanner`](../../../services/core-control-plane/src/fdai/core/workflow/approval.py) 를 통해
워크플로를 기존 HIL 기계장치에 연결한다.

`Workflow` 가 주어지면 플래너는 결정론적, 읽기 전용 `ApprovalPlan` 을 만든다 -
스텝마다 하나의 `StepApproval`:

- **게이트인가?** 스텝의 `ActionType` `ceiling_by_tier` 에 `enforce_hil` 티어가
  하나라도 있거나 `prod_downgrade` 가 `enforce_hil` 로 collapse 하면 승인 게이트다.
  이는 risk-gate 가 쓰는 것과 동일한 정본 다; 플래너는 두 번째 규칙을
  만들지 않는다.
- **누가 승인하나?** 필요한 human 역할은 HIL 티어 전반의 최상위 `min_role` 이며,
  RBAC [`GroupMapping`](../../../services/core-control-plane/src/fdai/core/rbac/resolver.py) 을 통해 Entra
  security-group objectId (`aw-approvers` 또는 `aw-owners` 그룹)로 해석 된다.
  no-self-approval 은 모든 게이트 스텝에 이어진다.
- **어떻게 도달하나?** [notifications 매트릭스](../../../config/notifications-matrix.yaml)
  의 A1 `hil_approval` 라우트 - Teams 기본, Slack / 이메일 대체 경로. 구체
  어댑터는 [`HilChannel`](../../../services/core-control-plane/src/fdai/shared/providers/hil_channel.py) 경계 을
  구현한다: [`TeamsHilAdapter`](../../../services/core-control-plane/src/fdai/delivery/chatops/teams_adapter.py)
  와 [`SlackHilAdapter`](../../../services/core-control-plane/src/fdai/delivery/chatops/)
  (Adaptive 카드 / 블록 키트, HMAC 서명, 실패 시 차단). 이메일 은 send-only 경보
  레인이지 A1 승인 back-channel 이 아니다.

알림 경로를 사용할 수 없으면 해당 경로가 필요한 작업 흐름과 인시던트 경로만
권한이 낮아집니다. 런타임은 공백을 보고하고 unrelated 읽기, 거부, 큐 및 shadow 경로를
유지하며 누락된 채널을 delivered 승인 또는 successful 알림으로 처리하지 않습니다.

플랜은 역할 및 채널 배정을 제공합니다. 적용 모드에서는 승인 프로바이더가
공유 영속 StateStore에 정족수 인원별 HIL 자리를 보류합니다. 개정 번호 compare-and-set은
증적 변환 결과보다 먼저 정확한 프로세스, 단계, 필수 역할, 정규화된 principal,
결정, 증적, 시간을 Var 감사 항목과 함께 기록합니다. 서명된 콜백과
`approve_hil`은 필수 역할 및 no-self-approval을 다시 검사합니다. 대소문자를 구분하지
않는 동일 principal은 두 자리를 점유할 수 없습니다. 증적 변환 결과가 중단되어도
프로세스는 권위 있는 결정에서 재개할 수 있습니다. Headless 런타임과 운영
Operator API가 이 프로바이더를 연결하며 interactive 로컬 적용 모드는 영속 데이터베이스와
Azure 이벤트 전송 계층도 요구합니다. 구체적인 on-call OID와 채널 카드는 기존
[`HilResumeCoordinator`](../../../services/core-control-plane/src/fdai/core/hil_resume/coordinator.py) 및
[`OnCallResolver`](../../../services/core-control-plane/src/fdai/core/oncall/resolver.py) 통합으로 남으며 두 번째
승인 권한은 추가되지 않습니다.

## 7. 로더와 CI 검증

[`load_workflow_catalog`](../../../services/core-control-plane/src/fdai/rule_catalog/schema/workflow.py) 는 순수
I/O + 검증이며, `ActionType` 및 ObjectType 로더를 미러한다. 실패 시 차단 다: 어느
파일의 어느 이슈든 모든 파일의 모든 이슈를 담은 하나의 집계 에러를 raise 한다.
각 `action_type_ref` 와 `compensated_by` 를 `ActionType` 카탈로그에 대해, 각
`guard_rule_ref` 를 룰 카탈로그에 대해 cross-reference 하며, 업스트림
shadow-default 정책을 강제한다. 엔트리 포인트는 시작 시 카탈로그를 로드하므로
malformed 워크플로는 첫 전달 가 아니라 부팅을 막는다.

## 8. 저작 표면 (콘솔 workflow-builder)

오퍼레이터는 YAML 을 기억으로 손수 쓰는 것도, 여러 섹션짜리 폼을 채우는 것도
아니라 콘솔의 **workflow-builder** 뷰를 통해 사용자 정의 비즈니스 프로세스를
저작합니다. 이 표면은 범위가 제한된 authoring 계약을 사용합니다. 검증, 미리보기 및
시각화를 수행하며 명시적 save 는 principal 소유 비공개 `draft` 만 만듭니다.
Publish, 연결, 활성화 및 실행 은 별도로 검토되는 경로로 유지됩니다.

단계 editor와 기타 authoring 그룹은 데이터 카드가 아닌 structural 패널입니다. Drill-down 목적지가
없으므로 editor 또는 섹션 의미 규칙을 사용하며, 데이터 카드는 소유 상세 또는 근거 화면으로
연결되는 요약에만 사용합니다.

뷰에는 두 모드가 있다. 기본은 **런치패드 + 빌트인 워크플로의 읽기 전용
목록**이다: `read-only 브라우즈 테이블`이 각 출시 프로세스를 트리거, 단계 수,
모드 와 함께 나열하고, 행마다 상세 패널 (속성 테이블, 스텝 테이블, anti-scope,
원본 카탈로그 YAML) 이 있어 오퍼레이터가 동작하는 예시를 먼저 학습할 수 있다.
단일 **"Design a new 작업 흐름"** 진입점이 대화형 디자이너를 연다.

### 8.1 대화형 디자이너

디자이너는 폼이 아니라 **오퍼레이터와 함께 워크플로를 공동 설계하는
채팅**이다. 깊은 평문 질문을 하고, 이해한 바를 다시 서술하며, 어시스턴트가 다음
액션을 제안하듯 옵션 칩을 제시한다 - 그래서 비전문가가 스키마를 배우는 대신
질문에 답하는 것만으로 유효한 워크플로에 도달한다. 이는 **결정론적,
LLM-free 인터뷰 엔진**
([`workflow-builder.chat.ts`](../../../console/src/routes/workflow-builder.chat.ts))
이 뒷받침한다. 이 슬롯 채우기 상태 기계는 deterministic-first 계약에 충실하다:
서술기 가 없어도 동작하고, `ActionType` 팔레트에 없는 변경 은 결코
만들어내지 않는다.

엔진은 고정된 단계 집합
(`welcome -> need_action -> need_trigger -> confirm_plan -> offer_extra ->
confirm_safety -> confirm_name -> 준비된`) 을 걷고, 각 턴마다 봇 메시지 하나를
반환합니다. 지금 이해한 바의 짧은 설명, 다음 질문, 그리고 값이 엔진으로 다시
echo 되는 클릭 가능한 **옵션 칩**입니다. 설계 속성은 다음과 같습니다.

- welcome 턴은 **작동 예시** (예: "`aks-cluster-01` 의 pod 가 과열되면 알림을
  보내줘") 를 보여주어, 오퍼레이터가 타이핑 전에 어떤 종류의 프로세스가 표현
  가능한지 본다;
- 단일 자유 텍스트 목표는 레거시 작성기 가 쓰던 것과 동일한 결정론 매처
  ([`suggestDraftFromText`](../../../console/src/routes/workflow-builder.intent.ts))
  가 미리 파싱한다: 문장이 이미 트리거 와 액션을 명명하면 인터뷰는 곧장 나머지
  확인으로 건너뛰고, 여전히 빠진 것만 묻는다;
- 각 답변 뒤 엔진은 **이해한 바를 다시 서술**한다 - 한 문장 "when -> do" 로 -
  그리고 `offer_extra` 에서 추가 스텝 (다른 액션, 가드, 알림) 을 오퍼레이터가
  수락하거나 거절하는 칩으로 제안한다;
- 추론된 액션 및 트리거 는 명시적 `confirm_plan` 턴 없이는 진행되지 않습니다.
  범위가 제한된 제안 보다 많은 3개 초과 액션 이 일치하면 확인 에서 추가
  액션 이 생략되었음을 알립니다.
- `confirm_safety` 는 실패 시 차단 행동, shadow 자세 및 승격 임계값 를
  보여줍니다. Operator 는 작업 흐름 이름을 정하기 전에 `anti_scope` 경계 를 기록할
  수 있습니다.
- 워크플로 이름은 목표에서 **자동 제안** (snake_case id) 되고 한 턴에
  확정되므로, 오퍼레이터가 식별자를 지어낼 필요가 없다.

`ready` 단계에서 UI
([`workflow-builder.chatpanel.tsx`](../../../console/src/routes/workflow-builder.chatpanel.tsx))
는 누적된 초안에 기존 validate + 미리 보기 경로를 실행하고, 채팅 안에 인라인으로
렌더한다:

- **인라인 플로우 맵 시각화** (`when -> do -> ... -> done`) 는 워크플로를
  오퍼레이터가
  [`mocks/ui/workflow-builder.html`](../../../mocks/ui/workflow-builder.html)
  에서 익힌 노드 체인으로 그려, 프로세스가 실제로 어떻게 동작할지 채팅이
  보여준다;
- **정본 YAML** 을 복사 가능한 코드 블록으로, "내가 생성한 워크플로가
  여기 있다" 로 제시한다;
- `POST /workflows/validate` 의 **structural 검증 결과** ("구조적으로
  유효하고, 모든 스텝이 해석 된다...") 를 보여줍니다. 이 검사는 작업 흐름 를
  execute, simulate 또는 predict 하지 않습니다.
- 확인 과 함께 `POST /workflows/definitions` 를 호출하는 명시적 **Save
  비공개 초안** 액션 은 비공개 `draft` 를 만듭니다. 저장된 정의 은 실행할
  수 없고 Operations 에 나타나지 않습니다.
- 접을 수 있는 **편집 검증된 초안** 표면에서 액션 단계 을 편집할 수 있습니다.
  ActionType 교체, 삽입, 제거, 순서 변경, 단계 id, 가드 및 복구 참조, 기본 요소
  매개변수, 트리거 메타데이터, anti-scope 및 승격 임계값 를 지원합니다. 편집하면
  이전 save 결과가 무효화되고 짧은 debounce 후 동일한 서버 structural 검증 을
  다시 실행합니다.
- 크기가 제한된 `sessionStorage` 에서 탭 범위 초안 를 복구합니다. 방어적 decoder 는
  malformed 또는 oversized 기록 를 신뢰할 수 없는 초안 로 로드하지 않고 폐기합니다.
- git-native 다음 단계: YAML 을 `rule-catalog/workflows/<name>.yaml` 로
  복사하고 교정 PR 을 연다.

추가 단계 제안은 명시한 목표에서 일치한 액션 과 communication 후속 조치 으로
제한됩니다. 빌더 는 모든 ActionType category 를 보여 주기 위해 무관한 변경 으로
제안 행을 채우지 않습니다.

엔진의 순수·무상태 조각은 각기 하나의 변경 축을 갖고 DOM 없이 단위 테스트
가능하도록 형제 모듈로 분리되어 있다: 칩 / 폼-슬롯 빌더와 옵션 토큰 문법
([`workflow-builder.chat.builders.ts`](../../../console/src/routes/workflow-builder.chat.builders.ts)),
인라인 마크다운 토크나이저
([`workflow-builder.richtext.ts`](../../../console/src/routes/workflow-builder.richtext.ts)),
플로우 맵 파생
([`workflow-builder.viz.ts`](../../../console/src/routes/workflow-builder.viz.ts)).
오퍼레이터가 직접 친 텍스트는 (마크다운 파서를 거치지 않고) 평문으로 echo 되며,
최신 턴의 칩만 인터랙티브해서 지난 제안이 이후 단계를 오염시킬 수 없다.

세 개의 명시적 선택, Reader-gated Operator API 라우트가 검증 및 browse 를
뒷받침합니다. 모두 상태를 쓰지 않는 pure 변환 결과 입니다 (see
[`workflow_authoring.py`](../../../services/operator-service/src/fdai_operator_service/)):

- **`GET /workflows/catalog`** - 빌트인 작업 흐름 카탈로그. 로드된 `Workflow`
  카탈로그의 읽기 전용 변환 결과 으로 각 워크플로의 전체 내용 (트리거, 단계,
  승격 게이트, `step_count`, 정본 YAML) 을 실어, 오퍼레이터가 새로
  작성하기 전에 콘솔이 출시 프로세스를 목록화하고 확인할 수 있게 한다.
- **`GET /workflows/action-types`** - `ActionType` 팔레트. 로드된 `ActionType`
  카탈로그의 변환 결과 (이름, category, `rollback_contract`, `irreversible`,
  `default_mode`, 그리고 상한 이 HIL 로 에스컬레이션하는 계층) 이라, 빌더가
  스텝마다 타입이 지정된 드롭다운을 제공한다. 팔레트에서 고르는 것이 스텝의
  `action_type_ref` 를 부하 시점에 해석 가능하게 만든다 - 빌더는 알 수 없는
  참조를 만들어낼 수 없다.
- **`POST /workflows/validate`** - 카탈로그 로더가 쓰는 것과 동일한
  [`load_workflow_from_mapping`](../../../services/core-control-plane/src/fdai/rule_catalog/schema/workflow.py)
  (JSON 스키마 + `Workflow` pydantic 구조 불변식 + `ActionType` / 룰
  cross-reference) 을 실행하는 순수 함수이며, 집계된 이슈와 정본 YAML
  미리보기를 반환한다. 아무것도 mutate 하지 않고 PR 도 만들지 않는다.

세 라우트는
[`OperatorApiConfig.workflow_authoring`](../../../services/operator-service/src/fdai_operator_service/)
(로드된 팔레트, 빌트인 워크플로, 룰 id, 스키마 레지스트리 를 담은
`WorkflowAuthoringConfig`) 를 통해 명시적 선택 이다; 업스트림 에선 unset 이라 콘솔이
minimal 로 유지되고, 로컬 dev 하네스에는 배선되어 뷰가 곧바로 렌더된다.

Console 은 privileged 읽기 전용 불변식을 유지합니다
([app-shape.instructions.md](../../../.github/instructions/app-shape.instructions.md)).
Palette 및 카탈로그 는 GET-only `OperatorApiClient` 를 통한 GET이고 검증 은 pure이며,
save 는 principal 소유 비공개 authoring 기록 만 씁니다. Save 경로 는 실행기
신원 를 받지 않으며 정의 을 publish, 연결, 활성화 또는 실행 할 수 없습니다.
유효한 초안 는 `rule-catalog/workflows/<name>.yaml` 에 제안할 YAML 도 제공합니다.
새 카탈로그 항목 는 `shadow` 로 잠기며 강제 적용 승격은 [6절](#6-거버넌스) 의 별도
거버넌스 PR 로 유지됩니다.

### 8.2 동적 런타임 뷰

**Processes** 콘솔 경로 는 프런트엔드 에 architecture-review 로직을 넣지 않고
실행 중이거나 완료된 작업 흐름 인스턴스 를 렌더합니다. 변환 결과 경로는 다음과
같습니다.

```text
Workflow -> Process snapshot + journal -> ontology projection
         -> ontology datasource -> ReportSpec -> ViewSpec
         -> RenderedView API -> generic console widgets
```

각 산출물 는 하나의 책임을 가집니다.

- **작업 흐름** 는 실행과 컨트롤 흐름 를 선언합니다. UI 배치 을 포함하지 않습니다.
- **프로세스 스냅샷 및 저널** 은 권위 있는 변경 가능한 상태 와 이력 입니다.
- **온톨로지 변환 결과** 은 런타임 상태 에 타입이 지정된 도메인 meaning 과 링크 를 제공합니다.
- **ReportSpec** 은 변환 결과 에서 범위가 제한된 데이터셋 및 위젯 데이터 를 선택합니다.
- **ViewSpec** 은 작업 흐름 참조 를 보고 지역 및 열 구간 에 매핑합니다.
  [`rule-catalog/views/`](../../../rule-catalog/views/) 아래 catalog-as-code 입니다.
- **ViewEngine** 은 프로세스, 일치하는 ViewSpec, 보고 를 범위가 제한된 `RenderedView` 로
  해석 합니다. Reader-gated `GET /views/process` 및
  `GET /views/process/{process_id}` 가 목록 및 workflow-specific 상세 변환 결과 을
  제공합니다. `GET /views/process/{process_id}/events` 는 ViewSpec 을 등록하지 않은
  작업 흐름 를 포함한 모든 프로세스 의 권위 있는 스냅샷 및 추가 전용 이벤트
  저널 을 반환합니다.
- **범용 콘솔 렌더러** 는 승인된 위젯 vocabulary 만 지원합니다. 임의의
  온톨로지 속성 를 executable UI 또는 액션 버튼 으로 변환하지 않습니다.

**Processes** 경로 는 모든 실행을 나열하고 활성, completed, 실패한 수를
요약하며 선택한 프로세스 타임라인 을 가장 오래된 이벤트 부터 최신 이벤트 순으로
렌더링합니다. CLI 또는 ChatOps 명령이 프로세스 를 진행시킨 후 오퍼레이터는 읽기
변환 결과 을 새로 고칠 수 있습니다. Workflow-specific ViewSpec 이 있으면 런타임
저널 아래에 표시됩니다. 화면은 시작, approve, 재시도, execute 버튼 을 제공하지
않습니다.

Operational-planning 프로세스는 추가 전용 `planning.phase.recorded` 하위 이벤트를 동일한 상세
경로의 계획 수립 Room으로 접기합니다. 변환 결과는 accountable 에이전트, 후보 ActionType,
예상 범위, 제약 및 시뮬레이션 증적, rejected 사유, 선택 margin, 사람 검토
상태를 보여 줍니다. 저널에서 재구축할 수 있고 경로를 추가하지 않으며 승인 또는 실행
컨트롤을 포함하지 않습니다.

아키텍처 지도 은 별도입니다. 인벤토리 그래프 가 반환한 실제 infrastructure
토폴로지 를 시각화합니다. 프로세스 화면 는 작업 흐름 상태 및 도메인 변환 결과 을
시각화합니다. 어느 표면 도 다른 표면 의 정본 가 아닙니다.

### 8.3 작업 흐름 앱 및 메뉴 노출

재사용 가능한 읽기 표면 가 필요한 작업 흐름 는 작업 흐름 및 ViewSpec 과 별도로
**WorkflowApp** 매니페스트 를 등록합니다. 매니페스트 는 검색 가능성만 제어합니다. 실행
logic, 액션 버튼, JavaScript 또는 임의 백엔드 경로 를 추가하지 않습니다.

Console 은 Operations 도메인 에 하나의 안정적인 **작업 흐름 apps** 항목을
노출합니다. 이 허브 는 현재 principal 에게 보이는 published 매니페스트 를 나열합니다.
각 앱 은 `/workflow-apps/{app_id}` 를 사용하며 `workflow_ref` 로 필터링된 범용
프로세스 목록, 저널, ViewSpec, ReportSpec 및 위젯 렌더러 를 재사용합니다. 생성된
작업 흐름 자체가 새 compiled `ConsolePanel` 이 되지 않으므로 런타임 카탈로그 증가가
프런트엔드 번들 을 변경하거나 활동 Bar 를 과도하게 늘리지 않습니다.

매니페스트 수명 주기 은 노출을 다음과 같이 제어합니다.

- `draft` 매니페스트 는 authoring 에서만 보이며 Operations 에 들어가지 않습니다.
- `shadow` 매니페스트 는 workflow-specific 프로세스 상세 ViewSpec 을 제공할 수 있지만
  작업 흐름 apps 허브 에는 나타나지 않습니다.
- `published` 매니페스트 는 작업 흐름, ViewSpec 및 역할 cross-reference 검증 후 허브 에
  나타납니다.
- `retired` 매니페스트 는 탐색 에서 사라지지만 기존 감사 및 프로세스 deep 링크 는
  계속 읽을 수 있습니다.

`WorkflowApp` id와 경로는 영구적인 머신 참조입니다. Launchpad, 카탈로그, 상세,
자동화, 채팅 및 Python-task 화면은 parity-checked 경로 카탈로그와 영어 대체 경로로 라벨을
현지화하며 작업 흐름 id, serialized 값 및 검증 결과는 바꾸지 않습니다. Operator API는
principal에게 authorized된 매니페스트만 반환하며 브라우저 hiding은 접근 컨트롤이 아닙니다. 새
interaction 모델이나 executable 프런트엔드 코드는 build-time `EXTRA_PANELS`, injected
`ReadPanel` 및 별도 검토된 release를 사용하고 대화에서 원격 코드로 생성하지 않습니다.

## 9. agent-workflows.md 와의 관계

[agent-workflows.md](../agents/agent-workflows-ko.md) 는 설계 참조다: 12개 워크플로, 그
에이전트, 시퀀스 다이어그램, exit criteria. 이 문서는 그 워크플로가 컴파일되는
구현 계약이다. 둘은 동기화된 채로 유지된다: 새 워크플로는 agent-workflows.md 의
문서 엔트리와 [`rule-catalog/workflows/`](../../../rule-catalog/workflows) 아래
카탈로그 YAML 로, 같은 PR 에서 도착한다.

## 10. 안티패턴

- **새 변경 기본 요소 를 선언하는 워크플로.** 스텝은 기존 `ActionType`
  카탈로그를 참조한다; 빠진 기능 는 inline 스텝 본문 가 아니라 업스트림
  `ActionType` PR 이다.
- **Risk-gate를 우회하는 상태 변경 단계.** 모든 액션 단계는 타입이 지정된 파이프라인에 재진입합니다.
  근거 및 컨트롤 단계는 실행기를 호출할 수 없습니다.
- **상시 구동 프로세스 오케스트레이터.** 프로세스는 event-driven, scale-to-zero 다;
  polling 데몬은 앱 형태 와 모순된다
  ([app-shape.instructions.md](../../../.github/instructions/app-shape.instructions.md)).
- **`enforce` 로 출시되는 워크플로.** 업스트림 워크플로는 shadow-first 다;
  강제 적용 는 별도 gated 승격이다.
- **보상 없는 실패 시 부분 상태.** `compensated_by` 없는 non-reversible 스텝은
  대상을 절반만 바꾼 채 두지 말고 실패를 HIL 로 라우팅 MUST.
