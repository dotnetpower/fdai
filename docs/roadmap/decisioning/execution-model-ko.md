---
title: Execution 모델
translation_of: execution-model.md
translation_source_sha: 9561c6975e046977c4e85253a8127e033a7721df
translation_revised: 2026-07-21
---

# Execution 모델

FDAI 이 액션 실행 **여부** 와 **방법** 을 결정하는 방식. 이 문서는
통합 RiskGate, 권위적 [risk-classification.md](risk-classification-ko.md)
first-match 표가 **6-axis** ActionType ceiling 과 결합하는 방식, 4개의
executor 경로 (PR-native / direct API / PR-manual / tool call), live-blast probe
combinator, 그리고 live 변경이 만족해야 하는 safety invariant 를
권위적으로 정의한다.

> 결정-엔진 관계 (권위적): FDAI 은 **하나의** 결정을 가지며, 그것은
> **두** 입력을 결합해 생성된다. [risk-classification.md](risk-classification-ko.md)
> first-match 표가 **권위적 baseline** - finding feature vector
> (`policy_violation`, `destructive`, `irreversible`, `data_plane_touched`,
> `cost_impact_monthly`, `verifier_confidence`, `blast_radius`,
> `environment`) 를 소비해 `auto | hil | deny` 와 `quorum` 을 반환. 이
> 문서의 6-axis ceiling 은 ActionType + 런타임 컨텍스트 (tier, ActionType
> ceiling, static/live blast, role, env) 를 소비해 dispatch 별 ceiling 을
> 반환. RiskGate 는 둘의 **minimum** 을 반환; 어느 쪽도 상대보다 autonomy
> 를 raise 못 함. 표는 매트릭스로 대체되지 않음 - 매트릭스는 그 위에
> layer 된, 절대 raise 안 하는 추가 제약이다.

이 모델의 소비자:

- ControlLoop 과 오퍼레이터-콘솔 coordinator 는 액션 dispatch 전에
  RiskGate 에 ask.
- 각 executor 경로는 액션의 ActionType 이 선언한 safety envelope 를 구현
  ([action-ontology.md](action-ontology-ko.md)).
- 오퍼레이터 콘솔은 `resolved_ceiling` 을 surface → 오퍼레이터가 시스템
  이 auto / HIL / deny 를 결정한 이유를 정확히 볼 수 있음.

> 고객-무관: 아래의 모든 ceiling default, probe expression, role assignment
> 는 placeholder. Fork 는
> [action-ontology.md § 7](action-ontology-ko.md#7-fork-override-seam)
> 에 문서화된 override seam 으로 tune.

> **구현 상태 (2026-07-21):** Authority, risk table, kill switch, HIL resume, 4개 path,
> probe catalog, typed operator proposal은 구현됐습니다. Azure Monitor probe I/O는 deployment binding입니다.

## 1. 여기서 "execute" 의 의미

이 문서 이전까지, FDAI 이 하는 모든 것은 **shadow** 였음 - judge
하고 log, mutate 절대 안 함. Execute 는 모든 gate 통과 후 executor 가
mutation surface (git PR merge, Azure ARM API, scripted rollback runner)
를 실제로 호출하는 것. Shadow mode 는 모든 신규 액션의 기본으로 여전히
유지; execution 은 promoted state, per-action, measured evidence 로
gated, 매 dispatch 에서 re-check.

4개의 실행 경로 (§5)가 있으며 venue lifecycle은 Thor 뒤에 유지됩니다([backend 설계](../interfaces/execution-backends-ko.md)).

- **PR-native** - 변경이 merge policy 가 auto-accept 하는 git PR 로
  landing (또는 사람이 accept). 감사 + rollback 은 git 으로부터.
- **Direct API** - executor 가 substrate API 를 직접 호출 (Azure ARM,
  kubectl, Redis). 감사는 audit log 에, rollback 은 ActionType 의
  `rollback_contract` 에.
- **PR-manual** - 변경이 `hil` label 을 carry 하는 PR 로 landing; auto-
  merge 없음, approver 가 accept MUST. 자동화된 검증이 부족한 high-risk
  액션에 사용.
- **Tool call** - 새 executor bypass 없이 `ToolExecutor` contract를 통해 등록된
  capability-bounded 함수를 호출.

단일 ActionType이 path를 선언하고 fork는 ontology overlay로 override합니다. Backend는 path나 role을
추가하지 않으며 risk, Var approval, lock, Vidar rollback, Saga audit은 외부에 남고 profile은 낮출 수만 있습니다.

## 2. 6-axis ceiling + risk-classification 표

RiskGate 는 **6개 직교 ceiling axis** 와 권위적 risk-classification 표를
하나의 결정으로 collapse. 각 axis 와 표는 독립적으로 autonomy 를 낮춤;
최종 결정은 각 입력이 permit 하는 것의 **minimum**. 여기서 어느 것도
autonomy 를 raise 하지 않음 - upgrade 는 promotion 파이프라인
([phase-2-quality-and-t1.md § Promotion](../phases/phase-2-quality-and-t1-ko.md#promotion-shadow--enforce))
을 통해, dispatch time 의 RiskGate 가 아님.

```
authority = min(
  A_risk_table    # risk-classification.md first-match 표 (권위적 baseline; quorum 도 산출)
  A_tier          # T0 | T1 | T2
  A_ceiling       # ActionType.ceiling_by_tier[tier]
  A_static_blast  # ActionType.blast_radius (선언됨)
  A_live_blast    # live probe -> quiet | active | overloaded (Month 1+)
  A_role          # min_role vs principal role (RBAC)
  A_env           # prod -> ActionType.prod_downgrade 별 downgrade
)
```

각 입력은 다음 중 하나 반환:

- `enforce_auto` - HIL 없이 실행 허용.
- `enforce_hil` - 실행 허용하되 사람 승인 필수.
- `shadow_only` - judge 하고 log; mutation 없음.
- `deny` - 진행 안 함; 결정은 hard stop.

최종 RiskGate 출력은 winning minimum, risk-classification 표로부터의
`quorum` (기본 1; irreversible 은 2,
[risk-classification.md](risk-classification-ko.md) 참조), 그리고 audit
consumer 가 reasoning 을 render 할 수 있도록 각 입력의 기여를 name 하는
`resolved_ceiling` breakdown (§8) 을 carry 하는 **`RiskDecision`**.

### 2.0 Axis A - Risk-classification 표 (권위적 baseline)

`A_risk_table` 은 [risk-classification.md](risk-classification-ko.md) 의
first-match 표를 finding feature vector 에 대해 평가한 결과. 이 axis 는
다음 신호가 평가되는 **유일한** 곳 - 6개 ceiling axis 는 의도적으로
이들을 재도출하지 않음:

- `policy_violation` (verifier 판정) -> `deny`.
- `destructive` (`operation in {delete, drop, purge, detach}`) -> `hil`.
- `irreversible` (`ActionType.irreversible == true`) -> `quorum: 2` 인
  `hil`.
- `data_plane_touched` (`interfaces include DataPlaneMutating`) -> `hil`.
- `cost_impact_monthly >= $100` -> `hil` (Cost Governance vertical gate;
  이것이 `ops.scale-out` 과 모든 비용-증가 액션이 cost threshold 를
  clear 하지 않고는 `auto` 갈 수 없는 이유 - §2.8 참조).
- `verifier_confidence < 0.85` (T2 quality-gate 신호) -> `hil`.
- `blast_radius` 와 `environment` 도 여기서 평가되며 그 두 신호의 권위적
  출처 (6-axis static/live blast 와 env axis 는 오직 *추가로* 낮출 뿐,
  절대 모순되지 않음).

`A_risk_table` 은 표의 `decision` 을 4 level 에 매핑해 반환 (`deny ->
deny`, `hil -> enforce_hil`, `auto -> enforce_auto`) 하고 매치된 룰 id +
`catalog_version` 을 audit entry 에 carry.

### 2.1 Axis B - Tier

Trust router 로부터.

| Tier | 기본 posture |
|------|-----------------|
| T0 (deterministic) | `enforce_auto` 허용 - T0 판정은 policy-as-code pass |
| T1 (lightweight similarity) | Upstream catalog ceiling은 보수적이며 overlay는 autonomy를 낮출 수만 있습니다. Authority 상향은 별도 governed promotion path를 사용하며 dispatch-time override가 아닙니다. |
| T2 (frontier reasoning) | Catalog loader가 T2를 `shadow_only`로 hard-cap합니다. Hard cap 변경은 reviewed upstream policy change이며 fork overlay가 아닙니다. |

### 2.2 Axis C - ActionType ceiling

ActionType 의 `ceiling_by_tier` 로부터
([action-ontology.md § 2](action-ontology-ko.md#2-스키마)).

### 2.3 Axis D - Static blast radius

ActionType 의 `blast_radius` 블록. 두 계산 mode:

- `static_enum` - `resource | resource_group | subscription` 중 하나
  ([risk-classification.md](risk-classification-ko.md) 와 공유하는
  CSP-neutral bucket vocabulary). Bucket 이 넓을수록 이 axis 는 낮은 값
  반환:
  - `resource` -> 자체적으로 autonomy 를 낮추지 않음.
  - `resource_group` -> `enforce_hil` 에 cap.
  - `subscription` -> `deny` (어떤 자율 변경도 전체 subscription 에
    걸치지 않음; risk-classification deny 룰과 일치).
- `graph_derived` - dispatch time 에 inventory 그래프로부터 computed.
  `max_affected_resources` 초과 값은 다른 axis 와 관계없이 `enforce_hil`
  에 cap.

### 2.4 Axis E - Live blast probe (Month 1+)

`ActionType.live_probe_ref` 가 probe 를 name. Probe 는 세 level 중
하나 반환 (§4). Mapping:

| Probe 결과 | Ceiling 에 대한 효과 |
|--------------|-------------------|
| `quiet` | 변경 없음 - static ceiling 승리 |
| `active` | `enforce_hil` 에 cap (사람 approve) |
| `overloaded` | `shadow_only` 에 cap (defer; 지금은 너무 risky) |

`live_probe_ref` 가 unset 이면 axis 는 "no opinion" 반환 - 자체적으로
autonomy 를 낮추지 않음.

### 2.5 Axis F - Role (RBAC)

`ActionType.ceiling_by_tier[tier].min_role` vs 호출 principal 의
resolved role ([user-rbac-and-identity.md](../interfaces/user-rbac-and-identity-ko.md)
로부터):

- Principal 이 통상 ladder (`reader < contributor < approver < owner`)
  에서 `min_role` 이상 -> axis 가 tier default 반환.
- Principal 이 `min_role` 미달 -> axis 가 `deny` 반환.
- **BreakGlass 는 off-ladder 이며 최상위 rung 이 아님.** BreakGlass 는
  Owner 안에 nested 되지 *않은* 별도 Entra 그룹
  ([user-rbac-and-identity.md § 2](../interfaces/user-rbac-and-identity-ko.md#2-롤-모델-4-tier--break-glass)).
  활성이고 time-box 된 BreakGlass grant 는 caller 가 원래 under-
  privileged 여서 approve 못 했을 HIL item 을 *approve 할 자격* 을 얻게
  하지만, `enforce_auto` 를 절대 반환 안 함 - BreakGlass-eligible caller
  에 대해 axis 는 `enforce_hil` 에 cap. BreakGlass 는 승인 자격을 raise
  하지, 자동화를 raise 하지 않는다.

룰-발화 액션의 경우 "principal" 은 executor identity (시스템 MI); 그
role 은 composition time 에 fixed
([composition.py](../../../src/fdai/composition/__init__.py)).

### 2.6 Axis G - Environment (prod downgrade)

`ActionType.prod_downgrade.detection_ref` 가 env-detector 를 name. "prod"
의 정의를 둘로 만들지 않기 위해, detector reference 는
[risk-classification.md § Environment Detection](risk-classification-ko.md#environment-detection)
에 정의된 **동일** env classifier (resource-group `environment` tag; 누락/
미인식 tag -> `prod`, fail-safe) 로 resolve. Detector 가 target 리소스에
대해 "prod" 반환 시, axis 는 `prod_downgrade.mode` (전형적으로
`enforce_hil` 또는 `shadow_only`) 에 cap.

`prod_downgrade` 블록 누락은 **`env_scope: non_prod` 를 선언하는 dev-only
ActionType 에 대해서만** axis 를 비활성화; 명시적 `env_scope` 없는
ActionType 은 risk-classification env 신호 (Axis A) 를 inherit 하므로,
누락된 블록이 prod auto-execution 으로 silently fail open 될 수 없음.

### 2.6a Fail-safe axis - System health (degradation)

일곱 번째 axis 인 `system_health` 는 **control plane 이 DEGRADED 일 때만**
존재함 - 하나 이상의 critical dependency (audit store, event bus,
substrate) 의 circuit breaker 가 trip 된 상태. autonomy 를 `shadow_only`
로 cap 하므로, 실패한 dependency 가 enforce-mode mutation 을 절대 driving
할 수 없음 (시스템 범위의 "fail toward safety",
[csp-neutrality.md](../architecture/csp-neutrality.md) 참고). 이 axis 는
[`DegradationController.autonomy_permitted()`](../../../src/fdai/shared/resilience/degradation.py)
가 `evaluate_execution_authority` 의 `system_degraded` 입력을 통해 공급함;
시스템이 healthy 하면 axis 는 생략되고 결정은 byte-identical 한 six-axis
결과와 동일함.

### 2.6b Fail-safe axis - Kill-switch (operator emergency stop)

여덟 번째 axis 인 `kill_switch` 는 **operator 가 global kill-switch 를
engage 했을 때만** 존재함 - 모든 auto-execution 을 즉시 halt 하는 의도적
비상 조치 (RBAC `TRIGGER_KILL_SWITCH`). `system_health` 처럼 autonomy 를
`shadow_only` 로 cap 하므로 halt 중에는 어떤 action 도 mutate 하지 않음
(HIL 로 human path 는 유지). 이 axis 는
[`KillSwitch.is_engaged()`](../../../src/fdai/shared/resilience/kill_switch.py)
가 `evaluate_execution_authority` 의 `kill_switch_engaged` 입력을 통해
공급함; kill-switch 는 executor identity 없이 operable 함 (fork 가 그 상태를
state store 에 backing) -
[security-and-identity.md](../architecture/security-and-identity.md) 참고.
disengage 상태면 axis 는 생략됨 (byte-identical 결과).

### 2.7 결합

각 입력은 위 4 level 중 하나 반환; RiskGate 는 순서
`enforce_auto > enforce_hil > shadow_only > deny` 에서 **minimum** 을
취함 (six axis 와 optional `system_health`, `kill_switch` fail-safe axis
전체 대상). 어느 입력 (risk-classification 표 포함) 의 `deny` 든 hard stop;
executor 는 절대 호출 안 됨. `enforce_hil` 에 동반되는 `quorum` 은 표
quorum 과 axis-선언 quorum 의 최대값.

### 2.8 비용-증가 ops 액션

지출을 늘리는 `ops.*` 액션 (`ops.scale-out`, 더 큰 tier 로의
`ops.failover-primary`) 은 Axis A (risk-classification 표) 가
`>= $100 -> hil` gate 를 적용할 수 있도록 ActionType 에
`cost_impact_monthly` 추정을 선언 MUST. Unknown 이거나 threshold 초과
비용 추정을 가진 `ops.scale-out` 은 절대 `auto` 아님; 이는 `direct_api`
fast path 를 통해 우회될 수 있는 런타임 ops 에 대해 Cost Governance
vertical 을 권위적으로 유지. Cost Governance vertical
([verticals](../../../src/fdai/core/verticals)) 이 추정 함수를 소유;
ActionType 은 그것을 참조만 함.

## 3. 통합 RiskGate

RiskGate 는
[`src/fdai/core/risk_gate/`](../../../src/fdai/core/risk_gate)
에 살고 **두** trigger surface (룰-발화와 오퍼레이터-요청; see
[action-ontology.md § 4](action-ontology-ko.md#4-트리거-surface))
의 단일 결정 지점.

> 구현 상태: 순수 combinator 는
> [`ceiling.py`](../../../src/fdai/core/risk_gate/ceiling.py) (6축),
> [`risk_table.py`](../../../src/fdai/core/risk_gate/risk_table.py)
> (Axis A first-match 표 + `rule-catalog/risk-classification.yaml`),
> [`feature.py`](../../../src/fdai/core/risk_gate/feature.py)
> (`FeatureVector` 추출기) 로 ship 되고,
> [`authority.py`](../../../src/fdai/core/risk_gate/authority.py)
> `evaluate_execution_authority()` 가 end-to-end 로 통합. 이 함수가 단일
> 파이프라인 `feature -> table (Axis A) -> 6축 min() -> ExecutionAuthorityDecision`.
> [`ControlLoop`](../../../src/fdai/core/control_loop/orchestrator.py) 이 두 모드로
> 호출한다. risk table 만 배선된 경우 실행 액션당 `risk_gate.shadow_authority`
> audit 엔트리 1개를 기록 (authority 전용, judge+log, executor 경로 무변경).
> risk table 과 기존
> [`gate.py`](../../../src/fdai/core/risk_gate/gate.py) `RiskGate` 가
> 모두 배선된 경우, gate (런타임 Action 안전: exemption / precondition /
> promotion) 와 authority (정책 ceiling) 를
> [`evaluator.py`](../../../src/fdai/core/risk_gate/evaluator.py)
> `combine()` 이 단일 `UnifiedRiskDecision` 으로 결합하고 (canonical-level
> `min()`, 두 evaluator 무변경), 루프가 그 위에서 **라우팅**한다: `deny` 나
> `hil` 결정은 executor 를 건너뛰고 (전체 outcome `DENIED` / `HIL`, PR 미발행),
> `auto` 만 실행으로 진행. 라우팅된 각 액션은 `risk_gate.unified` audit
> 엔트리 1개를 기록.

계약:

```python
class RiskGate(Protocol):
    def evaluate(
        self,
        *,
        action_type: OntologyActionType,
        action: Action,
        trigger_kind: TriggerKind,
        tier: TrustTier,
        principal: Principal,
        env: EnvClassification,
        risk_table_result: RiskTableResult,   # Axis A, 사전 계산 (§2.0)
        live_probe_result: ProbeResult | None, # Axis E, 사전 fetch (§4)
        promotion_state: ActionModeRecord,
    ) -> RiskDecision: ...

@dataclass(frozen=True)
class RiskDecision:
    decision: Literal["auto", "hil", "abstain", "deny"]
    mode: Literal["shadow", "enforce"]
    quorum: int                            # Axis A 로부터; 기본 1, irreversible 은 2
    matched_rule_id: str                   # risk-classification 룰 id (또는 "default")
    catalog_version: str                   # 결정 시점 risk-classification.yaml 버전
    execution_path: ExecutionPath          # ActionType 로부터 inherit, lower 강제 MAY
    resolved_ceiling: ResolvedCeiling      # audit-friendly breakdown (§8)
    hil_queue_id: str | None               # decision == "hil" 시 populated
```

- **RiskGate 는 pure, 동기 함수로 유지.** 모든 I/O (live probe,
  `graph_derived` blast 의 inventory 그래프 walk) 는 `evaluate` **이전**에
  수행되어 `live_probe_result` / 사전-resolve 된 blast 로 전달됨. 이는
  결정론성 (§7) 을 보존하고, `evaluate` 를
  [coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md#safety)
  의 async seam 목록 밖에 두며, 기존 동기
  [`RiskGate.evaluate`](../../../src/fdai/core/risk_gate/gate.py) 와 일치.
  Probe 사전-fetch 는 이미 async 인 ControlLoop / coordinator 에서 수행.
- **Compatibility boundary.** Runtime safety gate는 typed
  `RiskDecision(outcome: RiskDecisionOutcome, ...)`를 유지하고 authority evaluator는
  `ExecutionAuthorityDecision`을 생성합니다. `evaluator.py`가 둘을
  `UnifiedRiskDecision`으로 결합하며 caller는 원본 dataclass의 staged field migration이
  아니라 이 combined contract를 사용합니다.
- `promotion_state` 는 기존
  [`ActionPromotionRegistry`](../../../src/fdai/core/risk_gate/gate.py)
  로부터 read - shadow-mode ActionType 은 axis 가 permit 하는 것과 관계
  없이 `mode` 를 `shadow` 로 clamp.
- `execution_path` 는 ActionType 기본이나 axis (전형적으로 role 또는
  env axis) 가 downgrade 강제 시 (예: compliance-heavy fork 가 prod 의
  모든 direct-API ActionType 에 `pr_manual` 강제).
- RiskGate 는 **dispatch attempt 당 한 번** 호출. Retry 의 re-check 는
  fresh dispatch (fresh audit entry).

### 3.1 오퍼레이터-콘솔 verifier 와의 상호작용

콘솔의 coordinator 는 매 write-class tool call 에서 RiskGate 를 재실행
([operator-console.md § 7.2](../interfaces/operator-console-ko.md#72-chat-특화-3-invariant),
invariant 5). 콘솔은 이 경로를 절대 우회하지 않음; "trusted narrator
shortcut" 없음.

### 3.2 `ActionPromotionRegistry` 와의 상호작용

Promotion 은 RiskGate 와 직교:

- `ActionPromotionRegistry.mode_of(action_type)` 는 ActionType 이
  enforce-eligible 인지 결정.
- RiskGate 는 그것을 upper bound 로 취하고 6 axis 와 결합. 승격된
  ActionType 이 여전히 axis 에 의해 `hil` 로 gate MAY; promotion state
  가 `auto` 를 강제하지 않음.

## 4. Live blast probe

Static `blast_radius` 는 "이 ActionType 은 resource group 까지 영향 MAY" 말함;
live probe 는 "이 특정 리소스는 지난 5분 트래픽 0, 그러므로 실제 영향
없음" 말함. Static + live 결합은 "실행 중인 NSG rule 변경은 아무도
호출하지 않을 때 저-영향" 이라는 직관 뒤의 mechanism.

### 4.1 Probe 선언

Probe 는 [`rule-catalog/probes/`](../../../rule-catalog/probes) 아래 살음:

```yaml
schema_version: "1.0.0"
id: vm_traffic_last_5m
description: "지난 5분 VM 네트워크 throughput 기반 quiet/active/overloaded 반환."
adapter_ref: probe-adapters/azure-monitor       # DI seam id
adapter_payload:                                # adapter-특화; 코어 probe 스키마의
  kql: |                                        # 일부가 아니므로 코어가 CSP-neutral 유지
    AzureMetrics
    | where ResourceId == '{{ target_ref }}'
    | where MetricName == 'Network In Total'
    | where TimeGenerated > ago(5m)
    | summarize p = percentile(Total, 95)
interpretation:
  quiet:      p < 1000000            # <1 MB/5min
  active:     p < 100000000          # <100 MB/5min
  overloaded: p >= 100000000
timeout_seconds: 5
cache_ttl_seconds: 60
```

### 4.2 Runtime 형태

RiskGate 는 probe 를 **오직** 다음 시에만 호출:

- `ActionType.live_probe_ref` 가 set.
- 다른 axis 가 아직 `shadow_only` 또는 `deny` 로 강제하지 않음
  (probe cost 는 결정을 실제로 변경 가능할 때만 지불).
- Probe 캐시가 target 에 대해 fresh answer 없음.

Probe 실패 처리 (fail toward safety). Probe 는 *ceiling 을 낮추는* axis
이지 authorizer 가 아님. 단발 실패 (timeout, adapter error) 시 axis 는
`active` 반환 - auto 대신 HIL 을 강제해 probe 가 blind 인 동안 사람이
확인하게 하되, 오퍼레이터-개시 액션을 hard-stop 하진 않음. Rolling window 를
가로지르는 **반복** 실패 (기본 `cache_ttl_seconds * 5` 내 3회) 시 axis 는
자신의 posture 를 `shadow_only` 로 에스컬레이트하고 `probe.degraded` audit
entry 를 write: 지속적으로 blind 한 probe 는 그 ActionType 을 오퍼레이터가
inspect 할 때까지 실행 중단해야 함을 의미, 무한정 수작업 승인이 아님. 그래도
*전체* loop 를 fail-close 하진 않음 - degraded probe 에 bind 된 ActionType 만.

**Replay 는 기록된 결과를 사용, 재질의 안 함.** 디버깅/사개분석을 위해
audit log 를 replay 할 때 RiskGate 는 `live_probe_result` 를 기록된
`resolved_ceiling` (§8) 에서 read; probe 를 다시 호출 MUST NOT. 이는 replay 를
judge-only 이고 결정론적으로 유지
([architecture.instructions.md § Idempotency, Ordering, and Replay](../../../.github/instructions/architecture.instructions.md#idempotency-ordering-and-replay)).

### 4.3 Probe adapter seam

```python
class LiveBlastProbe(Protocol):
    async def measure(
        self,
        *,
        probe_id: str,
        target_ref: str,
        deadline_seconds: float,
    ) -> ProbeResult: ...
```

Upstream Day-1 는 fake `NoOpBlastProbe` (returns "no opinion") ship;
Month-1 은 `AzureMonitorBlastProbe` 추가. Fork 는 Protocol 을 구현하는
어떤 adapter 든 bind MAY.

## 5. Executor 경로

4 경로가 모든 액션 cover. 셋은 substrate-mutation ladder 를 이룬다
(`pr_native`, `direct_api`, `pr_manual`); ActionType 이 하나를 name 하고
RiskGate 는 `pr_manual` 로 downgrade MAY (upgrade 절대 안 함). 네 번째
`tool_call` 은 별도의 함수-호출 표면이다 (§5.6) - substrate 를 mutate 하지
않으므로 그 ladder 에 놓이지 않는다.

### 5.1 PR-native (`pr_native`)

- Executor 가
  [`GitOpsPrAdapter`](../../../src/fdai/delivery/gitops_pr/adapter.py)
  로 PR 빌드.
- `auto` 결정 시, PR 은 `hil` label 을 carry 안 함 → branch 의
  auto-merge 정책이 accept.
- `hil` 결정 시, PR 은 `hil` label 을 carry → approver 가 콘솔로 merge.
- 감사 + rollback 은 git 에 lean: revert commit 이 rollback path.

Best for: configuration 변경, IaC patch, 카탈로그 업데이트, governance
변경.

### 5.2 Direct API (`direct_api`)

- Executor 가 substrate API 를 직접 호출 (Azure ARM, kubectl,
  `src/fdai/delivery/` 아래 해당 delivery adapter 를 통한 Redis).
- `auto` 결정 시, call 이 HIL 없이 진행; ActionType 의 `stop_conditions`
  와 `preconditions` 가 call 전후로 executor 에 의해 enforce.
- `hil` 결정 시, executor 가 HIL item 을 enqueue (PR-manual 큐와 동일
  하지만 item 에 `mutation_target=direct` 로); approver 가 콘솔로
  accept; 그 후 executor 가 dispatch.
- Rollback 은 ActionType 의 `rollback_contract` 로부터 (`scripted`,
  `pitr`, `snapshot_restore`).
- **Idempotency invariant** - 매 direct-API call 은 액션의 안정된
  idempotency key 사용 (기존 invariant
  [coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md));
  retry 된 call 이 double-apply MUST NOT.

Best for: latency 가 중요한 ops 액션 (재시작, scale, cache flush).

### 5.3 PR-manual (`pr_manual`)

- PR-native 와 동일하지만 이 PR 에 대해 auto-merge 정책 비활성 (label
  `hil` + 명시적 `merge-not-eligible`).
- Axis 와 관계없이 사람 review 필수; 모든 axis 에서 `enforce_auto` 라도
  여전히 manual-merge PR 로 landing.
- 매우 high-risk 액션 또는 자동화와 관계없이 모든 mutation 이
  reviewable diff MUST 인 compliance-heavy 환경에 사용.

Best for: scripted rollback 있는 irreversible 변경, fork 가 자동화와
관계없이 두 번째 pair of eyes 를 원하는 governance 변경.

### 5.4 Dispatch 시 executor selection

```
requested_path = ActionType.execution_path
forced_path = RiskGate.resolved_ceiling.forced_execution_path  # 옵션 axis 출력
final_path = strictest(requested_path, forced_path)
                # 엄격 순서 (속도가 아닌 리뷰-엄격성 기준):
                #   pr_manual > pr_native > direct_api
```

여기서 "strictest" 는 가장 빠른이 아니라 **가장 사람-리뷰-gated** 를 의미:
`pr_manual` (필수 사람 merge) 이 `pr_native` (정책 auto-merge) 보다
엄격하고, 그것이 `direct_api` (diff 없음) 보다 엄격. Axis 는 dispatch 를 이
사다리에서 **위로** (더 많은 리뷰 쪽으로) 만 이동 가능; latency 를 위해
아래로 절대 이동 못 함. Fork 는 env axis 를 통해 prod 의 모든 dispatch 를
`pr_manual` 로 강제 가능. Upstream 은 절대 아래로부터 강제 안 함 (속도를
위해 `pr_manual` 을 `direct_api` 로 lift 안 함).

**Fallback idempotency.** dispatch 가 도중에 `direct_api` 에서 `pr_manual`
로 degrade 될 때 (§11), fallback PR 은 액션의 안정된 idempotency key 를
재사용. direct-API adapter 는 시도-및-실패한 call 을 그 key 하에 기록하여
manual PR 경로가 동일 mutation 을 double-apply 할 수 없도록 함.

### 5.5 HIL 승인 왕복 (park and resume)

RiskGate 가 `hil` 을 반환하면 executor 는 실행되지 않고 control loop 은
사람을 기다리며 block 하지 않는다. `HilResumeCoordinator`
(`core/hil_resume`) 는 **park and return** 모델을 적용한다:

1. **park** - 전체 `Action` (+ rule id, submitter, correlation id) 을
   opaque `approval_id` 하에 `status=pending` 으로 `StateStore` 에
   직렬화;
2. **push** - `HilChannel` (Teams / Slack) 로 A1 승인 카드 dispatch;
   배달 실패는 액션을 parked + 복구 가능 상태로 남기며 실행하지 않음;
3. **audit** - `hil.requested` 엔트리 기록 후
   `ControlLoop.process(...)` 는 block 없이 `hil` 반환.

이후 결정(ChatOps callback 또는 poll)이
`HilResumeCoordinator.resolve(approval_id, decision, approver_oid)` 를
구동한다:

- **APPROVE** - parked `Action` 을 복원(`model_validate`)해 동일한
  executor selection (§5.4) 으로 재-dispatch; `hil.approved.executed`
  audit 엔트리 하나 기록.
- **REJECT** / **TIMEOUT** - 기록하되 실행 안 함 (fail-closed).
- **만료된 APPROVE** - delegation과 executor selection 전에 `expires_at`을
  확인한다. Expiry 시각 이후의 승인은 atomic하게 `TIMEOUT`으로 resolve하고
  `hil.timeout`을 기록하며 실행하지 않는다. 만료 record는 Reader HIL queue와
  `hil_pending` KPI projection에서 제외한다.
- **idempotent** - park 는 첫 terminal 결정에서 `status=resolved` 로
  전환; 중복 결정은 no-op, 상충 결정은 거부되어 승인이 double-apply
  될 수 없음.
- **self-approval 금지** - `approver_oid == submitter_oid` 는 실행 전에
  거부; loop 은 system submitter 신원으로 park 하므로 실제 approver 는
  항상 구별됨.

**Role-scoped 큐 + delegation (Scenario A).** parked HIL 항목은 개인별
인박스가 아니라 **큐**다: `Capability.APPROVE_RUNTIME_HIL` 을 가진 어떤
operator 든 resolve 할 수 있다. park 는 선택적 `assignee_oid` - 항목이
표면화된 대상 operator, 기본값은 resolved on-call primary - 를 기록한다.
*다른* 권한 보유 operator 가 승인하면 그것은 **delegated** 승인이다: 허용
(동일 권한)하되 별도로 기록하여, audit 엔트리가 실제 `approver_oid` 와 원래
`assignee_oid` 를 모두 남긴다 (`delegation_mode` = `direct` / `delegated`
/ `role_scoped`). 이 gate 는 coordinator 와 read-API callback 이 공유하는
하나의 순수 함수(`core/hil_resume/delegation.py`)라서 규칙이 두 진입점
사이에서 벌어지지 않는다. 거부는 fail-closed 를 유지한다: 빈 /
self-approving / capability 없는 approver 는 실행되지 않는다
(`missing_capability` 는 403 을 반환하고 park 는 권한 있는 operator 가
resolve 할 수 있도록 남는다). read-API callback 은 push 채널이 주장한
HMAC 서명된 `actor_roles` 로부터 `approver_can_approve_hil` 를 도출한다;
`actor_roles` 가 없으면 채널을 신뢰(기본 허용)하되 no-self-approval 과
HMAC gate 는 여전히 적용된다.

이것으로 `hil` verdict (§2) 와 승인된 액션의 실제 실행 사이가, blocking
wait 나 gate 없는 auto-execute 없이 이어진다. read-API HIL callback
(`POST /hil/{approval_id}/decision`) 이 resolve trigger 를 구동한다:
인바운드 결정은 coordinator 를 먼저 거치고(park 경로 - `APPROVE` 는
executor 로 재-dispatch), park 가 없으면 `approve_hil` 로 올라온
console-pull 승인을 위해 registry 경로로 fall through 한다. coordinator 는
transport-neutral 이다. ChatOps 채널이 설정되면(`FDAI_CHATOPS_WEBHOOK_URL`)
`__main__` 이 이것을 control loop 에 wire 하여 `hil` verdict 가 액션을 park
하고 A1 카드를 push 한다; 없으면 loop 은 verdict 를 기록하고 영속화된
queue 로 fall back 한다. read-API 서버는 동일한 coordinator 를 callback
route 에 공급하여 인바운드 결정이 park 를 resolve 한다.

**Notify-on-decision.** 동일한 loop 은 모든 terminal 결정
(`executed` / `hil` / `denied`) 마다 notification router 를 통해 A2
operational-alert 도 emit 한다 - outbound-only, 정보성이며 승인 버튼을
절대 싣지 않음 (
[channels-and-notifications-ko.md § 3](../interfaces/channels-and-notifications-ko.md)
참조). router 는 optional seam 이다: 없으면 loop 은 이전과 정확히 동일하게
동작한다.

### 5.6 Tool call (`tool_call`)

- Executor 가 **등록된 함수** - PDF 리포트 생성, 알림 발송, 티켓 오픈 -
  를 [`ToolExecutor`](../../../src/fdai/shared/providers/tool.py) Protocol
  (`core/executor/tool_call.py` 의 `ToolCallShadowExecutor`) 로 invoke.
  클라우드 substrate 를 mutate 하지 않고 **아티팩트** 또는 side effect 를
  생산한다. LLM 이 tool 을 호출하는 방식의 온톨로지-네이티브 대응물이다:
  `tool.*` ActionType 이 등록된 tool 하나를 name 하고 executor 가 여기서
  dispatch. tool registry 는 MCP 어댑터의 자연스러운 attach point 다 -
  Protocol 을 구현한 `McpToolExecutor` 가 MCP 서버 tool 하나를 `tool.*`
  ActionType 하나에 매핑한다.
- MCP server는 `McpServerCatalog`를 통해 등록합니다. Server manifest는 endpoint 및
  ActionType-to-tool allowlist를 검증하고 disabled 상태로 install되며 read-only `tools/list`
  discovery가 모든 allowlisted tool의 존재를 확인한 후에만 enable할 수 있습니다. Public
  endpoint는 HTTPS가 필요하고 HTTP는 loopback sidecar에만 허용됩니다. Payload URL은 configured
  server endpoint를 override하지 않습니다. 두 enabled server는 같은 ActionType을 소유할 수
  없습니다. Enabled catalog는 기존 `RoutingToolExecutor`에 route를 project하며 새 execution
  path를 만들지 않습니다.
- `core/` 는 Protocol 만 안다; fork 가 composition root 에서 live 어댑터
  (네이티브 Python registry, MCP 클라이언트, HTTP callout) 를 bind. Default
  binding 은 `RecordingToolExecutor` (실제 함수 실행 없음). Configured
  `FDAI_JIRA_BASE_URL`은 PostgreSQL idempotency ledger 및 distributed resource
  lock과 함께 `JiraToolExecutor`를 bind합니다. ActionType promotion gate와
  `FDAI_JIRA_ENFORCE=1`이 모두 enforce를 허용하기 전까지 shadow를 유지합니다.
  Enforce creation은 deterministic `fdai-idem-<sha256>` label을 추가합니다. POST 전에
  durable pending claim을 atomically 기록하고 Jira enhanced
  `/rest/api/3/search/jql` endpoint에서 해당 label을 검색합니다.
  Create-before-ledger crash 이후 retry는 기존 issue를 reconcile하고
  `already_applied`를 반환할 수 있습니다. Prior claim이 남았지만 Jira에서 issue가 아직
  보이지 않으면 duplicate 위험을 감수하지 않고 fail closed합니다. POST 전 search
  failure와 definitive create `4xx` response는 새로 획득한 claim을 release합니다.
  Transport failure, `5xx` response, malformed successful create response는 side effect가
  ambiguous하므로 claim을 quarantine 상태로 유지합니다. 각 retry는 Jira를 다시 검색하며,
  retryable adapter failure는 audit하지만 core executor cache에는 넣지 않습니다.
  `fdai-idem-` label namespace는 adapter가 소유합니다. Request가 해당 prefix로 제공한
  label은 제거하여 한 request가 다른 key를 alias하지 못하게 합니다. Audit entry는
  Action의 실제 `shadow` 또는 `enforce` mode를 기록합니다. POST 전 cancellation은
  claim을 release하고 failed audit entry를 기록한 뒤 다시 raise합니다. Core는 durable
  execution result를 기록한 뒤에만 in-memory dedupe cache를 채우므로 transient durable
  write failure는 retryable 상태로 남습니다.
- `auto` 결정 시, HIL 없이 call 진행; ActionType 의 `preconditions` 와
  `stop_conditions` 를 executor 가 enforce.
- `hil` 결정 시, executor 가 액션을 park 하고 `direct_api` 와 동일한 HIL
  왕복 (§5.5) 으로 승인 후 resume.
- Rollback 은 ActionType 의 `rollback_contract` 로부터 - 보통
  `state_forward_only` (생산된 아티팩트 삭제) 또는 `scripted`.
- **Idempotency invariant** - 매 tool call 은 액션의 안정된 idempotency
  key 를 사용; 재시도 call 은 tool 을 재실행 MUST NOT (같은 key 의 두 번째
  call 은 `already_applied` 반환).
- 4 개 안전 invariant 는 그대로 적용. `tool.*` ActionType 은 mutation
  ActionType 과 똑같이 측정 가능한 `promotion_gate` 를 가진 shadow-first;
  executor 는 시도당 정확히 하나의 audit entry 를
  `action_kind=executor.tool_call.<outcome>` 와
  `execution_path=tool_call` 로 쓴다.
- `tool.open-incident-ticket`은 기본 제공 ticket ActionType입니다. Shadow receipt는
  실제 ticket으로 link되지 않습니다. 성공한 enforce receipt는 terminal executor
  success 전에 `link_ticket_receipt`를 통과하고 `incident.ticket`을 append합니다.
  Linkage failure는 retryable하며 success로 cache되지 않습니다.

Best for: 문서 생성, 알림, 티켓팅, 그리고 워크플로 스텝이 PR 을 열거나
substrate 를 건드리지 않고 `action_type_ref` 로 invoke 하려는 임의의 등록된
함수.

## 6. 안전 invariant (변경 없음 + 하나 확장)

모든 executed 액션은 이미
[coding-conventions.instructions.md § Safety](../../../.github/instructions/coding-conventions.instructions.md#safety)
의 4 autonomy invariant (stop-condition, rollback, blast-radius limit,
audit) 를 carry. 이 문서는 하나 추가:

5. **매 dispatch 는 `resolved_ceiling` 을 write.** Audit entry 는
   결정을 생성한 완전한 6-axis breakdown (`risk_table` axis 포함) 을
   carry MUST -> 향후 overlay 변경이 과거 결정의 재현성을 절대 break 안 함.

다른 invariant 는 정확히 이전과 같이 적용 - chat-specific carve-out
없음, direct-API relaxation 없음.

### 6.1 오퍼레이터-콘솔 invariant 와의 상호작용

Chat-특화 invariant ([operator-console.md § 7.2](../interfaces/operator-console-ko.md#72-chat-특화-3-invariant))
는 additive:

- **Chat invariant 5 (verifier re-check)** = "매 write-class tool call
  에서 RiskGate 실행". 이 문서가 해당 RiskGate 의 정의; 콘솔은 그저
  호출.
- **Chat invariant 6 (no self-approval)** = RiskGate 의 role axis
  (Axis F) 가 caller 의 Entra `oid` 가 큐잉된 item 의 requester 와
  매치할 때 `approve_hil` refuse.
- **Chat invariant 7 (BreakGlass time-boxed)** = Axis F 의 BreakGlass
  동작 (§2.5): BreakGlass 는 approval 을 위한 eligible role 을 raise
  하지만 HIL 을 절대 우회 안 함.

## 7. 결정론성 + 감사성

- 동일한 6-axis 입력이 주어지면 RiskGate 는 동일한 `RiskDecision`
  반환. 어떤 stochastic 구성요소 (moving window 를 query 하는 probe)
  든 probe 의 `cache_ttl_seconds` 로 bounded → TTL 내 replay 가
  identical 결정 yield.
- `resolved_ceiling` 블록은 결정의 완전한 self-explanation - dispatch
  시점에 in effect 였던 ceiling 이 record of truth 이므로 향후 overlay
  변경이 과거 audit entry 를 절대 invalidate 안 함.

## 8. `resolved_ceiling` audit 블록

매 dispatch 는 write:

```json
{
  "resolved_ceiling": {
    "tier": "T0",
    "action_type_id": "ops.restart-service",
    "axes": {
      "risk_table":     {"level": "enforce_hil",  "reason": "cost_impact_monthly >= 100", "matched_rule_id": "cost-threshold", "catalog_version": "1.0.0", "quorum": 1},
      "tier":           {"level": "enforce_auto", "reason": "shadow-promoted ActionType 의 T0 판정"},
      "ceiling":        {"level": "enforce_hil",  "reason": "ceiling_by_tier.t0.max_autonomy"},
      "static_blast":   {"level": "enforce_auto", "reason": "static_bucket=resource"},
      "live_blast":     {"level": "enforce_hil",  "reason": "probe=vm_traffic_last_5m returned active", "probe_result": "active"},
      "role":           {"level": "enforce_hil",  "reason": "principal=contributor >= min_role=contributor"},
      "env":            {"level": "enforce_auto", "reason": "not-prod"}
    },
    "winning_axis": "risk_table",
    "final_level":  "enforce_hil",
    "final_quorum": 1,
    "final_path":   "direct_api",
    "overlay_layers_applied": ["upstream", "rego"]
  }
}
```

`resolved_ceiling` 블록의 정확한 shape (risk_table axis 와 quorum 포함) 은
`ontology/resolved-ceiling` JSON 스키마로 validate 되는 고정된 versioned
계약이며, §3 의 `RiskDecision` 마이그레이션과 함께 Week-1 스키마-확장 PR
에서 landing. narrator 와 audit consumer 가 verbatim 으로 render 하므로
스키마-체크 된 shape 이 필수; contract test 가 매 dispatch 가 `risk_table`
axis 포함 schema-valid 블록 을 emit 함을 assert.

## 9. Rollout 기록

Execution 모델은 subsystem tier upgrade 없이 data + policy 변경으로 landing했습니다.
아래 sequence는 rollout 기록이며
[action-ontology.md § 10](action-ontology-ko.md#10-migration-기록)의
ActionType migration record와 일치합니다.

### Day 1

- 스키마 확장만. 로더가 신규 field 학습; 모든 기존 ActionType 이 validate.
  RiskGate 는 오늘처럼 계속 동작 (shadow-only) - `promotion_state` 가
  모든 entry 에 대해 shadow 이기 때문.
- **Exit gate**: 6-axis min-combination 에 대한 property test; 모든
  기존 shipped 룰이 변경 전과 동일한 shadow-only outcome 을 여전히
  produce.

### Week 1

- 온톨로지 backfill landing (action-ontology.md § 10 step 2 참조).
- ControlLoop 이 매 dispatch 에서 통합 RiskGate 로 routing 시작 (이전
  stub 이었음); ActionType 이 promote 안 됐으므로 execution 은 shadow-
  only 유지.
- 오퍼레이터-콘솔 pull-방향이 argument-schema-validated dispatch path
  (§3.1) 와 함께 ship.
- **Exit gate**: `resolved_ceiling` audit 블록이 매 dispatch 에 등장;
  룰-발화 + 오퍼레이터-발화 경로가 동일한 RiskGate 를 통해 동일한
  executor 에 도달함을 커버하는 end-to-end test.

### Week 2

- 첫 `ops.*` ActionType 이 `execution_path=direct_api` 와
  `ceiling_by_tier.t0.max_autonomy=enforce_auto` 로 landing. RiskGate
  는 이제 Reader-visible 리소스의 non-prod 에 대해 `auto` 를 produce.
- **Exit gate**: 콘솔을 통한 Contributor 가 live-probe fake (`quiet`)
  하에 non-prod 리소스에서 `ops.restart-service` 실행; executor 가
  (mocked) ARM API 호출; audit entry 가 `direct_api` path 를 carry.

### Month 1

- 실 `AzureMonitorBlastProbe` bind; live probe 가 opt in 한 ActionType
  에서 live 로 감.
- `governance.override-ceiling` landing → Owner 가 콘솔로부터 ceiling
  downgrade 를 time-box 가능 (action-ontology §7.4).
- **Exit gate**: 최소 하나의 live probe 가 production shadow 측정에서
  최소 한 번 autonomy 를 reduce; 그 dispatch 의 audit entry 가
  `winning_axis=live_blast` 를 표시.

## 10. Testability

- **6-axis + 표 매트릭스** - 전체 카테시안 곱
  (`risk_table` x tier x ceiling x static_blast x live_blast x role x env)
  은 조합적으로 크므로, suite 는 determinate 값에 대한
  **pairwise (all-pairs)** 생성 + 명시적 hand-picked corner case (any-`deny`
  short-circuit, irreversible-quorum, prod downgrade, BreakGlass-eligible)
  를 사용; 각 생성 row 는 `min()` semantics 와 어느 입력도 autonomy 를
  raise 하지 않음을 assert.
- **Overlay 우선순위 + resolved_ceiling** - 동일 axis 에 모든 네 overlay
  layer 가 active 인 fixture; higher-precedence layer 승리 및
  `overlay_layers_applied` 아래 이름 등장 assert.
- **Live-probe fake** - `NoOpBlastProbe` 가 `quiet / active /
  overloaded` 각각 반환; RiskGate 출력이 예상대로 변경.
- **Executor path selection** - table-driven: ActionType.default vs
  forced_path; strict-order winner assert.
- **Direct-API idempotency** - executor 의 dispatch 가 동일한
  idempotency key 로 두 번 호출; substrate adapter 가 정확히 하나의
  mutation 기록.
- **PR-native + PR-manual auto-merge 정책** - adapter 가 emit 하는
  label set 에 대한 contract test; label 매트릭스 assert.
- **RiskDecision 은 authority 를 upgrade 할 수 없음** - property test:
  ActionType 의 `promotion_state=shadow` → RiskDecision.mode 는 다른
  모든 axis 와 관계없이 항상 `shadow`.

## 11. 실패 모드

- **Probe timeout / error** -> 단발 실패는 `active`, 반복 실패는
  `shadow_only` 반환 (§4.2); `probe.degraded` 로그; 전체 loop 를
  fail-close 하지 않음.
- **Overlay 로드 error** (Rego syntax error, missing file overlay
  target) -> **upstream 이 아니라 더 안전한 값으로 fail.** 실패한
  overlay 가 *tightening* overlay (fork 가 autonomy 다운그레이드) 였으면
  RiskGate 는 더 느슨한 upstream 기본으로 되돌리는 대신 last-known 조인
  ceiling 을 유지 (fail-closed); 실패한 loosening overlay 는 단지 더 엄격한
  upstream 값을 그대로 둠. 어느 쪽든 `overlay.load_failed` audit 를 write
  하고 `overlay_layers_applied` 를 mark 하여 overlay 가 applied 인 척 절대
  안 함.
- **Executor path 도달 불가** (direct_api adapter down) -> 저-긴급 액션은
  `pr_manual` 로 fallback 하고 `executor.path.degraded` write. **latency-
  critical ops 액션** (`ops.restart-service`, `ops.failover-primary`,
  ActionType 이 `urgency: high` 설정한 것) 은 `pr_manual` fallback 이
  목적을 무효화하므로, 대신 on-call approver 가 콘솔에서 수 초 내
  accept 할 수 있는 **direct HIL item** (`mutation_target=direct`) 으로
  enqueue; fallback 과 그 이유가 `resolved_ceiling` 에 등장. fallback 은
  액션의 idempotency key (§5.4) 를 재사용해 어느 경로도 double-apply 안 함.
- **RiskGate 자체 unavailable** (일어나면 안 됨 - 입력의 pure function)
  -> fail-close: dispatch 없음, `deny` audit, operational lane 페이지.

## 12. 관련 문서

- [action-ontology.md](action-ontology-ko.md) - 이 문서가 소비하는
  ActionType 스키마 + fork 가 매트릭스를 tune 하는 override seam.
- [operator-console.md](../interfaces/operator-console-ko.md) - RiskGate 는 콘솔의
  chat invariant 가 매 write-class tool call 에 요구하는 verifier.
- [phase-2-quality-and-t1.md](../phases/phase-2-quality-and-t1-ko.md) -
  ActionType 을 shadow 에서 enforce 로 flip 하는 promotion 파이프라인.
- [risk-classification.md](risk-classification-ko.md) - 6-axis ceiling 이
  `min()` 으로 결합하는 권위적 first-match auto / HIL / deny 표 (Axis A,
  §2.0); 매트릭스로 대체되지 않음.
- [security-and-identity.md](../architecture/security-and-identity-ko.md) - 4 autonomy
  invariant + executor identity 계약.
- [architecture.instructions.md](../../../.github/instructions/architecture.instructions.md) -
  trust routing, verifier authority.
