---
title: 프로세스 자동화(Process Automation)
translation_of: process-automation.md
translation_source_sha: 92126870965207169072b5f1ecf9481805eec52d
translation_revised: 2026-07-13
---

# 프로세스 자동화(Process Automation)

프로세스 자동화는 다단계 비즈니스 프로세스를 1급, 온톨로지 연결, 거버넌스된
아티팩트로 바꾼다. 프로세스는 컨트롤 플레인을 우회하는 스크립트가 아니다. 이는
온톨로지 `ActionType` 호출의 선언적 시퀀스이며, 동일한 trust-routing 컨트롤
루프가 한 번에 한 스텝씩, 단일 remediation 과 동일한 안전 불변식 아래에서
dispatch 한다.

이 문서는 [agent-workflows.md](../agents/agent-workflows-ko.md) 의 머신-리더블 대응물이다.
그 문서가 11개 cross-agent 워크플로를 산문과 시퀀스 다이어그램으로 기술한다면,
이 문서는 워크플로를 catalog-as-code 로 출시하고 shadow 모드로 실행하게 하는
카탈로그 스키마, 온톨로지 추가분, 런타임 배선을 정의한다.

> **범위.** 여기의 모든 것은 customer-agnostic 이다
> ([generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md)).
> 워크플로는 [`rule-catalog/action-types/`](../../../rule-catalog/action-types)
> 아래의 upstream `ActionType` 카탈로그만 참조하며, 새 mutation primitive 를
> 선언하지 않는다. 새 capability 가 필요한 프로세스는 먼저 upstream `ActionType`
> 문서 PR 을 열라는 신호다.

## 1. 혼동하면 안 되는 네 가지 개념

프로세스 자동화는 절대 혼동하면 안 되는 네 개념을 조합한다. 각각 단일 책임을
가진다.

| 개념 | 책임 | 백킹 |
|------|------|------|
| **ActionType** | 안전 불변식(stop-condition, rollback contract, blast-radius cap, audit)을 가진 하나의 CSP-중립 mutation 카테고리 | [`rule-catalog/action-types/`](../../../rule-catalog/action-types), [action-ontology.md](action-ontology-ko.md) |
| **Workflow** | 비즈니스 프로세스의 *선언*: 각각 하나의 `ActionType` 을 참조하는 스텝의 순서 리스트 + 트리거 + promotion gate + 기본 모드 | [`rule-catalog/workflows/`](../../../rule-catalog/workflows), 아래 스키마 |
| **Process** | 실행 중 워크플로의 *런타임 인스턴스와 상태*: 현재 스텝, 대상 리소스, 진행한 finding | `Process` ObjectType (ontology) |
| **Runbook** | *실행 메커니즘*: 스텝 리스트를 걷고, `on_failure` 를 존중하며, 집계 audit row 를 기록 | [`src/fdai/core/runbook/`](../../../src/fdai/core/runbook) |

분리가 중요하다: `Workflow` 는 *무엇*이 *언제* 실행되는지 선언하고, `Runbook` 은
컴파일된 `Workflow` 가 만들어내는 얇은 executor 이며, `Process` 는 한 번의 실행에
대한 audit 된 상태다. 스텝은 자기만의 mutation 로직을 갖지 않는다 - `ActionType`
에 위임하므로 모든 스텝이 네 가지 안전 불변식을 공짜로 상속한다.

## 2. 워크플로 카탈로그 스키마

워크플로는 [`rule-catalog/workflows/`](../../../rule-catalog/workflows) 아래의
catalog-as-code 이며, 로드 시
[`shared/contracts/workflow/schema.json`](../../../src/fdai/shared/contracts/workflow/schema.json)
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

- `name` 은 안정 dotted id (`^[a-z][a-z0-9_.-]{0,79}$`); 로더는 upstream 과 모든
  fork 추가분에 걸쳐 이 값으로 dedupe 한다.
- `steps` 는 최소 하나; step `id` 는 워크플로 내에서 유일하다.
- 모든 `action_type_ref` 는
  [`load_action_type_catalog`](../../../src/fdai/rule_catalog/schema/action_type.py)
  의 등록된 `ActionType` name 으로 resolve MUST. 오타는 첫 dispatch 가 아니라
  로드 시 실패한다 - [`rule.py`](../../../src/fdai/rule_catalog/schema/rule.py) 의
  `remediates` 링크가 쓰는 동일한 cross-reference 규율.
- `compensated_by` 는 설정 시 역시 `ActionType` name 으로 resolve MUST. 그 스텝의
  saga rollback 액션이다 ([5절](#5-saga-보상saga-compensation) 참조).
- `on_failure` 는 설정 시 같은 워크플로 내 스텝 리스트에서 **뒤에 오는** 기존 step
  `id` 를 참조 MUST (자기 자신이나 앞 스텝은 불가), 정확히
  [`Runbook`](../../../src/fdai/core/runbook/models.py) 스텝처럼. 역방향 fallback 은
  러너가 이미 적용된 스텝을 재실행하게 만들므로 로드 시 거부된다.
- `guard_rule_ref` 는 설정 시 로드된 rule 카탈로그의 Rule id 로 resolve MUST.
  guard 는 스텝의 결정론적 "언제"다 - policy-as-code 술어이지, 모델 텍스트가
  아니다.
- upstream 워크플로는 `default_mode: shadow` MUST. `enforce` 로 출시되는
  워크플로는 upstream 스키마 위반이다; enforce 승격은 별도의 gated governance PR.
- `params` 는 설정 시 스텝의 scalar (string / number / boolean) 인자 맵이다.
  문자열 값은 `${event.resource_ref}` / `${event.trigger_ts}` /
  `${event.event_type}` 토큰을 담을 MAY 하며 오케스트레이터가 런타임에 트리거
  이벤트에서 치환한다; 알 수 없는 토큰은 verbatim 으로 남아 미해결 참조가 audit 에
  보인다. 해결된 params 는 `workflow.step` audit row 에 기록된다.

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

[`rule-catalog/vocabulary/object-types/Process.yaml`](../../../rule-catalog/vocabulary/object-types/Process.yaml)
는 한 번의 워크플로 실행에 대한 런타임 상태를 선언한다. 모든 출시 built-in 처럼
`id` 로 key 한다.

| 속성 | 타입 | 의미 |
|------|------|------|
| `id` | string | `(workflow_ref, target_resource_id, trigger_ts)` 에서 파생한 idempotent process id이며 재시도는 이를 재사용합니다. 저장된 모든 Process를 읽기 API에서 조회할 수 있도록 1-200자의 URL-safe 영문자, 숫자, `_`, `.`, `:`, `-`만 사용합니다. |
| `workflow_ref` | string | 이 프로세스가 인스턴스화하는 `Workflow` name. |
| `workflow_version` | string | 이 실행에 선택된 불변 Workflow 버전. |
| `status` | string | `pending`, `running`, `waiting`, `compensating`, `compensated`, `succeeded`, `failed`, `cancelled`, `timed_out`. |
| `current_step` | string | 현재 진행 중 step id (terminal 일 때 빈 값). |
| `target_resource_id` | string | 프로세스가 작동하는 주 Resource. |
| `started_at` | datetime | RFC 3339 UTC 시작 타임스탬프. |
| `updated_at` | datetime | 최근 commit transition 의 RFC 3339 UTC 타임스탬프. |
| `correlation_id` | string | Process journal, audit row, projection 이 공유하는 correlation id. |
| `revision` | integer | 권위 있는 snapshot 의 optimistic concurrency revision. |

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
[`WorkflowCompiler`](../../../src/fdai/core/workflow/compiler.py) 는 `Workflow` 를
[`Runbook`](../../../src/fdai/core/runbook/models.py) 으로 바꾸고, 기존
[`RunbookRunner`](../../../src/fdai/core/runbook/runner.py) 가 스텝을 걷는다. 각
스텝은 주입된 `StepExecutor` 를 통해 dispatch 되며, 이는 typed 파이프라인에
재진입한다: `ActionType` -> risk-gate -> executor -> audit. 스텝 간 direct RPC 도,
risk-gate 우회도 없다. 이는 행동 요청은 typed 파이프라인에 재진입한다는 pantheon
규칙과 일치한다
([architecture.instructions.md](../../../.github/instructions/architecture.instructions.md)).

모든 스텝이 `ActionType` 호출이므로, 네 가지 안전 불변식이 스텝마다 성립한다:
stop-condition, rollback contract, blast-radius cap, audit-log 엔트리. 러너는
리뷰어가 id 로 전체 실행을 재구성할 수 있도록 하나의 집계 `runbook.terminal`
audit row 를 추가한다.

### 4.1 Shadow 오케스트레이터 (P1)

[`WorkflowOrchestrator`](../../../src/fdai/core/workflow/orchestrator.py) 가 첫
라이브 소비자다. 승인을 계획하고 ([6.1절](#61-승인자-할당approver-assignment)),
`(workflow, target_resource_id, trigger_ts)` 에서 idempotent `Process` id 를
파생하고, 워크플로를 컴파일한 뒤
[`ShadowWorkflowStepExecutor`](../../../src/fdai/core/workflow/orchestrator.py) 로
걷는다 - 이 `StepExecutor` 는 publisher 도, direct-API executor 도, resource lock
도 없어서 **구조적으로 mutation 이 불가능**하다. 각 스텝은 (해결된 승인자 할당과
함께) judge-and-log 되어 `SUCCESS` 로 보고되고, 실행은 `workflow.process-plan`
audit row 하나, 스텝마다 `workflow.step` row 하나, 러너의 `runbook.terminal` 을
emit 합니다. 실행은 전용 `ProcessRuntimeStore` 에도 기록됩니다. 여기에는 현재
snapshot 하나와 append-only transition journal 이 있습니다. PostgreSQL adapter 는
optimistic revision 을 검사하면서 snapshot 갱신과 typed `ProcessEvent` append 를
한 transaction 에서 처리합니다. In-memory storage 는 테스트와 로컬 개발에 같은
contract 를 구현합니다. risk-gate -> executor -> delivery 경로에 재진입하는 라이브
executor 로의 승격은 별도의 gated 변경입니다. 그 전까지 워크플로 실행은 클라우드
상태를 바꿀 수 없으며, shadow-before-enforce 불변식과 일치합니다.

이벤트 진입점은
[`WorkflowTriggerCoordinator`](../../../src/fdai/core/workflow/coordinator.py) 다:
`event-ingest` 를 통과한 Event 는 `event_type` 으로
[`WorkflowTriggerIndex`](../../../src/fdai/core/workflow/trigger_index.py) 에 매칭되고,
매칭된 모든 Workflow 는 shadow 로 실행된다 (name 순서, 리소스 + 타임스탬프는
Event 에서). 어떤 Workflow 도 매칭하지 않는 이벤트는 아무것도 시작하지 않는다.

코디네이터는 [`ControlLoop`](../../../src/fdai/core/control_loop/orchestrator.py) 에 **opt-in,
fail-safe side-consumer** 로 배선된다: `FDAI_WORKFLOW_SHADOW` 가 truthy 이고
카탈로그가 Workflow 를 실으면, 엔트리 포인트가 (로드된 Workflow 카탈로그, RBAC
그룹 매핑, notification matrix 로) 조립하고 모든 ingested 이벤트가 매칭된
Workflow 를 발화시킨다. audit row 만 추가한다 - routing, risk 결정, return 경로를
절대 바꾸지 않으며, 코디네이터 실패는 로깅되고 swallow 된다. upstream 기본은
off 이므로, 배포가 opt-in 하지 않는 한 컨트롤 루프는 이전과 똑같이 동작한다.

### 4.2 Guard 평가 (seam)

스텝의 `guard_rule_ref` 는 스텝의 결정론적 "언제"다 - policy-as-code 술어이지,
모델 텍스트가 아니다. 오케스트레이터는
[`WorkflowGuardEvaluator`](../../../src/fdai/core/workflow/orchestrator.py) seam 을
노출한다 (async, 결정론적, side-effect 없음). upstream 기본값은 evaluator 를 **주입
하지 않는다**: guard 는 rule 카탈로그에 대해 load-validate 되지만 런타임엔
`guard_evaluated: false` 로 기록되어 upstream 은 동작상 중립을 유지한다. fork (또는
향후 enforce 경로)가 이 seam 을 통해 구체 OPA-backed evaluator 를 바인딩한다.
evaluator 가 바인딩되고 스텝의 guard 가 false 를 반환하면, shadow 실행은
`guard_passed: false` 를 기록하고 그 스텝을 judged no-op 로 취급한다 (reason
`guard_blocked_shadow_noop`) - 실행은 계속되고 아무것도 mutate 하지 않는다. 모든
`workflow.step` audit row 는 `guard_rule_ref` / `guard_evaluated` /
`guard_passed` 를 담아 리뷰어가 어느 guard 가 어느 스텝을 gate 했는지 정확히 본다.

### 4.3 런타임 journal 과 온톨로지 projection

런타임 snapshot 은 "이 Process 가 지금 어디에 있는가?"에 답하고, append-only
journal 은 "어떻게 여기까지 왔는가?"에 답합니다. Typed event 는 생성, step
lifecycle, wait/approval/decision 상태, parallel branch 결과, compensation, timeout,
terminal 결과를 다룹니다. Approval step 은 서로 다른 승인 principal 수를 세고,
`no_self_approval` 이 켜져 있으면 requester 를 제외하며, quorum 을 충족할 때까지
waiting 상태를 유지합니다. Wait 및 approval timeout 은 Process 를 `timed_out` 으로
종료합니다. Parallel branch 는 동시에 실행되고 parent snapshot revision 을 두고
경쟁하지 않는 child event 를 기록합니다.

Ontology graph 는 source of truth 가 아니라 read model 입니다. 각 event 가 commit 된
후 `ProcessOntologyProjector` 가 현재 `Process` object 와 `targets` link 를
materialize 합니다. Workflow 전용 projector 는 domain object 와 link 를 추가할 수
있습니다. 예를 들어 architecture-review projector 는 같은 snapshot 과 event 에서
review case, check, evidence, principal, approval, decision 을 materialize 합니다.

Projection delivery 는 durable retry outbox 를 사용합니다.

- PostgreSQL runtime adapter 는 `process_event` 와 그
  `process_projection_outbox` job 을 같은 transaction 에 insert 합니다.
- Immediate projector 는 best effort 입니다. Projection 실패는 Process correlation id 와
  함께 log 하지만 commit 된 runtime 결과를 바꾸거나 가리지 않습니다.
- `ProcessProjectionWorker.run_once()` 는 `FOR UPDATE SKIP LOCKED` 로 bounded batch 를
  lease 하고, idempotent projection 을 재시도하며, 실패한 job 은 설정된 지연 후
  release 합니다. 새 projection 성공 시에도 due batch 하나를 drain 합니다.
- Worker 는 always-on polling daemon 이 아니라 one-shot event/job primitive 입니다.
  Container Apps Job 또는 startup hook 이 `retry_pending()` 을 호출해 backlog 를
  복구할 수 있습니다.

이 분리 덕분에 ontology store 가 잠시 unavailable 해도 runtime 처리는 계속되고,
모든 projection intent 는 복구를 위해 보존됩니다.

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

### 6.1 승인자 할당(approver assignment)

HIL 로 라우팅되는 워크플로 스텝은 "누가 승인하고, 어떻게 도달하는가"에 대한 구체적
답이 필요하다. 프로세스 자동화는 새 approval 표면을 추가하지 않는다;
[`WorkflowApprovalPlanner`](../../../src/fdai/core/workflow/approval.py) 를 통해
워크플로를 기존 HIL 기계장치에 연결한다.

`Workflow` 가 주어지면 플래너는 결정론적, read-only `ApprovalPlan` 을 만든다 -
스텝마다 하나의 `StepApproval`:

- **게이트인가?** 스텝의 `ActionType` `ceiling_by_tier` 에 `enforce_hil` 티어가
  하나라도 있거나 `prod_downgrade` 가 `enforce_hil` 로 collapse 하면 승인 게이트다.
  이는 risk-gate 가 쓰는 것과 동일한 source of truth 다; 플래너는 두 번째 규칙을
  만들지 않는다.
- **누가 승인하나?** 필요한 human 역할은 HIL 티어 전반의 최상위 `min_role` 이며,
  RBAC [`GroupMapping`](../../../src/fdai/core/rbac/resolver.py) 을 통해 Entra
  security-group objectId (`aw-approvers` 또는 `aw-owners` 그룹)로 resolve 된다.
  no-self-approval 은 모든 게이트 스텝에 이어진다.
- **어떻게 도달하나?** [notifications matrix](../../../config/notifications-matrix.yaml)
  의 A1 `hil_approval` 라우트 - Teams primary, Slack / email fallback. 구체
  어댑터는 [`HilChannel`](../../../src/fdai/shared/providers/hil_channel.py) seam 을
  구현한다: [`TeamsHilAdapter`](../../../src/fdai/delivery/chatops/teams_adapter.py)
  와 [`SlackHilAdapter`](../../../src/fdai/delivery/chatops/slack_adapter.py)
  (Adaptive Card / Block Kit, HMAC 서명, fail-closed). email 은 send-only alert
  레인이지 A1 승인 back-channel 이 아니다.

플랜은 role 및 channel assignment 를 제공합니다. 런타임에서 approval step 은
Process 를 park 하고 `approval.requested` 를 기록하며, 서로 다른 principal 과
no-self-approval 을 검증하고 선언된 quorum 뒤에만 resume 합니다. Decision step 은
catalog 에 선언된 outcome 중 하나만 허용하고 `decision.recorded` 를 기록합니다.
구체 on-call OID 와 channel card push 는 기존
[`HilResumeCoordinator`](../../../src/fdai/core/hil_resume/coordinator.py) 및
[`OnCallResolver`](../../../src/fdai/core/oncall/resolver.py) integration 으로 남습니다.
Workflow runtime 은 두 번째 approval authority 를 만들지 않습니다.

## 7. 로더와 CI 검증

[`load_workflow_catalog`](../../../src/fdai/rule_catalog/schema/workflow.py) 는 순수
I/O + 검증이며, `ActionType` 및 ObjectType 로더를 미러한다. fail-closed 다: 어느
파일의 어느 이슈든 모든 파일의 모든 이슈를 담은 하나의 집계 에러를 raise 한다.
각 `action_type_ref` 와 `compensated_by` 를 `ActionType` 카탈로그에 대해, 각
`guard_rule_ref` 를 rule 카탈로그에 대해 cross-reference 하며, upstream
shadow-default 정책을 강제한다. 엔트리 포인트는 시작 시 카탈로그를 로드하므로
malformed 워크플로는 첫 dispatch 가 아니라 부팅을 막는다.

## 8. 저작 표면 (console workflow-builder)

오퍼레이터는 YAML 을 기억으로 손수 쓰는 것도, 여러 섹션짜리 폼을 채우는 것도
아니라 콘솔의 **workflow-builder** 뷰를 통해 사용자 정의 비즈니스 프로세스를
저작한다. 이 표면은 프로세스를 온톨로지에 매핑하며 **구조적으로 read-only**
다: 검증하고, 미리보기하고, 시각화하지만 커밋하지 않는다.

뷰에는 두 모드가 있다. 기본은 **런치패드 + 빌트인 워크플로의 read-only
목록**이다: `read-only 브라우즈 테이블`이 각 출시 프로세스를 trigger, step 수,
mode 와 함께 나열하고, 행마다 상세 패널 (속성 테이블, 스텝 테이블, anti-scope,
원본 카탈로그 YAML) 이 있어 오퍼레이터가 동작하는 예시를 먼저 학습할 수 있다.
단일 **"Design a new workflow"** 진입점이 대화형 디자이너를 연다.

### 8.1 대화형 디자이너

디자이너는 폼이 아니라 **오퍼레이터와 함께 워크플로를 공동 설계하는
채팅**이다. 깊은 평문 질문을 하고, 이해한 바를 다시 서술하며, 어시스턴트가 다음
액션을 제안하듯 옵션 칩을 제시한다 - 그래서 비전문가가 스키마를 배우는 대신
질문에 답하는 것만으로 유효한 워크플로에 도달한다. 이는 **결정론적,
LLM-free 인터뷰 엔진**
([`workflow-builder.chat.ts`](../../../console/src/routes/workflow-builder.chat.ts))
이 뒷받침한다. 이 슬롯 채우기 상태 기계는 deterministic-first 계약에 충실하다:
narrator 가 없어도 동작하고, `ActionType` 팔레트에 없는 mutation 은 결코
만들어내지 않는다.

엔진은 고정된 단계 집합
(`welcome -> need_action -> need_trigger -> offer_extra -> confirm_name ->
ready`) 을 걷고, 각 턴마다 봇 메시지 하나를 반환한다: 지금 이해한 바의 짧은
설명, 다음 질문, 그리고 값이 엔진으로 다시 echo 되는 클릭 가능한 **옵션 칩**.
설계 속성:

- welcome 턴은 **작동 예시** (예: "`aks-cluster-01` 의 pod 가 과열되면 알림을
  보내줘") 를 보여주어, 오퍼레이터가 타이핑 전에 어떤 종류의 프로세스가 표현
  가능한지 본다;
- 단일 자유 텍스트 목표는 레거시 composer 가 쓰던 것과 동일한 결정론 매처
  ([`suggestDraftFromText`](../../../console/src/routes/workflow-builder.intent.ts))
  가 미리 파싱한다: 문장이 이미 trigger 와 액션을 명명하면 인터뷰는 곧장 나머지
  확인으로 건너뛰고, 여전히 빠진 것만 묻는다;
- 각 답변 뒤 엔진은 **이해한 바를 다시 서술**한다 - 한 문장 "when -> do" 로 -
  그리고 `offer_extra` 에서 추가 스텝 (다른 액션, guard, 알림) 을 오퍼레이터가
  수락하거나 거절하는 칩으로 제안한다;
- 워크플로 이름은 목표에서 **자동 제안** (snake_case id) 되고 한 턴에
  확정되므로, 오퍼레이터가 식별자를 지어낼 필요가 없다.

`ready` 단계에서 UI
([`workflow-builder.chatpanel.tsx`](../../../console/src/routes/workflow-builder.chatpanel.tsx))
는 누적된 초안에 기존 validate + preview 경로를 실행하고, 채팅 안에 인라인으로
렌더한다:

- **인라인 플로우 맵 시각화** (`when -> do -> ... -> done`) 는 워크플로를
  오퍼레이터가
  [`mocks/ui/workflow-builder.html`](../../../mocks/ui/workflow-builder.html)
  에서 익힌 노드 체인으로 그려, 프로세스가 실제로 어떻게 동작할지 채팅이
  보여준다;
- **canonical YAML** 을 복사 가능한 코드 블록으로, "내가 생성한 워크플로가
  여기 있다" 로 제시한다;
- `POST /workflows/validate` 의 **드라이런 테스트 결과** ("구조적으로 유효하고,
  모든 스텝이 resolve 된다...") 로, 오퍼레이터가 설계를 어디로 가져가기 전에
  테스트할 수 있다;
- git-native 다음 단계: YAML 을 `rule-catalog/workflows/<name>.yaml` 로
  복사하고 remediation PR 을 연다.

엔진의 순수·무상태 조각은 각기 하나의 변경 축을 갖고 DOM 없이 단위 테스트
가능하도록 형제 모듈로 분리되어 있다: 칩 / 폼-슬롯 빌더와 옵션 토큰 문법
([`workflow-builder.chat.builders.ts`](../../../console/src/routes/workflow-builder.chat.builders.ts)),
인라인 마크다운 토크나이저
([`workflow-builder.richtext.ts`](../../../console/src/routes/workflow-builder.richtext.ts)),
플로우 맵 파생
([`workflow-builder.viz.ts`](../../../console/src/routes/workflow-builder.viz.ts)).
오퍼레이터가 직접 친 텍스트는 (마크다운 파서를 거치지 않고) 평문으로 echo 되며,
최신 턴의 칩만 인터랙티브해서 지난 제안이 이후 단계를 오염시킬 수 없다.

동일한 세 개의 opt-in, Reader-gated read API 라우트가 이를 뒷받침하며, 모두
상태를 쓰지 않는 순수 projection 이다 (see
[`workflow_authoring.py`](../../../src/fdai/delivery/read_api/routes/workflow_authoring.py)):

- **`GET /workflows/catalog`** - 빌트인 Workflow 카탈로그. 로드된 `Workflow`
  카탈로그의 read-only projection 으로 각 워크플로의 전체 내용 (trigger, steps,
  promotion gate, `step_count`, canonical YAML) 을 실어, 오퍼레이터가 새로
  작성하기 전에 콘솔이 출시 프로세스를 목록화하고 확인할 수 있게 한다.
- **`GET /workflows/action-types`** - `ActionType` 팔레트. 로드된 `ActionType`
  카탈로그의 projection (name, category, `rollback_contract`, `irreversible`,
  `default_mode`, 그리고 ceiling 이 HIL 로 에스컬레이션하는 tier) 이라, 빌더가
  스텝마다 타입이 지정된 드롭다운을 제공한다. 팔레트에서 고르는 것이 스텝의
  `action_type_ref` 를 load 시점에 resolve 가능하게 만든다 - 빌더는 알 수 없는
  참조를 만들어낼 수 없다.
- **`POST /workflows/validate`** - 카탈로그 로더가 쓰는 것과 동일한
  [`load_workflow_from_mapping`](../../../src/fdai/rule_catalog/schema/workflow.py)
  (JSON Schema + `Workflow` pydantic 구조 불변식 + `ActionType` / rule
  cross-reference) 을 실행하는 순수 함수이며, 집계된 이슈와 canonical YAML
  미리보기를 반환한다. 아무것도 mutate 하지 않고 PR 도 만들지 않는다.

세 라우트는
[`ReadApiConfig.workflow_authoring`](../../../src/fdai/delivery/read_api/main.py)
(로드된 팔레트, 빌트인 워크플로, rule id, schema registry 를 담은
`WorkflowAuthoringConfig`) 를 통해 opt-in 이다; upstream 에선 unset 이라 콘솔이
minimal 로 유지되고, 로컬 dev 하네스에는 배선되어 뷰가 곧바로 렌더된다.

콘솔은 read-only 불변식을 유지한다
([app-shape.instructions.md](../../../.github/instructions/app-shape.instructions.md)):
팔레트와 카탈로그는 GET-only `ReadApiClient` 를 통한 GET 이고, validate 호출은
콘솔이 만드는 유일한 non-GET 이다 - `ReadApiClient` 밖에 사는 (chat backend 를
미러) read-only 검증기로 어떤 상태도 바꾸지 않는다. 커밋하는 콘솔 버튼은 없다.
유효한 draft 는 오퍼레이터가 `rule-catalog/workflows/<name>.yaml` 로 복사해
git-native 경로의 remediation PR 로 랜딩하는 YAML 을 낸다 - 그래서 audit,
review, rollback 이 공짜로 따라온다. 새 draft 는 `shadow` 로 잠긴다; enforce
승격은 [6절](#6-거버넌스) 의 별도 거버넌스 PR 로 남는다.

### 8.2 동적 런타임 뷰

**Processes** console route 는 frontend 에 architecture-review 로직을 넣지 않고
실행 중이거나 완료된 workflow instance 를 렌더합니다. Projection 경로는 다음과
같습니다.

```text
Workflow -> Process snapshot + journal -> ontology projection
         -> ontology datasource -> ReportSpec -> ViewSpec
         -> RenderedView API -> generic console widgets
```

각 artifact 는 하나의 책임을 가집니다.

- **Workflow** 는 실행과 control flow 를 선언합니다. UI layout 을 포함하지 않습니다.
- **Process snapshot 및 journal** 은 권위 있는 mutable state 와 history 입니다.
- **Ontology projection** 은 runtime state 에 typed domain meaning 과 link 를 제공합니다.
- **ReportSpec** 은 projection 에서 bounded dataset 및 widget data 를 선택합니다.
- **ViewSpec** 은 workflow reference 를 report region 및 column span 에 매핑합니다.
  [`rule-catalog/views/`](../../../rule-catalog/views/) 아래 catalog-as-code 입니다.
- **ViewEngine** 은 Process, 일치하는 ViewSpec, report 를 bounded `RenderedView` 로
  resolve 합니다. Reader-gated `GET /views/process` 및
  `GET /views/process/{process_id}` 가 list/detail projection 을 제공합니다.
- **Generic console renderer** 는 승인된 widget vocabulary 만 지원합니다. 임의의
  ontology property 를 executable UI 또는 action button 으로 변환하지 않습니다.

Architecture map 은 별도입니다. Inventory graph 가 반환한 실제 infrastructure
topology 를 시각화합니다. Process view 는 workflow state 및 domain projection 을
시각화합니다. 어느 surface 도 다른 surface 의 source of truth 가 아닙니다.

## 9. agent-workflows.md 와의 관계

[agent-workflows.md](../agents/agent-workflows-ko.md) 는 설계 참조다: 11개 워크플로, 그
에이전트, 시퀀스 다이어그램, exit criteria. 이 문서는 그 워크플로가 컴파일되는
구현 계약이다. 둘은 동기화된 채로 유지된다: 새 워크플로는 agent-workflows.md 의
문서 엔트리와 [`rule-catalog/workflows/`](../../../rule-catalog/workflows) 아래
카탈로그 YAML 로, 같은 PR 에서 도착한다.

## 10. 안티패턴

- **새 mutation primitive 를 선언하는 워크플로.** 스텝은 기존 `ActionType`
  카탈로그를 참조한다; 빠진 capability 는 inline 스텝 body 가 아니라 upstream
  `ActionType` PR 이다.
- **risk-gate 를 우회하는 스텝.** 모든 스텝은 typed 파이프라인에 재진입한다.
  executor 를 직접 호출하는 스텝은 defect 다.
- **상시 구동 process orchestrator.** 프로세스는 event-driven, scale-to-zero 다;
  polling 데몬은 app shape 와 모순된다
  ([app-shape.instructions.md](../../../.github/instructions/app-shape.instructions.md)).
- **`enforce` 로 출시되는 워크플로.** upstream 워크플로는 shadow-first 다;
  enforce 는 별도 gated 승격이다.
- **보상 없는 실패 시 부분 상태.** `compensated_by` 없는 non-reversible 스텝은
  대상을 절반만 바꾼 채 두지 말고 실패를 HIL 로 라우팅 MUST.
