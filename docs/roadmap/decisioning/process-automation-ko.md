---
title: 프로세스 자동화(Process Automation)
translation_of: process-automation.md
translation_source_sha: f5cf03ca353e6028862601865dda17a19712eba0
translation_revised: 2026-07-23
---

# 프로세스 자동화(Process Automation)

프로세스 자동화는 다단계 비즈니스 프로세스를 1급, 온톨로지 연결, 거버넌스된
아티팩트로 바꾼다. 프로세스는 컨트롤 플레인을 우회하는 스크립트가 아니다. 이는
온톨로지 `ActionType` 호출의 선언적 시퀀스이며, 동일한 trust-routing 컨트롤
루프가 한 번에 한 스텝씩, 단일 remediation 과 동일한 안전 불변식 아래에서
dispatch 한다.

이 문서는 [agent-workflows.md](../agents/agent-workflows-ko.md) 의 머신-리더블 대응물이다.
그 문서가 12개 cross-agent 워크플로를 산문과 시퀀스 다이어그램으로 기술한다면,
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

분리가 중요합니다. `Workflow`는 *무엇*이 *언제* 실행되는지 선언하고 `Runbook`은 compiled
`Workflow`의 thin executor이며 `Process`는 한 번의 실행에 대한 audited state입니다. Mutation
step은 `ActionType`에 위임하여 safety invariant를 상속합니다. 읽기 전용 `evidence` step은 대신
`WorkflowEvidenceDispatcher`를 사용하고 action authority가 없으며 browser evidence가 unavailable이면
fail-closed됩니다. ([설계](../interfaces/browser-evidence-ko.md))

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

### 2.2 Definition, 소유권, binding

Catalog document와 operator의 automation 설정은 별도 record다.

- **`WorkflowDefinition`**은 immutable content-hash workflow document다.
  `origin` (`upstream`, `tenant`, `user`), `visibility` (`global`, `team`,
  `private`), lifecycle, owner, provenance, resolve된 ActionType version,
  ActionType catalog digest를 기록한다.
- **`WorkflowBinding`**은 인증된 principal 하나에 속하며, 보이는 definition을
  `deck_open`, `schedule`, `signal`에 bind한다. Schedule binding은 strict cron과
  IANA timezone이 필요하고 signal binding은 signal type이 필요하다. Parameter는
  scalar로 제한되며 새 action을 정의할 수 없다.

콘솔은 definition을 **Built-in**, **Shared**, **Mine**으로 그룹화한다. Built-in은
upstream git catalog에서 오고, Shared는 review를 통과한 tenant catalog artifact다.
Mine은 private user definition을 포함한다. **My automations**는 principal binding을
별도로 표시하므로 새 trigger나 timezone이 step graph를 복제하지 않고 기존
definition을 재사용한다.

모든 action step은 계속 ActionType catalog를 통해 resolve된다. Binding은 autonomy를
높이거나 등록되지 않은 action을 추가할 수 없다. Process 시작 전 compiler는 workflow
version, definition hash, resolve된 ActionType version, catalog digest를 pin하므로 replay가
현재 catalog에 의존하지 않는다. Private definition의 공유 또는 승격은 in-place
visibility toggle이 아니라 reviewed governance flow로 유지한다.

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

focused owner 문서로 이동했습니다: [workflow-control-loop-integration-ko.md](workflow-control-loop-integration-ko.md). governed shadow/enforce orchestrator, guard 평가 seam, runtime journal과 ontology projection, manual shadow/enforce command, governed Python task 및 cron schedule, governed command 및 shell artifact를 다룹니다.

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
저작합니다. 이 표면은 bounded authoring 계약을 사용합니다. 검증, 미리보기 및
시각화를 수행하며 명시적 save 는 principal 소유 private `draft` 만 만듭니다.
Publish, binding, enable 및 execution 은 별도로 검토되는 경로로 유지됩니다.

Step editor와 기타 authoring group은 data card가 아닌 structural panel입니다. Drill-down 목적지가
없으므로 editor 또는 section semantics를 사용하며, data card는 소유 detail 또는 evidence view로
연결되는 summary에만 사용합니다.

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
(`welcome -> need_action -> need_trigger -> confirm_plan -> offer_extra ->
confirm_safety -> confirm_name -> ready`) 을 걷고, 각 턴마다 봇 메시지 하나를
반환합니다. 지금 이해한 바의 짧은 설명, 다음 질문, 그리고 값이 엔진으로 다시
echo 되는 클릭 가능한 **옵션 칩**입니다. 설계 속성은 다음과 같습니다.

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
- 추론된 action 및 trigger 는 명시적 `confirm_plan` turn 없이는 진행되지 않습니다.
  Bounded proposal 보다 많은 3개 초과 action 이 일치하면 confirmation 에서 추가
  action 이 생략되었음을 알립니다.
- `confirm_safety` 는 fail-closed behavior, shadow posture 및 promotion threshold 를
  보여줍니다. Operator 는 workflow 이름을 정하기 전에 `anti_scope` boundary 를 기록할
  수 있습니다.
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
- `POST /workflows/validate` 의 **structural validation result** ("구조적으로
  유효하고, 모든 스텝이 resolve 된다...") 를 보여줍니다. 이 검사는 workflow 를
  execute, simulate 또는 predict 하지 않습니다.
- confirmation 과 함께 `POST /workflows/definitions` 를 호출하는 명시적 **Save
  private draft** action 은 private `draft` 를 만듭니다. 저장된 definition 은 실행할
  수 없고 Operations 에 나타나지 않습니다.
- 접을 수 있는 **Edit validated draft** 표면에서 action step 을 편집할 수 있습니다.
  ActionType 교체, 삽입, 제거, 순서 변경, step id, guard 및 recovery 참조, primitive
  parameter, trigger metadata, anti-scope 및 promotion threshold 를 지원합니다. 편집하면
  이전 save 결과가 무효화되고 짧은 debounce 후 동일한 server structural validation 을
  다시 실행합니다.
- 크기가 제한된 `sessionStorage` 에서 탭 범위 draft 를 복구합니다. 방어적 decoder 는
  malformed 또는 oversized record 를 신뢰할 수 없는 draft 로 로드하지 않고 폐기합니다.
- git-native 다음 단계: YAML 을 `rule-catalog/workflows/<name>.yaml` 로
  복사하고 remediation PR 을 연다.

추가 step 제안은 명시한 목표에서 일치한 action 과 communication follow-up 으로
제한됩니다. Builder 는 모든 ActionType category 를 보여 주기 위해 무관한 mutation 으로
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

세 개의 opt-in, Reader-gated read API 라우트가 validation 및 browse 를
뒷받침합니다. 모두 상태를 쓰지 않는 pure projection 입니다 (see
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

Console 은 privileged read-only 불변식을 유지합니다
([app-shape.instructions.md](../../../.github/instructions/app-shape.instructions.md)).
Palette 및 catalog 는 GET-only `ReadApiClient` 를 통한 GET이고 validation 은 pure이며,
save 는 principal 소유 private authoring record 만 씁니다. Save route 는 executor
identity 를 받지 않으며 definition 을 publish, bind, enable 또는 run 할 수 없습니다.
유효한 draft 는 `rule-catalog/workflows/<name>.yaml` 에 제안할 YAML 도 제공합니다.
새 catalog entry 는 `shadow` 로 잠기며 enforce 승격은 [6절](#6-거버넌스) 의 별도
governance PR 로 유지됩니다.

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
  `GET /views/process/{process_id}` 가 list 및 workflow-specific detail projection 을
  제공합니다. `GET /views/process/{process_id}/events` 는 ViewSpec 을 등록하지 않은
  workflow 를 포함한 모든 Process 의 authoritative snapshot 및 append-only event
  journal 을 반환합니다.
- **Generic console renderer** 는 승인된 widget vocabulary 만 지원합니다. 임의의
  ontology property 를 executable UI 또는 action button 으로 변환하지 않습니다.

**Processes** route 는 모든 실행을 나열하고 active, completed, failed 수를
요약하며 선택한 Process timeline 을 가장 오래된 event 부터 최신 event 순으로
렌더링합니다. CLI 또는 ChatOps 명령이 Process 를 진행시킨 후 오퍼레이터는 read
projection 을 새로 고칠 수 있습니다. Workflow-specific ViewSpec 이 있으면 runtime
journal 아래에 표시됩니다. 화면은 start, approve, retry, execute button 을 제공하지
않습니다.

Architecture map 은 별도입니다. Inventory graph 가 반환한 실제 infrastructure
topology 를 시각화합니다. Process view 는 workflow state 및 domain projection 을
시각화합니다. 어느 surface 도 다른 surface 의 source of truth 가 아닙니다.

### 8.3 Workflow app 및 메뉴 노출

재사용 가능한 read surface 가 필요한 workflow 는 Workflow 및 ViewSpec 과 별도로
**WorkflowApp** manifest 를 등록합니다. Manifest 는 검색 가능성만 제어합니다. 실행
logic, action button, JavaScript 또는 임의 backend route 를 추가하지 않습니다.

Console 은 Operations domain 에 하나의 안정적인 **Workflow apps** 항목을
노출합니다. 이 hub 는 현재 principal 에게 보이는 published manifest 를 나열합니다.
각 app 은 `/workflow-apps/{app_id}` 를 사용하며 `workflow_ref` 로 필터링된 generic
Process list, journal, ViewSpec, ReportSpec 및 widget renderer 를 재사용합니다. 생성된
workflow 자체가 새 compiled `ConsolePanel` 이 되지 않으므로 runtime catalog 증가가
frontend bundle 을 변경하거나 Activity Bar 를 과도하게 늘리지 않습니다.

Manifest lifecycle 은 노출을 다음과 같이 제어합니다.

- `draft` manifest 는 authoring 에서만 보이며 Operations 에 들어가지 않습니다.
- `shadow` manifest 는 workflow-specific Process detail ViewSpec 을 제공할 수 있지만
  Workflow apps hub 에는 나타나지 않습니다.
- `published` manifest 는 workflow, ViewSpec 및 role cross-reference 검증 후 hub 에
  나타납니다.
- `retired` manifest 는 navigation 에서 사라지지만 기존 audit 및 Process deep link 는
  계속 읽을 수 있습니다.

`WorkflowApp` id와 route는 영구적인 machine reference입니다. Launchpad, catalog, detail,
automation, chat 및 Python-task view는 parity-checked route catalog와 영어 fallback으로 label을
현지화하며 workflow id, serialized value 및 validation result는 바꾸지 않습니다. Read API는
principal에게 authorized된 manifest만 반환하며 browser hiding은 access control이 아닙니다. 새
interaction model이나 executable frontend code는 build-time `EXTRA_PANELS`, injected
`ReadPanel` 및 별도 reviewed release를 사용하고 대화에서 remote code로 생성하지 않습니다.

## 9. agent-workflows.md 와의 관계

[agent-workflows.md](../agents/agent-workflows-ko.md) 는 설계 참조다: 12개 워크플로, 그
에이전트, 시퀀스 다이어그램, exit criteria. 이 문서는 그 워크플로가 컴파일되는
구현 계약이다. 둘은 동기화된 채로 유지된다: 새 워크플로는 agent-workflows.md 의
문서 엔트리와 [`rule-catalog/workflows/`](../../../rule-catalog/workflows) 아래
카탈로그 YAML 로, 같은 PR 에서 도착한다.

## 10. 안티패턴

- **새 mutation primitive 를 선언하는 워크플로.** 스텝은 기존 `ActionType`
  카탈로그를 참조한다; 빠진 capability 는 inline 스텝 body 가 아니라 upstream
  `ActionType` PR 이다.
- **Risk-gate를 우회하는 상태 변경 step.** 모든 action step은 typed pipeline에 재진입합니다.
  Evidence 및 control step은 executor를 호출할 수 없습니다.
- **상시 구동 process orchestrator.** 프로세스는 event-driven, scale-to-zero 다;
  polling 데몬은 app shape 와 모순된다
  ([app-shape.instructions.md](../../../.github/instructions/app-shape.instructions.md)).
- **`enforce` 로 출시되는 워크플로.** upstream 워크플로는 shadow-first 다;
  enforce 는 별도 gated 승격이다.
- **보상 없는 실패 시 부분 상태.** `compensated_by` 없는 non-reversible 스텝은
  대상을 절반만 바꾼 채 두지 말고 실패를 HIL 로 라우팅 MUST.
