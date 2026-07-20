---
title: Action 온톨로지
translation_of: action-ontology.md
translation_source_sha: 71388cd5d28db06d12be8070f4d013b437dedf10
translation_revised: 2026-07-21
---

# Action 온톨로지

FDAI 의 모든 액션 - 룰이 발화시킨 remediation 이든 오퍼레이터가
요청한 ops task 든 - 는 shipped 온톨로지의 **`ActionType`** entry 하나의
instance 이다. 이 문서는 스키마, 트리거 축 (`rule_violation` vs
`operator_request`), tier 및 role 상한, live-probe 참조, 그리고 `core/`
편집 없이 고객이 재정의 가능하게 하는 **fork-override seam** 을 권위적으로
정의한다.

이 온톨로지의 소비자:

- T0Engine + ActionBuilder ([phase-1](../phases/phase-1-rule-catalog-t0-ko.md))
  는 룰이 발화시킨 액션을 빌드할 때 `rollback_contract`,
  `preconditions`, `stop_conditions`, `blast_radius` 를 read.
- 통합 RiskGate + Executor ([execution-model.md](execution-model-ko.md))
  는 실행 **여부** 와 **방법** 을 결정할 때 tier 상한, min-role,
  live-probe 참조, execution path 를 read.
- 오퍼레이터 콘솔 narrator ([operator-console.md](../interfaces/operator-console-ko.md))
  는 ops-flavoured tool call 을 제안하거나 실행할 때 `trigger_kind`,
  `description`, `argument_schema` 를 read.

단일 온톨로지가 세 곳 모두를 feed 하기 때문에, 새 remediation 또는 새 ops
verb 추가는 YAML 파일 하나 - 엔진에 branching 없음, 새 executor 없음.

> 고객-무관: 아래의 모든 ActionType 이름, 파라미터, blast-radius 값은
> placeholder 또는 예시. Fork 가 config 로 entry 추가/재정의
> ([generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md)).

## 1. 하나의 온톨로지, 두 트리거

초기 ActionType 집합은 룰이 발화시킨 remediation만 포함했습니다. 현재 catalog는
같은 schema 아래 remediation, ops, governance, tool entry를 포함합니다. 오퍼레이터
콘솔 pull-방향 ([operator-console.md](../interfaces/operator-console-ko.md) §4) 는 룰
발화가 아니라 **오퍼레이터의 chat 요청** 으로 트리거되는 액션이 필요:
"이 pod 재시작", "scale out", "cache flush". 이들은 같은 safety envelope
를 공유하지만 다른 trigger surface 를 가진다.

온토로지는 둘 다 **하나의 스키마 + 하나의 축** 으로 처리. `trigger_kind`
은 `kind` 필드가 세 허용 값 중 하나를 취하는 오브젝트:

```yaml
trigger_kind:
  kind: rule_violation | operator_request | both
  # rule_violation   - T0/T1/T2 엔진이 룰 매치 -> 자동 proposal
  # operator_request - 콘솔의 사람 -> 명시적 ops
  # both             - 어느 경로든 사용 가능한 동일 ActionType
```

- **`rule_violation`** - ControlLoop 이 매치된 룰 + finding 로부터 액션을
  construct. 트리거는 T0/T1/T2 판정.
- **`operator_request`** - 오퍼레이터-콘솔 narrator 가 이 ActionType 을
  대상으로 하는 tool_call 을 emit. 트리거는 콘솔 세션 + principal +
  arguments.
- **`both`** - 일부 액션은 두 surface 모두에 속함. 예: `ops.restart-service`
  는 오퍼레이터가 트리거 ("restart this") 하거나 룰이 트리거 (health-probe
  fail 룰) MAY. 온톨로지 entry 는 합집합을 declare; runtime 이 path 선택.

이 축을 제외하고 스키마의 어느 것도 trigger-specific 이 아니다; executor,
RiskGate, audit 계약은 둘 다 동일.

## 2. 스키마

```yaml
schema_version: "1.0.0"
name: string                            # 안정된 UNIQUE 식별자, snake+dot: "ops.restart-service"
                                        # 이것이 온토로지 id. audit 는 action_type_id
                                        # 로 참조; 로더가 이것으로 dedupe; override overlay
                                        # 파일은 <name>.yaml (7.1 참조).
                                        # (별도 `id` 필드 없음 - 모든 shipped YAML 에
                                        # `name` 이 이미 있고 마이그레이션-safe 키).
version: semver
category:                               # 최상위 bucket - 리스트가 아니라 단일 값
                                        # remediation | ops | governance | tool 중 하나
                                        #   remediation - 룰 발화, config-drift 스타일
                                        #   ops         - 오퍼레이터 요청 runtime 액션
                                        #   governance  - 정책 / 예외 / promotion 변경
description: string                     # <= 200 자, 영어, 마케팅 없음

# --- Operation + interfaces (기존, 유지 - risk-classification 이 읽음) ---
operation: enum                         # tag | delete | drop | purge | detach | rotate | ...
                                        # risk-classification `destructive` = operation in
                                        # {delete, drop, purge, detach}
interfaces:                             # ActionType 의 capability flag
  - ControlPlane | DataPlaneMutating    # risk-classification `data_plane_touched`
  - RequiresInventoryFresh              # risk-classification `graph_stale` 입력
  - IdempotentByKey | GraphTraversalRequired

# --- 트리거 축 (§1) ------------------------------------------------------
trigger_kind:                           # rule_violation | operator_request | both 중 하나
  kind: enum
  restrict_to_scenarios: [string, ...]  # 옵션; 어느 시나리오가 이걸 fire MAY 인지 narrow

# --- Autonomy + safety (기존, phase-1 그대로 유지) -----------------------
default_mode: shadow                    # 신규 ActionType 은 shadow MUST
promotion_gate:
  min_shadow_days: int
  min_samples: int
  min_accuracy: float
  max_policy_escapes: int

# --- Execution path (execution-model.md 상세) ----------------------------
execution_path: pr_native | direct_api | pr_manual | tool_call
                                        # pr_native → shipped GitOpsPrAdapter (기본)
                                        # direct_api → ops-fast-path (Azure ARM call)
                                        # pr_manual → hil label PR, auto-merge 없음

# --- Rollback contract (기존) --------------------------------------------
rollback_contract: pr_revert | scripted | pitr | snapshot_restore | state_forward_only
irreversible: bool                       # true 면 tier 무관 HIL 필수

# --- Preconditions + stop conditions (기존) -----------------------------
preconditions:
  - kind: graph_fresh_within_seconds
    value: int
  - kind: resource_tag_present
    tag: string
  - ...                                  # 기존 카탈로그 재사용

stop_conditions:
  - kind: provider_api_error_streak
    count: int
  - kind: time_box_exceeded_seconds
    seconds: int
  - ...

# --- Blast radius (기존 static) ---------------------------------------
blast_radius:
  computation: static_enum | graph_derived
  static_bucket: resource | resource_group | subscription
                                        # CSP-neutral bucket, risk-classification.md 와 공유
  max_affected_resources: int            # graph_derived 만

# --- 신규: live-blast probe pointer (TOP-LEVEL; Month 1+; §6 참조) -------
live_probe_ref: string                   # 옵션; 예: "probes/vm_traffic_last_5m"
                                         # RiskGate 가 ActionType.live_probe_ref 로 read

# --- 신규: tier × role 상한 (execution-model.md §3) ---------------------
ceiling_by_tier:
  t0:
    max_autonomy: enforce_auto | enforce_hil | shadow_only
    min_role: reader | contributor | approver | owner
  t1:
    max_autonomy: enforce_auto | enforce_hil | shadow_only
                                         # shipped YAML은 catalog loader가 제한하며
                                         # overlay는 autonomy를 낮출 수만 있음
    min_role: contributor | approver | owner
  t2:
    max_autonomy: shadow_only            # catalog loader가 shadow-only를 요구하며
                                         # hard-cap 변경은 reviewed policy change가 소유
    min_role: approver | owner
# NOTE: min_role 은 통상 ladder reader<contributor<approver<owner 만 사용.
# BreakGlass 는 OFF-LADDER (Owner 에 nested 안 된 별도 Entra 그룹) 이며 절대
# min_role 값이 아니고; dispatch 시 승인 자격에만 영향 (execution-model 2.5).

# --- 신규: prod-vs-non-prod downgrade -----------------------------------
env_scope: prod | non_prod | any        # 기본: any. `non_prod` = dev-only ActionType
                                        # (prod_downgrade 생략 MAY). `any`/`prod` 는
                                        # prod_downgrade 를 carry 하거나 risk-table env
                                        # 신호를 inherit MUST - 누락된 블록이 prod auto 로 fail open 안 함.
prod_downgrade:
  mode: enforce_hil | shadow_only        # "prod" 가 collapse 되는 값
  detection_ref: string                  # risk-classification.md (Environment Detection) 에
                                         # 정의된 동일 env classifier 로 resolve; 여기서
                                         # 두 번째 prod-감지 룰을 정의하지 말 것

# --- Arguments (operator_request 또는 both 만) --------------------------
argument_schema:                         # JSON Schema; 콘솔이 렌더 + 검증
  type: object
  properties: {...}
  required: [...]

# --- Provenance (기존) ---------------------------------------------------
provenance:
  source_url: string
  resolved_ref: string                   # git sha / registry version
  content_hash: string                   # sha256
  license: string
  retrieved_at: RFC3339
```

Catalog backfill은 다음 상태로 완료되었습니다:

- `trigger_kind.kind = rule_violation`
- `category = remediation`
- `ceiling_by_tier` 는 현 implicit default 로 채워짐 (T0 → medium/high
  severity 는 `enforce_hil`, low 는 `enforce_auto`; T1/T2 → `shadow_only`)
- 스키마-깨는 rename 없음; 로더는 누락된 신규 field 를 가장 safe 한 값으로
  취급.

## 3. Category 카탈로그

네 최상위 category. 신규 category 는 doc PR + 도메인 어휘를 flat 하게
유지하기 위해
[architecture.instructions.md](../../../.github/instructions/architecture.instructions.md)
에 short-form entry 필요.

### 3.1 `remediation.*`

룰 발화, config-drift 스타일. 현재 shipping:

- `remediate.tag-add`
- `remediate.disable-public-access`
- `remediate.right-size`
- `remediate.rotate-secret`
- `remediate.enable-tde`
- `remediate.enable-encryption`
- `remediate.enable-diagnostic-settings`
- `remediate.enable-backup-protection`
- `remediate.enable-zone-redundancy`
- `remediate.enable-rbac`
- `remediate.restrict-network-access`
- `remediate.remove-orphan-resource`
- `remediate.set-tls-policy`
- `remediate.enable-purge-protection`
- `remediate.set-retention-policy`
- `remediate.assign-identity`
- `remediate.apply-preflight-toggle`
- `remediate.azure-policy-managed`
- `remediate.right-size-role`

기본 `execution_path: pr_native` (GitOps). Fork 는 API 변경이 하나의
idempotent call 인 액션 별로 `direct_api` 로 override MAY.

### 3.2 `ops.*`

오퍼레이터 요청 runtime 액션. Day 1 shipping:

- `ops.restart-service` - AKS pod 재시작, App Service 재시작, Container App revision 재시작.
- `ops.scale-out` - replica / instance count 증가. 지출-증가이므로
  `cost_impact_monthly` 를 선언 MUST -> risk-classification cost gate 적용
  ([execution-model.md § 2.8](execution-model-ko.md#28-비용-증가-ops-액션)).
- `ops.scale-in` - replica count 감소 (Approver + live probe).
- `ops.flush-cache` - Redis / CDN cache flush.
- `ops.drain-connection` - load balancer backend 의 connection drain.
- `ops.rotate-cert` - TLS cert 회전 (App Gateway / Front Door).
- `ops.failover-primary` - 복제 리소스에서 failover 트리거. 더 큰 tier 로
  failover 시 `cost_impact_monthly` 선언 MUST.
- `ops.publish-change-summary` - resource-group 에 대해 정해진 시간
  범위의 변경 이력을 rendered Markdown 요약으로 만들어 delivery adapter 에
  전달. Non-Resource 비즈니스-오브젝트 flow 의 reference 예제; 짝을 이루는
  ObjectType `ChangeSummary` 와 LinkType `summarizes` 가 copy-ready
  scaffold ([downstream-fork-example-vertical-ko.md](../fork-and-sequencing/downstream-fork-example-vertical-ko.md)
  참조).

**Vertical 매핑.** 각 ops ActionType 은 소유 vertical 로 태깅되어
[verticals](../../../src/fdai/core/verticals) 가 claim 하고 vertical 룰이
`remediates:` 할 수 있음: `ops.failover-primary` 와 `ops.restart-service`
-> Resilience; `ops.scale-in` / `ops.scale-out` -> Cost Governance;
`ops.drain-connection` / `ops.rotate-cert` -> Change Safety.
`ops.flush-cache` 와 `ops.publish-change-summary` 는 cross-vertical
(오퍼레이터-트리거).

기본 `execution_path: direct_api` (ops 는 latency-sensitive; PR overhead
는 목적을 defeat). Fork 는 모든 runtime change 가 reviewable diff 로
landing 해야 하는 compliance-heavy 환경에서 `pr_manual` 을 강제 MAY.

### 3.3 `governance.*`

온톨로지 / 카탈로그 / 예외 / promotion 변경. 네 entry 가 오늘의
온톨로지에 authored; **오직 하나만 현재 live dispatcher 를 가짐**
(나머지 셋은 P2 에서 land 될 PR-native writer 대기 중인
catalog-as-code artifact):

- `governance.promote-action-type` - 하나의 ActionType 의 `default_mode`
  를 shadow → enforce 로 flip (해당 ActionType 의 `promotion_gate` 로
  bounded).
  **Dispatcher: not yet implemented (P2 backlog).**
- `governance.retire-rule` - enforce 집합에서 룰 제거 (shadow-only 또는
  full retire).
  **Dispatcher: not yet implemented (P2 backlog).**
- `governance.grant-exemption` - time-boxed 예외 생성
  ([rule-governance.md](../rules-and-detection/rule-governance-ko.md)). 기존 예외는
  `rule-catalog/exemptions/` 아래 JSON 으로 authored 되어 risk gate 가
  `ExemptionRegistry` 를 통해 소비; 런타임 **create-a-new-exemption**
  operator flow 는 동일한 P2 PR-native writer 와 함께 land.
- `governance.override-ceiling` - 특정 resource / tag 스코프에 대한 tier
  ceiling 의 operator-측 override (fork extension).
  **Dispatcher shipped**:
  [`src/fdai/core/risk_gate/override_writer.py`](../../../src/fdai/core/risk_gate/override_writer.py).

Governance 액션은 항상 `execution_path: pr_native` 사용 - catalog-as-code
변경이고 reviewed diff 로 landing MUST.

### 3.4 `tool.*`

substrate 를 mutate 하지 않고 등록된 함수 (tool) 를 invoke. LLM 이 tool 을
호출하는 방식의 온톨로지-네이티브 대응물: executor 가
[`ToolExecutor`](../../../src/fdai/shared/providers/tool.py) Protocol
(`ToolCallShadowExecutor`) 을 통해, **아티팩트** 또는 side effect (문서,
메시지, 티켓) 를 생산하는 등록된 함수로 dispatch. Shipped 예시:

- `tool.generate-pdf` - 리포트 템플릿으로부터 PDF 문서 (resilience summary,
  cost report, change audit) 렌더. Rollback 은 `state_forward_only` (생산된
  아티팩트 삭제).
  **Dispatcher: shadow-only** (`RecordingToolExecutor` Day-1 binding; fork 가
  live 어댑터 bind).
- `tool.run-python-on-vm` - 검증된 content-addressed Python artifact 를
  inventory 에서 선택한 Linux VM 하나에 stage 하고 `VmTaskRunner` provider 로
  실행합니다. Task 는 `gpu`, `network`, filesystem access, child-process 생성 같은
  host capability 를 선언합니다. Target 은 필요한 모든 capability 를 제공해야
  합니다. Action 은 source text 또는 arbitrary shell command 가 아니라 artifact
  reference 만 받습니다. Shadow mode 는 plan 을 만들고, enforce mode 는 Owner HIL
  이후 Azure Managed Run Command 를 사용합니다. Immutable file 은 설정된 non-root
  account 가 bounded timeout 으로 entrypoint 를 실행하기 전에 guest 에서 SHA-256
  으로 다시 검증됩니다.

기본 `execution_path: tool_call`. `core/` 는 Protocol 만 안다; fork 가
composition root 에서 live 어댑터 (네이티브 Python registry, MCP 클라이언트,
HTTP callout) 를 bind - registry 는 MCP 어댑터의 자연스러운 attach point 로,
MCP 서버 tool 하나를 `tool.*` ActionType 하나에 매핑한다. `tool.*` ActionType
은 측정 가능한 `promotion_gate` 를 가진 shadow-first 이고 임의의 mutation
ActionType 과 동일한 4 개 안전 invariant 를 carry 하므로, 워크플로 스텝이
`action_type_ref` 로 참조하며 이를 상속 MAY.
[execution-model-ko.md § 5.6](execution-model-ko.md#56-tool-call-tool_call) 참조.

`tool.*` ActionType 은 `ceiling_by_tier` 를 declare SHOULD. reversible,
resource-scoped, control-plane, low-cost 인 tool 은 risk-classification
테이블의 `auto-low-risk` 행에 매칭되므로, **ceiling 이 없으면 enforce 승격 후
`auto` 로 분류될 수 있다** - idempotent 리포트 렌더엔 괜찮지만 알림/티켓 tool
엔 잘못된 것이다. ceiling 은 테이블과 무관하게 autonomy 를 `enforce_hil` 로
캡한다; shipped `tool.generate-pdf` 는 이 이유로 `t0.max_autonomy: enforce_hil`
을 설정한다.

## 4. 트리거 surface

### 4.1 `rule_violation` (동작 변경 없음)

```
Event → EventIngest → TrustRouter → T0/T1/T2 → Finding →
  ActionBuilder(finding, rule, action_type) → Action → RiskGate → Executor
```

- 룰은 `remediates: <action_type_id>` (기존 field) 로 ActionType 을
  declare.
- `ActionBuilder` 는 룰의 `parameters` 블록으로부터 Action 의 `params`
  populate.
- 트리거 surface 는 event bus.

### 4.2 `operator_request` (신규)

```
Chat turn → Narrator → tool_call(action_type_id, args) →
  Coordinator argument_schema 대비 args validate →
  RiskGate → Executor
```

- 오퍼레이터는 narrator 가 tool_call 로 translate 한 자연어 turn 을
  통해 ActionType pick.
- ActionType 의 `argument_schema` (JSON Schema) 는 coordinator 경계에서
  args 를 validate ([operator-console.md § 5.2](../interfaces/operator-console-ko.md#52-consoletool)) -
  콘솔은 잘못된 형태의 액션을 executor 에 절대 dispatch 안 함.
- 트리거 surface 는 오퍼레이터-콘솔 세션.

Note: 두 surface 는 RiskGate 에서 만남 (execution-model.md §3).
ActionType 은 자신의 invocation 을 어느 트리거가 생성했는지 모름 - 오직
`trigger_kind` scoping (§1) 만 제약.

### 4.3 세 분류 축 (관계)

액션을 설명하는 세 직교 label; 동의어가 아니다:

| 축 | 소유 doc | 값 | 답 |
|------|-----------|------|------|
| `category` | 이 doc (§3) | remediation / ops / governance | *어떤 종류의 변경* |
| `trigger_kind` | 이 doc (§1) | rule_violation / operator_request / both | *누가 시작* |
| `side_effect_class` | [operator-console.md § 3.4](../interfaces/operator-console-ko.md#34-tool-discovery-계약) | read / simulate / approve / execute / breakglass | *콘솔 tool 이 뭐를 함* |

전형적 조합: `remediation` ActionType 은 `trigger_kind=rule_violation`
이고 콘솔 tool 로 surface 될 때 그 tool 은 `side_effect_class=execute`;
`ops` ActionType 은 보통 `trigger_kind=both` 에 `execute` tool; `governance`
ActionType 은 `trigger_kind=operator_request` 이고 tool 은 `approve` 또는
`execute`. audit entry (§9) 가 세 것 모두 carry 하여 어느 축으로든 slice 가능.

### 4.4 실행 인가 vs 온톨로지 property ACL

온톨로지 **property read** 는 두 독립 차원 - `access_scope` (role rank)
AND `purpose_binding` (purpose-set 교집합) - 으로 gate 됨. read 는 아니면
single-gate 연산이고 data-minimization 이 두 번째 축을 필요로 하기 때문
([`shared/ontology/acl.py`](../../../src/fdai/shared/ontology/acl.py)).

ActionType **execution** 은 의도적으로 `purpose_binding` 을 carry 하지
않음; 그 인가는 `ceiling_by_tier.min_role` 에 더해 full 6-축 RiskGate
ceiling (risk table, tier cap, static blast, live blast, role, env),
quorum, HIL gate, shadow-first promotion. 따라서 execution 은 read 보다
더 적은 게 아니라 더 많은 차원으로 gate 됨 - 비대칭은 missing gate 가
아니라 의도된 것. Purpose-scoped execution (오퍼레이터가 purpose X 에
한해서만 이 액션 실행 가능) 은 future scope; `ceiling_by_tier` 에
`min_purpose` 축과 dispatch principal 에 purpose 를 추가하는 것이고,
현재 risk 모델엔 불필요 (critique #30).

## 5. Argument 스키마 (`operator_request` 만)

룰-발화 ActionType 은 params 를 룰의 `parameters` 블록에서 받음; 오퍼레이터
-요청 ActionType 은 params 를 오퍼레이터의 tool_call arguments 에서 받고
`argument_schema` JSON Schema 를 declare MUST → 콘솔이:

1. `list_tools()` 에서 machine-readable shape 로 tool 렌더.
2. 액션 호출 전 coordinator 경계에서 arguments validate
   ([operator-console.md § 5.2](../interfaces/operator-console-ko.md#52-consoletool)).
3. 감사-write 경계에서 sensitive field (`x-fdai-redact: true` mark)
   redact.

### 5.1 예시 - `ops.restart-service`

```yaml
argument_schema:
  type: object
  additionalProperties: false
  required: [target_resource_ref, restart_reason]
  properties:
    target_resource_ref:
      type: string
      description: >-
        CSP-중립 리소스 id, 예 "example-rg/aks/cluster/pod-name".
        문법은 csp-neutrality.md (Inventory 계약) 에 정의된 CSP-중립
        inventory 리소스 id; coordinator 가 dispatch 전 그 문법으로 ref 검증.
    restart_reason:
      type: string
      minLength: 10
      maxLength: 200
      description: Human-readable justification; audit trail 에 기록.
    grace_period_seconds:
      type: integer
      default: 30
      minimum: 0
      maximum: 300
```

### 5.2 Redaction 힌트

Redaction 은 **denylist 가 아니라 allowlist**: 모든 free-text string
property (`enum`, `pattern`, `const`, `format` 제약 없는 `string`) 는 두
힌트 중 정확히 하나를 선언 MUST - secret 이나 PII 를 carry MAY 하는 field
가 verbatim 저장으로 절대 default 되지 않도록:

- `x-fdai-redact: true` - redactor 가 audit write 전 값을 strip. leaf
  `string`/`number` property 에만 유효.
- `x-fdai-audit-safe: true` - 저자가 값이 저장 안전하다고 assert (resource
  ref, justification, region 이름 등).

힌트 둘 다 없는 free-text string 은 fatal load error. property 는 둘 다
설정 MUST NOT. 이 둘 외 `x-fdai-*` key 는 fatal typo guard - 오철자
`x-fdai-redcat` 가 secret 을 silently redact 실패 못 하게. 제약된 string
(enum/pattern/format) 과 non-string type 은 힌트 불필요.

```yaml
properties:
  temp_admin_password:
    type: string
    x-fdai-redact: true       # verbatim 저장 절대 안 됨
  restart_reason:
    type: string
    minLength: 10
    x-fdai-audit-safe: true   # justification 은 저장 안전
```

로더는 모든 `x-fdai-redact` path 를 set 으로 수집해
`argument_schema_redaction_paths(action_type)` 로 노출; audit redactor 가
`operator_request` argument blob 을 append-only 로그에 저장하기 전 그 path
들을 strip.

## 6. Live blast probe (execution-model.md §6, Month 1+)

Static `blast_radius` 만으로는 coarse - 같은 "delete storage account"
mutation 이 dead 리소스에서는 사소하지만 live 리소스에서는 catastrophic.
Month 1 은 ActionType 에 **`live_probe_ref`** field 를 추가하므로 RiskGate
가 결정 전에 probe 를 consult 가능.

```yaml
live_probe_ref: probes/vm_traffic_last_5m
```

- Probe 는 [`rule-catalog/probes/`](../../../rule-catalog/probes) 아래
  YAML 로 declare - probe id 당 하나의 파일.
- 각 probe 는 input (target resource ref), query (Azure Monitor KQL /
  Metric API / ARG), interpretation 함수 (`quiet | active | overloaded`)
  를 declare.
- `RiskGate` 는 probe 를 호출하고 answer 를 static ceiling 과 결합 (see
  [execution-model.md § 4](execution-model-ko.md#4-live-blast-probe)).

Probe 는 ActionType 및 환경 별로 opt-in. Fork 가 자체 probe 를 ship;
upstream 카탈로그는 small starter set 을 ship (VM traffic, storage
access log, load-balancer backend health).

## 7. Fork override seam

위의 모든 것은 데이터. Fork 는 `core/` 또는 upstream YAML 을 편집하지
않고 어느 축이든 재정의 MUST 가능해야 함. 온톨로지는 네 override 채널을
노출한다.

### 7.1 파일 기반 overlay

- Upstream 은 `rule-catalog/action-types/<name>.yaml` ship.
- Fork 는 `rule-catalog/action-types-overrides/<name>.yaml` 을 override
  할 field 의 strict subset 으로 배치.
- 로더는 startup 시 upstream + overrides 를 **key-by-key 우선순위**
  로 merge (overrides 승리); 누락된 overrides field 는 upstream 으로
  fallback. `name` 이 매칭되는 upstream ActionType 이 없는 overlay 는
  fatal load error - overlay 계층은 기존 ActionType 을 *tighten* 만
  하며 새로 도입할 수는 없음. **새** ActionType 을 추가하는 fork 는
  `rule-catalog/action-types-custom/` 아래에 ship 하고 그 root 를
  concat 한다 (7.6 참조).
- 매 merge 는 audit entry
  (`action_kind=catalog.load.action_type_overlay`) 를 write → 승격된
  override 는 traceable.

```yaml
# 예시: fork 가 prod 에서 tag-add 를 tighten
# path: rule-catalog/action-types-overrides/remediate.tag-add.yaml
name: remediate.tag-add
ceiling_by_tier:
  t0:
    max_autonomy: enforce_hil      # upstream 은 enforce_auto; fork downgrade
prod_downgrade:
  mode: shadow_only
```

### 7.2 Policy-as-code overlay

- `policies/action_types/` 아래 Rego 정책이 per-invocation override 를
  compute MAY, 예: "금요일 오후에 모든 enforce_auto 를 enforce_hil 로
  downgrade" (change freeze).
- RiskGate 는 파일 overlay 후 정책 evaluate - 둘 다 같은 축에 대해
  something 을 express 하면 Rego 승리.

### 7.3 Config-driven overlay

- Coarse switch (feature-flag 스타일) 를 위한 env-var toggle:
  `FDAI_OVERRIDE_ACTION_TYPE_<id>_MAX_AUTONOMY=shadow_only`.
- **Downgrade-only**: 값은 `shadow_only` 또는 `enforce_hil` MUST, 절대
  `enforce_auto` 아님 - config toggle 은 autonomy 를 낮추기만 할 수 있고
  절대 올릴 수 없음 (모든 overlay 와 동일한 never-raise 규칙).
- **항상 감사됨**: config override 적용은 env-var 이름과 resolved 값을
  담은 audit entry (`action_kind=catalog.override.config`) 를 write하므로
  emergency downgrade 가 절대 silent 하지 않음.
- Rare; Rego re-deploy 가 너무 느린 emergency downgrade 를 위해 문서화.

### 7.4 Runtime override (chat)

- 오퍼레이터 콘솔의 Approver / Owner 가 bounded scope
  (`resource_group=X, until=YYYY-MM-DDT..Z`) 로
  `governance.override-ceiling` 호출 MAY. 이는 `pr_native` 로 (감사됨)
  `policies/action_types/` 아래 Rego 정책 fragment 를 write.
- Time-boxed; 자동 만료는 기존 exemption workflow 와 함께 ship
  ([rule-governance.md](../rules-and-detection/rule-governance-ko.md)).

### 7.5 우선순위

여러 overlay 가 같은 축에 대해 speak 하면 우선순위는:

1. Config-driven override (env var, §7.3) - emergency break-glass, 가장
   specific 하고 가장 urgent; downgrade-only 이고 항상 감사됨.
2. Runtime override (Rego fragment, chat-authored, time-boxed) - 가장
   specific 한 steady-state, 가장 recent.
3. Rego 정책 (`policies/action_types/`) - operator-authored steady state.
4. 파일 overlay (`rule-catalog/action-types-overrides/`) - fork
   compile-time.
5. Upstream YAML (`rule-catalog/action-types/`) - repository default.

모든 layer 는 downgrade-only (autonomy 절대 안 올림) 이므로 우선순위는
*어느* downgrade 가 이기는지를 정할 뿐, autonomy 가 올라가는지는 결코
아님. RiskGate 는 그 순서로 resolve 하고 winning overlay layer 를 audit
entry 에 기록.

### 7.6 새 ActionType 추가 (별도 root)

위 네 채널은 shipped ActionType 을 *수정*만 함. **새** ActionType 추가는
override 가 아니며 7.5 우선순위 체인에 참여하지 않는다. Fork 는 새
ActionType 을 `rule-catalog/action-types-custom/` 아래에 ship 하고
(upstream 은 `.yaml.example` 템플릿을 제외하면 이 디렉토리를 비워둠) 두
번째 catalog root 로 로드해 upstream catalog 와 concat 한다:

```python
action_types = (
    load_action_type_catalog(Path("rule-catalog/action-types"), ...)
    + load_action_type_catalog(Path("fork/action-types-custom"), ...)
)
```

두 root 간 중복 `name` 은 fatal load error 이므로 추가가 upstream
ActionType 을 조용히 shadow 할 수 없다 (shadowing 은 7.1 overlay 계층의
역할). [../../rule-catalog/action-types-custom/README.md](../../../rule-catalog/action-types-custom/README.md)
참조.

## 8. 로더 + 검증

- 로더 ([`rule_catalog/schema/action_type.py`](../../../src/fdai/rule_catalog/schema/action_type.py))
  는 startup 시 upstream + overrides + Rego reference 를 load.
- Cross-check (기존 shipping):
  - 모든 룰의 `remediates:` 는 로딩된 ActionType 을 pointing.
  - 모든 `check_logic.reference` 는 `policies/` 아래 실제 파일로 resolve.
- 신규 Day-1 cross-check:
  - `trigger_kind = rule_violation | both` → 적어도 하나의 shipped 룰이
    reference, 그렇지 않으면 로더는 "dangling remediation-only ActionType"
    warning 로그 (fatal 아님 - fork 가 나중에 enable MAY).
  - `trigger_kind = operator_request | both` → `argument_schema` 는
    non-empty MUST. 누락된 스키마는 fatal load error.
  - `ceiling_by_tier.t2.max_autonomy` 는 카탈로그에서 `shadow_only` MUST
    (로더 강제, 아니면 fatal). T2 는 ceiling 모듈 내부에서도
    shadow-only 로 hard-cap (`_TIER_HARD_CAP`) 되므로 stray YAML 값은 어차피
    runtime 에 cap 됨; 로드 시 reject 하는 것은 저자 의도를 정직하게 유지.
    T2 상향은 hard cap 을 lift 하는 operator-authored **Rego overlay**
    (`policies/action_types/`) 이지 YAML ceiling 이 아님 - 로드 시 Rego
    text 의 brittle name-scan 을 피함.
  - `live_probe_ref` -> 참조된 probe 는 `rule-catalog/probes/` 아래 (또는
    fork-only path 아래) 존재 MUST. 누락된 probe 는 fatal. Upstream probe catalog는
    VM traffic, storage access, load-balancer health, blast-radius descriptor를 ship하며
    `ops.restart-service`와 `ops.scale-in`은 `vm_traffic_last_5m`을 bind합니다.
  - `x-fdai-redact: true` 로 flag 된 모든 `argument_schema` property 는
    leaf `string`/`number` MUST; 로더가 redaction path set 을 수집해 audit
    redactor 에 전달해 값이 verbatim landing 안 함 (§5.2). 알 수 없는
    `x-fdai-*` extension key 는 fatal load error (오타 guard, 오철자
    redact 힌트가 secret 을 silently leak 못 하게).
- 카탈로그 엔트리 정책 (fatal, `load_action_type_catalog` 에서만): Day-1
  backfill (§10) 을 위해 JSON Schema 가 optional 로 남긴 안전-핵심 field 는
  실제 카탈로그 엔트리에 존재 MUST. 누락된 field 는 permissive default 를
  silently 상속하는 게 아니라 fatal load error:
  - `category`, `trigger_kind`, `execution_path`, `blast_radius` 는
    선언 MUST.
  - `ceiling_by_tier` 는 세 tier (`t0`, `t1`, `t2`) 모두 선언 MUST.
  - `argument_schema` 는 존재 시 `type: object` 와
    `additionalProperties: false` 설정 MUST - 콘솔이 명시되지 않은 argument
    를 절대 전달 못 하도록.
  - `operation: drop` 또는 `operation: purge` (둘 다 데이터/스키마 파괴) 는
    `DataPlaneMutating` interface 선언 MUST - risk gate 가 data-plane HIL
    gate 를 적용하도록. 누락 시 risk 분류가 silently 하향됨.
  - separator 나 case 만 다른 두 ActionType name (`ops.restart-service` vs
    `ops.restart_service`) 은 typo-squatting hazard 로 reject: file-overlay
    layer 가 exact name 으로 매칭하므로 near-miss 가 silently phantom
    custom ActionType 가 됨.
  - 모든 `trigger_kind.restrict_to_scenarios` entry 는 non-empty scenario
    id MUST.
- Risk-table fail-close (`load_risk_table`): `risk-classification.yaml` 의
  단일 `default` rule 은 `auto` MUST NOT. 매칭 안 된 event 는 safety 쪽으로
  fail (`hil` 또는 `deny`) - 이것이 `env_scope: any` ActionType 가 prod
  처리를 table 에 defer 해도 안전한 이유 (§2). `hil-prod` rule 과 이
  non-auto default 이 함께 prod event 가 ActionType 의 `prod_downgrade`
  누락 때문에 auto-execute 되는 일을 막음.
  이 gate 는 실제 카탈로그 root (upstream + `action-types-custom/`) 에서만
  동작; `load_action_type_from_mapping` 은 permissive 하게 유지되어 unit-test
  model fixture 는 pydantic-required field 만 있으면 됨. `blast_radius` 없이
  RiskGate 에 도달한 ActionType (테스트나 fork adapter 의 hand-built model
  에서만 가능) 은 static-blast axis 를 `enforce_auto` 가 아니라 `enforce_hil`
  로 cap - 알 수 없는 impact surface 는 fail closed.

## 9. 감사 계약

매 액션 dispatch (룰-발화든 오퍼레이터-발화든) 는 ActionType metadata 를
attach 한 audit entry 를 write:

```json
{
  "action_kind": "action.dispatch",
  "action_type_id": "ops.restart-service",
  "category": "ops",
  "trigger_kind": "operator_request",
  "side_effect_class": "execute",
  "principal": {...},
  "arguments": {...},
  "arguments_redacted": [...],
  "resolved_ceiling": { "...": "execution-model.md 8 의 전체 6-axis + risk_table 블록" },
  "risk_decision": "hil",
  "quorum": 1,
  "mode": "enforce",
  "execution_path": "direct_api",
  "started_at": "...",
  ...
}
```

`resolved_ceiling` 블록은 risk-classification 표 + 6 axis 가 결정에 도달한
방식의 readable proof; 그 정확한 shape (risk_table axis 와 quorum 포함) 은
[execution-model.md § 8](execution-model-ko.md#8-resolved_ceiling-audit-블록)
에서 권위적. 향후 overlay 변경은 dispatch 시점에 in effect 였던 ceiling 이
verbatim 기록되므로 과거 audit entry 를 절대 break 하지 않음.

## 10. Migration 기록

온톨로지 변경은 세 reviewed catalog-as-code 단계로 landing했습니다
([rule-governance.md](../rules-and-detection/rule-governance-ko.md) 참조):

1. **스키마 확장** - 로더가 신규 field를 safe default로 학습.
2. **Backfill** - `trigger_kind = rule_violation` 이 모든 기존 entry 에
   set; `ceiling_by_tier` 는 pre-existing implicit ceiling (`default_mode`,
   `promotion_gate.max_policy_escapes`) 로부터 populate.
3. **Ops 카탈로그** - shipped ops.* 집합 (§3.2) 이 `argument_schema`,
   `direct_api` path, appropriate ceiling 과 함께 landing.

세 단계는 완료되었습니다. 현재 catalog entry는 loader가 검증하며 operator proposal은
정상 ControlLoop로 다시 진입합니다.

## 11. Testability

- **스키마** - 매 YAML 로드에서 JSON Schema 검증 (기존).
- **Overlay 우선순위** - 모든 축 + layer 조합에 대한 table-driven test
  (§7.5).
- **Argument 스키마** - property test: 스키마 밖의 어느 입력이든 dispatch
  전 reject; redact 된 field 는 audit payload 에 절대 등장 안 함.
- **Live-probe hook** - fake `LiveBlastProbe` 가 `quiet / active /
  overloaded` 각각 반환; ceiling adjustment table-driven.
- **Rego overlay** - 금요일에 downgrade 하는 정책을 exercise 하는 통합
  test; time frozen; audit entry 가 overlay layer 를 name 함을 assert.
- **Cross-check 로드 error** - `operator_request` 에 `argument_schema`
  누락한 fixture ActionType 가 특정 error 로 로드 실패.

## 12. 설계 경계와 라이프사이클

온톨로지 shape 에 대한 반복 질문에 명시적으로 답해, 리뷰어가 의도된
경계를 gap 으로 오인하지 않도록.

- **세 orthogonal 분류 축은 redundant 하지 않음** (#12). `category`
  (어떤 종류의 변경), `trigger_kind` (누가 initiate), `side_effect_class`
  (콘솔 tool 이 무엇을 함) 은 서로 다른 질문에 답하고 audit entry 에 함께
  기록됨 (§4.3). 하나의 변경이 다른 것을 함의하지 않음.
- **두 autonomy source 는 conflict 가 아니라 strictest-wins 로 compose**
  (#15). risk-classification table (Axis A) 과 `ceiling_by_tier`
  (Axis C) 둘 다 autonomy 를 bound; RiskGate 는 6축 + table 에 대해 `min`
  을 취하므로 어느 쪽도 다른 쪽 위로 raise 못 함. hand-tuned
  `ceiling_by_tier` 가 무시되는 것처럼 보이면 table 이 더 strict 한 rule 을
  match 한 것 - audit `resolved_ceiling.winning_axis` 가 어느 쪽이
  이겼는지 name (§9), 그래서 상호작용은 항상 inspectable, silent 아님.
- **`argument_schema` 버전 관리** (#20). `argument_schema` 의 backward-
  incompatible 변경 (field 제거, type tightening) 은 ActionType `version`
  (semver major) bump MUST. Audit entry 는 argument 를 받은 그대로 기록하니
  replay 는 dispatch 시점에 유효했던 version 으로 읽음; 로더는 과거 argument
  blob 을 새 스키마로 재해석 안 함.
- **ActionType 은퇴** (#21). ActionType 은퇴는 governance PR 로 (a) 그것을
  `remediates:` 하는 모든 룰을 제거하거나 shadow-only 로 pin 한 뒤 (안 그러면
  `remediates:` cross-check 가 로드 실패), (b) ActionType YAML 을 제거. 로더의
  dangling `remediates:` 체크가 룰이 아직 참조하는 동안 ActionType 제거를
  막으므로, 은퇴가 dangling ref 를 남길 수 없음.
- **자기수정 governance 는 bounded** (#24). `governance.*` ActionType
  (promote, retire, override-ceiling) 은 safety envelope 자체를 바꾸므로
  가장 strict 한 default 를 carry: `pr_native` 실행 (reviewed diff),
  `default_mode: shadow`, distinct approver (self-approval 없음 - promotion
  PR 을 author 한 actor 는 절대 그 approver 아님). `governance.override-ceiling`
  은 downgrade-only 이고 time-boxed. Envelope 는 이 경로로 *narrow* 될 수
  있어도 reviewed, quorum-approved PR 없이 *widen* 될 수 없음.
- **Blast traversal depth 는 tunable 한 safe default** (#28).
  `graph_derived` blast radius 는 `contains` + `depends_on` 를
  `traversal_depth` (default 2, max 5) 까지 walk. depth-2 walk 는 depth 2
  초과 transitive chain 을 under-count; `RequiresInventoryFresh` interface
  와 `graph_fresh_within_seconds` precondition 이 stale graph data 로 act
  하는 것을 막고, `max_affected_resources` 초과 instance 는 HIL 로 escalate.
  deep dependency graph 를 다루는 fork 는 ActionType 별로 `traversal_depth`
  를 raise.

### 12.1 Consumer 구현 상태 (declared vs. live)

Ontology 는 의도적으로 runtime 이 오늘 consume 하는 것보다 많이 declare
한다. 이는 숨겨진 gap 이 아니라 명시적 boundary 다: ActionType 은
dispatcher 가 landing 하기 전에 catalog-as-code 로 존재할 수 있고, 그때까지
**구조적으로 inert** 하다. 아래 safety property 는 어떤 consumer 가 live
인지와 무관하게 성립하므로, declare 됐지만 아직 dispatch 되지 않는
ActionType 은 act 할 수 없다.

- **Inert-by-default 는 assume 이 아니라 enforce 된다** (#5, #8, #9).
  shipped `ops.*` 와 `governance.*` ActionType 은 모두
  `default_mode: shadow` 로 ship 된다
  (`test_every_shipped_action_type_defaults_to_shadow` 로 검증). live
  dispatcher 가 없는 declare 된 ActionType 은 judge-and-log 만; 절대
  mutate 하지 않음. enforce 로의 promotion 은 별도 gated governance PR.
- **`rule_violation` (remediation) 이 live path.** T0Engine ->
  ActionBuilder -> RiskGate -> Executor loop (§4.1) 이 오늘 remediation
  ActionType 을 dispatch 한다. 이것이 primary autonomy surface 이며 완전히
  wired 됨.
- **`operator_request` -> typed proposal dispatch는 live** (#6, #7).
  Optional `/chat/action` route와 Bragi proposal sink는 등록된 operator command를
  `ActionProposal`로 변환하고 server-derived RBAC를 강제한 뒤 canonical ingress topic에
  publish합니다. Executor를 직접 호출하지 않습니다. Catalog loader가 `argument_schema`를
  검증하며 각 live command surface는 bounded server-owned argument shape만 받습니다.
- **`governance.*` dispatcher 3 개는 P2 backlog** (#8). `governance.
  override-ceiling` 만 live dispatcher
  (`core/risk_gate/override_writer.py`) 를 가짐; `promote-action-type`,
  `retire-rule`, runtime `grant-exemption` writer 는 P2 PR-native writer
  와 함께 landing. 그때까지 YAML entry 는 inert catalog data
  (shadow-default, dispatcher 없음 = side effect 없음).
- **`live_probe_ref`는 selected ops action에서 live** (#9).
  `ops.restart-service`와 `ops.scale-in`은 shipped `vm_traffic_last_5m` probe를
  bind합니다. Probe가 없는 action은 static blast bound를 사용하며 참조된 probe가
  없으면 catalog load가 실패합니다.
- **Agent 는 ontology 를 read 하지, 그 위에서 free-form reason 하지 않음**
  (#10, #11). autonomy decision 은 procedural: RiskGate 가 ActionType
  field (`ceiling_by_tier`, `blast_radius`, `irreversible`, `operation`,
  `interfaces`) 를 deterministic 하게 read. ObjectType / LinkType
  declaration 은 검증되고 codegen 및 `graph_derived` blast 에 쓰이는
  inventory graph 를 구동하지만, pantheon 이 reason 하는 free-form
  knowledge graph 는 아님. 이는 design 상 의도 - determinism-first 가
  safety core 를 inspectable 하게 유지. 미래의 graph-reasoning consumer 는
  additive 이고 어떤 ceiling 도 바꾸지 않음.

## 13. 관련 문서

- [execution-model.md](execution-model-ko.md) - 이 온톨로지를 소비;
  RiskGate + Executor + live-probe combinator.
- [operator-console.md](../interfaces/operator-console-ko.md) - operator-request
  트리거 surface; tool 스키마는 `argument_schema`.
- [rule-governance.md](../rules-and-detection/rule-governance-ko.md) - ActionType promotion,
  retirement, override 가 catalog PR 파이프라인을 통해 flow 하는 방식.
- [phase-1-rule-catalog-t0.md](../phases/phase-1-rule-catalog-t0-ko.md) -
  원본 ActionType 도입과 rule → ActionType dispatch.
- [security-and-identity.md](../architecture/security-and-identity-ko.md) - 모든 액션이
  상속하는 safety invariant 와 identity 계약.
