---
title: 프로세스 자동화(Process Automation)
translation_of: process-automation.md
translation_source_sha: ec50935ed2ee32b917765aed8d5b9ebb2b03e1f3
translation_revised: 2026-07-09
---

# 프로세스 자동화(Process Automation)

프로세스 자동화는 다단계 비즈니스 프로세스를 1급, 온톨로지 연결, 거버넌스된
아티팩트로 바꾼다. 프로세스는 컨트롤 플레인을 우회하는 스크립트가 아니다. 이는
온톨로지 `ActionType` 호출의 선언적 시퀀스이며, 동일한 trust-routing 컨트롤
루프가 한 번에 한 스텝씩, 단일 remediation 과 동일한 안전 불변식 아래에서
dispatch 한다.

이 문서는 [agent-workflows.md](agent-workflows-ko.md) 의 머신-리더블 대응물이다.
그 문서가 11개 cross-agent 워크플로를 산문과 시퀀스 다이어그램으로 기술한다면,
이 문서는 워크플로를 catalog-as-code 로 출시하고 shadow 모드로 실행하게 하는
카탈로그 스키마, 온톨로지 추가분, 런타임 배선을 정의한다.

> **범위.** 여기의 모든 것은 customer-agnostic 이다
> ([generic-scope.instructions.md](../../.github/instructions/generic-scope.instructions.md)).
> 워크플로는 [`rule-catalog/action-types/`](../../rule-catalog/action-types/)
> 아래의 upstream `ActionType` 카탈로그만 참조하며, 새 mutation primitive 를
> 선언하지 않는다. 새 capability 가 필요한 프로세스는 먼저 upstream `ActionType`
> 문서 PR 을 열라는 신호다.

## 1. 혼동하면 안 되는 네 가지 개념

프로세스 자동화는 절대 혼동하면 안 되는 네 개념을 조합한다. 각각 단일 책임을
가진다.

| 개념 | 책임 | 백킹 |
|------|------|------|
| **ActionType** | 안전 불변식(stop-condition, rollback contract, blast-radius cap, audit)을 가진 하나의 CSP-중립 mutation 카테고리 | [`rule-catalog/action-types/`](../../rule-catalog/action-types/), [action-ontology.md](action-ontology-ko.md) |
| **Workflow** | 비즈니스 프로세스의 *선언*: 각각 하나의 `ActionType` 을 참조하는 스텝의 순서 리스트 + 트리거 + promotion gate + 기본 모드 | [`rule-catalog/workflows/`](../../rule-catalog/workflows/), 아래 스키마 |
| **Process** | 실행 중 워크플로의 *런타임 인스턴스와 상태*: 현재 스텝, 대상 리소스, 진행한 finding | `Process` ObjectType (ontology) |
| **Runbook** | *실행 메커니즘*: 스텝 리스트를 걷고, `on_failure` 를 존중하며, 집계 audit row 를 기록 | [`src/fdai/core/runbook/`](../../src/fdai/core/runbook/) |

분리가 중요하다: `Workflow` 는 *무엇*이 *언제* 실행되는지 선언하고, `Runbook` 은
컴파일된 `Workflow` 가 만들어내는 얇은 executor 이며, `Process` 는 한 번의 실행에
대한 audit 된 상태다. 스텝은 자기만의 mutation 로직을 갖지 않는다 - `ActionType`
에 위임하므로 모든 스텝이 네 가지 안전 불변식을 공짜로 상속한다.

## 2. 워크플로 카탈로그 스키마

워크플로는 [`rule-catalog/workflows/`](../../rule-catalog/workflows/) 아래의
catalog-as-code 이며, 로드 시
[`shared/contracts/workflow/schema.json`](../../src/fdai/shared/contracts/workflow/schema.json)
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
  - id: apply_rightsize
    action_type_ref: remediate.right-size
    on_failure: null
anti_scope: >-                          # 선택적; 워크플로가 의도적으로 제외하는 것
  Not a budget enforcement path; it only annotates SRE actions with cost.
```

로더가 강제하는 필드 규칙:

- `name` 은 안정 dotted id (`^[a-z][a-z0-9_.-]{0,79}$`); 로더는 upstream 과 모든
  fork 추가분에 걸쳐 이 값으로 dedupe 한다.
- `steps` 는 최소 하나; step `id` 는 워크플로 내에서 유일하다.
- 모든 `action_type_ref` 는
  [`load_action_type_catalog`](../../src/fdai/rule_catalog/schema/action_type.py)
  의 등록된 `ActionType` name 으로 resolve MUST. 오타는 첫 dispatch 가 아니라
  로드 시 실패한다 - [`rule.py`](../../src/fdai/rule_catalog/schema/rule.py) 의
  `remediates` 링크가 쓰는 동일한 cross-reference 규율.
- `compensated_by` 는 설정 시 역시 `ActionType` name 으로 resolve MUST. 그 스텝의
  saga rollback 액션이다 ([5절](#5-saga-보상saga-compensation) 참조).
- `on_failure` 는 설정 시 같은 워크플로 내 기존 step `id` 를 참조 MUST, 정확히
  [`Runbook`](../../src/fdai/core/runbook/models.py) 스텝처럼.
- `guard_rule_ref` 는 설정 시 로드된 rule 카탈로그의 Rule id 로 resolve MUST.
  guard 는 스텝의 결정론적 "언제"다 - policy-as-code 술어이지, 모델 텍스트가
  아니다.
- upstream 워크플로는 `default_mode: shadow` MUST. `enforce` 로 출시되는
  워크플로는 upstream 스키마 위반이다; enforce 승격은 별도의 gated governance PR.

### 2.1 알려진 한계 (P1)

- **`signal_type` 는 자유 문자열이다.** 트리거 `signal_type` 은 signal-type
  레지스트리에 대해 cross-reference 되지 않으므로 (upstream 에 아직 없음) 오타가
  로드 시 잡히지 않는다. `SignalType` 온톨로지 승격이 도착하기 전까지는 문서로
  취급하라.
- **`on_failure` 는 성공 경로에서도 실행된다.** 컴파일된 Runbook 러너는 선언된
  모든 스텝을 순서대로 걷는다; `on_failure` 대상은 성공 시에도 실행되는 일반
  스텝이며, 추가로 실패 시 fallback 으로도 실행된다. `on_failure` 대상은 두 경로
  모두에서 안전하게 (idempotent) 실행되는 스텝으로 작성하거나, null 로 두고
  `compensated_by` 에 의존하라. 출시된 워크플로는 이 이유로 `on_failure` 를 null
  로 둔다.

## 3. 온톨로지 추가분

프로세스 자동화는 정확히 하나의 ObjectType 과 두 개의 LinkType 를 추가한다. 이는
audit 로그를 복제하지 않으면서 실행 중 프로세스를 그래프에서 traverse 가능하게
만드는 최소한의 정당한 확장이다.

### 3.1 `Process` ObjectType

[`rule-catalog/vocabulary/object-types/Process.yaml`](../../rule-catalog/vocabulary/object-types/Process.yaml)
는 한 번의 워크플로 실행에 대한 런타임 상태를 선언한다. 모든 출시 built-in 처럼
`id` 로 key 한다.

| 속성 | 타입 | 의미 |
|------|------|------|
| `id` | string | `(workflow_ref, target_resource_id, trigger_ts)` 에서 파생한 idempotent process id; 재시도는 이를 재사용한다. |
| `workflow_ref` | string | 이 프로세스가 인스턴스화하는 `Workflow` name. |
| `status` | string | `pending`, `running`, `succeeded`, `failed`, `compensating`, `compensated`. |
| `current_step` | string | 현재 진행 중 step id (terminal 일 때 빈 값). |
| `target_resource_id` | string | 프로세스가 작동하는 주 Resource. |
| `started_at` | datetime | RFC 3339 UTC 시작 타임스탬프. |
| `context` | object | 트리거가 캡처한 open-shape 컨텍스트 bag. |

### 3.2 LinkType

| LinkType | 엔드포인트 | Cardinality | 플래그 | 의미 |
|----------|-----------|-------------|--------|------|
| `targets` | Process -> Resource | many_to_one | - | 프로세스가 작동하는 리소스; risk-gate 가 프로세스 대상에 대한 blast radius 를 계산하게 한다. |
| `advances` | Process -> Finding | many_to_many | `temporal_order` | 프로세스가 진행한 순서 있는 finding; replay 를 위한 시간-존중 체인. |

비즈니스 핵심 링크 - 프로세스 스텝에서 `ActionType` 로 - 는 온톨로지 LinkType 가
아니다. `ActionType` 인스턴스는 카탈로그에 살고 name 으로 cross-reference 되기
때문이며, 정확히 `remediates` 가 Rule 을 `ActionType` 로 resolve 하는 방식이다.
워크플로 로더가 로드 시 그 연결을 강제한다; 온톨로지 LinkType 는 1급 object type
간 런타임 그래프 엣지만 커버한다.

## 4. 컨트롤 루프 통합

컴파일된 워크플로는 side channel 에서 실행되지 않는다.
[`WorkflowCompiler`](../../src/fdai/core/workflow/compiler.py) 는 `Workflow` 를
[`Runbook`](../../src/fdai/core/runbook/models.py) 으로 바꾸고, 기존
[`RunbookRunner`](../../src/fdai/core/runbook/runner.py) 가 스텝을 걷는다. 각
스텝은 주입된 `StepExecutor` 를 통해 dispatch 되며, 이는 typed 파이프라인에
재진입한다: `ActionType` -> risk-gate -> executor -> audit. 스텝 간 direct RPC 도,
risk-gate 우회도 없다. 이는 행동 요청은 typed 파이프라인에 재진입한다는 pantheon
규칙과 일치한다
([architecture.instructions.md](../../.github/instructions/architecture.instructions.md)).

모든 스텝이 `ActionType` 호출이므로, 네 가지 안전 불변식이 스텝마다 성립한다:
stop-condition, rollback contract, blast-radius cap, audit-log 엔트리. 러너는
리뷰어가 id 로 전체 실행을 재구성할 수 있도록 하나의 집계 `runbook.terminal`
audit row 를 추가한다.

## 5. saga 보상(saga compensation)

중간에 실패하는 다단계 프로세스는 이미 적용된 스텝을 되돌릴 수 있어야 MUST. 각
스텝은 그것을 되돌리는 `ActionType` 인 `compensated_by` 를 선언 MAY. 보상 계약은:

- 스텝 실패 시, 앞서 적용된 스텝들은 동일 파이프라인을 통해 그들의
  `compensated_by` 액션을 dispatch 하여 역순으로 보상된다.
- 보상 액션 자체가 `ActionType` 호출이므로 자기만의 rollback contract 와 audit
  엔트리를 가진다 - audit 없는 undo 는 없다.
- `compensated_by` 가 없고 non-reversible `ActionType` 인 스텝은 부분 상태를
  남기는 대신 실패를 HIL 로 라우팅하도록 워크플로를 강제한다.

P1 에서 러너는 선형 시퀀스 + 단일 `on_failure` 분기를 실행한다; 선언된
`compensated_by` 매핑은 로드 시 검증되고 컴파일러가 노출하지만, risk-gate 통합과
함께 도착하는 process orchestrator 가 dispatch 한다. 이는 action 온톨로지가 쓰는
declared-versus-live 경계와 동일하다 ([action-ontology.md § 12.1](action-ontology-ko.md)):
선언됐지만 아직 dispatch 되지 않은 필드는 구성상 inert 이며 행동할 수 없다.

## 6. 거버넌스

- **Shadow-first.** 모든 워크플로는 `default_mode: shadow` 로 출시된다: 각 스텝을
  mutation 없이 judge-and-log 한다. enforce 승격은 frozen 시나리오 세트에서
  워크플로의 `promotion_gate` 를 측정하는 명시적, 별도 리뷰된 governance PR 이다.
- **HIL 은 Var 통해, audit 은 Saga 통해.** `ActionType` 이 HIL 로 라우팅되는
  스텝은 approver principal (Var) 을 거친다; 모든 terminal 결과는 Saga 가 audit
  한다. 프로세스 자동화는 새 approval 이나 audit 표면을 추가하지 않는다.
- **Human override 적용.** 스텝을 gate 하는 룰에 대한 오퍼레이터 override 는
  override 스코프에서 그 스텝의 실행을 억제하며, evaluator 는 무엇을 했을지
  계속 기록해 discovery 루프에 공급한다.
- **주입에 의한 fork 커스터마이즈.** fork 는 자기 카탈로그 루트 아래 자기
  워크플로를 추가하고 동일 로더 seam 을 통해 등록한다; `core/` 를 편집하지 않는다.

## 7. 로더와 CI 검증

[`load_workflow_catalog`](../../src/fdai/rule_catalog/schema/workflow.py) 는 순수
I/O + 검증이며, `ActionType` 및 ObjectType 로더를 미러한다. fail-closed 다: 어느
파일의 어느 이슈든 모든 파일의 모든 이슈를 담은 하나의 집계 에러를 raise 한다.
각 `action_type_ref` 와 `compensated_by` 를 `ActionType` 카탈로그에 대해, 각
`guard_rule_ref` 를 rule 카탈로그에 대해 cross-reference 하며, upstream
shadow-default 정책을 강제한다. 엔트리 포인트는 시작 시 카탈로그를 로드하므로
malformed 워크플로는 첫 dispatch 가 아니라 부팅을 막는다.

## 8. agent-workflows.md 와의 관계

[agent-workflows.md](agent-workflows-ko.md) 는 설계 참조다: 11개 워크플로, 그
에이전트, 시퀀스 다이어그램, exit criteria. 이 문서는 그 워크플로가 컴파일되는
구현 계약이다. 둘은 동기화된 채로 유지된다: 새 워크플로는 agent-workflows.md 의
문서 엔트리와 [`rule-catalog/workflows/`](../../rule-catalog/workflows/) 아래
카탈로그 YAML 로, 같은 PR 에서 도착한다.

## 9. 안티패턴

- **새 mutation primitive 를 선언하는 워크플로.** 스텝은 기존 `ActionType`
  카탈로그를 참조한다; 빠진 capability 는 inline 스텝 body 가 아니라 upstream
  `ActionType` PR 이다.
- **risk-gate 를 우회하는 스텝.** 모든 스텝은 typed 파이프라인에 재진입한다.
  executor 를 직접 호출하는 스텝은 defect 다.
- **상시 구동 process orchestrator.** 프로세스는 event-driven, scale-to-zero 다;
  polling 데몬은 app shape 와 모순된다
  ([app-shape.instructions.md](../../.github/instructions/app-shape.instructions.md)).
- **`enforce` 로 출시되는 워크플로.** upstream 워크플로는 shadow-first 다;
  enforce 는 별도 gated 승격이다.
- **보상 없는 실패 시 부분 상태.** `compensated_by` 없는 non-reversible 스텝은
  대상을 절반만 바꾼 채 두지 말고 실패를 HIL 로 라우팅 MUST.
