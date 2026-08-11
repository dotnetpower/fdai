---
title: Fork Example Vertical - 새 비즈니스 오브젝트 end-to-end
translation_of: downstream-fork-example-vertical.md
translation_source_sha: dfdb3c93558d3a5f0f9de3e93de58aaef5d515b2
translation_revised: 2026-08-11
---

# 포크 예시 버티컬: 새 비즈니스 오브젝트 종단 간

FDAI 위에 **새 비즈니스-오브젝트 버티컬**을 배포하는 포크를 위한
구체적인 walkthrough - 배포된 복원력 / 변경 안전성 / 비용
거버넌스 버티컬이 커버하지 않는 업무 카테고리. 대표 예시:
아키텍처-리뷰 제안 흐름, compliance-attestation 레코드 흐름,
incident-postmortem 작업 흐름.

이 문서는 범용 **`GovernanceProposal`** 예시를 사용 - 하나 이상의
영향 리소스를 지정하는 제안 레코드로, 영향 리소스에 따라
검토자 세트로 라우팅되고, 승인 후 결정 문서를 발행. 패턴은 포크에
필요한 어떤 non-Resource ObjectType 수명 주기로도 일반화됩니다.

**이 walkthrough의 성격**: [downstream-fork-seam-recipes-ko.md](downstream-fork-seam-recipes-ko.md)
에서 필요한 모든 recipe를 참조하며 stitch한 투어. Recipe 본문은
재수록하지 않으므로 두 파일을 나란히 열어두세요.

**이 문서가 아닌 것**: 작업 흐름 도구 배포에 대한 green light가 아님.
아래 §8은 제안 흐름을 프로덕션 자율성으로 취급하기 전에 포크가
반드시 내려야 하는 설계 결정을 다룹니다.

**업스트림의 작동 참조**: 이 walkthrough는 풀-lifecycle 패턴 (검토자와
결정을 가진 제안 흐름). **최소 작동 shipped 예제**는 더 작고
single-shot: 오퍼레이터가 이름으로 요청하는 on-demand `resource-group`
**변경 요약**. 전체 아티팩트 세트가 이미 업스트림 트리에 있고
[`services/core-control-plane/tests/verticals/test_change_summary_example.py`](../../../services/core-control-plane/tests/verticals/test_change_summary_example.py)
가 검증:

| 조각 | 위치 |
|--------|------|
| ObjectType | [`rule-catalog/vocabulary/object-types/ChangeSummary.yaml`](../../../rule-catalog/vocabulary/object-types/ChangeSummary.yaml) |
| LinkType | [`rule-catalog/vocabulary/link-types/summarizes.yaml`](../../../rule-catalog/vocabulary/link-types/summarizes.yaml) |
| ActionType | [`rule-catalog/action-types/ops.publish-change-summary.yaml`](../../../rule-catalog/action-types/ops.publish-change-summary.yaml) |
| Rule | [`rule-catalog/catalog/ops.change-summary.yaml`](../../../rule-catalog/catalog/ops.change-summary.yaml) |
| Rego | [`policies/change_summary/publish_change_summary.rego`](../../../policies/change_summary/publish_change_summary.rego) |
| 템플릿 | [`rule-catalog/remediation/change_summary/publish_change_summary.tftpl`](../../../rule-catalog/remediation/change_summary/publish_change_summary.tftpl) |

이 6개-파일 scaffold를 복사해서 자기 비즈니스 오브젝트로 이름 변경 하면
작동 시작점을 갖게 됨. 아래 전체 walkthrough는 작업 흐름이 수명 주기 (검토자,
승인 정족수, 결정 발행)을 필요로 할 때 single-shot 리포트가 아닌 그 위에
무엇이 자라나는지 보여줌.

**Contents**

1. [개요와 설계 제약](#1-개요와-설계-제약)
2. [온톨로지 (ObjectType + LinkType)](#2-ontology-objecttype--linktype)
3. [신호 소스](#3-signal-소스)
4. [ActionType 카탈로그](#4-actiontype-카탈로그)
5. [Rule 카탈로그](#5-rule-카탈로그)
6. [전달 어댑터 (결정 발행기)](#6-delivery-adapter-결정-publisher)
7. [읽기 패널](#7-read-panel)
8. [`entry.py`에서 배선](#8-entrypy에서-wiring)
9. [Shadow-first 승격 경로](#9-shadow-first-승격-경로)
10. [Anti-pattern](#10-anti-pattern)

## 1. 개요와 설계 제약

**목표**: "제안이 열림"을 "올바른 검토자가 배정되고, 결정이
기록되고, 결과 문서가 발행됨"으로 변환 - 안전한 곳에서는 자율,
그렇지 않은 곳에서는 HIL.

**FDAI 모델 내 fit**:

| FDAI 개념 | 거버넌스 제안 예시 |
|---|---|
| ObjectType | `GovernanceProposal`, `Reviewer`, `ApprovalDecision` |
| 신호 | `governance.proposal.opened`, `governance.review.received` |
| Rule | "영향 컴포넌트에 기반해 검토자 배정" |
| ActionType | `governance.assign-reviewers`, `governance.publish-decision` |
| 전달 어댑터 | Confluence 페이지 발행기 (또는 Word / Markdown PR) |
| HIL 채널 | 검토자는 Teams Adaptive 카드로 결정 |
| 읽기 패널 | 최근 결정 대시보드 |

**설계 제약 (포크 MUST 준수)**:

- **Deterministic-first**: 검토자 라우팅은 T0 룰이지 LLM 호출이
  아님. 컴포넌트-오너 매핑은 포크 룰 카탈로그의 조회 테이블.
- **Shadow-first**: 모든 신규 ActionType은 `default_mode: shadow`
  배포. §9가 승격 다룸.
- **읽기 전용 콘솔**: 대시보드는 상태를 project; 승인은 콘솔 버튼에서
  오지 않음.
- **수명 주기당 하나의 작업 흐름 ObjectType**: 상태 필드
  (`draft` -> `under_review` -> `approved` / `rejected` -> `published`)
  는 `GovernanceProposal` 자체에 배치. 배포된 `Finding` 타입에
  두지 말 것 - 감사 로그는 추가 전용, non-mutable 유지.
- **Approver 신원 ≠ 실행 신원**: 검토자는 Teams로
  승인; 실행기가 결정을 적용. 별개의 principal
  ([security-and-identity-ko.md](../architecture/security-and-identity-ko.md) 참조).

## 2. 온톨로지 (ObjectType + LinkType)

Recipe 참조:
[seam-recipes 5.8a](downstream-fork-seam-recipes-ko.md#58a-ontology-objecttype--linktype-추가).

**새 ObjectType** (`fork/vocabulary/object-types/` 아래):

- `GovernanceProposal` - 작업 흐름 오브젝트. `state`,
  `affected_components`, `submitted_at`, `decision_ref` (nullable) 보유.
  `key: id`.
- `Reviewer` - 투표할 MAY 하는 신원. `key: id`. 포크의 IdP sync가
  populate (Entra 그룹 -> 검토자 인스턴스).
- `ApprovalDecision` - 한 검토자 투표의 변경할 수 없는 레코드. `key: id`.
  여러 `ApprovalDecision` 인스턴스가 제안 결과로 집계;
  집계는 T0 룰이지 `GovernanceProposal`의 변경 가능한 필드가 아님.

**새 LinkType** (`fork/vocabulary/link-types/` 아래):

- `affects: GovernanceProposal -> Resource` (M:M). 제안 페이로드가
  populate; 검토자 라우팅을 driven.
- `assigned_reviewer: GovernanceProposal -> Reviewer` (M:M).
  assign-reviewers ActionType이 populate.
- `decides_on: ApprovalDecision -> GovernanceProposal` (M:1,
  temporal_order: true). 각 표결은 결정 순간을 시각.

**Anti-pattern**: `state` LinkType (`state_of` 등) 추가. 상태는
`GovernanceProposal`의 속성이지 간선이 아님. LinkType은 객체
신원들 간의 관계를 모델링.

## 3. 신호 소스

신호는 `event-ingest`에 들어가는 기본 요소. 제안 흐름에서 포크는
두 신호 타입을 발행:

- `governance.proposal.opened` - 제안 제출됨 (GitHub PR에
  `proposal` 라벨, 양식 게시, Slack 작업 흐름). 페이로드는 제안 id,
  submitter id, 영향 리소스 id 리스트를 반드시 포함.
- `governance.review.received` - 검토자 투표됨 (Teams Adaptive 카드
  콜백). 페이로드는 제안 id, 검토자 id, 결정 (`approve` /
  `reject`), 자유 텍스트 정당화를 반드시 포함.

**신호가 컨트롤 루프에 도달하는 방법**: 배포된 `EventBus` 경계의
포크 Kafka 토픽에 publish. 업스트림의 `event-ingest` 모듈이 배포된
`event/1.0.0` 스키마에 대해 페이로드를 정규화하므로 커스텀 ingest 코드는
불필요 - 포크의 생산자는 스키마에 매칭되는 JSON만 게시.

**멱등성**: 각 신호는 고정된 id (`gov.proposal.<uuid>` /
`gov.review.<uuid>`)를 가져야 합니다. 배포된 deduplication은 재전달이 동일 side 효과를
두 번 적용하지 않게 하며, 실패한 처리를 성공한 것으로 가장하지 않습니다.

**스키마 note**: 배포된 `event/1.0.0` 스키마는 범용 (페이로드는 열림
객체). 포크 편집 불필요. 포크는 어댑터 테스트 안에서 페이로드 형태에
대한 자체 JSON 스키마 조각을 등록 MAY 하지만 코어는 그것들을
검증하지 않음.

## 4. ActionType 카탈로그

Recipe 참조:
[seam-recipes 5.12](downstream-fork-seam-recipes-ko.md#512-actiontype-카탈로그-추가).

두 ActionType이 작업 흐름을 커버. `fork/action-types/` 아래에 배포.

### 4.1 `governance.assign-reviewers`

```yaml
# fork/action-types/governance.assign-reviewers.yaml
schema_version: "1.0.0"
name: governance.assign-reviewers
version: "1.0.0"
operation: update
interfaces: [ControlPlane, IdempotentByKey, RequiresInventoryFresh]
rollback_contract: state_forward_only
irreversible: false
default_mode: shadow
promotion_gate:
  min_shadow_days: 14
  min_samples: 30
  min_accuracy: 0.98
  max_policy_escapes: 0
preconditions:
  - kind: graph_fresh_within_seconds
    value: 300
  - kind: link_exists
    link_type: affects
  - kind: no_conflicting_open_action_on_resource
stop_conditions:
  - kind: provider_api_error_streak
    count: 3
  - kind: time_box_exceeded_seconds
    seconds: 300
blast_radius:
  computation: static_enum
  static_bucket: resource
description: Assign the deterministic reviewer set for one governance proposal.
category: governance
trigger_kind:
  kind: rule_violation
execution_path: pr_native
ceiling_by_tier:
  t0: { max_autonomy: enforce_hil, min_role: approver }
  t1: { max_autonomy: shadow_only, min_role: approver }
  t2: { max_autonomy: shadow_only, min_role: approver }
prod_downgrade:
  mode: enforce_hil
  detection_ref: risk-classification/env-detector
```

검토자 배정은 non-destructive이므로 롤백은 `state_forward_only`입니다.
잘못된 배정은 superseding 배정 기록으로 교정합니다. `IdempotentByKey`와
`no_conflicting_open_action_on_resource`가 동일 제안 재처리를 제한합니다.

### 4.2 `governance.publish-decision`

```yaml
# fork/action-types/governance.publish-decision.yaml
schema_version: "1.0.0"
name: governance.publish-decision
version: "1.0.0"
operation: create
interfaces: [ControlPlane, DataPlaneMutating, IdempotentByKey, RequiresInventoryFresh]
rollback_contract: pr_revert  # publisher가 retraction 페이지 발행
irreversible: false
default_mode: shadow
promotion_gate:
  min_shadow_days: 21
  min_samples: 20
  min_accuracy: 0.99
  max_policy_escapes: 0
preconditions:
  - kind: graph_fresh_within_seconds
    value: 300
  - kind: resource_property_equals
    property: state
    value: approved
  - kind: no_conflicting_open_action_on_resource
stop_conditions:
  - kind: provider_api_error_streak
    count: 3
  - kind: time_box_exceeded_seconds
    seconds: 300
blast_radius:
  computation: static_enum
  static_bucket: resource
description: Publish the approved decision artifact for one governance proposal.
category: governance
trigger_kind:
  kind: rule_violation
execution_path: pr_native
ceiling_by_tier:
  t0: { max_autonomy: enforce_hil, min_role: approver }
  t1: { max_autonomy: shadow_only, min_role: approver }
  t2: { max_autonomy: shadow_only, min_role: approver }
prod_downgrade:
  mode: enforce_hil
  detection_ref: risk-classification/env-detector
```

`rollback_contract: pr_revert`가 Confluence 발행기의 retract-page
경로와 매핑 (§6). 추가 전용 스토어 (locked SharePoint 라이브러리의
Word 문서)에 publish 하는 포크는 대신 `state_forward_only`를 사용하고
대체 하는 결정 위에 재발행을 블록 하는 `stop_conditions` 엔트리를
추가.

## 5. Rule 카탈로그

Recipe 참조:
[seam-recipes 5.8](downstream-fork-seam-recipes-ko.md#58-rule-catalog-추가).

두 룰이 작업 흐름을 driven.

### 5.1 검토자 라우팅 (T0)

```yaml
# fork/rules/governance.assign-reviewers.yaml
schema_version: "1.0.0"
id: fork-x.governance.assign-reviewers
version: "1.0.0"
source: custom
severity: medium
category: compliance
resource_type: governance.proposal   # 아래 caveat 참조
check_logic:
  kind: rego
  reference: policies/fork-x/governance/assign_reviewers.rego
remediation:
  template_ref: remediation/fork-x/governance/assign_reviewers.yaml
  cost_impact_monthly_usd: 0
remediates: governance.assign-reviewers
provenance:
  source_url: https://example.com/governance-baseline
  resolved_ref: "0000000000000000000000000000000000000000"
  content_hash: "sha256:0000000000000000000000000000000000000000000000000000000000000000"
  license: LicenseRef-reference-only
  redistribution: reference-only
  retrieved_at: "2026-07-08T00:00:00Z"
```

**`resource_type` caveat**: 배포된 룰 로더는 `resource_type`을
ResourceType 레지스트리 (built-in `Resource` ObjectType의 subtype
레지스트리)에 대해 검증. 업스트림 로더가 등록된 어떤 ObjectType이든
받도록 일반화되기 전까지 포크는 두 옵션:

1. **포크의 자체 vocabulary 확장에서 제안 subtype을 ResourceType
   엔트리로 모델링** (`fork/vocabulary/resource-types-fork.yaml`를
   별도 `load_resource_type_registry_from_mapping` 호출로 로드해서
   업스트림과 concatenate). 이름이 오도적이지만 (클라우드 리소스가
   아님) 메커니즘은 작동.
2. **업스트림 issue를 열어 `Rule.target_object_type` 필드 추가**.
   Rule 로더를 fork-patch 하지 말 것; cross-reference는 load-time
   오타 가드.

옵션 1은 첫 번째 shipping; 옵션 2가 cleaner long-term 방향이고
업스트림 설계 통과를 블록.

### 5.2 결정 발행 (T0)

```yaml
# fork/rules/governance.publish-decision.yaml
schema_version: "1.0.0"
id: fork-x.governance.publish-decision
version: "1.0.0"
source: custom
severity: medium
category: compliance
resource_type: governance.proposal
check_logic:
  kind: rego
  reference: policies/fork-x/governance/publish_decision.rego
remediation:
  template_ref: remediation/fork-x/governance/publish_decision.yaml
  cost_impact_monthly_usd: 0
remediates: governance.publish-decision
provenance:
  source_url: https://example.com/governance-baseline
  resolved_ref: "0000000000000000000000000000000000000000"
  content_hash: "sha256:0000000000000000000000000000000000000000000000000000000000000000"
  license: LicenseRef-reference-only
  redistribution: reference-only
  retrieved_at: "2026-07-08T00:00:00Z"
```

두 룰 모두 `policies/fork-x/governance/` 아래 정책을 배포. Rego는
제안이 올바른 상태 (검토자 배정을 위해 `under_review`, 발행을
위해 정족수 충족한 `approved`)인지 평가하고 결정론적 판정 반환.
**이 결정 경로에는 어떤 LLM 호출도 닿지 않음** - 순수 상태-기계 로직.

## 6. 전달 어댑터 (결정 발행기)

Recipe 참조:
[seam-recipes 5.13](downstream-fork-seam-recipes-ko.md#513-delivery-adapter-커스텀-publisher).

`governance.publish-decision` ActionType이 렌더된 결정 페이로드를
포크의 발행기에 전달. 최소 Confluence 페이지 발행기는
`fork/adapters/confluence_publisher.py` 아래 위치 (코드는 recipe 5.13
참조).

**결정 발행에서 페이로드가 carry 하는 것**:

- `title` - `"Governance Decision: <proposal-id>"`
- `body` - 템플릿된 Markdown / storage-format XML. 필드는 온톨로지
  에서 옴: 제안 요약, 영향 컴포넌트 리스트, 검토자 투표, 최종
  결과, 정당화. **모든 필드는 결정론적 온톨로지 데이터** - 배포된
  템플릿에 LLM narrative 없음.
- `diff` - 문서 발행기에는 미사용; 업스트림이 `RemediationPr`
  페이로드의 빈 차이를 tolerate.
- `labels` - `("governance", "decision", proposal.state)`.

**Narrative 필드 (선택)**: 포크가 LLM-생성 executive 요약을
원하면, 배포된 quality 게이트 (5.7)와 abstain-on-ungrounded 룰을 통해
생성을 라우팅 MUST. 온톨로지 필드를 인용할 수 없는 요약은 폐기
되고 페이지는 요약 없이 발행. LLM에게 판정을 쓰게 하지 말 것;
판정은 결정론적.

## 7. 읽기 패널

Recipe 참조:
[seam-recipes 5.14](downstream-fork-seam-recipes-ko.md#514-console-readpanel-추가).

`/panels/governance/decisions`의 `GovernanceDecisionsPanel`이 마지막
N개 제안을 다음과 함께 리스트:

- 제안 id + submitted-at
- 검토자 세트 (`assigned_reviewer` 링크에서)
- 결정들 (`decides_on` 링크에서, 시각 정렬)
- 현재 상태 + 발행된 결정 페이지 링크 (`decision_ref`에서)

패널은 포크가 감사 로그에서 유지하는 **변환 결과 저장소**에서 읽음;
실제 운영 Confluence API나 실행 중인 컨트롤 루프에서 읽지 않음. mount +
레지스트리 편집은 recipe 5.14 참조.

## 8. `entry.py`에서 배선

Recipe 참조:
[seam-recipes 5.15](downstream-fork-seam-recipes-ko.md#515-fork-진입점-entrypy).

포크의 `entry.py`가 조립:

1. Base 경계를 위해 `default_container_from_env()`.
2. 온톨로지 concatenation (ObjectType + LinkType) - recipe 5.8a.
3. ActionType concatenation (업스트림 + `fork/action-types/`) -
   recipe 5.12.
4. Rule concatenation (업스트림 + `fork/rules/`) - recipe 5.8.
5. `_finalize_llm_bindings`를 통한 `wire_azure_container` - recipe 5.1.
6. 포크 발행기 (`ConfluencePagePublisher`) - recipe 5.13.
7. 포크 HIL 채널 (`TeamsHilChannel`) - recipe 5.5.
8. 포크 읽기 패널 (`GovernanceDecisionsPanel`) - recipe 5.14.
9. Kafka 이벤트 루프 실행을 위한 업스트림의 `_consume`.

Entry-point recipe (5.15)가 골격을 제공; 포크는 위 7 항목을
순서대로 그 골격에 wire.

**Composition-root 순서 중요**: ObjectType이 LinkType 전에 로드
MUST (LinkType이 ObjectType cross-reference), ActionType이 Rule 전에
로드 MUST (Rule이 `remediates`를 통해 ActionType cross-reference).
Recipe 5.15의 골격이 이 순서를 존중.

## 9. Shadow-first 승격 경로

두 포크 ActionType 모두 `default_mode: shadow` 배포. 강제 적용으로 승격은
`promotion_gate` 블록이 green인 것을 게이트로 하는 **별도 PR**이고 한
필드를 flip.

**`governance.assign-reviewers`에 대한 구체 게이트**:

- 14 shadow 일 관찰된.
- 룰을 통해 라우팅된 제안 최소 30개.
- 룰이 생성한 검토자 세트가 운영자가 선택한 검토자 세트와
  >= 98% 일치.
- 제로 policy-violation escape (shadow 룰이 필수 범위가 없는
  검토자를 배정하려 했던 제안).

**측정 방법**: 배포된 감사 로그가 모든 shadow-mode 판정을
would-be 액션과 함께 기록. 포크의 측정 작업 (cron, Container App
Jobs, 처음 몇 번은 수동 notebook)이 각 shadow 창 끝에 비교 쿼리 실행.
4개 기준 모두 green -> 별도 PR이 `default_mode: enforce`로 flip 되고
shadow 증거에 대해 리뷰됨.

**회귀 demote**: 강제 적용 후, 포크의 KPI 대시보드가 룰
정밀도가 승격 하한 아래로 떨어짐을 보이면, demote 경로는
모드를 다시 `shadow`로 flip 하는 same-shape PR. 오늘 auto-demote 없음;
포크의 on-call이 회귀 경보를 읽고 PR 제출.

## 10. Anti-pattern

- **Recipe 5.8a 건너뛰고 ObjectType을 룰 매개변수 dict에 밀어
  넣기**. Rule은 여전히 fire 되지만 assurance twin, 운영자 콘솔,
  어떤 커스텀 전달 어댑터도 그 오브젝트에 전달 불가.
  Ontology-first가 전체 요점.
- **`GovernanceProposal.state`를 audit-log 필드로 만들기**. 감사
  로그는 추가 전용; 상태 전이는 오브젝트에 있고, 전이 자체가
  자체 감사 행을 생성하는 신호로 발행.
- **T2 (LLM)를 통한 검토자 라우팅**. 여기서 어떤 T2 호출도 red
  플래그 - 컴포넌트-오너 매핑은 결정론적 테이블 조회이지 reasoning이
  아님. 검토자 세트가 진짜로 모호하면 올바른 결과는 HIL
  (`escalate`)이지 LLM 추측이 아님.
- **모든 것을 하나의 거대한 포크 PR로 번들링**. §8 순서로 포크를
  shipping: 온톨로지 먼저, ActionType 둘째, 룰 셋째, 전달
  넷째, 패널 다섯째, 항목 지점 마지막. 각 PR은 recipe 5.11의
  통과하는 테스트 슬라이스를 carry.
- **포크의 스크립트 진입점을 `fdai` 이외로 이름 변경 하고 컨테이너 CMD
  업데이트 잊음**. Recipe 5.15가 이를 커버; 실패 모드가 silent -
  컨테이너 이미지가 업스트림의 `__main__`을 실행하고 포크 배선은
  하나도 실행되지 않음.
- **측정된 증거 없이 ActionType 자동-승격**. 모든 승격 PR은
  shadow-window 리포트를 참조; 증거 없는 승격 PR은 리뷰어가 반드시
  거부 해야 하는 정책 bypass.
