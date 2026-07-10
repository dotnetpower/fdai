---
title: 리스크 분류 (auto vs HIL vs deny)
translation_of: risk-classification.md
translation_source_sha: f2ea058d103595c1a37913f1b1ac1c53be7ce18e
translation_revised: 2026-07-11
---

# 리스크 분류 (auto vs HIL vs deny)

리스크 게이트
([architecture.instructions.md § Control Loop](../../.github/instructions/architecture.instructions.md#control-loop))
는 모든 후보 액션을 `auto`, `hil`, `deny` 중 하나로 라우팅합니다. 이 문서는 **그 라우팅을
만드는 분류 규칙**에 대한 진실 원본입니다: 형상, 초기 규칙 테이블, 소유권, 업데이트 프로세스.
[security-and-identity-ko.md](security-and-identity-ko.md#open-decisions)의 P0 Open
Decision *"Risk-classification policy (auto vs HIL) and initial policy approver"*를 해결합니다.

> 고객-비종속: 아래 모든 값(비용 임계, 태그 키, 리소스 그룹 이름)은 상류의 **기본값** 입니다;
> 포크가 config로 튜닝합니다
> ([generic-scope.instructions.md](../../.github/instructions/generic-scope.instructions.md)).

## 테이블이 사는 곳

- **런타임 경로**: `rule-catalog/risk-classification.yaml` - catalog-as-code, 규칙/할당/예외/
  오버라이드처럼 PR로 리뷰. 모든 변경에 `aw-approvers` 리뷰어의 **elevated quorum of 2**
  ([user-rbac-and-identity-ko.md § 5.1](user-rbac-and-identity-ko.md#51-codeowners-single-approver-group-path-based-reviewer-count)).
- **정책 소유자**: `aw-owners` Entra 보안 그룹. 소유권은 Owner-티어에 있음 - 테이블이 전체
  자율성 표면을 게이팅.
- **평가**: first-match wins. 규칙은 가장 엄격(`deny`)부터 가장 관대(`auto`)로 정렬; 어느
  규칙과도 매칭되지 않는 케이스는 **`default: hil`** fail-close 엔트리로 fall through.

## Execution-Model 6-axis ceiling 과의 관계

이 테이블이 **권위적 baseline** 결정입니다. 통합 RiskGate
([execution-model.md](execution-model-ko.md))는 이 테이블을 `risk_table`
axis (Axis A)로 평가한 뒤 그 결과와 6개 ActionType-컨텍스트 ceiling axis
(tier, ActionType ceiling, static blast, live blast, role, env)의 `min()`
을 취합니다. 6-axis ceiling은 오직 autonomy를 **더 낮출**뿐, 이 테이블이
내린 결정을 override 하거나 raise 하지 않습니다. finding-수준 데이터가 필요한
신호 - `cost_impact_monthly`, `destructive`, `irreversible` (그 `quorum: 2`
포함), `data_plane_touched`, `verifier_confidence` - 는 **여기서만** 평가되며
ceiling axis는 의도적으로 이들을 재도출하지 않습니다. 두 개의 결정 엔진이
있는 것이 아니라: 이 테이블 + 그 위에 layer 된 절대-raise-안-하는 ceiling 입니다.

## 분류 차원

리스크 게이트는 이미 가지고 있는 온톨로지 신호로부터 모든 후보 액션에 대해 **특성 벡터**
를 구성합니다
([llm-strategy-ko.md § Rule-to-Decision Lookup Pipeline](llm-strategy-ko.md#rule-to-decision-lookup-pipeline)).
새로운 데이터 수집은 도입되지 않습니다.

| 차원 | 타입 | 소스 |
|------|------|------|
| `policy_violation` | bool | OPA/Rego verifier 판정 |
| `destructive` | bool | 온톨로지 `ActionType.operation ∈ {delete, drop, purge, detach}` |
| `irreversible` | bool | 온톨로지 `ActionType.irreversible == true` (롤백된 상태가 액션 이전 상태를 완전 복원 불가) |
| `blast_radius` | enum `resource` \| `resource_group` \| `subscription` | `applies_to` × 영향받은 리소스의 스코프; `ActionType.blast_radius.computation == graph_derived` 일 때 risk-gate가 Resource→Resource 링크(기본 `contains` + 역방향 `depends_on`, depth 2)를 walk 해서 영향받는 리소스 count를 bucket으로 매핑 |
| `rollback_path` | enum `pr_revert` \| `scripted` \| `pitr` \| `snapshot_restore` \| `state_forward_only` | `remediates` 액션의 롤백 계약 (`none`은 유효 값 아님 - 모든 ActionType이 undo 경로를 선언) |
| `reversible` | bool | `irreversible == false`의 지름길 |
| `environment` | enum `prod` \| `non-prod` | [Environment Detection](#environment-detection) 참조 |
| `data_plane_touched` | bool | 온톨로지 `ActionType.interfaces`가 `DataPlaneMutating` 포함 |
| `graph_stale` | bool | `ActionType.interfaces`에 `RequiresInventoryFresh` 포함 AND 대상 Resource의 인벤토리 레코드가 `freshness_ttl` 초과 |
| `cross_resource_impact` | int | `ActionType.blast_radius.computation == graph_derived` ⇒ traversal이 반환한 영향받는 Resource count; `GraphTraversalRequired` 없고 그래프 또한 없으면 `unknown` |
| `cost_impact_monthly` | number (USD/월) | 규칙의 `remediation.cost_impact` 추정, 또는 관찰된 사후 정산 |
| `verifier_confidence` | number [0..1] | LLM quality-gate 신호 (T2 생산 액션에만 설정) |

차원은 엄격하게 타입 지정; 알려지지 않은 키를 참조하는 규칙은 CI 로드에서 실패합니다.

## 초기 규칙 테이블 (상류 기본)

```yaml
# rule-catalog/risk-classification.yaml (상류 기본; 포크는 임계값 튜닝 가능)
version: 1.0.0
owner_group: aw-owners
rules:
  # ── DENY (절대 실행 안 함) ──
  - if: { policy_violation: true }
    decision: deny
    reason: "policy-as-code verifier rejected the action"
  - if: { blast_radius: subscription }
    decision: deny
    reason: "no autonomous change spans a full subscription"
  - if: { graph_stale: true }
    decision: deny
    reason: "inventory graph is stale; refuse to act on a possibly-ghost resource"

  # ── HIL (사람 승인 필요) ──
  - if: { irreversible: true }
    decision: hil
    reason: "irreversible mutation always requires an approver quorum >= 2"
    quorum: 2
  - if: { destructive: true }
    decision: hil
    reason: "delete/drop/purge/detach always requires an approver"
  - if: { environment: prod, allowlist_prod_auto: false }
    decision: hil
    reason: "prod defaults to HIL unless the rule is on the prod-auto allowlist"
  - if: { data_plane_touched: true }
    decision: hil
    reason: "data-plane mutations always require an approver"
  - if: { cost_impact_monthly: '>= 100' }
    decision: hil
    reason: "cost impact above the auto threshold"
  - if: { blast_radius: resource_group }
    decision: hil
    reason: "RG-wide changes require an approver"
  - if: { verifier_confidence: '< 0.85' }
    decision: hil
    reason: "T2 quality-gate confidence below auto threshold"

  # ── AUTO (승인 없이 실행) ──
  - if:
      all:
        - reversible: true
        - blast_radius: resource
        - cost_impact_monthly: '< 100'
        - data_plane_touched: false
    decision: auto
    reason: "reversible, resource-scoped, low cost, control-plane only"

  # ── FAIL-CLOSE ──
  - default: hil
    reason: "no matching rule - fail toward safety"
```

**규칙 순서 (MUST)**: `deny` 규칙이 먼저, 다음 `hil`, 다음 `auto`, 다음 `default: hil`
catch-all. First-match wins이므로 가장 엄격한 적용 가능한 규칙이 지배합니다. CI가 순서를
검증(deny가 hil보다 앞, hil이 auto보다 앞)하고 선행 광범위 규칙에 의해 dead-code가 될 수
있는 규칙을 거부합니다.

## 환경 감지(Environment Detection)

이 섹션은 전체 컨트롤 플레인에 대한 **단일 권위적 환경 classifier** 입니다.
[execution-model.md](execution-model-ko.md) (env axis, `ActionType.prod_downgrade.detection_ref`
경유)와 [action-ontology.md](action-ontology-ko.md) (`env_scope`) 모두 이
규칙을 통해 "prod" vs "non-prod"를 resolve 하며, 두 번째 정의를 통하지
않습니다.

`environment: prod` vs `non-prod`는 대상 **리소스 그룹 태그** 에서 파생됩니다:

- 태그 키: `environment` (대소문자 무시)
- 값: `prod` / `production` → `prod`; `non-prod` / `dev` / `test` / `staging` / `qa` →
  `non-prod`
- **누락 또는 인식되지 않은 태그 → `prod`** (fail-safe: 알려지지 않은 환경은 최고 리스크
  카테고리로 취급)

강제: Azure Policy 할당이 `environment` 태그 없이 리소스 그룹 생성을 거부해야 하며, 그래서
거버넌스된 환경에서는 fail-safe 경로가 절대 적용되지 않습니다. 정책 할당은
[phase-1-rule-catalog-t0-ko.md](phases/phase-1-rule-catalog-t0-ko.md)의 Phase 1 산출물입니다.

## 환경 승격(Environment Promotion, 핸드오프 대상)

위의 binary `prod` / `non-prod` 축은 authoritative 런타임 분류기입니다. dev-to-ops
핸드오프 게이트([operational-readiness.md](operational-readiness-ko.md))는 런타임 축이
싣지 않는 한 가지가 필요합니다: 방향(direction). 그것은 `ownership_transfer` signal 의
**대상(target)** environment 를 읽고, 그 이전이 *prod 를 향한* 승격인지로 gate 합니다.

단일 정의를 유지하기 위해, lifecycle 단계는 분류기가 이미 인식하는 정확한 태그 값에 대한
순서(ordering) 입니다 - 새 태그 없음, second classifier 없음:

`dev < test < staging < qa < prod`

- `dev`, `test`, `staging`, `qa` 단계는 모두 런타임 축에서 `non-prod` 로 resolve 됩니다;
  순서는 핸드오프 시점에 "대상 단계가 `prod` 인가" 만 답하는 데 사용됩니다.
- **대상 단계가 `prod`** 인 이전은 production 으로의 승격입니다: ORR 은 활성 프로파일
  기본값과 무관하게 어떤 `critical` finding 도 `blocking` 으로 취급하며, `prod_downgrade`
  와 동일한 fail-safe posture 를 재사용합니다(downgrade 는 절대 autonomy 를 올리지 않음).
- 누락 또는 인식되지 않은 대상 단계는 `prod` 로 resolve 됩니다(Environment Detection 과
  동일한 fail-safe). 따라서 태그 없는 핸드오프는 가장 엄격한 수준에서 gate 됩니다.
- 순서는 절대 autonomy 를 넓히지 않습니다: 더 낮은 대상 단계가 런타임 축이 gate 했을 auto
  경로를 unlock 하지 않습니다.

순서는 ORR 게이트만 consume 하는 문서 수준 계약입니다; `risk-classification.yaml` 에
런타임 축을 추가하지 않습니다. 런타임 리스크 테이블은 여전히 `environment: prod | non-prod`
만 봅니다.

## 비용 영향 임계값

- **Auto 상한**: 액션당 **$100 / 월**.
- 근거: 큰 폐기를 승인하지 않으면서 작은 right-sizing / stop-idle / tier-adjust remediation을
  커버. Phase 1 shadow 측정을 위해 보수적으로 선택; 임계값은 config 값이며 측정 후 governance
  PR로 조정 가능.
- 추정은 규칙의 `remediation.cost_impact` 필드에서; 규칙이 추정 못 하면 값은 `unknown` →
  `>= 100`으로 취급 → HIL.

## Prod-Auto Allowlist

극소수의 매우 낮은 리스크 규칙은 prod에서 auto 자격 표시될 수 있음(`allowlist_prod_auto: true`).
초기 allowlist 후보 (승격 전 shadow에서 평가):

- 태그 remediation (누락된 owner / cost-center / environment 태그 추가).
- 미부착 public IP 주소 해제.
- 데이터 평면 노출 없는 리소스의 NSG allow-any-source 규칙 제거.

**모든 allowlist 엔트리는 별도 승격된 할당** 이며 표준 shadow → enforce 게이트를 통과합니다
([architecture.instructions.md § Shadow → Enforce Promotion](../../.github/instructions/architecture.instructions.md#safety-invariants)).
Allowlist는 bypass가 아니라 prod 기본의 opt-in 감소입니다.

## 변경 프로세스

리스크 테이블 업데이트는 표준 governance PR 흐름을 따릅니다:

- **모든 변경**은 **quorum of 2** `aw-approvers`와 PR 본문의 `Justification:` 블록 필요.
- **완화 변경** (auto 확대, 비용 임계 상승, deny 제거)은 quorum에 Owner-티어 리뷰어(`aw-owners`
  멤버) 필요.
- **강화 변경** (deny 추가, 비용 임계 하락, auto→HIL 이동)은 일반 quorum으로 머지 가능 -
  안전-측 변경은 Owner 승인이 필요 없음.
- 테이블 버전은 모든 변경에 bump되고 카탈로그 버전에 캡처되어, 어떤 과거 액션을 분류한 리스크
  결정도 재구성 가능
  ([llm-strategy-ko.md § Signature Composition](llm-strategy-ko.md#signature-composition)).

## 감사

모든 리스크 게이트 결과는 다음을 기록하는 감사 엔트리를 씁니다:

- 매칭된 규칙 id (또는 fail-through 시 `default`).
- 결정 시점의 특성 벡터 스냅샷.
- `risk-classification.yaml`의 `catalog_version`.
- 라우팅 결과 (`auto` / `hil` / `deny`)와 하류 승인 id.

향후 회고에서 매칭 규칙 id로 감사 로그를 필터링하여 과도하게 트리거된 규칙(예: "모든 prod
변경이 HIL - 모든 것이 Rule 5에 걸림")을 식별하고, 같은 governance PR 흐름을 통해 개선을
제안할 수 있습니다.

## Open Decisions

- [ ] 향후 차원으로 `time_of_day` 게이트(업무 시간 vs 비업무 시간)를 추가할지 - shadow
      측정이 실제 필요를 보일 때까지 연기.
- [ ] 결정론적 규칙 테이블에 더해 숫자 `risk_score`를 계산할지 (동점에서만 또는 tie-breaker
      로만 작동 - 결정론 테이블이 여전히 권위).
- [ ] 포크 오버라이드 정책: 포크가 상류 기본을 *완화* (예: 비용 임계 상승)할 수 있는가, 아니면
      강화만 가능한가? 권장 기본: 강화는 무료, 완화는 감사된 Owner override 필요.
