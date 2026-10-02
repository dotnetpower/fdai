---
title: 위험 분류 (자동 실행 vs 사람 승인 vs 차단)
translation_of: risk-classification.md
translation_source_sha: 0c344ec8e9cae2d8522f042126f9677804ea1432
translation_revised: 2026-10-02
---

# 위험 분류 (자동 실행 vs 사람 승인 vs 차단)

리스크 분류 테이블
([architecture.instructions.md § 컨트롤 루프](../../../.github/instructions/architecture.instructions.md#control-loop))
은 모든 후보 액션의 기준선을 `auto`, `hil`, `deny` 중 하나로 분류합니다. 통합 RiskGate는
6-axis 상한을 적용해 최종 결과를 `shadow`까지 낮출 수 있습니다. 이 문서는 **기준선
분류 규칙**의 진실 원본입니다: 형상, 초기 규칙 테이블, 소유권, 업데이트 프로세스.
[security-and-identity-ko.md](../architecture/security-and-identity-ko.md#open-decisions)의 P0 열림
결정 *"Risk-classification 정책 (auto vs HIL) and initial 정책 승인자"*를 해결합니다.

> 고객-비종속: 아래 모든 값(비용 임계, 태그 키, 리소스 그룹 이름)은 상류의 **기본값** 입니다;
> 포크가 구성으로 튜닝합니다
> ([generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md)).
## 테이블이 사는 곳

- **런타임 경로**: `rule-catalog/risk-classification.yaml` - catalog-as-code, 규칙/할당/예외/
  오버라이드처럼 PR로 리뷰. 저장소 CODEOWNERS는 GitHub `fdai-owners` team을 지정합니다.
  `aw-approvers` 2인 정족수는 배포의 가지 protection/CI가 적용하는 거버넌스 계약입니다
  ([user-rbac-and-identity-ko.md § 5.1](../interfaces/user-rbac-and-identity-ko.md#51-codeowners-single-approver-group-path-based-reviewer-count)).
- **정책 소유자**: `aw-owners` Entra 보안 그룹. 소유권은 Owner-티어에 있음 - 테이블이 전체
  자율성 표면을 게이팅.
- **평가**: first-match wins. 규칙은 가장 엄격(`deny`)부터 가장 관대(`auto`)로 정렬; 어느
  규칙과도 매칭되지 않는 케이스는 **`default: hil`** fail-close 엔트리로 fall through.

## Execution-Model 6-axis 상한 과의 관계

이 테이블이 **권위적 기준선** 결정입니다. 통합 RiskGate
([execution-model.md](execution-model-ko.md))는 이 테이블을 `risk_table`
축 (축 A)로 평가한 뒤 그 결과와 6개 ActionType-컨텍스트 상한 축
(계층, ActionType 상한, static 영향, 실제 운영 영향, 역할, env)의 `min()`
을 취합니다. 6-axis 상한은 오직 자율성을 **더 낮출**뿐, 이 테이블이
내린 결정을 재정의 하거나 raise 하지 않습니다. finding-수준 데이터가 필요한
신호 - `cost_impact_monthly`, `destructive`, `irreversible` (그 `quorum: 2`
포함), `data_plane_touched`, `verifier_confidence` - 는 **여기서만** 평가되며
상한 축은 의도적으로 이들을 재도출하지 않습니다. 두 개의 결정 엔진이
있는 것이 아니라: 이 테이블 + 그 위에 계층 된 절대-raise-안-하는 상한 입니다.

상시 권한은 `hil` 기준 판정을 `auto`로 높이거나 매칭된 규칙을 변경하지 않습니다. 대신 정확한
A3-E 경계가 계속 유효하고 에스컬레이션 기한이 지난 후 사람이 미리 작성한 Approval을
제공합니다. Thor는 승인된 HIL 작업을 실행할 수 있으며 감사에는 원래 위험 규칙, 승인 ID,
상시 권한 ID 및 권한 등급이 유지됩니다. 해당 Approval 없이 침묵만 발생하면 no-op으로
종료됩니다. [에스컬레이션 및 상시 권한](escalation-and-standing-authority-ko.md)을 참조하세요.

### 전권 개발 프로필

계획된 단독 운영자 프로덕션 프로필은 이와 다른, 더 좁은 예외입니다. 이 프로필은 운영 설치 하나에서
지정된 운영자 한 명이 승인과 정족수를 충족하게 하지만, 이 테이블의 위험 등급과 차단은 그대로
유지합니다. [운영자 거버넌스 프로필](operator-governance-profiles-ko.md)을 참조하세요.

이 프로필은 다른 위험 테이블 규칙이 아니라 별도의 개발 권한 축입니다. 테이블은 계속 기준
판정을 계산하고 기록하지만, 만료되지 않은 정확한 프로필 결속과 유일한 Owner의 현재 승인이
있으면 전용 테스트 범위 안에서 등록된 모든 작업 범주를 허용할 수 있습니다. 결속된 테스트
구독 안의 구독 전체 Azure 변경, 파괴적 또는 비가역적 작업, Chaos, ActionType 또는 Workflow
승격, 강등 및 롤백을 포함합니다. 알 수 없는 작업, 범위 이탈, 신원 불일치 또는 감사, 잠금 및
멱등성 근거 누락은 계속 실행할 수 없습니다. 공유 계약은 불변이며 테넌트, 구독 및 선택적인
리소스 그룹 신원에 다이제스트만 사용합니다. 배포 구성은 프로필, 현재 Owner 확인 및 별도
실행기 신원을 명시적으로 주입해야 합니다. Var와 Thor는 원래 위험 및 정족수를 유지하면서
개발 환경의 유효 정족수 1을 기록합니다. 개발 승격은 정확한 프로필 네임스페이스에만 기록되고
`production_ready: false`로 표시됩니다. Core가 권위 있는 원본을 제공합니다. Core는 직접 만든
Action, 결정론적 예행 실행 증적 및 선택된 프로필로 각 결속을 준비하고 감사 기록과 함께 한 번만
기록하며, 현재 기록된 결속만 검증합니다. 배포는 `FDAI_FULL_AUTHORITY_DEVELOPMENT_PROFILE_JSON`과
별도 실행기 주체로 프로필을 선택하고, ControlLoop와 Pantheon은 같은 원본을 공유합니다.
ControlLoop는 이벤트에 담긴 확인을 받아들이지 않습니다. Owner 본인의 운영자 요청이 사람 승인으로
라우팅되면 Core는 정확한 대상 revision을 읽고, 보류할 정확한 Action의 결속을 기록하며, 다이제스트로
결속한 개발 블록을 보류 기록에 씁니다. 이 블록은 원래 수준과 정족수, 유효 정족수 1, 대상 revision,
dry-run 및 범위 다이제스트, 승인된 실행기 신원을 보존하며, 승인 카드는 이 정확한 사실을 Owner에게 표시합니다. Owner는 Entra에 새로 로그인한 뒤 FDAI Console 승인 대기열에서
승인합니다. Operator는 보류 이후이면서 10분 이내인 서명된 `auth_time`을 요구하고, 결정 트랜잭션은
잠긴 보류 행을 기준으로 예외를 다시 검증합니다. Core는 영속 Operator 영수증과 결속을 다시 읽고 대상
revision이 바뀌지 않았음을 확인하며 공유 평가기가 현재 ActionType을 포함해 재구성한 확인을 수락한 뒤에만
이를 허용합니다. Owner의 결정이 해당 승인의 유일한 영수증이므로 자기 승인이 거부되면 Core는 거부 사유와 함께
보류 항목을 닫고, Owner는 요청을 다시 제출할 수 있습니다.
Owner 본인 요청의 범주 전용 거부는 거부하지 않고 보류합니다. 일치하는 모든 거부 규칙이
ActionType 범주 차원(영향 범위, 파괴성, 가역성, 롤백 경로 또는 데이터 평면 변경)만 조건으로
삼고, 그 규칙을 뺀 테이블이 거부하지 않으며, 거부하는 상한 축이 `risk_table`과
`static_blast`뿐이고, 다른 모든 축이 이미 사람 승인을 허용하며, 런타임 게이트 자체가 거부하지
않고, 현재 근거에 충돌이 없으며, 개발 경로의 모든 안전 및 근거 전제 조건이 충족될 때만 범주
전용입니다. 상류 테이블에서는 `deny-subscription-blast`만 이에 해당합니다. 결속이
결정적인 direct-API dry-run 영수증을 기록하므로 Core는 등록된 direct-API
ActionType만, 프로필이 유효한 동안에만 보류하며 워크플로 단계는 보류하지 않습니다. 제공되는 구독
범위 ActionType인 `governance.retire-rule`은 `pr_native`이므로 거부가
유지됩니다. 결속 범위는 대상 위치를 선언된 영향 범위까지 넓힌 범위입니다. 영향 범위가 구독 전체이거나,
선언되지 않았거나, 그래프에서 파생되면 전용 구독 전체가 필요하며, 리소스 그룹만 결속한 프로필은 이를
포함하지 않습니다. 허용 단계는 더 좁은 결속을 거부합니다. 블록은 원래 `deny`, 범주 사실, 평가에
사용한 이벤트를 기록하고, 범주 규칙을 제외했을 때 테이블이 요구하는 정족수를 원래 정족수로 기록하며,
보류를 Owner 전용으로 표시합니다. Operator, 결정 트랜잭션 및 Core는 각각 Owner의
증명된 자기 승인 외의 모든 승인을 거부합니다. 반려는 권한을 부여하지 않으므로 요청한 Owner를 포함한
모든 권한 있는 승인자는 이를 반려할 수 있으며, 응답이 없는 보류는 만료됩니다. 일반 재개 claim이
허용된 자기 승인을 디스패치하기 전에 ControlLoop는 전체 현재 평가를 다시 실행합니다. 현재
인벤토리, 실행 권한 부여, 킬 스위치, 성능 저하, 승격 상태, 근거 충돌, 사전 조건, live
probe 및 위험 테이블이 같은 모드에서 같은 범주 전용 거부와 잔여 정족수를 계속 산출해야 하며 대상
revision도 바뀌지 않아야 합니다. 다른 모든 거부와 프로필 또는 범위 밖의 모든 거부는 계속
거부합니다. 프로필 안에서는 일회용 리소스 재생성이 범위가 정해진 복구 경로입니다. 근거가 하나라도 없으면
일반 여러 운영자 승인으로 보류합니다. 런타임 Owner 검사는 프로필이 유효한 동안 프로필의 Owner
주체만 허용합니다. 감사에는 원래 역할, 정족수, 자기 승인 차단 규칙을 보존하고 가상의 신원을 만들지 않은
채 유효 개발 정족수 1을 기록합니다. 타입이 지정된 권한 레코드는 공개 계약 모델 facade를 사용하며
다이제스트 도우미는 권한을 추가하지 않습니다. 프로필, 결속 원본, 현재 Owner 검사 또는 구분된 실행기
중 하나라도 없으면 기존 자기 승인 차단 규칙을 유지하고, Slack과 Teams는 Owner의 자기 승인을
전달하지 않으며, 다른 개발 보류에 대한 본인 반려는 기존 차단 규칙을 유지합니다. 실제 Owner 실행
기록을 보존하기 전까지 기능 상태는 `in-progress`입니다. 집중 검사는 실제 배포 또는 프로덕션
준비 상태를 입증하지 않습니다.

## 분류 차원

리스크 게이트는 이미 가지고 있는 온톨로지 신호로부터 모든 후보 액션에 대해 **특성 벡터**
를 구성합니다
([llm-strategy-ko.md § Rule-to-Decision 조회 파이프라인](../architecture/llm-strategy-ko.md#rule-to-decision-lookup-pipeline)).
새로운 데이터 수집은 도입되지 않습니다.

| 차원 | 타입 | 소스 |
|------|------|------|
| `policy_violation` | bool | OPA/Rego 검증기 판정 |
| `destructive` | bool | 온톨로지 `ActionType.operation ∈ {delete, drop, purge, detach}` |
| `irreversible` | bool | 온톨로지 `ActionType.irreversible == true` (롤백된 상태가 액션 이전 상태를 완전 복원 불가) |
| `blast_radius` | enum `resource` \| `resource_group` \| `subscription` | `applies_to` × 영향받은 리소스의 스코프; `ActionType.blast_radius.computation == graph_derived` 일 때 risk-gate가 Resource→Resource 링크(기본 `contains` + 역방향 `depends_on`, 깊이 2)를 walk 해서 영향받는 리소스 개수를 버킷으로 매핑 |
| `rollback_path` | enum `pr_revert` \| `scripted` \| `pitr` \| `snapshot_restore` \| `state_forward_only` | `remediates` 액션의 롤백 계약 (`none`은 유효 값 아님 - 모든 ActionType이 undo 경로를 선언) |
| `reversible` | bool | `irreversible == false`의 지름길 |
| `environment` | enum `prod` \| `non-prod` | [환경 감지 방법](#환경-감지환경-detection) 참조 |
| `data_plane_touched` | bool | 온톨로지 `ActionType.interfaces`가 `DataPlaneMutating` 포함 |
| `graph_stale` | bool | `ActionType.interfaces`에 `RequiresInventoryFresh` 포함 AND 대상 Resource의 인벤토리 레코드가 `freshness_ttl` 초과 |
| `cross_resource_impact` | int | `ActionType.blast_radius.computation == graph_derived` ⇒ 탐색이 반환한 영향받는 Resource 개수; `GraphTraversalRequired` 없고 그래프 또한 없으면 `unknown` |
| `cost_impact_monthly` | number (USD/월) | 규칙의 `remediation.cost_impact_monthly_usd` 추정, 또는 관찰된 사후 정산 |
| `verifier_confidence` | number [0..1] | LLM quality-gate 신호 (T2 생산 액션에만 설정) |

차원은 엄격하게 타입 지정; 알려지지 않은 키를 참조하는 규칙은 CI 로드에서 실패합니다.

## 초기 규칙 테이블 (상류 기본)

```yaml
# rule-catalog/risk-classification.yaml (상류 기본; 포크는 임계값 튜닝 가능)
version: 1.0.0
owner_group: aw-owners
rules:
  # ── DENY (절대 실행 안 함) ──
  - id: deny-policy-violation
    if: { policy_violation: true }
    decision: deny
    reason: "policy-as-code verifier rejected the action"
  - id: deny-subscription-blast
    if: { blast_radius: subscription }
    decision: deny
    reason: "no autonomous change spans a full subscription"
  - id: deny-graph-stale
    if: { graph_stale: true }
    decision: deny
    reason: "inventory graph is stale; refuse to act on a possibly-ghost resource"

  # ── HIL (사람 승인 필요) ──
  - id: hil-irreversible
    if: { irreversible: true }
    decision: hil
    reason: "irreversible mutation always requires an approver quorum >= 2"
    quorum: 2
  - id: hil-destructive
    if: { destructive: true }
    decision: hil
    reason: "delete/drop/purge/detach always requires an approver"
  - id: hil-prod
    if: { environment: prod, allowlist_prod_auto: false }
    decision: hil
    reason: "prod defaults to HIL unless the rule is on the prod-auto allowlist"
  - id: hil-data-plane
    if: { data_plane_touched: true }
    decision: hil
    reason: "data-plane mutations always require an approver"
  - id: hil-cost
    if: { cost_impact_monthly: '>= 100' }
    decision: hil
    reason: "cost impact above the auto threshold"
  - id: hil-resource-group-blast
    if: { blast_radius: resource_group }
    decision: hil
    reason: "RG-wide changes require an approver"
  - id: hil-low-confidence
    if: { verifier_confidence: '< 0.85' }
    decision: hil
    reason: "T2 quality-gate confidence below auto threshold"

  # ── AUTO (승인 없이 실행) ──
  - id: auto-low-risk
    if:
      all:
        - reversible: true
        - blast_radius: resource
        - cost_impact_monthly: '< 100'
        - data_plane_touched: false
    decision: auto
    reason: "reversible, resource-scoped, low cost, control-plane only"

  # ── FAIL-CLOSE ──
  - id: default-hil
    default: hil
    reason: "no matching rule - fail toward safety"
```

**규칙 순서 (MUST)**: `deny` 규칙이 먼저, 다음 `hil`, 다음 `auto`, 다음 `default: hil`
catch-all. First-match wins이므로 가장 엄격한 적용 가능한 규칙이 지배합니다. CI가 순서를
검증(거부가 hil보다 앞, hil이 auto보다 앞)하고 선행 광범위 규칙에 의해 dead-code가 될 수
있는 규칙을 거부합니다.

## 환경 감지(환경 Detection)

이 섹션은 전체 컨트롤 플레인에 대한 **단일 권위적 환경 classifier** 입니다.
[execution-model.md](execution-model-ko.md) (env 축, `ActionType.prod_downgrade.detection_ref`
경유)와 [action-ontology.md](action-ontology-ko.md) (`env_scope`) 모두 이
규칙을 통해 "prod" vs "non-prod"를 해석 하며, 두 번째 정의를 통하지
않습니다.

`environment: prod` vs `non-prod`는 대상 **리소스 그룹 태그** 에서 파생됩니다:

- 정본 태그 키: Terraform base tag 집합이 기록하는 `fdai:env`.
- 호환성 키: namespaced tag 이전 리소스를 위해 `environment`와 `Environment`도
  수락합니다. 둘 다 있으면 `fdai:env`가 우선합니다.
- 값: `prod` / `production` → `prod`; `non-prod` / `dev` / `test` / `staging` / `qa` →
  `non-prod`
- **누락 또는 인식되지 않은 태그 → `prod`** (fail-safe: 알려지지 않은 환경은 최고 리스크
  카테고리로 취급)

강제: Azure Policy 할당이 `fdai:env` 태그 없이 리소스 그룹 생성을 거부해야 하며, 그래서
거버넌스된 환경에서는 fail-safe 경로가 절대 적용되지 않습니다. 정책 할당은
[phase-1-rule-catalog-t0-ko.md](../phases/phase-1-rule-catalog-t0-ko.md)의 단계 1 산출물입니다.

## 환경 승격(환경 승격, 핸드오프 대상)

위의 binary `prod` / `non-prod` 축은 권위 있는 런타임 분류기입니다. dev-to-ops
핸드오프 게이트([operational-readiness.md](../operations/operational-readiness-ko.md))는 런타임 축이
싣지 않는 한 가지가 필요합니다: 방향(direction). 그것은 `ownership_transfer` 신호 의
**대상(대상)** 환경 를 읽고, 그 이전이 *prod 를 향한* 승격인지로 게이트 합니다.

단일 정의를 유지하기 위해, 수명 주기 단계는 분류기가 이미 인식하는 정확한 태그 값에 대한
순서(정렬) 입니다 - 새 태그 없음, second classifier 없음:

`dev < test < staging < qa < prod`

- `dev`, `test`, `staging`, `qa` 단계는 모두 런타임 축에서 `non-prod` 로 해석 됩니다;
  순서는 핸드오프 시점에 "대상 단계가 `prod` 인가" 만 답하는 데 사용됩니다.
- **대상 단계가 `prod`** 인 이전은 운영 으로의 승격입니다: ORR 은 활성 프로파일
  기본값과 무관하게 어떤 `critical` 발견 사항 도 `blocking` 으로 취급하며, `prod_downgrade`
  와 동일한 fail-safe 자세 를 재사용합니다(downgrade 는 절대 자율성 를 올리지 않음).
- 누락 또는 인식되지 않은 대상 단계는 `prod` 로 해석 됩니다(환경 Detection 과
  동일한 fail-safe). 따라서 태그 없는 핸드오프는 가장 엄격한 수준에서 게이트 됩니다.
- 순서는 절대 자율성 를 넓히지 않습니다: 더 낮은 대상 단계가 런타임 축이 게이트 했을 auto
  경로를 unlock 하지 않습니다.

순서는 ORR 게이트만 consume 하는 문서 수준 계약입니다; `risk-classification.yaml` 에
런타임 축을 추가하지 않습니다. 런타임 리스크 테이블은 여전히 `environment: prod | non-prod`
만 봅니다.

## 비용 영향 임계값

- **Auto 상한**: 액션당 **$100 / 월**.
- 근거: 큰 폐기를 승인하지 않으면서 작은 right-sizing / stop-idle / tier-adjust 교정을
  커버. 단계 1 shadow 측정을 위해 보수적으로 선택; 임계값은 구성 값이며 측정 후 거버넌스
  PR로 조정 가능.
- 추정은 규칙의 `remediation.cost_impact_monthly_usd` 필드에서; 규칙이 추정 못 하면 값은 `unknown` →
  `>= 100`으로 취급 → HIL.

## Prod-Auto 허용 목록

극소수의 매우 낮은 리스크 규칙은 prod에서 auto 자격 표시될 수 있음(`allowlist_prod_auto: true`).
초기 허용 목록 후보 (승격 전 shadow에서 평가):

- 태그 교정 (누락된 소유자 / cost-center / 환경 태그 추가).
- 미부착 공개 IP 주소 해제.
- 데이터 평면 노출 없는 리소스의 NSG allow-any-source 규칙 제거.

**모든 허용 목록 엔트리는 별도 승격된 할당** 이며 표준 shadow → 강제 적용 게이트를 통과합니다
([architecture.instructions.md § Shadow → 강제 적용 승격](../../../.github/instructions/architecture.instructions.md#safety-invariants)).
허용 목록은 bypass가 아니라 prod 기본의 명시적 선택 감소입니다.

## 변경 프로세스

리스크 테이블 업데이트는 표준 거버넌스 PR 흐름을 따릅니다:

- **모든 변경**은 **정족수 of 2** `aw-approvers`와 PR 본문의 `Justification:` 블록 필요.
- **완화 변경** (auto 확대, 비용 임계 상승, 거부 제거)은 정족수에 Owner-티어 리뷰어(`aw-owners`
  멤버) 필요.
- **강화 변경** (거부 추가, 비용 임계 하락, auto→HIL 이동)은 일반 정족수로 머지 가능 -
  안전-측 변경은 Owner 승인이 필요 없음.
- 테이블 버전은 모든 변경에 bump되고 카탈로그 버전에 캡처되어, 어떤 과거 액션을 분류한 리스크
  결정도 재구성 가능
  ([llm-strategy-ko.md § 서명 조립](../architecture/llm-strategy-ko.md#signature-composition)).

### 커밋 게이트가 증명하는 것

승인 정족수는 branch protection에 있어 로컬 체크아웃에서 읽을 수 없으므로,
[`check-risk-table-change.py`](../../../scripts/quality/architecture/check-risk-table-change.py)는
차이(diff)로 판정되는 절반만 적용합니다. 테이블을 건드리는 모든 커밋에서 다음을 요구합니다:

- 엄격히 증가하는 `MAJOR.MINOR.PATCH` 버전. 그래야 어떤 변경도 자신이 대체한 리비전의
  버전을 달고 감사 페이로드에 도달하지 않습니다.
- 변하지 않는 `owner_group`. 테이블의 blast radius가 요구하는 Owner 계층에서 소유권을
  조용히 옮기는 테이블 편집을 막습니다.
- 모든 규칙의 비어 있지 않은 `reason`. PR `Justification:` 블록의 파일 내 절반입니다.
- 고유한 규칙 id, 정확히 하나의 fail-close `default`, 그리고 그 기본값이 마지막에 위치.
  기본값이 위로 흘러가면 어떤 규칙도 매치하지 않은 경우를 더 이상 잡지 못합니다.
- 완화 변경에는 최소 **minor** 버전 bump. 재현된 감사 기록이 보여주는 것은 카탈로그
  버전뿐이므로, patch bump 뒤에 숨은 완화는 몇 달 뒤 오타 수정과 구분되지 않습니다.

방향 분류는 fail-closed입니다. 판정 확대, 가드레일 규칙 제거, 정족수 하향, 매치 조건 편집,
규칙 재정렬은 모두 완화로 셉니다. first-match 평가에서는 게이트가 그중 어느 것도 테이블을
좁힌다고 증명할 수 없기 때문입니다. 증명 가능한 안전-측 편집만 강화로 보고되므로, 알아보지
못한 편집 형태는 검토 기준을 낮추는 대신 높입니다. 게이트는 리뷰어 정족수나 Owner 계층
리뷰어를 확인했다고 주장하지 않으며, 해당 변경에 무엇이 필요한지를 출력합니다.

## 감사

현재 control-loop 감사 엔트리는 다음을 기록합니다:

- 매칭된 규칙 id (fail-through 시 `default-hil`).
- 최종 결정 (`auto` / `hil` / `shadow` / `deny`)과 정족수.
- 최종 결정에 기여한 모든 축을 담은 `resolved_ceiling`.
- 해당 액션을 분류한 `risk-classification.yaml` 리비전의 `catalog_version`.
- 설정되지 않은 차원까지 포함한 `feature_vector` 스냅샷. 신호가 없었던 것인지
  누락된 것인지 구분할 수 있습니다.
- `ceiling_inputs` 블록: 해석된 역할, 그래프 기반 영향 개수, 기록된 live probe
  관측값과 연속 실패 횟수, 그리고 `system_degraded` 와 `kill_switch_engaged` 안전 플래그.

마지막 세 항목이 재현을 자기완결적으로 만듭니다. 기록된 페이로드는 자신이 명시한
테이블 버전과 자신이 담은 입력으로 다시 평가되므로, 이후 카탈로그 변경이 과거 판정을
조용히 바꿔 쓸 수 없고 재현이 live probe를 다시 조회하지도 않습니다.

향후 회고에서 매칭 규칙 id로 감사 로그를 필터링하여 과도하게 트리거된 규칙(예: "모든 prod
변경이 HIL - 모든 것이 Rule 5에 걸림")을 식별하고, 같은 거버넌스 PR 흐름을 통해 개선을
제안할 수 있습니다.

## 열림 Decisions

- [ ] 향후 차원으로 `time_of_day` 게이트(업무 시간 vs 비업무 시간)를 추가할지 - shadow
      측정이 실제 필요를 보일 때까지 연기.
- [ ] 결정론적 규칙 테이블에 더해 숫자 `risk_score`를 계산할지 (동점에서만 또는 tie-breaker
      로만 작동 - 결정론 테이블이 여전히 권위).
- [ ] 포크 오버라이드 정책: 포크가 상류 기본을 *완화* (예: 비용 임계 상승)할 수 있는가, 아니면
      강화만 가능한가? 권장 기본: 강화는 무료, 완화는 감사된 Owner 재정의 필요.

## 관련 문서

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| 구현 상태 및 남은 작업 | [구현 원장](../../roadmap-implementation/decisioning/risk-classification.md) |
