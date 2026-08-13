---
title: Execution 모델
translation_of: execution-model.md
translation_source_sha: 3b89e39e846e5fcd297b37071a692d94485541d5
translation_revised: 2026-08-14
---

# 실행 모델

FDAI 이 액션 실행 **여부** 와 **방법** 을 결정하는 방식. 이 문서는 통합 RiskGate, 권위적 [risk-classification.md](risk-classification-ko.md) first-match 표가 **6-axis** ActionType 상한 과 결합하는 방식, 4개의 실행기 경로 (PR-native / direct API / PR-manual / 도구 호출), live-blast 탐색 combinator, 그리고 실제 운영 변경이 만족해야 하는 안전성 불변식 를 권위적으로 정의한다.

> 결정-엔진 관계 (권위적): FDAI 은 **하나의** 결정을 가지며, 그것은 **두** 입력을 결합해 생성된다. [risk-classification.md](risk-classification-ko.md)
> first-match 표가 **권위적 기준선** - 발견 사항 feature vector
> (`policy_violation`, `destructive`, `irreversible`, `data_plane_touched`,
> `cost_impact_monthly`, `verifier_confidence`, `blast_radius`,
> `environment`) 를 소비해 `auto | hil | deny` 와 `quorum` 을 반환. 이
> 문서의 6-axis 상한 은 ActionType + 런타임 컨텍스트 (계층, ActionType 상한, static/실제 운영 영향, 역할, env) 를 소비해 전달 별 상한 을 반환. RiskGate 는 둘의 **최소** 을 반환; 어느 쪽도 상대보다 자율성
> 를 raise 못 함. 표는 매트릭스로 대체되지 않음 - 매트릭스는 그 위에
> 계층 된, 절대 raise 안 하는 추가 제약이다.

이 모델의 소비자:

- ControlLoop 과 오퍼레이터-콘솔 조정기 는 액션 전달 전에
  RiskGate 에 ask.
- 각 실행기 경로는 액션의 ActionType 이 선언한 안전성 묶음 를 구현
  ([action-ontology.md](action-ontology-ko.md)).
- 오퍼레이터 콘솔은 `resolved_ceiling` 을 표면 → 오퍼레이터가 시스템
  이 auto / HIL / 거부 를 결정한 이유를 정확히 볼 수 있음.

> 고객-무관: 아래의 모든 상한 기본값, 탐색 표현식, 역할 배정
> 는 자리 표시자. 포크 는
> [action-ontology.md § 7](action-ontology-ko.md#7-fork-override-seam)
> 에 문서화된 재정의 경계 으로 tune.

## 구현 상태

### 구현 범위

| 영역 | 상태 | 근거 | 참고 |
|------|------|------|------|
| Risk 표 및 권한을 높이지 않는 상한 | implemented | [`test_authority.py`](../../../services/core-control-plane/tests/core/risk_gate/test_authority.py), [`test_ceiling.py`](../../../services/core-control-plane/tests/core/risk_gate/test_ceiling.py) | 기준선, 6개 맥락 축, 성능 저하 및 비상 정지는 권한을 높이지 않고 결합됩니다. |
| 승격, HIL 재개 및 실행기 선택 | implemented | [`test_gate.py`](../../../services/core-control-plane/tests/core/risk_gate/test_gate.py), [`test_coordinator.py`](../../../services/core-control-plane/tests/core/hil_resume/test_coordinator.py) | Shadow 우선 승격, 승인 재개 및 타입이 지정된 경로 선택에 집중 테스트가 있습니다. |
| 모든 실행 경로의 7개 안전장치 | in-progress | [`constitution-traceability.json`](../../../config/constitution-traceability.json), [7개 안전장치](#6-7개-안전조건과-하나의-재생-확장) | 개별 동작은 있지만 하나의 공유 계약이 모든 경로의 동등한 보장을 아직 증명하지 않습니다. |
| 실제 영향 탐색 배포 및 운영 근거 | not-started | [탐색 어댑터 경계](#43-탐색-어댑터-경계), [롤아웃 기록](#9-롤아웃-기록) | 실패 시 차단되는 탐색 경계는 있지만 보존된 실제 탐색 연결이나 운영 shadow 증적은 없습니다. |

### 구현 이력

| 날짜 | 상태 | 변경 | 근거 | 남은 작업 |
|------|------|------|------|-----------|
| 2026-08-14 | in-progress | 이전 출처 이력을 재구성하지 않고 구현 원장을 도입하고 테스트된 동작과 배포 근거를 분리했습니다. | `current change`; 구현 범위 표의 현재 소스, 집중 테스트 및 헌법 추적성입니다. | 공유 안전장치와 실제 탐색 근거 공백을 완료해야 합니다. |

### 남은 작업

- [ ] PR-native, direct API, PR-manual 및 tool-call 실행 전체에서 7개 안전장치와 독립 효과
  종결을 하나의 공유 계약으로 표현하고 경로 동등성 테스트를 보존합니다.
- [ ] 운영 `AzureMonitorBlastProbe`를 연결하고 실제 근거가 `winning_axis=live_blast`로
  권한을 낮추며 변경하지 않는 shadow 증적을 보존합니다.
- [ ] 운영 검증을 주장하기 전에 하나의 고정된 ActionType 및 risk 카탈로그 리비전에서 각
  실행기 경로의 통제된 종단 간 증적을 보존합니다.

## 1. 여기서 "execute" 의 의미

이 문서 이전까지, FDAI 이 하는 모든 것은 **shadow** 였음 - 판정자
하고 로그, mutate 절대 안 함. Execute 는 모든 게이트 통과 후 실행기 가
변경 표면 (git PR 병합, Azure ARM API, scripted 롤백 실행기)
를 실제로 호출하는 것. Shadow 모드 는 모든 신규 액션의 기본으로 여전히
유지; 실행 은 promoted 상태, per-action, measured 근거 로
gated, 매 전달 에서 re-check.

4개의 실행 경로 (§5)가 있으며 venue 수명 주기는 Thor 뒤에 유지됩니다([백엔드 설계](../interfaces/execution-backends-ko.md)).

- **PR-native** - 변경이 병합 정책 가 auto-accept 하는 git PR 로
  landing (또는 사람이 수용). 감사 + 롤백 은 git 으로부터.
- **Direct API** - 실행기 가 기반 API 를 직접 호출 (Azure ARM,
  kubectl, Redis). 감사는 감사 로그 에, 롤백 은 ActionType 의
  `rollback_contract` 에.
- **PR-manual** - 변경이 `hil` 라벨 을 carry 하는 PR 로 landing; auto-
  병합 없음, 승인자 가 수용 MUST. 자동화된 검증이 부족한 high-risk
  액션에 사용.
- **도구 호출** - 새 실행기 bypass 없이 `ToolExecutor` 계약을 통해 등록된
  capability-bounded 함수를 호출.

단일 ActionType이 경로를 선언하고 포크는 온톨로지 오버레이로 재정의합니다. 백엔드는 경로나 역할을
추가하지 않으며 risk, Var 승인, 잠금, Vidar 롤백, Saga 감사는 외부에 남고 프로파일은 낮출 수만 있습니다.

## 2. 6-axis 상한 + risk-classification 표

RiskGate 는 **6개 직교 상한 축** 와 권위적 risk-classification 표를
하나의 결정으로 collapse. 각 축 와 표는 독립적으로 자율성 를 낮춤;
최종 결정은 각 입력이 permit 하는 것의 **최소**. 여기서 어느 것도
자율성 를 raise 하지 않음 - 업그레이드 는 승격 파이프라인
([phase-2-quality-and-t1.md § 승격](../phases/phase-2-quality-and-t1-ko.md#promotion-shadow--enforce))
을 통해, 전달 시간 의 RiskGate 가 아님.

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
- `shadow_only` - 판정자 하고 로그; 변경 없음.
- `deny` - 진행 안 함; 결정은 hard stop.

최종 RiskGate 출력은 winning 최소, risk-classification 표로부터의
`quorum` (기본 1; irreversible 은 2,
[risk-classification.md](risk-classification-ko.md) 참조), 그리고 감사
소비자 가 reasoning 을 렌더링 할 수 있도록 각 입력의 기여를 이름 하는
`resolved_ceiling` breakdown (§8) 을 carry 하는 **`RiskDecision`**.

### 2.0 축 A - Risk-classification 표 (권위적 기준선)

`A_risk_table` 은 [risk-classification.md](risk-classification-ko.md) 의
first-match 표를 발견 사항 feature vector 에 대해 평가한 결과. 이 축 는
다음 신호가 평가되는 **유일한** 곳 - 6개 상한 축 는 의도적으로
이들을 재도출하지 않음:

- `policy_violation` (검증기 판정) -> `deny`.
- `destructive` (`operation in {delete, drop, purge, detach}`) -> `hil`.
- `irreversible` (`ActionType.irreversible == true`) -> `quorum: 2` 인
  `hil`.
- `data_plane_touched` (`interfaces include DataPlaneMutating`) -> `hil`.
- `cost_impact_monthly >= $100` -> `hil` (비용 거버넌스 버티컬 게이트;
  이것이 `ops.scale-out` 과 모든 비용-증가 액션이 비용 임계값 를
  clear 하지 않고는 `auto` 갈 수 없는 이유 - §2.8 참조).
- `verifier_confidence < 0.85` (T2 quality-gate 신호) -> `hil`.
- `blast_radius` 와 `environment` 도 여기서 평가되며 그 두 신호의 권위적
  출처 (6-axis static/실제 운영 영향 와 env 축 는 오직 *추가로* 낮출 뿐,
  절대 모순되지 않음).

`A_risk_table` 은 표의 `decision` 을 4 수준 에 매핑해 반환 (`거부 ->
거부`, `hil -> enforce_hil`, `auto -> enforce_auto`) 하고 매치된 룰 id +
`catalog_version` 을 감사 항목 에 carry.

### 2.1 축 B - Tier

Trust 라우터 로부터.

| Tier | 기본 자세 |
|------|-----------------|
| T0 (결정론적) | `enforce_auto` 허용 - T0 판정은 policy-as-code 통과 |
| T1 (lightweight 유사도) | 업스트림 카탈로그 상한은 보수적이며 오버레이는 자율성을 낮출 수만 있습니다. 권한 상향은 별도 통제된 승격 경로를 사용하며 dispatch-time 재정의가 아닙니다. |
| T2 (frontier reasoning) | 카탈로그 로더가 T2를 `shadow_only`로 hard-cap합니다. Hard 상한 변경은 검토된 업스트림 정책 변경이며 포크 오버레이가 아닙니다. |

### 2.2 축 C - ActionType 상한

ActionType 의 `ceiling_by_tier` 로부터
([action-ontology.md § 2](action-ontology-ko.md#2-스키마)).

### 2.3 축 D - Static 영향 범위

ActionType 의 `blast_radius` 블록. 두 계산 모드:

- `static_enum` - `resource | resource_group | subscription` 중 하나
  ([risk-classification.md](risk-classification-ko.md) 와 공유하는
  CSP-neutral 버킷 vocabulary). 버킷 이 넓을수록 이 축 는 낮은 값
  반환:
  - `resource` -> 자체적으로 자율성 를 낮추지 않음.
  - `resource_group` -> `enforce_hil` 에 상한.
  - `subscription` -> `deny` (어떤 자율 변경도 전체 구독 에
    걸치지 않음; risk-classification 거부 룰과 일치).
- `graph_derived` - 전달 시간 에 인벤토리 그래프로부터 computed.
  `max_affected_resources` 초과 값은 다른 축 와 관계없이 `enforce_hil`
  에 상한.

### 2.4 축 E - 실제 운영 영향 탐색 (월 1+)

`ActionType.live_probe_ref` 가 탐색 를 이름. 탐색 는 세 수준 중
하나 반환 (§4). 대응:

| 탐색 결과 | 상한 에 대한 효과 |
|--------------|-------------------|
| `quiet` | 변경 없음 - static 상한 승리 |
| `active` | `enforce_hil` 에 상한 (사람 approve) |
| `overloaded` | `shadow_only` 에 상한 (defer; 지금은 너무 risky) |

`live_probe_ref` 가 unset 이면 축 는 "no opinion" 반환 - 자체적으로
자율성 를 낮추지 않음.

### 2.5 축 F - 역할 (RBAC)

`ActionType.ceiling_by_tier[tier].min_role` vs 호출 principal 의
resolved 역할 ([user-rbac-and-identity.md](../interfaces/user-rbac-and-identity-ko.md)
로부터):

- principal 이 통상 단계 구조 (`reader < contributor < approver < owner`)
  에서 `min_role` 이상 -> 축 가 계층 기본값 반환.
- principal 이 `min_role` 미달 -> 축 가 `deny` 반환.
- **BreakGlass 는 off-ladder 이며 최상위 rung 이 아님.** BreakGlass 는
  Owner 안에 중첩된 되지 *않은* 별도 Entra 그룹
  ([user-rbac-and-identity.md § 2](../interfaces/user-rbac-and-identity-ko.md#2-롤-모델-4-tier--break-glass)).
  활성이고 time-box 된 BreakGlass 권한 부여 는 호출자 가 원래 under-
  privileged 여서 approve 못 했을 HIL 항목 을 *approve 할 자격* 을 얻게
  하지만, `enforce_auto` 를 절대 반환 안 함 - BreakGlass-eligible 호출자
  에 대해 축 는 `enforce_hil` 에 상한. BreakGlass 는 승인 자격을 raise
  하지, 자동화를 raise 하지 않는다.

룰-발화 액션의 경우 "principal" 은 실행기 신원 (시스템 MI); 그
역할 은 조립 시간 에 fixed
([composition.py](../../../services/core-control-plane/src/fdai/composition/__init__.py)).

### 2.6 축 G - 환경 (prod downgrade)

`ActionType.prod_downgrade.detection_ref` 가 env-detector 를 이름. "prod"
의 정의를 둘로 만들지 않기 위해, detector 참조 는
[risk-classification.md § 환경 Detection](risk-classification-ko.md#environment-detection)
에 정의된 **동일** env classifier (resource-group `environment` tag; 누락/
미인식 tag -> `prod`, fail-safe) 로 해석. Detector 가 대상 리소스에
대해 "prod" 반환 시, 축 는 `prod_downgrade.mode` (전형적으로
`enforce_hil` 또는 `shadow_only`) 에 상한.

`prod_downgrade` 블록 누락은 **`env_scope: non_prod` 를 선언하는 dev-only
ActionType 에 대해서만** 축 를 비활성화; 명시적 `env_scope` 없는
ActionType 은 risk-classification env 신호 (축 A) 를 inherit 하므로,
누락된 블록이 prod auto-execution 으로 silently fail 열림 될 수 없음.

### 2.6a Fail-safe 축 - System 상태 (성능 저하)

일곱 번째 축 인 `system_health` 는 **컨트롤 플레인 이 DEGRADED 일 때만**
존재함 - 하나 이상의 critical 의존성 (감사 저장소, 이벤트 버스,
기반) 의 circuit 차단기 가 trip 된 상태. 자율성 를 `shadow_only`
로 상한 하므로, 실패한 의존성 가 enforce-mode 변경 을 절대 driving
할 수 없음 (시스템 범위의 "fail toward 안전성",
[csp-neutrality.md](../architecture/csp-neutrality.md) 참고). 이 축 는
[`DegradationController.autonomy_permitted()`](../../../services/core-control-plane/src/fdai/shared/resilience/degradation.py)
가 `evaluate_execution_authority` 의 `system_degraded` 입력을 통해 공급함;
시스템이 healthy 하면 축 는 생략되고 결정은 byte-identical 한 six-axis
결과와 동일함.

### 2.6b Fail-safe 축 - 비상 정지 (운영자 emergency stop)

여덟 번째 축 인 `kill_switch` 는 **운영자 가 global 비상 정지 를
engage 했을 때만** 존재함 - 모든 auto-execution 을 즉시 halt 하는 의도적
비상 조치 (RBAC `TRIGGER_KILL_SWITCH`). `system_health` 처럼 자율성 를
`shadow_only` 로 상한 하므로 halt 중에는 어떤 액션 도 mutate 하지 않음
(HIL 로 human 경로 는 유지). 이 축 는
[`KillSwitch.is_engaged()`](../../../services/core-control-plane/src/fdai/shared/resilience/kill_switch.py)
가 `evaluate_execution_authority` 의 `kill_switch_engaged` 입력을 통해
공급함; 비상 정지 는 실행기 신원 없이 operable 함 (포크 가 그 상태를
상태 저장소 에 backing) -
[security-and-identity.md](../architecture/security-and-identity.md) 참고.
disengage 상태면 축 는 생략됨 (byte-identical 결과).

### 2.7 결합

각 입력은 위 4 수준 중 하나 반환; RiskGate 는 순서
`enforce_auto > enforce_hil > shadow_only > deny` 에서 **최소** 을
취함 (six 축 와 선택적 `system_health`, `kill_switch` fail-safe 축
전체 대상). 어느 입력 (risk-classification 표 포함) 의 `deny` 든 hard stop;
실행기 는 절대 호출 안 됨. `enforce_hil` 에 동반되는 `quorum` 은 표
정족수 과 axis-선언 정족수 의 최대값.

### 2.8 비용-증가 ops 액션

지출을 늘리는 `ops.*` 액션 (`ops.scale-out`, 더 큰 계층 로의
`ops.failover-primary`) 은 축 A (risk-classification 표) 가
`>= $100 -> hil` 게이트 를 적용할 수 있도록 ActionType 에
`cost_impact_monthly` 추정을 선언 MUST. 알 수 없음 이거나 임계값 초과
비용 추정을 가진 `ops.scale-out` 은 절대 `auto` 아님; 이는 `direct_api`
fast 경로 를 통해 우회될 수 있는 런타임 ops 에 대해 비용 거버넌스
버티컬 을 권위적으로 유지. 비용 거버넌스 버티컬
([verticals](../../../services/core-control-plane/src/fdai/core/verticals)) 이 추정 함수를 소유;
ActionType 은 그것을 참조만 함.

## 3. 통합 RiskGate

RiskGate 는
[`services/core-control-plane/src/fdai/core/risk_gate/`](../../../services/core-control-plane/src/fdai/core/risk_gate)
에 살고 **두** 트리거 표면 (룰-발화와 오퍼레이터-요청; see
[action-ontology.md § 4](action-ontology-ko.md#4-트리거-surface))
의 단일 결정 지점.

> 구현 상태: 순수 combinator 는
> [`ceiling.py`](../../../services/core-control-plane/src/fdai/core/risk_gate/ceiling.py) (6축),
> [`risk_table.py`](../../../services/core-control-plane/src/fdai/core/risk_gate/risk_table.py)
> (축 A first-match 표 + `rule-catalog/risk-classification.yaml`),
> [`feature.py`](../../../services/core-control-plane/src/fdai/core/risk_gate/feature.py)
> (`FeatureVector` 추출기) 로 ship 되고,
> [`authority.py`](../../../services/core-control-plane/src/fdai/core/risk_gate/authority.py)
> `evaluate_execution_authority()` 가 종단 간 로 통합. 이 함수가 단일
> 파이프라인 `feature -> table (Axis A) -> 6축 min() -> ExecutionAuthorityDecision`.
> [`ControlLoop`](../../../services/core-control-plane/src/fdai/core/control_loop/orchestrator.py) 이 두 모드로
> 호출한다. risk 표 만 배선된 경우 실행 액션당 `risk_gate.shadow_authority`
> 감사 엔트리 1개를 기록 (권한 전용, 판정자+로그, 실행기 경로 무변경).
> risk 표 과 기존
> [`gate.py`](../../../services/core-control-plane/src/fdai/core/risk_gate/gate.py) `RiskGate` 가
> 모두 배선된 경우, 게이트 (런타임 액션 안전: exemption / precondition /
> 승격) 와 권한 (정책 상한) 를
> [`evaluator.py`](../../../services/core-control-plane/src/fdai/core/risk_gate/evaluator.py)
> `combine()` 이 단일 `UnifiedRiskDecision` 으로 결합하고 (canonical-level
> `min()`, 두 평가기 무변경), 루프가 그 위에서 **라우팅**한다: `deny` 나
> `hil` 결정은 실행기 를 건너뛰고 (전체 결과 `DENIED` / `HIL`, PR 미발행),
> `auto` 만 실행으로 진행. 라우팅된 각 액션은 `risk_gate.unified` 감사
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

- **RiskGate 는 pure, 동기 함수로 유지.** 모든 I/O (실제 운영 탐색,
  `graph_derived` 영향 의 인벤토리 그래프 walk) 는 `evaluate` **이전**에
  수행되어 `live_probe_result` / 사전-resolve 된 영향 로 전달됨. 이는
  결정론성 (§7) 을 보존하고, `evaluate` 를
  [coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md#safety)
  의 비동기 경계 목록 밖에 두며, 기존 동기
  [`RiskGate.evaluate`](../../../services/core-control-plane/src/fdai/core/risk_gate/gate.py) 와 일치.
  탐색 사전-fetch 는 이미 비동기 인 ControlLoop / 조정기 에서 수행.
- **호환성 경계.** 런타임 안전성 게이트는 타입이 지정된
  `RiskDecision(outcome: RiskDecisionOutcome, ...)`를 유지하고 권한 평가기는
  `ExecutionAuthorityDecision`을 생성합니다. `evaluator.py`가 둘을
  `UnifiedRiskDecision`으로 결합하며 호출자는 원본 데이터 클래스의 staged 필드 이행이
  아니라 이 combined 계약을 사용합니다.
- `promotion_state` 는 기존
  [`ActionPromotionRegistry`](../../../services/core-control-plane/src/fdai/core/risk_gate/gate.py)
  로부터 읽기 - shadow-mode ActionType 은 축 가 permit 하는 것과 관계
  없이 `mode` 를 `shadow` 로 clamp.
- `execution_path` 는 ActionType 기본이나 축 (전형적으로 역할 또는
  env 축) 가 downgrade 강제 시 (예: compliance-heavy 포크 가 prod 의
  모든 direct-API ActionType 에 `pr_manual` 강제).
- RiskGate 는 **전달 시도 당 한 번** 호출. 재시도 의 re-check 는
  fresh 전달 (fresh 감사 항목).

### 3.1 오퍼레이터-콘솔 검증기 와의 상호작용

콘솔의 조정기 는 매 write-class 도구 호출 에서 RiskGate 를 재실행
([operator-console.md § 7.2](../interfaces/operator-console-ko.md#72-chat-특화-3-invariant),
불변식 5). 콘솔은 이 경로를 절대 우회하지 않음; "trusted 서술기
shortcut" 없음.

### 3.2 `ActionPromotionRegistry` 와의 상호작용

승격 은 RiskGate 와 직교:

- `ActionPromotionRegistry.mode_of(action_type)` 는 ActionType 이
  enforce-eligible 인지 결정.
- RiskGate 는 그것을 upper 한계 로 취하고 6 축 와 결합. 승격된
  ActionType 이 여전히 축 에 의해 `hil` 로 게이트 MAY; 승격 상태
  가 `auto` 를 강제하지 않음.

## 4. 실제 운영 영향 탐색

Static `blast_radius` 는 "이 ActionType 은 리소스 그룹 까지 영향 MAY" 말함;
실제 운영 탐색 는 "이 특정 리소스는 지난 5분 트래픽 0, 그러므로 실제 영향
없음" 말함. Static + 실제 운영 결합은 "실행 중인 NSG 룰 변경은 아무도
호출하지 않을 때 저-영향" 이라는 직관 뒤의 방식.

### 4.1 탐색 선언

탐색 는 [`rule-catalog/probes/`](../../../rule-catalog/probes) 아래 살음:

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

### 4.2 런타임 형태

RiskGate 는 탐색 를 **오직** 다음 시에만 호출:

- `ActionType.live_probe_ref` 가 집합.
- 다른 축 가 아직 `shadow_only` 또는 `deny` 로 강제하지 않음
  (탐색 비용 는 결정을 실제로 변경 가능할 때만 지불).
- 탐색 캐시가 대상 에 대해 fresh 답변 없음.

탐색 실패 처리 (fail toward 안전성). 탐색 는 *상한 을 낮추는* 축
이지 authorizer 가 아님. 단발 실패 (시간 초과, 어댑터 오류) 시 축 는
`active` 반환 - auto 대신 HIL 을 강제해 탐색 가 blind 인 동안 사람이
확인하게 하되, 오퍼레이터-개시 액션을 hard-stop 하진 않음. Rolling 구간 를
가로지르는 **반복** 실패 (기본 `cache_ttl_seconds * 5` 내 3회) 시 축 는
자신의 자세 를 `shadow_only` 로 에스컬레이트하고 `probe.degraded` 감사
항목 를 쓰기: 지속적으로 blind 한 탐색 는 그 ActionType 을 오퍼레이터가
inspect 할 때까지 실행 중단해야 함을 의미, 무한정 수작업 승인이 아님. 그래도
*전체* 루프 를 fail-close 하진 않음 - degraded 탐색 에 연결 된 ActionType 만.

**재생 는 기록된 결과를 사용, 재질의 안 함.** 디버깅/사개분석을 위해
감사 로그 를 재생 할 때 RiskGate 는 `live_probe_result` 를 기록된
`resolved_ceiling` (§8) 에서 읽기; 탐색 를 다시 호출 MUST NOT. 이는 재생 를
judge-only 이고 결정론적으로 유지
([architecture.instructions.md § 멱등성, 정렬, and 재생](../../../.github/instructions/architecture.instructions.md#idempotency-ordering-and-replay)).

### 4.3 탐색 어댑터 경계

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

업스트림 Day-1 는 가짜 `NoOpBlastProbe` (returns "no opinion") ship;
Month-1 은 `AzureMonitorBlastProbe` 추가. 포크 는 프로토콜 을 구현하는
어떤 어댑터 든 연결 MAY.

## 5. 실행기 경로

4 경로가 모든 액션 cover. 셋은 substrate-mutation 단계 구조 를 이룬다
(`pr_native`, `direct_api`, `pr_manual`); ActionType 이 하나를 이름 하고
RiskGate 는 `pr_manual` 로 downgrade MAY (업그레이드 절대 안 함). 네 번째
`tool_call` 은 별도의 함수-호출 표면이다 (§5.6) - 기반 를 mutate 하지
않으므로 그 단계 구조 에 놓이지 않는다.

### 5.1 PR-native (`pr_native`)

- 실행기 가 [`GitOpsPrAdapter`](../../../services/core-control-plane/src/fdai/delivery/gitops_pr/adapter.py) 로 PR 빌드.
- `auto` 결정 시, PR 은 `hil` 라벨 을 carry 안 함 → 가지 의 auto-merge 정책이 수용.
- `hil` 결정 시, PR 은 `hil` 라벨 을 carry → 승인자 가 콘솔로 병합.
- 감사 + 롤백 은 git 에 lean: revert 커밋 이 롤백 경로.
- PR-native 실행기는 발행기를 호출하기 전에 내용 기반 주소를 가진 예행 실행과 감사 의도를
  영속화합니다. 권위 있는 증적 없는 예외는 최종 `publish_outcome_unknown`을 기록하고
  성공 캐시에 넣지 않은 채 다시 전달합니다. 재시도는 같은 멱등성 키를 사용하므로
  발행기는 새 PR 생성 전에 원격에서 수락된 PR이 있는지 조정해야 합니다.

Best for: 구성 변경, IaC patch, 카탈로그 업데이트, 거버넌스 변경.

### 5.2 Direct API (`direct_api`)

- 실행기 가 기반 API 를 직접 호출 (Azure ARM, kubectl, `services/core-control-plane/src/fdai/delivery/` 아래 해당 전달 어댑터 를 통한 Redis).
- `auto` 결정 시, 호출 이 HIL 없이 진행되고 ActionType 의 `stop_conditions` 와 `preconditions` 가 호출 전후로 실행기 에 의해 강제 적용.
  어댑터는 모든 임계값, 구간, seconds, 개수 매개변수를 포함한 완전한 ordered stop-condition 튜플을 받으며 singular 문자열은 호환성 shorthand로만 유지.
- `hil` 결정 시, 실행기 가 HIL 항목 을 큐에 추가 (PR-manual 큐와 동일
  하지만 항목 에 `mutation_target=direct` 로); 승인자 가 콘솔로
  수용; 그 후 실행기 가 전달.
- Rollback 은 ActionType 의 `rollback_contract` 로부터 (`scripted`,
  `pitr`, `snapshot_restore`).
- **멱등성 불변식** - 매 direct-API 호출 은 액션의 안정된
  멱등성 키 사용 (기존 불변식
  [coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md));
  재시도 된 호출 이 double-apply MUST NOT.
- Shadow 관측은 영속 변경 원장을 채우지 않습니다. Process-local 캐시는
  멱등성 키와 모드를 함께 사용하므로, 이후 검토된 승격은 같은 액션을 강제 적용
  모드로 실행할 수 있습니다. 이전 방식 shadow 원장 행은 이 shadow-to-enforce 전환에서만
  무시되며 강제 적용 변경 증적은 계속 권위 있는하여 페이로드 충돌을 거부합니다.
- **업스트림 Azure 게이트웨이 연결** - 개발 operations 게이트웨이 URL과 Easy Auth 대상이
  모두 구성되면 headless 런타임은 enforce-capable `AzureGatewayDirectApiExecutor`를 연결합니다.
  이 어댑터는 `ops.start-vm`, `ops.deallocate-vm`, `ops.upsert-network-rule`,
  `ops.delete-network-rule`만 지원합니다. 각 ActionType은 shadow-first를 유지하며 shipped T0
  상한은 사람 승인을 요구합니다. Shadow는 서버 계획만 수행하고 변경하지 않으며 강제 적용은
  일회용 증적이 반환된 후에만 제출합니다.
- **Long-running 연산 잠금** - ARM `202`는 대상 Blob 임차 기간을 비공개 연산 기록에
  유지합니다. 실행기 상태 polling이 임차 기간을 renew하고 최종 상태를 ETag
  compare-and-swap으로 기록한 후 release합니다. 알 수 없는 상태 URL 조회 필드는 차단합니다.

Best for: 지연 시간 가 중요한 ops 액션 (재시작, 규모, 캐시 플러시).

### 5.3 PR-manual (`pr_manual`)

- PR-native 와 동일하지만 이 PR 에 대해 auto-merge 정책 비활성 (라벨
  `hil` + 명시적 `merge-not-eligible`).
- 축 와 관계없이 사람 검토 필수; 모든 축 에서 `enforce_auto` 라도
  여전히 manual-merge PR 로 landing.
- 매우 high-risk 액션 또는 자동화와 관계없이 모든 변경 이
  reviewable 차이 MUST 인 compliance-heavy 환경에 사용.

Best for: scripted 롤백 있는 irreversible 변경, 포크 가 자동화와
관계없이 두 번째 쌍 of eyes 를 원하는 거버넌스 변경.

### 5.4 전달 시 실행기 선택

```
requested_path = ActionType.execution_path
forced_path = RiskGate.resolved_ceiling.forced_execution_path  # 옵션 axis 출력
final_path = strictest(requested_path, forced_path)
                # 엄격 순서 (속도가 아닌 리뷰-엄격성 기준):
                #   pr_manual > pr_native > direct_api
```

여기서 "strictest" 는 가장 빠른이 아니라 **가장 사람-리뷰-gated** 를 의미:
`pr_manual` (필수 사람 병합) 이 `pr_native` (정책 auto-merge) 보다
엄격하고, 그것이 `direct_api` (차이 없음) 보다 엄격. 축 는 전달 를 이
사다리에서 **위로** (더 많은 리뷰 쪽으로) 만 이동 가능; 지연 시간 를 위해
아래로 절대 이동 못 함. 포크 는 env 축 를 통해 prod 의 모든 전달 를
`pr_manual` 로 강제 가능. 업스트림 은 절대 아래로부터 강제 안 함 (속도를
위해 `pr_manual` 을 `direct_api` 로 lift 안 함).

**대체 경로 멱등성.** `direct_api`는 side-effect 전 또는 권위 있는 no-effect 증적 후에만 고정된 멱등성 키로 `pr_manual` 대체 경로할 수 있습니다. 시간 초과, lost 응답 또는 accepted
비동기 요청은 연산 기록, 대상 잠금 및 pending 결과를 유지하며 권위 있는 상태를
조정합니다. 최종 증적 전에는 다른 변경 경로를 열지 않고 exhaustion은 자동화 보류로 escalate합니다.

### 5.5 사람 승인 왕복 (보류 and 재개)

RiskGate 가 `hil` 을 반환하면 실행기 는 실행되지 않고 컨트롤 루프 은
사람을 기다리며 블록 하지 않는다. `HilResumeCoordinator`
(`core/hil_resume`) 는 **보류 and return** 모델을 적용한다:

1. **보류** - 전체 `Action` (+ 룰 id, submitter, 상관관계 id) 을
   opaque `approval_id` 하에 `status=pending` 으로 `StateStore` 에
   직렬화;
2. **push** - `HilChannel` (Teams / Slack) 로 A1 승인 카드 전달;
   배달 실패는 액션을 parked + 복구 가능 상태로 남기며 실행하지 않음;
3. **감사** - `hil.requested` 엔트리 기록 후
   `ControlLoop.process(...)` 는 블록 없이 `hil` 반환.

이후 결정(ChatOps 콜백 또는 poll)이
`HilResumeCoordinator.resolve(approval_id, decision, approver_oid)` 를
구동한다:

- **APPROVE** - parked `Action` 을 복원(`model_validate`)해 동일한
  실행기 선택 (§5.4) 으로 재-dispatch; `hil.approved.executed`
  감사 엔트리 하나 기록.
- **거부** / **시간 초과** - 기록하되 실행 안 함 (실패 시 차단).
- **만료된 APPROVE** - 위임과 실행기 선택 전에 `expires_at`을
  확인한다. 만료 시각 이후의 승인은 atomic하게 `TIMEOUT`으로 해석하고
  `hil.timeout`을 기록하며 실행하지 않는다. 만료 기록은 읽기 담당 HIL 큐와
  `hil_pending` KPI 변환 결과에서 제외한다.
- **멱등적** - 첫 최종 결정이 보류를 해석하고, 중복은 no-op이며 상충 결정은
  거부되므로 승인이 double-apply될 수 없습니다.
- **승인 ID 점유** - parking은 ID와 requested 감사 기록을 원자적으로 점유합니다. 동일 재생은 채널 push 없이 기존 보류를 반환하고 다른 내용은 audited 충돌이 됩니다.
- **자기 승인 금지** - `approver_oid == submitter_oid`는 실행 전에 거부되며, 루프는
  system submitter 신원으로 보류하므로 실제 승인자는 항상 구별됩니다.

**Role-scoped 큐 + 위임 (시나리오 A).** parked HIL 항목은 개인별
인박스가 아니라 **큐**다: `Capability.APPROVE_RUNTIME_HIL` 을 가진 어떤
운영자 든 해석 할 수 있다. 보류 는 선택적 `assignee_oid` - 항목이
표면화된 대상 운영자, 기본값은 resolved on-call 기본 - 를 기록한다.
*다른* 권한 보유 운영자 가 승인하면 그것은 **delegated** 승인이다: 허용
(동일 권한)하되 별도로 기록하여, 감사 엔트리가 실제 `approver_oid` 와 원래
`assignee_oid` 를 모두 남긴다 (`delegation_mode` = `direct` / `delegated`
/ `role_scoped`). 이 게이트 는 조정기 와 Operator API 콜백 이 공유하는
하나의 순수 함수(`core/hil_resume/delegation.py`)라서 규칙이 두 진입점
사이에서 벌어지지 않는다. 거부는 실패 시 차단 를 유지한다: 빈 /
self-approving / 기능 없는 승인자 는 실행되지 않는다
(`missing_capability` 는 403 을 반환하고 보류 는 권한 있는 운영자 가
해석 할 수 있도록 남는다). Operator API 콜백 은 push 채널이 주장한
HMAC 서명된 `actor_roles` 로부터 `approver_can_approve_hil` 를 도출한다;
`actor_roles` 가 없으면 채널을 신뢰(기본 허용)하되 no-self-approval 과
HMAC 게이트 는 여전히 적용된다.

이것으로 `hil` 판정 (§2) 와 승인된 액션의 실제 실행 사이가, 차단
wait 나 게이트 없는 auto-execute 없이 이어진다. Operator API HIL 콜백
(`POST /hil/{approval_id}/decision`) 이 해석 트리거 를 구동한다:
인바운드 결정은 조정기 를 먼저 거치고(보류 경로 - `APPROVE` 는
실행기 로 재-dispatch), 보류 가 없으면 `approve_hil` 로 올라온
console-pull 승인을 위해 레지스트리 경로로 fall through 한다. 조정기 는
transport-neutral 이다. ChatOps 채널이 설정되면(`FDAI_CHATOPS_WEBHOOK_URL`)
`__main__` 이 이것을 컨트롤 루프 에 wire 하여 `hil` 판정 가 액션을 보류
하고 A1 카드를 push 한다; 없으면 루프 은 판정 를 기록하고 영속화된
큐 로 fall back 한다. Operator API 서버는 동일한 조정기 를 콜백
경로 에 공급하여 인바운드 결정이 보류 를 해석 한다.

**Notify-on-decision.** 동일한 루프 은 모든 최종 결정
(`executed` / `hil` / `denied`) 마다 알림 라우터 를 통해 A2
operational-alert 도 발행 한다 - outbound-only, 정보성이며 승인 버튼을
절대 싣지 않음 (
[channels-and-notifications-ko.md § 3](../interfaces/channels-and-notifications-ko.md)
참조). 라우터 는 선택적 경계 이다: 없으면 루프 은 이전과 정확히 동일하게
동작한다.

### 5.6 도구 호출 (`tool_call`)

- 실행기 가 **등록된 함수** - PDF 리포트 생성, 알림 발송, 티켓 오픈 -
  를 [`ToolExecutor`](../../../services/core-control-plane/src/fdai/shared/providers/tool.py) 프로토콜
  (`core/executor/tool_call.py` 의 `ToolCallShadowExecutor`) 로 invoke.
  클라우드 기반 를 mutate 하지 않고 **아티팩트** 또는 side 효과 를
  생산한다. LLM 이 도구 을 호출하는 방식의 온톨로지-네이티브 대응물이다:
  `tool.*` ActionType 이 등록된 도구 하나를 이름 하고 실행기 가 여기서
  전달. 도구 레지스트리 는 MCP 어댑터의 자연스러운 첨부 지점 다 -
  프로토콜 을 구현한 `McpToolExecutor` 가 MCP 서버 도구 하나를 `tool.*`
  ActionType 하나에 매핑한다.
- MCP 서버는 `McpServerCatalog`를 통해 등록합니다. 서버 매니페스트는 엔드포인트 및
  ActionType-to-tool 허용 목록을 검증하고 비활성화된 상태로 install되며 읽기 전용 `tools/list`
  발견이 모든 허용 목록에 있는 도구의 존재를 확인한 후에만 활성화할 수 있습니다. 공개
  엔드포인트는 HTTPS가 필요하고 HTTP는 loopback sidecar에만 허용됩니다. 페이로드 URL은 구성된
  서버 엔드포인트를 재정의하지 않습니다. Encoded 요청 및 응답 본문은 네트워크 전달
  또는 JSON 파싱 전에 서로 독립적인 hard 바이트 상한을 적용합니다. 두 활성화된 서버는 같은 ActionType을 소유할 수
  없습니다. 활성화된 카탈로그는 기존 `RoutingToolExecutor`에 경로를 project하며 새 실행
  경로를 만들지 않습니다.
- `core/` 는 프로토콜 만 안다; 포크 가 조립 루트 에서 실제 운영 어댑터
  (네이티브 Python 레지스트리, MCP 클라이언트, HTTP callout) 를 연결. 기본값
  연결 은 `RecordingToolExecutor` (실제 함수 실행 없음). 구성된
  `FDAI_JIRA_BASE_URL`은 PostgreSQL 멱등성 원장 및 distributed 리소스
  잠금과 함께 `JiraToolExecutor`를 연결합니다. ActionType 승격 게이트와
  `FDAI_JIRA_ENFORCE=1`이 모두 강제 적용을 허용하기 전까지 shadow를 유지합니다.
  강제 적용 creation은 결정론적 `fdai-idem-<sha256>` 라벨을 추가합니다. 게시 전에
  영속 pending 점유를 atomically 기록하고 Jira enhanced
  `/rest/api/3/search/jql` 엔드포인트에서 해당 라벨을 검색합니다.
  Create-before-ledger 비정상 종료 이후 재시도는 기존 issue를 조정하고
  `already_applied`를 반환할 수 있습니다. 이전 점유가 남았지만 Jira에서 issue가 아직
  보이지 않으면 중복 위험을 감수하지 않고 실패 시 차단합니다. 게시 전 검색
  실패와 definitive 생성 `4xx` 응답은 새로 획득한 점유를 release합니다.
  전송 계층 실패, `5xx` 응답, malformed successful 생성 응답은 side 효과가
  모호한하므로 점유를 격리 구역 상태로 유지합니다. 각 재시도는 Jira를 다시 검색하며,
  retryable 어댑터 실패는 감사하지만 코어 실행기 캐시에는 넣지 않습니다.
  `fdai-idem-` 라벨 이름 공간은 어댑터가 소유합니다. 요청이 해당 접두사로 제공한
  라벨은 제거하여 한 요청이 다른 키를 별칭하지 못하게 합니다. 감사 항목은
  액션의 실제 `shadow` 또는 `enforce` 모드를 기록합니다. 게시 전 취소는
  점유를 release하고 실패한 감사 항목을 기록한 뒤 다시 raise합니다. Core는 영속
  실행 결과를 기록한 뒤에만 in-memory dedupe 캐시를 채우므로 transient 영속
  쓰기 실패는 retryable 상태로 남습니다.
- `auto` 결정 시, HIL 없이 호출 진행하며 실행기가 ActionType 의 `preconditions` 와 `stop_conditions` 를 강제 적용.
  도구 어댑터는 첫 조건 이름만이 아니라 authored 매개변수를 모두 포함한 완전한 ordered stop-condition 튜플을 받음.
  범용 MCP 어댑터는 `time_box_exceeded_seconds`를 outer 전송 계층 기한으로 적용합니다.
  시간 초과는 롤백 미확인 상태의 `stopped`를 반환합니다. 다른 dynamic stop 조건을 가진
  강제 적용 요청은 한계 어댑터가 해당 평가기를 제공하지 않으면 네트워크 I/O 전에 거부됩니다.
  어댑터는 평가하지 않은 조건을 무시하지 않습니다.
- `hil` 결정 시, 실행기 가 액션을 보류 하고 `direct_api` 와 동일한 HIL
  왕복 (§5.5) 으로 승인 후 재개.
- Rollback 은 ActionType 의 `rollback_contract` 로부터 - 보통
  `state_forward_only` (생산된 아티팩트 삭제) 또는 `scripted`.
- **멱등성 불변식** - 매 도구 호출 은 액션의 안정된 멱등성
  키 를 사용; 재시도 호출 은 도구 을 재실행 MUST NOT (같은 키 의 두 번째
  호출 은 `already_applied` 반환).
- 7개 안전조건은 그대로 적용. `tool.*` ActionType 은 변경
  ActionType 과 똑같이 측정 가능한 `promotion_gate` 를 가진 shadow-first;
  실행기 는 시도당 정확히 하나의 감사 항목 를
  `action_kind=executor.tool_call.<outcome>` 와
  `execution_path=tool_call` 로 쓴다.
- `tool.open-incident-ticket`은 기본 제공 티켓 ActionType입니다. Shadow 증적은
  실제 티켓으로 링크되지 않습니다. 성공한 강제 적용 증적은 최종 실행기
  성공 전에 `link_ticket_receipt`를 통과하고 `incident.ticket`을 덧붙이기합니다.
  연결 실패는 retryable하며 성공으로 캐시되지 않습니다.

Best for: 문서 생성, 알림, 티켓팅, 그리고 워크플로 스텝이 PR 을 열거나
기반 를 건드리지 않고 `action_type_ref` 로 invoke 하려는 임의의 등록된
함수.

## 6. 7개 안전조건과 하나의 재생 확장

모든 executed 액션은 이미
[coding-conventions.instructions.md § 안전성](../../../.github/instructions/coding-conventions.instructions.md#safety)
의 7개 안전조건(stop-condition, 롤백, blast-radius 한도, 예행 실행, 리소스 잠금,
멱등성, 감사)을 carry. 이 문서는 재생 요구사항 하나를 추가:

- **매 전달 는 `resolved_ceiling` 을 쓰기.** 감사 항목 는
   결정을 생성한 완전한 6-axis breakdown (`risk_table` 축 포함) 을
   carry MUST -> 향후 오버레이 변경이 과거 결정의 재현성을 절대 break 안 함.

안전조건은 정확히 이전과 같이 적용 - chat-specific carve-out
없음, direct-API relaxation 없음.

### 6.1 오퍼레이터-콘솔 불변식 와의 상호작용

Chat-특화 불변식 ([operator-console.md § 7.2](../interfaces/operator-console-ko.md#72-chat-특화-3-invariant))
는 가산:

- **Chat safeguard 8 (검증기 re-check)** = "매 write-class 도구 호출
  에서 RiskGate 실행". 이 문서가 해당 RiskGate 의 정의; 콘솔은 그저
  호출.
- **Chat safeguard 9 (no 자기 승인)** = RiskGate 의 역할 축
  (축 F) 가 호출자 의 Entra `oid` 가 큐잉된 항목 의 요청자 와
  매치할 때 `approve_hil` refuse.
- **Chat safeguard 10 (BreakGlass time-boxed)** = 축 F 의 BreakGlass
  동작 (§2.5): BreakGlass 는 승인 을 위한 조건을 충족한 역할 을 raise
  하지만 HIL 을 절대 우회 안 함.

## 7. 결정론성 + 감사성

- 동일한 6-axis 입력이 주어지면 RiskGate 는 동일한 `RiskDecision`
  반환. 어떤 stochastic 구성요소 (moving 구간 를 조회 하는 탐색)
  든 탐색 의 `cache_ttl_seconds` 로 범위가 제한된 → TTL 내 재생 가
  identical 결정 yield.
- `resolved_ceiling` 블록은 결정의 완전한 self-explanation - 전달
  시점에 in 효과 였던 상한 이 기록 of truth 이므로 향후 오버레이
  변경이 과거 감사 항목 를 절대 invalidate 안 함.

## 8. `resolved_ceiling` 감사 블록

매 전달 는 쓰기:

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

`resolved_ceiling` 블록의 정확한 형태 (risk_table 축 와 정족수 포함) 은
`ontology/resolved-ceiling` JSON 스키마로 validate 되는 고정된 versioned
계약이며, §3 의 `RiskDecision` 마이그레이션과 함께 Week-1 스키마-확장 PR
에서 landing. 서술기 와 감사 소비자 가 verbatim 으로 렌더링 하므로
스키마-체크 된 형태 이 필수; 계약 테스트 가 매 전달 가 `risk_table`
축 포함 schema-valid 블록 을 발행 함을 assert.

## 9. 롤아웃 기록

구현 원장이 기존 날짜 기반 롤아웃 설명을 대체합니다. 스키마, 통합 RiskGate 라우팅,
타입이 지정된 제안 및 모의 경로 검사는 구현되어 있습니다. 남은 롤아웃 게이트는 위에
기록한 실제 탐색 및 경로 간 운영 근거입니다.

## 10. Testability

- **6-axis + 표 매트릭스** - 전체 카테시안 곱
  (`risk_table` x 계층 x 상한 x static_blast x live_blast x 역할 x env)
  은 조합적으로 크므로, 모음 는 determinate 값에 대한
  **pairwise (all-pairs)** 생성 + 명시적 hand-picked corner 사례 (any-`deny`
  short-circuit, irreversible-quorum, prod downgrade, BreakGlass-eligible)
  를 사용; 각 생성 행 는 `min()` 의미 규칙 와 어느 입력도 자율성 를
  raise 하지 않음을 assert.
- **오버레이 우선순위 + resolved_ceiling** - 동일 축 에 모든 네 오버레이
  계층 가 활성 인 고정본; higher-precedence 계층 승리 및
  `overlay_layers_applied` 아래 이름 등장 assert.
- **Live-probe 가짜** - `NoOpBlastProbe` 가 `quiet / 활성 /
  overloaded` 각각 반환; RiskGate 출력이 예상대로 변경.
- **실행기 경로 선택** - table-driven: ActionType.기본값 vs
  forced_path; strict-order winner assert.
- **Direct-API 멱등성** - 동일 키로 전달을 두 번 호출해도 기반 어댑터는
  변경을 하나만 기록합니다.
- **멱등성 충돌** - 각 키는 액션 지문에 연결됩니다. 다른 액션,
  대상, 룰 또는 안전성 입력은 충돌이고 같은 키 요청은 리소스 잠금 전에 직렬화됩니다.
- **PR-native + PR-manual auto-merge 정책** - 어댑터 가 발행 하는
  라벨 집합 에 대한 계약 테스트; 라벨 매트릭스 assert.
- **RiskDecision 은 권한 를 업그레이드 할 수 없음** - 속성 테스트:
  ActionType 의 `promotion_state=shadow` → RiskDecision.모드 는 다른
  모든 축 와 관계없이 항상 `shadow`.

## 11. 실패 모드

- **탐색 시간 초과 / 오류** -> 단발 실패는 `active`, 반복 실패는
  `shadow_only` 반환 (§4.2); `probe.degraded` 로그; 전체 루프 를
  fail-close 하지 않음.
- **오버레이 로드 오류** (Rego 구문 오류, 누락된 파일 오버레이
  대상) -> **업스트림 이 아니라 더 안전한 값으로 fail.** 실패한
  오버레이 가 *tightening* 오버레이 (포크 가 자율성 다운그레이드) 였으면
  RiskGate 는 더 느슨한 업스트림 기본으로 되돌리는 대신 last-known 조인
  상한 을 유지 (실패 시 차단); 실패한 loosening 오버레이 는 단지 더 엄격한
  업스트림 값을 그대로 둠. 어느 쪽든 `overlay.load_failed` 감사 를 쓰기
  하고 `overlay_layers_applied` 를 mark 하여 오버레이 가 applied 인 척 절대
  안 함.
- **실행기 경로 도달 불가** (side-effect 시도 전 direct_api 어댑터 down) -> 저-긴급 액션은
  `pr_manual` 로 대체 경로 하고 `executor.path.degraded` 쓰기. **latency-
  critical ops 액션** (`ops.restart-service`, `ops.failover-primary`,
  ActionType 이 `urgency: high` 설정한 것) 은 `pr_manual` 대체 경로 이
  목적을 무효화하므로, 대신 on-call 승인자 가 콘솔에서 수 초 내
  수용 할 수 있는 **direct HIL 항목** (`mutation_target=direct`) 으로
  큐에 추가; 대체 경로 과 그 이유가 `resolved_ceiling` 에 등장. 대체 경로 은
  액션의 멱등성 키 (§5.4) 를 재사용해 어느 경로도 double-apply 안 함.
- **RiskGate 자체 사용 불가** (일어나면 안 됨 - 입력의 pure 함수)
  -> fail-close: 전달 없음, `deny` 감사, operational 레인 페이지.

## 12. 관련 문서

- [action-ontology.md](action-ontology-ko.md) - 이 문서가 소비하는
  ActionType 스키마 + 포크 가 매트릭스를 tune 하는 재정의 경계.
- [operator-console.md](../interfaces/operator-console-ko.md) - RiskGate 는 콘솔의
  채팅 불변식 가 매 write-class 도구 호출 에 요구하는 검증기.
- [phase-2-quality-and-t1.md](../phases/phase-2-quality-and-t1-ko.md) -
  ActionType 을 shadow 에서 강제 적용 로 flip 하는 승격 파이프라인.
- [risk-classification.md](risk-classification-ko.md) - 6-axis 상한 이
  `min()` 으로 결합하는 권위적 first-match auto / HIL / 거부 표 (축 A,
  §2.0); 매트릭스로 대체되지 않음.
- [security-and-identity.md](../architecture/security-and-identity-ko.md) - 7개 안전조건 + 실행기
  신원 계약.
- [architecture.instructions.md](../../../.github/instructions/architecture.instructions.md) -
  trust 라우팅, 검증기 권한.
