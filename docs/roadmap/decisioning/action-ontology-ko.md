---
title: Action 온톨로지
translation_of: action-ontology.md
translation_source_sha: 462aaf3c821f34f795c8917cf5b476b5396a099d
translation_revised: 2026-08-12
---

# 액션 온톨로지

FDAI 의 모든 액션 - 룰이 발화시킨 교정 이든 오퍼레이터가 요청한 ops 작업 든 - 는 shipped 온톨로지의 **`ActionType`** 항목 하나의 인스턴스 이다. 이 문서는 스키마, 트리거 축 (`rule_violation` vs `operator_request`), 계층 및 역할 상한, live-probe 참조, 그리고 `core/` 편집 없이 고객이 재정의 가능하게 하는 **fork-override 경계** 을 권위적으로 정의한다.

이 온톨로지의 소비자:

- T0Engine + ActionBuilder ([phase-1](../phases/phase-1-rule-catalog-t0-ko.md))
  는 룰이 발화시킨 액션을 빌드할 때 `rollback_contract`, `preconditions`, `stop_conditions`, `blast_radius` 를 읽기.
- 통합 RiskGate + 실행기 ([execution-model.md](execution-model-ko.md))
  는 실행 **여부** 와 **방법** 을 결정할 때 계층 상한, min-role, live-probe 참조, 실행 경로 를 읽기.
- 오퍼레이터 콘솔 서술기 ([operator-console.md](../interfaces/operator-console-ko.md))
  는 ops-flavoured 도구 호출 을 제안하거나 실행할 때 `trigger_kind`, `description`, `argument_schema` 를 읽기.

단일 온톨로지가 세 곳 모두를 피드 하기 때문에, 새 교정 또는 새 ops 동사 추가는 YAML 파일 하나 - 엔진에 branching 없음, 새 실행기 없음.

> 고객-무관: 아래의 모든 ActionType 이름, 파라미터, blast-radius 값은 자리 표시자 또는 예시. 포크 가 구성 로 항목 추가/재정의
> ([generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md)).

## 1. 하나의 온톨로지, 두 트리거

초기 ActionType 집합은 룰이 발화시킨 교정만 포함했습니다. 현재 카탈로그는 같은 스키마 아래
교정, ops, 거버넌스, 도구 항목을 포함합니다. 오퍼레이터 콘솔 pull-방향 ([operator-console.md](../interfaces/operator-console-ko.md) §4) 는 룰
발화가 아니라 **오퍼레이터의 채팅 요청** 으로 트리거되는 액션이 필요:
"이 pod 재시작", "규모 out", "캐시 플러시". 이들은 같은 안전성 묶음
를 공유하지만 다른 트리거 표면 를 가진다.

온토로지는 둘 다 **하나의 스키마 + 하나의 축** 으로 처리. `trigger_kind`
은 `kind` 필드가 세 허용 값 중 하나를 취하는 오브젝트:

```yaml
trigger_kind:
  kind: rule_violation | operator_request | both
  # rule_violation   - T0/T1/T2 엔진이 룰 매치 -> 자동 proposal
  # operator_request - 콘솔의 사람 -> 명시적 ops
  # both             - 어느 경로든 사용 가능한 동일 ActionType
```

- **`rule_violation`** - ControlLoop 이 매치된 룰 + 발견 사항 로부터 액션을
  construct. 트리거는 T0/T1/T2 판정.
- **`operator_request`** - 오퍼레이터-콘솔 서술기 가 이 ActionType 을
  대상으로 하는 tool_call 을 발행. 트리거는 콘솔 세션 + principal +
  arguments.
- **`both`** - 일부 액션은 두 표면 모두에 속함. 예: `ops.restart-service`
  는 오퍼레이터가 트리거 ("재시작 this") 하거나 룰이 트리거 (health-probe
  fail 룰) MAY. 온톨로지 항목 는 합집합을 declare; 런타임 이 경로 선택.

이 축을 제외하고 스키마의 어느 것도 trigger-specific 이 아니다; 실행기,
RiskGate, 감사 계약은 둘 다 동일.

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

# --- 의미 계획 계약 (레거시 디코딩에서는 선택 사항) --------------------
semantic:
  target:
    type_ref:                            # 정확한 ObjectType 또는 InterfaceType 선언
      kind: object | interface
      name: Workload
      version: 1.0.0
      declaration_digest: sha256:<hex>
    cardinality: one | set
  parameters:                            # 각 항목은 inline_schema 또는 schema_ref 사용
    - name: replicas
      required: true
      inline_schema: {type: integer, minimum: 1, maximum: 100}
      redaction: audit_safe | redact
  read_sets:                             # 범위가 제한된 query FunctionType 참조
    - function_ref: {kind: function, name: query.workloads,
                     version: 1.0.0, declaration_digest: sha256:<hex>}
      properties: [replicas]
      max_objects: 100
  submission_criteria:
    - criterion_ref: capacity-within-policy
    - function_ref: {kind: function, name: validate.capacity,
                     version: 1.0.0, declaration_digest: sha256:<hex>}
  planner_ref: {kind: function, name: plan.scale,
                version: 1.0.0, declaration_digest: sha256:<hex>}
  effects:
    - effect_id: scale-command
      kind: provider_command
      operation_ref: provider.scale
      rollback_operation_ref: provider.scale.rollback
      grants_authority: false
  postconditions:
    - postcondition_id: replicas-converged
      kind: property
      observation_ref: property.replicas
      evidence_required: true
      grants_authority: false
  transaction_policy:
    mode: atomic | saga
    lock_scope: target | target_set
    max_affected_objects: 100

# --- Provenance (기존) ---------------------------------------------------
provenance:
  source_url: string
  resolved_ref: string                   # git sha / registry version
  content_hash: string                   # sha256
  license: string
  retrieved_at: RFC3339
```

shipped ObjectType, LinkType, ActionType은 모두 이 출처 이력 블록을 운반합니다. `content_hash`는
Pydantic-normalized 선언에서 `provenance`를 제외하고 정본 JSON으로 인코딩한 값의 `sha256:<hex>`입니다.
카탈로그 로더가 이를 다시 계산하고 mismatch 시 시작을 차단하므로 변경이 stale 근거를 유지할 수 없습니다.
`resolved_ref`는 authored 선언 버전을, `source_url`은 검토 가능한 출처를 식별합니다.

Precondition 매개 변수는 자유 형식 레이블이 아니라 타입이 지정된 참조입니다. 카탈로그 부하 시 `link_exists`와
`link_absent`의 `link_type`은 업스트림 및 포크 LinkType을 합친 레지스트리에서 확인하며 알 수 없는 이름은 시작을 차단합니다.
각 종류는 정의된 매개 변수만 사용하며, 필수 매개 변수가 없거나 관련 없는 매개 변수가 있으면 risk 게이트 전에 차단됩니다.

런타임 `Action` 기록은 `threshold`, `window_seconds`, `seconds`, `count`를 포함한 전체 ordered `stop_conditions` 목록을 보존합니다.
호환성 shorthand인 `stop_condition`은 첫 구조화된 조건의 `kind`와 같아야 합니다. 액션 JSON 스키마는 비어 있지 않은 구조화된 목록을 요구하며
direct-API 및 tool-call 요청과 감사 항목은 같은 목록을 flatten하지 않고 전달합니다.

작업 흐름에서 시작된 런타임 `Action`은 정확한 `process_id`, `step_id`, 전달 `proposal_ref`를
포함하는 `workflow_action`도 전달할 수 있습니다. 이 계보는 ActionType 인자가 아니라
액션 메타데이터이므로 strict `argument_schema` 검증은 그대로 유지됩니다. 제안 참조는
전달만 입증하며 프로세스가 진행하려면 독립적인 결과 증적이 필요합니다.

`semantic` 블록은 선택 사항이므로 보존된 v1 YAML과 감사 고정본을 변경 없이 디코딩할 수
있습니다. 블록이 있으면 완전하고 범위가 제한되어야 합니다. ActionType 내부 참조는
`OntologyDeclarationRef`를 사용합니다. 이 참조는 선언 종류, 이름, 버전, 선언 다이제스트를
고정하면서 포함하는 release 다이제스트를 재귀적으로 넣지 않습니다. 이후 순수
`compile_action_mutation_plan` 함수는 모든 참조가 활성 `OntologyRelease`의 정확한 멤버인지
확인합니다. 읽기 집합은 `query` 함수, 제출 및 함수 postcondition은 `validate` 함수,
플래너는 `plan` 함수를 사용해야 합니다.

컴파일은 변경할 수 없는한 제안 전용 `MutationPlan` 버전 2만 반환합니다. 컴파일러는 계획
신원을 만들기 전에 다음을 확인합니다.

- 정본 인자에는 모든 필수 매개변수가 있어야 하고 undeclared 매개변수가 없어야
  하며 각 inline JSON 스키마를 통과해야 합니다. 계획은 전체 정본 인자 객체의 다이제스트와
  supplied 매개변수별 연결을 저장합니다. `audit_safe` 연결은 정본 JSON만 보존하고,
  `redact` 연결은 값 다이제스트와 고정 `<redacted>` 변환 결과만 보존하며 raw 값은 저장하지
  않습니다.
- 선언된 읽기 집합마다 내용 기반 주소를 가진 증적 하나가 있어야 하고 제출 criterion마다
  내용 기반 주소를 가진 `CriterionResult` 하나가 있어야 합니다. 컴파일러는 누락, 중복, undeclared,
  불완전한, 잘린, future-observed, stale 또는 다이제스트 mismatch 증적을 차단합니다. Criterion은
  계획을 제안하기 전에 통과해야 합니다.
- Forward 효과는 선언된 `effect_id`와 선택된 대상 id의 정확한 Cartesian 집합과 일치해야 합니다.
  예상 효과는 정확한 `postcondition_id` 집합 및 해당 속성, 관측 또는 함수
  참조와 일치해야 합니다. 프로바이더 명령에는 `command_ref`가 필요하며 forward와 롤백
  명령 참조는 선언된 연산 참조와 같아야 합니다.
- Reversible 액션은 모든 forward 효과에 `rollback_operation_ref`를 선언하고 롤백 효과가
  모든 `(effect_id, target_id)` 쌍을 포함해야 합니다. Irreversible 액션은 계획에 표시되며,
  복구 연산이 선언되지 않은 효과에 가짜 롤백을 만들지 않습니다.
- 계획은 트랜잭션 모드, 잠금 범위, 정렬된 결정론적 대상 잠금 키, 선언된 최대 affected
  객체 수를 결합합니다. Set-cardinality 대상에는 `target_set` 잠금이 필요합니다.

컴파일러는 선택된 ObjectType 또는 컴파일된 InterfaceType 대상과 정확한 대상 개정 번호도
검증합니다. 기존 버전 2 계획을 받으면 제안을 다시 빌드하고 다이제스트와 내용을 비교한 뒤 같은
계획을 반환합니다. 보존된 버전 1 `MutationPlan` 페이로드는 버전 2 신원 필드 없이도 계속
decode되지만 의미 compilation은 항상 버전 2를 생성합니다. 컴파일러는 RiskGate, 에이전트,
실행기 또는 프로바이더를 호출하지 않으며 효과와 postcondition은 권한을 선언할 수 없습니다.

카탈로그 backfill은 다음 상태로 완료되었습니다:

- `trigger_kind.kind = rule_violation`
- `category = remediation`
- `ceiling_by_tier` 는 현 암묵적 기본값 로 채워짐 (T0 → medium/high 심각도 는
  `enforce_hil`, low 는 `enforce_auto`; T1/T2 → `shadow_only`)
- 스키마-깨는 이름 변경 없음; 로더는 누락된 신규 필드 를 가장 safe 한 값으로
  취급.

## 3. Category 카탈로그

네 최상위 category. 신규 category 는 doc PR과
[architecture.instructions.md](../../../.github/instructions/architecture.instructions.md)의 short-form 항목이 필요.

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

기본 `execution_path: pr_native` (GitOps). 포크 는 API 변경이 하나의 멱등적 호출 인 액션 별로 `direct_api` 로 재정의 MAY.

### 3.2 `ops.*`

오퍼레이터 요청 런타임 액션. Day 1 shipping:

- `ops.restart-service` - AKS pod 재시작, App Service 재시작, Container App 개정 번호 재시작.
- `ops.scale-out` - 복제본 / 인스턴스 개수 증가. 지출-증가이므로 `cost_impact_monthly` 를 선언 MUST ->
  risk-classification 비용 게이트 적용 ([execution-model.md § 2.8](execution-model-ko.md#28-비용-증가-ops-액션)).
- `ops.scale-in` - 복제본 개수 감소 (Approver + 실제 운영 탐색).
- `ops.flush-cache` - Redis / CDN 캐시 플러시.
- `ops.drain-connection` - 부하 balancer 백엔드 의 연결 배출.
- `ops.rotate-cert` - TLS cert 회전 (App 게이트웨이 / Front Door).
- `ops.failover-primary` - 복제 리소스에서 장애 조치 트리거. 더 큰 계층 로
  장애 조치 시 `cost_impact_monthly` 선언 MUST.
- `ops.switch-t2-proposer-route` - Heimdall이 요청 내 모든 후보의 실패를 확인한 뒤 T2 제안자 역할 하나를 검증된 보조 경로로 전환합니다.
  Shadow-first를 유지하고 사람 승인을 요구하며 전환 후 검증이 실패하면 이전 경로를 복원합니다.
- `ops.apply-human-access` - 검토된 FDAI 역할 그룹 멤버 자격 부여를 계획합니다. Direct 어댑터는
  별도 승격 전까지 관찰 모드를 유지합니다.
- `ops.revoke-human-access` - 검토된 대체 담당 범위 케이스가 준비될 때까지 역할 그룹 멤버 자격
  제거를 보류합니다.
- `ops.publish-change-summary` - resource-group 에 대해 정해진 시간
  범위의 변경 이력을 rendered Markdown 요약으로 만들어 전달 어댑터 에
  전달. Non-Resource 비즈니스-오브젝트 흐름 의 참조 예제; 짝을 이루는
  ObjectType `ChangeSummary` 와 LinkType `summarizes` 가 copy-ready
  scaffold ([downstream-fork-example-vertical-ko.md](../fork-and-sequencing/downstream-fork-example-vertical-ko.md)
  참조).
- `ops.start-vm` / `ops.deallocate-vm` - 개발 operations 게이트웨이를 통해 Azure VM 하나를
  시작하거나 deallocate합니다. 둘 다 shadow-first를 유지하며 shipped T0 상한에서 사람 승인을
  요구합니다.
- `ops.upsert-network-rule` / `ops.delete-network-rule` - 개발 operations 게이트웨이를 통해
  범위가 제한된 NSG 룰 하나를 생성, 교체 또는 삭제합니다. 삭제는 Owner-tier 승인이 필요하며 복구는
  별도로 통제된 state-forward 액션입니다.

**버티컬 매핑.** 각 ops ActionType 은 소유 버티컬 로 태깅되어
[verticals](../../../services/core-control-plane/src/fdai/core/verticals) 가 점유 하고 버티컬 룰이
`remediates:` 할 수 있음: `ops.failover-primary` 와 `ops.restart-service`
-> 복원력; `ops.scale-in` / `ops.scale-out` -> 비용 거버넌스;
`ops.drain-connection` / `ops.rotate-cert` -> 변경 안전성.
`ops.flush-cache` 와 `ops.publish-change-summary` 는 cross-vertical
(오퍼레이터-트리거). VM 및 network-rule 게이트웨이 연산은 업스트림 운영자 액션을 위한 Azure
전달 연결이며 버티컬 소유권을 변경하지 않습니다.

기본 `execution_path: direct_api` (ops 는 latency-sensitive; PR overhead
는 목적을 defeat). 포크 는 모든 런타임 변경 가 reviewable 차이 로
landing 해야 하는 compliance-heavy 환경에서 `pr_manual` 을 강제 MAY.

### 3.3 `governance.*`

온톨로지 / 카탈로그 / 예외 / 승격 변경. 현재 온톨로지에 5개 항목이 있으며
**3개는 실제 운영 dispatcher를 보유합니다**. 나머지 2개는 PR-native writer를 기다리는
catalog-as-code 산출물입니다.

- `governance.promote-action-type` - 하나의 ActionType에 대한 exact 영속
  operational-promotion 증적을 런타임 모드 레지스트리에 적용합니다. 카탈로그의 ActionType은
  변경하지 않으며 증적은 `promotion_gate`, exact 코드/카탈로그 개정 번호, 시나리오 집합,
  근거 다이제스트 및 Owner HIL로 제한됩니다.
  **디스패처 shipped:** Thor 뒤의 `OperationalPromotionDirectApiExecutor`. Shadow는 변경
  없이 검증하며 HIL-only 권한 초기화만 강제 적용 모드를 제공합니다.
- `governance.promote-effect-model` - 하나의 exact reviewed `GraphEffectModel` 승격 또는
  rollback receipt를 적용해 active pointer만 원자적으로 변경합니다. Owner HIL, exact receipt와
  slot digest, fresh graph, idempotency, audit 및 scripted rollback을 모두 요구합니다.
  **디스패처 shipped:** Thor 뒤의 assurance-twin graph model promotion provider입니다.
- `governance.retire-rule` - 강제 적용 집합에서 룰 제거 (shadow-only 또는
  full retire).
  **디스패처: not yet implemented (P2 적체).**
- `governance.grant-exemption` - time-boxed 예외 생성
  ([rule-governance.md](../rules-and-detection/rule-governance-ko.md)). 기존 예외는
  `rule-catalog/exemptions/` 아래 JSON 으로 authored 되어 risk 게이트 가
  `ExemptionRegistry` 를 통해 소비; 런타임 **create-a-new-exemption**
  운영자 흐름 는 동일한 P2 PR-native 쓰기 담당 와 함께 land.
- `governance.override-ceiling` - 특정 리소스 / tag 스코프에 대한 계층
  상한 의 operator-측 재정의 (포크 확장).
  **디스패처 shipped**:
  [`services/core-control-plane/src/fdai/core/risk_gate/override_writer.py`](../../../services/core-control-plane/src/fdai/core/risk_gate/override_writer.py).

거버넌스 액션은 catalog-as-code 변경이므로 `execution_path: pr_native`를 사용하고 검토된
차이로 landing해야 하며 닫힌 예외는 2개입니다. `governance.promote-action-type`은 영속 런타임
모드 레지스트리만 변경하고 `governance.promote-effect-model`은 reviewed graph-model active
pointer만 변경합니다. 둘 다 Owner HIL과 exact-receipt 검증 이후에만 `direct_api`를 사용하며
카탈로그 데이터나 managed 기반을 변경하지 않습니다. 다른 거버넌스 액션은 이 예외를 사용할 수 없습니다.

### 3.4 `tool.*`

기반 를 mutate 하지 않고 등록된 함수 (도구) 를 invoke. LLM 이 도구 을
호출하는 방식의 온톨로지-네이티브 대응물: 실행기 가
[`ToolExecutor`](../../../services/core-control-plane/src/fdai/shared/providers/tool.py) 프로토콜
(`ToolCallShadowExecutor`) 을 통해, **아티팩트** 또는 side 효과 (문서,
메시지, 티켓) 를 생산하는 등록된 함수로 전달. Shipped 예시:

- `tool.generate-pdf` - 리포트 템플릿으로부터 PDF 문서 (복원력 요약,
  비용 보고, 변경 감사) 렌더. Rollback 은 `state_forward_only` (생산된
  아티팩트 삭제).
  **디스패처: shadow-only** (`RecordingToolExecutor` Day-1 연결; 포크 가
  실제 운영 어댑터 연결).
- `tool.run-python-on-vm` - 검증된 내용 기반 주소를 가진 Python 산출물 를
  인벤토리 에서 선택한 Linux VM 하나에 단계 하고 `VmTaskRunner` 프로바이더 로
  실행합니다. 작업 는 `gpu`, `network`, 파일 시스템 접근, child-process 생성 같은
  호스트 기능 를 선언합니다. 대상 은 필요한 모든 기능 를 제공해야
  합니다. 액션 은 출처 텍스트 또는 arbitrary 셸 명령 가 아니라 산출물
  참조 만 받습니다. Shadow 모드 는 계획 을 만들고, 강제 적용 모드 는 Owner HIL
  이후 Azure Managed Run Command 를 사용합니다. 변경할 수 없는 파일 은 설정된 non-root
  계정 가 범위가 제한된 시간 초과 으로 entrypoint 를 실행하기 전에 게스트 에서 SHA-256
  으로 다시 검증됩니다.

기본 `execution_path: tool_call`. `core/` 는 프로토콜 만 안다; 포크 가
조립 루트 에서 실제 운영 어댑터 (네이티브 Python 레지스트리, MCP 클라이언트,
HTTP callout) 를 연결 - 레지스트리 는 MCP 어댑터의 자연스러운 첨부 지점 로,
MCP 서버 도구 하나를 `tool.*` ActionType 하나에 매핑한다. `tool.*` ActionType
은 측정 가능한 `promotion_gate` 를 가진 shadow-first 이고 임의의 변경
ActionType 과 동일한 7개 안전조건을 carry 하므로, 워크플로 스텝이
`action_type_ref` 로 참조하며 이를 상속 MAY.
[execution-model-ko.md § 5.6](execution-model-ko.md#56-tool-call-tool_call) 참조.

`tool.*` ActionType 은 `ceiling_by_tier` 를 declare SHOULD. reversible,
resource-scoped, control-plane, low-cost 인 도구 은 risk-classification
테이블의 `auto-low-risk` 행에 매칭되므로, **상한 이 없으면 강제 적용 승격 후
`auto` 로 분류될 수 있다** - 멱등적 리포트 렌더엔 괜찮지만 알림/티켓 도구
엔 잘못된 것이다. 상한 은 테이블과 무관하게 자율성 를 `enforce_hil` 로
캡한다; shipped `tool.generate-pdf` 는 이 이유로 `t0.max_autonomy: enforce_hil`
을 설정한다.

## 4. 트리거 표면

### 4.1 `rule_violation` (동작 변경 없음)

```
Event → EventIngest → TrustRouter → T0/T1/T2 → Finding →
  ActionBuilder(finding, rule, action_type) → Action → RiskGate → Executor
```

- 룰은 `remediates: <action_type_id>` (기존 필드) 로 ActionType 을
  declare.
- `ActionBuilder` 는 룰의 `parameters` 블록으로부터 액션 의 `params`
  populate.
- 트리거 표면 는 이벤트 버스.

### 4.2 `operator_request` (신규)

```
Chat turn → Narrator → tool_call(action_type_id, args) →
  Coordinator argument_schema 대비 args validate →
  RiskGate → Executor
```

- 오퍼레이터는 서술기 가 tool_call 로 translate 한 자연어 턴 을
  통해 ActionType pick.
- ActionType 의 `argument_schema` (JSON 스키마) 는 조정기 경계에서
  args 를 validate ([operator-console.md § 5.2](../interfaces/operator-console-runtime-model-ko.md#52-consoletool)) -
  콘솔은 잘못된 형태의 액션을 실행기 에 절대 전달 안 함.
- 트리거 표면 는 오퍼레이터-콘솔 세션.

Note: 두 표면 는 RiskGate 에서 만남 (execution-model.md §3).
ActionType 은 자신의 호출 을 어느 트리거가 생성했는지 모름 - 오직
`trigger_kind` scoping (§1) 만 제약.

### 4.3 세 분류 축 (관계)

액션을 설명하는 세 직교 라벨; 동의어가 아니다:

| 축 | 소유 doc | 값 | 답 |
|------|-----------|------|------|
| `category` | 이 doc (§3) | 교정 / ops / 거버넌스 | *어떤 종류의 변경* |
| `trigger_kind` | 이 doc (§1) | rule_violation / operator_request / both | *누가 시작* |
| `side_effect_class` | [operator-console.md § 3.4](../interfaces/operator-console-ko.md#34-tool-discovery-계약) | 읽기 / simulate / approve / execute / breakglass | *콘솔 도구 이 뭐를 함* |

전형적 조합: `remediation` ActionType 은 `trigger_kind=rule_violation`
이고 콘솔 도구 로 표면 될 때 그 도구 은 `side_effect_class=execute`;
`ops` ActionType 은 보통 `trigger_kind=both` 에 `execute` 도구; `governance`
ActionType 은 `trigger_kind=operator_request` 이고 도구 은 `approve` 또는
`execute`. 감사 항목 (§9) 가 세 것 모두 carry 하여 어느 축으로든 구획 가능.

### 4.4 실행 인가 vs 온톨로지 속성 ACL

온톨로지 **속성 읽기** 는 두 독립 차원 - `access_scope` (역할 순위)
AND `purpose_binding` (purpose-set 교집합) - 으로 게이트 됨. 읽기 는 아니면
single-gate 연산이고 data-minimization 이 두 번째 축을 필요로 하기 때문
([`shared/ontology/acl.py`](../../../services/core-control-plane/src/fdai/shared/ontology/acl.py)).

ActionType **실행** 은 의도적으로 `purpose_binding` 을 carry 하지
않음; 그 인가는 `ceiling_by_tier.min_role` 에 더해 full 6-축 RiskGate
상한 (risk 표, 계층 상한, static 영향, 실제 운영 영향, 역할, env),
정족수, HIL 게이트, shadow-first 승격. 따라서 실행 은 읽기 보다
더 적은 게 아니라 더 많은 차원으로 게이트 됨 - 비대칭은 누락된 게이트 가
아니라 의도된 것. Purpose-scoped 실행 (오퍼레이터가 용도 X 에
한해서만 이 액션 실행 가능) 은 future 범위; `ceiling_by_tier` 에
`min_purpose` 축과 전달 principal 에 용도 를 추가하는 것이고,
현재 risk 모델엔 불필요 (비평 #30).

## 5. 인자 스키마 (`operator_request` 만)

룰-발화 ActionType 은 params 를 룰의 `parameters` 블록에서 받음; 오퍼레이터
-요청 ActionType 은 params 를 오퍼레이터의 tool_call arguments 에서 받고
`argument_schema` JSON 스키마 를 declare MUST → 콘솔이:

1. `list_tools()` 에서 기계가 읽는 형태 로 도구 렌더.
2. 액션 호출 전 조정기 경계에서 arguments validate
   ([operator-console.md § 5.2](../interfaces/operator-console-runtime-model-ko.md#52-consoletool)).
3. 감사-write 경계에서 민감한 필드 (`x-fdai-redact: true` mark)
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

### 5.2 민감정보 제거 힌트

민감정보 제거 은 **denylist 가 아니라 허용 목록**: 모든 free-text 문자열
속성 (`enum`, `pattern`, `const`, `format` 제약 없는 `string`) 는 두
힌트 중 정확히 하나를 선언 MUST - 시크릿 이나 PII 를 carry MAY 하는 필드
가 verbatim 저장으로 절대 기본값 되지 않도록:

- `x-fdai-redact: true` - redactor 가 감사 쓰기 전 값을 strip. leaf
  `string`/`number` 속성 에만 유효.
- `x-fdai-audit-safe: true` - 저자가 값이 저장 안전하다고 assert (리소스
  참조, justification, 지역 이름 등).

힌트 둘 다 없는 free-text 문자열 은 fatal 부하 오류. 속성 는 둘 다
설정 MUST NOT. 이 둘 외 `x-fdai-*` 키 는 fatal typo 가드 - 오철자
`x-fdai-redcat` 가 시크릿 을 silently redact 실패 못 하게. 제약된 문자열
(enum/pattern/format) 과 non-string 타입 은 힌트 불필요.

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

로더는 모든 `x-fdai-redact` 경로 를 집합 으로 수집해
`argument_schema_redaction_paths(action_type)` 로 노출; 감사 redactor 가
`operator_request` 인자 블롭 을 추가 전용 로그에 저장하기 전 그 경로
들을 strip.

## 6. 실제 운영 영향 탐색 (execution-model.md §6, 월 1+)

Static `blast_radius` 만으로는 coarse - 같은 "삭제 저장소 계정"
변경 이 dead 리소스에서는 사소하지만 실제 운영 리소스에서는 catastrophic.
월 1 은 ActionType 에 **`live_probe_ref`** 필드 를 추가하므로 RiskGate
가 결정 전에 탐색 를 consult 가능.

```yaml
live_probe_ref: probes/vm_traffic_last_5m
```

- 탐색 는 [`rule-catalog/probes/`](../../../rule-catalog/probes) 아래
  YAML 로 declare - 탐색 id 당 하나의 파일.
- 각 탐색 는 입력 (대상 리소스 참조), 조회 (Azure Monitor KQL /
  메트릭 API / ARG), interpretation 함수 (`quiet | active | overloaded`)
  를 declare.
- `RiskGate` 는 탐색 를 호출하고 답변 를 static 상한 과 결합 (see
  [execution-model.md § 4](execution-model-ko.md#4-live-blast-probe)).

탐색 는 ActionType 및 환경 별로 명시적 선택. 포크 가 자체 탐색 를 ship;
업스트림 카탈로그는 small starter 집합 을 ship (VM 트래픽, 저장소
접근 로그, load-balancer 백엔드 상태).

## 7. 포크 재정의 경계

위의 모든 것은 데이터. 포크 는 `core/` 또는 업스트림 YAML 을 편집하지
않고 어느 축이든 재정의 MUST 가능해야 함. 온톨로지는 네 재정의 채널을
노출한다.

### 7.1 파일 기반 오버레이

- 업스트림 은 `rule-catalog/action-types/<name>.yaml` ship.
- 포크 는 `rule-catalog/action-types-overrides/<name>.yaml` 을 재정의
  할 필드 의 strict subset 으로 배치.
- 로더는 시작 시 업스트림 + overrides 를 **key-by-key 우선순위**
  로 병합 (overrides 승리); 누락된 overrides 필드 는 업스트림 으로
  대체 경로. `name` 이 매칭되는 업스트림 ActionType 이 없는 오버레이 는
  fatal 부하 오류 - 오버레이 계층은 기존 ActionType 을 *tighten* 만
  하며 새로 도입할 수는 없음. **새** ActionType 을 추가하는 포크 는
  `rule-catalog/action-types-custom/` 아래에 ship 하고 그 루트 를
  concat 한다 (7.6 참조).
- 매 병합 는 감사 항목
  (`action_kind=catalog.load.action_type_overlay`) 를 쓰기 → 승격된
  재정의 는 traceable.

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

### 7.2 Policy-as-code 오버레이

- `policies/action_types/` 아래 Rego 정책이 per-invocation 재정의 를
  compute MAY, 예: "금요일 오후에 모든 enforce_auto 를 enforce_hil 로
  downgrade" (변경 freeze).
- RiskGate 는 파일 오버레이 후 정책 evaluate - 둘 다 같은 축에 대해
  something 을 express 하면 Rego 승리.

### 7.3 Config-driven 오버레이

- Coarse 전환 (feature-flag 스타일) 를 위한 env-var 토글:
  `FDAI_OVERRIDE_ACTION_TYPE_<id>_MAX_AUTONOMY=shadow_only`.
- **Downgrade-only**: 값은 `shadow_only` 또는 `enforce_hil` MUST, 절대
  `enforce_auto` 아님 - 구성 토글 은 자율성 를 낮추기만 할 수 있고
  절대 올릴 수 없음 (모든 오버레이 와 동일한 never-raise 규칙).
- **항상 감사됨**: 구성 재정의 적용은 env-var 이름과 resolved 값을
  담은 감사 항목 (`action_kind=catalog.override.config`) 를 쓰기하므로
  emergency downgrade 가 절대 silent 하지 않음.
- Rare; Rego re-deploy 가 너무 느린 emergency downgrade 를 위해 문서화.

### 7.4 런타임 재정의 (채팅)

- 오퍼레이터 콘솔의 Approver / Owner 가 범위가 제한된 범위
  (`resource_group=X, until=YYYY-MM-DDT..Z`) 로
  `governance.override-ceiling` 호출 MAY. 이는 `pr_native` 로 (감사됨)
  `policies/action_types/` 아래 Rego 정책 조각 를 쓰기.
- Time-boxed; 자동 만료는 기존 exemption 작업 흐름 와 함께 ship
  ([rule-governance.md](../rules-and-detection/rule-governance-ko.md)).

### 7.5 우선순위

여러 오버레이 가 같은 축에 대해 speak 하면 우선순위는:

1. Config-driven 재정의 (env var, §7.3) - emergency break-glass, 가장
   specific 하고 가장 urgent; downgrade-only 이고 항상 감사됨.
2. 런타임 재정의 (Rego 조각, chat-authored, time-boxed) - 가장
   specific 한 steady-state, 가장 recent.
3. Rego 정책 (`policies/action_types/`) - operator-authored steady 상태.
4. 파일 오버레이 (`rule-catalog/action-types-overrides/`) - 포크
   compile-time.
5. 업스트림 YAML (`rule-catalog/action-types/`) - 저장소 기본값.

모든 계층 는 downgrade-only (자율성 절대 안 올림) 이므로 우선순위는
*어느* downgrade 가 이기는지를 정할 뿐, 자율성 가 올라가는지는 결코
아님. RiskGate 는 그 순서로 해석 하고 winning 오버레이 계층 를 감사
항목 에 기록.

### 7.6 새 ActionType 추가 (별도 루트)

위 네 채널은 shipped ActionType 을 *수정*만 함. **새** ActionType 추가는
재정의 가 아니며 7.5 우선순위 체인에 참여하지 않는다. 포크 는 새
ActionType 을 `rule-catalog/action-types-custom/` 아래에 ship 하고
(업스트림 은 `.yaml.example` 템플릿을 제외하면 이 디렉토리를 비워둠) 두
번째 카탈로그 루트 로 로드해 업스트림 카탈로그 와 concat 한다:

```python
action_types = (
    load_action_type_catalog(Path("rule-catalog/action-types"), ...)
    + load_action_type_catalog(Path("fork/action-types-custom"), ...)
)
```

두 루트 간 중복 `name` 은 fatal 부하 오류 이므로 추가가 업스트림
ActionType 을 조용히 shadow 할 수 없다 (shadowing 은 7.1 오버레이 계층의
역할). [../../rule-catalog/action-types-custom/README.md](../../../rule-catalog/action-types-custom/README.md)
참조.

## 8. 로더 + 검증

- 로더 ([`rule_catalog/schema/action_type.py`](../../../services/core-control-plane/src/fdai/rule_catalog/schema/action_type.py))
  는 시작 시 업스트림 + overrides + Rego 참조 를 부하.
- 교차 검증 (기존 shipping):
  - 모든 룰의 `remediates:` 는 로딩된 ActionType 을 pointing.
  - 모든 `check_logic.reference` 는 `policies/` 아래 실제 파일로 해석.
- 신규 Day-1 교차 검증:
  - `trigger_kind = rule_violation | both` → 적어도 하나의 shipped 룰이
    참조, 그렇지 않으면 로더는 "dangling remediation-only ActionType"
    경고 로그 (fatal 아님 - 포크 가 나중에 활성화 MAY).
  - `trigger_kind = operator_request | both` → `argument_schema` 는
    비어 있지 않은 MUST. 누락된 스키마는 fatal 부하 오류.
  - `ceiling_by_tier.t2.max_autonomy` 는 카탈로그에서 `shadow_only` MUST
    (로더 강제, 아니면 fatal). T2 는 상한 모듈 내부에서도
    shadow-only 로 hard-cap (`_TIER_HARD_CAP`) 되므로 stray YAML 값은 어차피
    런타임 에 상한 됨; 로드 시 거부 하는 것은 저자 의도를 정직하게 유지.
    T2 상향은 hard 상한 을 lift 하는 operator-authored **Rego 오버레이**
    (`policies/action_types/`) 이지 YAML 상한 이 아님 - 로드 시 Rego
    텍스트 의 brittle name-scan 을 피함.
  - `live_probe_ref` -> 참조된 탐색 는 `rule-catalog/probes/` 아래 (또는
    fork-only 경로 아래) 존재 MUST. 누락된 탐색 는 fatal. 업스트림 탐색 카탈로그는
    VM 트래픽, 저장소 접근, load-balancer 상태, blast-radius 서술자를 ship하며
    `ops.restart-service`와 `ops.scale-in`은 `vm_traffic_last_5m`을 연결합니다.
  - `x-fdai-redact: true` 로 플래그 된 모든 `argument_schema` 속성 는
    leaf `string`/`number` MUST; 로더가 민감정보 제거 경로 집합 을 수집해 감사
    redactor 에 전달해 값이 verbatim landing 안 함 (§5.2). 알 수 없는
    `x-fdai-*` 확장 키 는 fatal 부하 오류 (오타 가드, 오철자
    redact 힌트가 시크릿 을 silently leak 못 하게).
- 카탈로그 엔트리 정책 (fatal, `load_action_type_catalog` 에서만): Day-1
  backfill (§10) 을 위해 JSON 스키마 가 선택적 로 남긴 안전-핵심 필드 는
  실제 카탈로그 엔트리에 존재 MUST. 누락된 필드 는 permissive 기본값 를
  silently 상속하는 게 아니라 fatal 부하 오류:
  - `category`, `trigger_kind`, `execution_path`, `blast_radius` 는
    선언 MUST.
  - `ceiling_by_tier` 는 세 계층 (`t0`, `t1`, `t2`) 모두 선언 MUST.
  - `argument_schema` 는 존재 시 `type: object` 와
    `additionalProperties: false` 설정 MUST - 콘솔이 명시되지 않은 인자
    를 절대 전달 못 하도록.
  - `operation: drop` 또는 `operation: purge` (둘 다 데이터/스키마 파괴) 는
    `DataPlaneMutating` 인터페이스 선언 MUST - risk 게이트 가 data-plane HIL
    게이트 를 적용하도록. 누락 시 risk 분류가 silently 하향됨.
  - 구분자 나 사례 만 다른 두 ActionType 이름 (`ops.restart-service` vs
    `ops.restart_service`) 은 typo-squatting hazard 로 거부: file-overlay
    계층 가 exact 이름 으로 매칭하므로 near-miss 가 silently phantom
    custom ActionType 가 됨.
  - 모든 `trigger_kind.restrict_to_scenarios` 항목 는 비어 있지 않은 시나리오
    id MUST.
- Risk-table fail-close (`load_risk_table`): `risk-classification.yaml` 의
  단일 `default` 룰 은 `auto` MUST NOT. 매칭 안 된 이벤트 는 안전성 쪽으로
  fail (`hil` 또는 `deny`) - 이것이 `env_scope: any` ActionType 가 prod
  처리를 표 에 defer 해도 안전한 이유 (§2). `hil-prod` 룰 과 이
  non-auto 기본값 이 함께 prod 이벤트 가 ActionType 의 `prod_downgrade`
  누락 때문에 auto-execute 되는 일을 막음.
  이 게이트 는 실제 카탈로그 루트 (업스트림 + `action-types-custom/`) 에서만
  동작; `load_action_type_from_mapping` 은 permissive 하게 유지되어 unit-test
  모델 고정본 는 pydantic-required 필드 만 있으면 됨. `blast_radius` 없이
  RiskGate 에 도달한 ActionType (테스트나 포크 어댑터 의 hand-built 모델
  에서만 가능) 은 static-blast 축 를 `enforce_auto` 가 아니라 `enforce_hil`
  로 상한 - 알 수 없는 영향 표면 는 실패 시 차단.

## 9. 감사 계약

매 액션 전달 (룰-발화든 오퍼레이터-발화든) 는 ActionType 메타데이터 를
첨부 한 감사 항목 를 쓰기:

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

`resolved_ceiling` 블록은 risk-classification 표 + 6 축 가 결정에 도달한
방식의 readable 증명; 그 정확한 형태 (risk_table 축 와 정족수 포함) 은
[execution-model.md § 8](execution-model-ko.md#8-resolved_ceiling-audit-블록)
에서 권위적. 향후 오버레이 변경은 전달 시점에 in 효과 였던 상한 이
verbatim 기록되므로 과거 감사 항목 를 절대 break 하지 않음.

## 10. 이행 기록

온톨로지 변경은 세 검토된 catalog-as-code 단계로 landing했습니다
([rule-governance.md](../rules-and-detection/rule-governance-ko.md) 참조):

1. **스키마 확장** - 로더가 신규 필드를 safe 기본값으로 학습.
2. **Backfill** - `trigger_kind = rule_violation` 이 모든 기존 항목 에
   집합; `ceiling_by_tier` 는 pre-existing 암묵적 상한 (`default_mode`,
   `promotion_gate.max_policy_escapes`) 로부터 populate.
3. **Ops 카탈로그** - shipped ops.* 집합 (§3.2) 이 `argument_schema`,
   `direct_api` 경로, appropriate 상한 과 함께 landing.

세 단계는 완료되었습니다. 현재 카탈로그 항목은 로더가 검증하며 운영자 제안은
정상 ControlLoop로 다시 진입합니다.

## 11. Testability

- **스키마** - 매 YAML 로드에서 JSON 스키마 검증 (기존).
- **오버레이 우선순위** - 모든 축 + 계층 조합에 대한 table-driven 테스트
  (§7.5).
- **인자 스키마** - 속성 테스트: 스키마 밖의 어느 입력이든 전달
  전 거부; redact 된 필드 는 감사 페이로드 에 절대 등장 안 함.
- **Live-probe 훅** - 가짜 `LiveBlastProbe` 가 `quiet / 활성 /
  overloaded` 각각 반환; 상한 adjustment table-driven.
- **Rego 오버레이** - 금요일에 downgrade 하는 정책을 exercise 하는 통합
  테스트; 시간 고정된; 감사 항목 가 오버레이 계층 를 이름 함을 assert.
- **교차 검증 로드 오류** - `operator_request` 에 `argument_schema`
  누락한 고정본 ActionType 가 특정 오류 로 로드 실패.
- **의미 컴파일러** - 집중 테스트가 레거시 ActionType 및 `MutationPlan` decode를 유지하고,
  exact 참조를 수락하며, stale 참조를 차단하고, 정본 및 민감정보가 제거된 인자를 검증하며, 완료하고
  fresh한 내용 기반 주소를 가진 읽기 및 criterion 증적을 요구합니다. 또한 일대일 효과 및
  postcondition 연결을 강제하고, reversible 및 irreversible 복구 의미 규칙을 보존하며,
  결정론적 target-set 잠금과 트랜잭션 한도를 결합하고, `plan` 플래너를 요구하고, 기존
  계획 다이제스트와 개정 번호를 검증하며, 효과와 postcondition이 권한을 부여할 수 없음을
  입증합니다.

## 12. 설계 경계와 라이프사이클

설계 경계, 라이프사이클 규칙, 소비자 구현 상태는
[액션 온톨로지 라이프사이클](action-ontology-lifecycle-ko.md)에서 확인하세요.

## 13. 관련 문서

- [execution-model.md](execution-model-ko.md) - 이 온톨로지를 소비;
  RiskGate + 실행기 + live-probe combinator.
- [operator-console.md](../interfaces/operator-console-ko.md) - operator-request
  트리거 표면; 도구 스키마는 `argument_schema`.
- [rule-governance.md](../rules-and-detection/rule-governance-ko.md) - ActionType 승격,
  retirement, 재정의 가 카탈로그 PR 파이프라인을 통해 흐름 하는 방식.
- [phase-1-rule-catalog-t0.md](../phases/phase-1-rule-catalog-t0-ko.md) -
  원본 ActionType 도입과 룰 → ActionType 전달.
- [security-and-identity.md](../architecture/security-and-identity-ko.md) - 모든 액션이
  상속하는 안전성 불변식 와 신원 계약.
