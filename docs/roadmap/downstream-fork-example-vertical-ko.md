---
title: Fork Example Vertical - 새 비즈니스 오브젝트 end-to-end
translation_of: downstream-fork-example-vertical.md
translation_source_sha: 1ffc25f9558a4c315d82fb2b34435df1dd40521a
translation_revised: 2026-07-11
---

# Fork Example Vertical: 새 비즈니스 오브젝트 end-to-end

FDAI 위에 **새 비즈니스-오브젝트 vertical**을 배포하는 fork를 위한
구체적인 walkthrough - 배포된 Resilience / Change Safety / Cost
Governance vertical이 커버하지 않는 업무 카테고리. 대표 예시:
아키텍처-리뷰 제안 flow, compliance-attestation 레코드 flow,
incident-postmortem workflow.

이 문서는 generic **`GovernanceProposal`** 예시를 사용 - 하나 이상의
영향 리소스를 지정하는 proposal 레코드로, 영향 리소스에 따라
Reviewer 세트로 라우팅되고, 승인 후 결정 문서를 발행. 패턴은 fork에
필요한 어떤 non-Resource ObjectType lifecycle로도 일반화됩니다.

**이 walkthrough의 성격**: [downstream-fork-seam-recipes-ko.md](downstream-fork-seam-recipes-ko.md)
에서 필요한 모든 recipe를 참조하며 stitch한 투어. Recipe 본문은
재수록하지 않으므로 두 파일을 나란히 열어두세요.

**이 문서가 아닌 것**: workflow tool 배포에 대한 green light가 아님.
아래 §8은 proposal flow를 프로덕션 자율성으로 취급하기 전에 fork가
반드시 내려야 하는 설계 결정을 다룹니다.

**upstream의 작동 reference**: 이 walkthrough는 풀-lifecycle 패턴 (reviewer와
결정을 가진 proposal flow). **최소 작동 shipped 예제**는 더 작고
single-shot: 오퍼레이터가 이름으로 요청하는 on-demand `resource-group`
**change summary**. 전체 아티팩트 세트가 이미 upstream 트리에 있고
[`tests/verticals/test_change_summary_example.py`](../../tests/verticals/test_change_summary_example.py)
가 검증:

| 조각 | 위치 |
|--------|------|
| ObjectType | [`rule-catalog/vocabulary/object-types/ChangeSummary.yaml`](../../rule-catalog/vocabulary/object-types/ChangeSummary.yaml) |
| LinkType | [`rule-catalog/vocabulary/link-types/summarizes.yaml`](../../rule-catalog/vocabulary/link-types/summarizes.yaml) |
| ActionType | [`rule-catalog/action-types/ops.publish-change-summary.yaml`](../../rule-catalog/action-types/ops.publish-change-summary.yaml) |
| Rule | [`rule-catalog/catalog/ops.change-summary.yaml`](../../rule-catalog/catalog/ops.change-summary.yaml) |
| Rego | [`policies/change_summary/publish_change_summary.rego`](../../policies/change_summary/publish_change_summary.rego) |
| 템플릿 | [`rule-catalog/remediation/change_summary/publish_change_summary.tftpl`](../../rule-catalog/remediation/change_summary/publish_change_summary.tftpl) |

이 6개-파일 scaffold를 복사해서 자기 비즈니스 오브젝트로 rename 하면
작동 시작점을 갖게 됨. 아래 전체 walkthrough는 workflow가 lifecycle (reviewer,
승인 quorum, 결정 발행)을 필요로 할 때 single-shot 리포트가 아닌 그 위에
무엇이 자라나는지 보여줌.

**Contents**

1. [개요와 설계 제약](#1-개요와-설계-제약)
2. [Ontology (ObjectType + LinkType)](#2-ontology-objecttype--linktype)
3. [Signal 소스](#3-signal-소스)
4. [ActionType 카탈로그](#4-actiontype-카탈로그)
5. [Rule 카탈로그](#5-rule-카탈로그)
6. [Delivery adapter (결정 publisher)](#6-delivery-adapter-결정-publisher)
7. [Read panel](#7-read-panel)
8. [`entry.py`에서 wiring](#8-entrypy에서-wiring)
9. [Shadow-first 승격 경로](#9-shadow-first-승격-경로)
10. [Anti-pattern](#10-anti-pattern)

## 1. 개요와 설계 제약

**목표**: "proposal이 열림"을 "올바른 reviewer가 배정되고, 결정이
기록되고, outcome 문서가 발행됨"으로 변환 - 안전한 곳에서는 자율,
그렇지 않은 곳에서는 HIL.

**FDAI 모델 내 fit**:

| FDAI 개념 | Governance proposal 예시 |
|---|---|
| ObjectType | `GovernanceProposal`, `Reviewer`, `ApprovalDecision` |
| Signal | `governance.proposal.opened`, `governance.review.received` |
| Rule | "영향 컴포넌트에 기반해 reviewer 배정" |
| ActionType | `governance.assign-reviewers`, `governance.publish-decision` |
| Delivery adapter | Confluence 페이지 publisher (또는 Word / Markdown PR) |
| HIL 채널 | reviewer는 Teams Adaptive Card로 결정 |
| Read panel | 최근 결정 대시보드 |

**설계 제약 (fork MUST 준수)**:

- **Deterministic-first**: reviewer 라우팅은 T0 rule이지 LLM 호출이
  아님. 컴포넌트-오너 매핑은 fork rule 카탈로그의 lookup 테이블.
- **Shadow-first**: 모든 신규 ActionType은 `default_mode: shadow`
  배포. §9가 승격 다룸.
- **Read-only 콘솔**: 대시보드는 상태를 project; 승인은 콘솔 버튼에서
  오지 않음.
- **Lifecycle당 하나의 workflow ObjectType**: state 필드
  (`draft` -> `under_review` -> `approved` / `rejected` -> `published`)
  는 `GovernanceProposal` 자체에 배치. 배포된 `Finding` 타입에
  두지 말 것 - audit log는 append-only, non-mutable 유지.
- **Approver identity ≠ execution identity**: reviewer는 Teams로
  승인; executor가 결정을 적용. 별개의 principal
  ([security-and-identity-ko.md](security-and-identity-ko.md) 참조).

## 2. Ontology (ObjectType + LinkType)

Recipe 참조:
[seam-recipes 5.8a](downstream-fork-seam-recipes-ko.md#58a-ontology-objecttype--linktype-추가).

**새 ObjectType** (`fork/vocabulary/object-types/` 아래):

- `GovernanceProposal` - workflow 오브젝트. `state`,
  `affected_components`, `submitted_at`, `decision_ref` (nullable) 보유.
  `key: id`.
- `Reviewer` - 투표할 MAY 하는 identity. `key: id`. Fork의 IdP sync가
  populate (Entra group -> Reviewer instance).
- `ApprovalDecision` - 한 reviewer 투표의 immutable 레코드. `key: id`.
  여러 `ApprovalDecision` 인스턴스가 proposal outcome으로 집계;
  집계는 T0 rule이지 `GovernanceProposal`의 mutable 필드가 아님.

**새 LinkType** (`fork/vocabulary/link-types/` 아래):

- `affects: GovernanceProposal -> Resource` (M:M). Proposal payload가
  populate; reviewer 라우팅을 driven.
- `assigned_reviewer: GovernanceProposal -> Reviewer` (M:M).
  assign-reviewers ActionType이 populate.
- `decides_on: ApprovalDecision -> GovernanceProposal` (M:1,
  temporal_order: true). 각 vote는 결정 순간을 timestamp.

**Anti-pattern**: `state` LinkType (`state_of` 등) 추가. State는
`GovernanceProposal`의 property이지 edge가 아님. LinkType은 object
identity들 간의 relationship을 모델링.

## 3. Signal 소스

Signal은 `event-ingest`에 들어가는 primitive. Proposal flow에서 fork는
두 signal 타입을 emit:

- `governance.proposal.opened` - proposal 제출됨 (GitHub PR에
  `proposal` 라벨, form POST, Slack workflow). Payload는 proposal id,
  submitter id, 영향 리소스 id 리스트를 반드시 포함.
- `governance.review.received` - reviewer 투표됨 (Teams Adaptive Card
  콜백). Payload는 proposal id, reviewer id, 결정 (`approve` /
  `reject`), 자유 텍스트 정당화를 반드시 포함.

**Signal이 컨트롤 루프에 도달하는 방법**: 배포된 `EventBus` seam의
fork Kafka 토픽에 publish. Upstream의 `event-ingest` 모듈이 배포된
`event/1.0.0` 스키마에 대해 payload를 정규화하므로 커스텀 ingest 코드는
불필요 - fork의 producer는 스키마에 매칭되는 JSON만 POST.

**Idempotency**: 각 signal은 stable id (`gov.proposal.<uuid>` /
`gov.review.<uuid>`) carry MUST - 배포된 deduplication이 unique 이벤트당
정확히 한 번의 처리를 보장.

**Schema note**: 배포된 `event/1.0.0` 스키마는 generic (payload는 open
object). Fork 편집 불필요. Fork는 어댑터 테스트 안에서 payload shape에
대한 자체 JSON Schema fragment를 등록 MAY 하지만 core는 그것들을
검증하지 않음.

## 4. ActionType 카탈로그

Recipe 참조:
[seam-recipes 5.12](downstream-fork-seam-recipes-ko.md#512-actiontype-카탈로그-추가).

두 ActionType이 workflow를 커버. `fork/action-types/` 아래에 배포.

### 4.1 `governance.assign-reviewers`

```yaml
# fork/action-types/governance.assign-reviewers.yaml
schema_version: "1.0.0"
name: governance.assign-reviewers
version: "1.0.0"
operation: configure          # GovernanceProposal에 reviewer ref로 태깅
interfaces: [Governance]
rollback_contract: state_forward_only
irreversible: false
default_mode: shadow
promotion_gate:
  min_shadow_days: 14
  min_samples: 30
  min_accuracy: 0.98
  max_policy_escapes: 0
preconditions:
  - kind: property_exists
    property: affected_components
  - kind: link_exists
    link_type: affects
stop_conditions:
  - kind: count
    count: 1            # proposal당 assign-reviewers 한 번; 재시도는 no-op
trigger_kind: rule_violation
```

Reviewer 배정은 non-destructive이므로 rollback은 `state_forward_only`:
잘못된 배정은 supersede 하는 배정 레코드로 교정하지 그래프를 되감아서
교정하지 않음. `count: 1` stop condition은 재시도를 idempotent 하게
만듦 (동일 proposal에 대한 re-fire 시그널이 추가 edge를 생성하지 않음).

### 4.2 `governance.publish-decision`

```yaml
# fork/action-types/governance.publish-decision.yaml
schema_version: "1.0.0"
name: governance.publish-decision
version: "1.0.0"
operation: create             # publisher를 통해 결정 아티팩트 생성
interfaces: [Governance, DataPlane]
rollback_contract: pr_revert  # publisher가 retraction 페이지 발행
irreversible: false
default_mode: shadow
promotion_gate:
  min_shadow_days: 21
  min_samples: 20
  min_accuracy: 0.99
  max_policy_escapes: 0
preconditions:
  - kind: property_exists
    property: decision_ref
stop_conditions:
  - kind: count
    count: 1
trigger_kind: rule_violation
```

`rollback_contract: pr_revert`가 Confluence publisher의 retract-page
경로와 매핑 (§6). Append-only 스토어 (locked SharePoint 라이브러리의
Word 문서)에 publish 하는 fork는 대신 `state_forward_only`를 사용하고
supersede 하는 결정 위에 재발행을 block 하는 `stop_conditions` 엔트리를
추가.

## 5. Rule 카탈로그

Recipe 참조:
[seam-recipes 5.8](downstream-fork-seam-recipes-ko.md#58-rule-catalog-추가).

두 rule이 workflow를 driven.

### 5.1 Reviewer 라우팅 (T0)

```yaml
# fork/rules/governance.assign-reviewers.yaml
schema_version: "1.0.0"
id: fork-x.governance.assign-reviewers
version: "1.0.0"
source: authored
severity: medium
category: governance
resource_type: governance.proposal   # 아래 caveat 참조
check_logic:
  kind: rego
  reference: policies/fork-x/governance/assign_reviewers.rego
remediation:
  template_ref: remediation/fork-x/governance/assign_reviewers.yaml
remediates: governance.assign-reviewers
provenance:
  source_ref: internal.governance-baseline
  resolved_ref: internal
  content_hash: sha256:<...>
  license: proprietary
  redistribution: internal
  retrieved_at: 2026-07-08T00:00:00Z
```

**`resource_type` caveat**: 배포된 rule 로더는 `resource_type`을
ResourceType 레지스트리 (built-in `Resource` ObjectType의 subtype
레지스트리)에 대해 검증. Upstream 로더가 등록된 어떤 ObjectType이든
받도록 일반화되기 전까지 fork는 두 옵션:

1. **Fork의 자체 vocabulary 확장에서 proposal subtype을 ResourceType
   엔트리로 모델링** (`fork/vocabulary/resource-types-fork.yaml`를
   별도 `load_resource_type_registry_from_mapping` 호출로 로드해서
   upstream과 concatenate). 이름이 오도적이지만 (클라우드 리소스가
   아님) 메커니즘은 작동.
2. **Upstream issue를 열어 `Rule.target_object_type` 필드 추가**.
   Rule 로더를 fork-patch 하지 말 것; cross-reference는 load-time
   오타 가드.

옵션 1은 첫 번째 shipping; 옵션 2가 cleaner long-term 방향이고
upstream 설계 pass를 block.

### 5.2 결정 발행 (T0)

```yaml
# fork/rules/governance.publish-decision.yaml
schema_version: "1.0.0"
id: fork-x.governance.publish-decision
version: "1.0.0"
source: authored
severity: medium
category: governance
resource_type: governance.proposal
check_logic:
  kind: rego
  reference: policies/fork-x/governance/publish_decision.rego
remediation:
  template_ref: remediation/fork-x/governance/publish_decision.yaml
remediates: governance.publish-decision
provenance:
  source_ref: internal.governance-baseline
  resolved_ref: internal
  content_hash: sha256:<...>
  license: proprietary
  redistribution: internal
  retrieved_at: 2026-07-08T00:00:00Z
```

두 rule 모두 `policies/fork-x/governance/` 아래 policy를 배포. Rego는
proposal이 올바른 상태 (reviewer 배정을 위해 `under_review`, 발행을
위해 quorum 충족한 `approved`)인지 평가하고 결정론적 verdict 반환.
**이 결정 경로에는 어떤 LLM 호출도 닿지 않음** - 순수 상태-기계 로직.

## 6. Delivery adapter (결정 publisher)

Recipe 참조:
[seam-recipes 5.13](downstream-fork-seam-recipes-ko.md#513-delivery-adapter-커스텀-publisher).

`governance.publish-decision` ActionType이 렌더된 결정 payload를
fork의 publisher에 전달. 최소 Confluence 페이지 publisher는
`fork/adapters/confluence_publisher.py` 아래 위치 (코드는 recipe 5.13
참조).

**결정 발행에서 payload가 carry 하는 것**:

- `title` - `"Governance Decision: <proposal-id>"`
- `body` - 템플릿된 Markdown / storage-format XML. 필드는 ontology
  에서 옴: proposal 요약, 영향 컴포넌트 리스트, reviewer 투표, 최종
  outcome, 정당화. **모든 필드는 결정론적 ontology 데이터** - 배포된
  템플릿에 LLM narrative 없음.
- `diff` - 문서 publisher에는 미사용; upstream이 `RemediationPr`
  payload의 빈 diff를 tolerate.
- `labels` - `("governance", "decision", proposal.state)`.

**Narrative 필드 (선택)**: fork가 LLM-생성 executive summary를
원하면, 배포된 quality gate (5.7)와 abstain-on-ungrounded rule을 통해
생성을 라우팅 MUST. Ontology 필드를 인용할 수 없는 summary는 drop
되고 페이지는 summary 없이 발행. LLM에게 verdict를 쓰게 하지 말 것;
verdict는 결정론적.

## 7. Read panel

Recipe 참조:
[seam-recipes 5.14](downstream-fork-seam-recipes-ko.md#514-console-readpanel-추가).

`/panels/governance/decisions`의 `GovernanceDecisionsPanel`이 마지막
N개 proposal을 다음과 함께 리스트:

- proposal id + submitted-at
- reviewer 세트 (`assigned_reviewer` link에서)
- 결정들 (`decides_on` link에서, timestamp 정렬)
- 현재 state + 발행된 결정 페이지 링크 (`decision_ref`에서)

Panel은 fork가 audit log에서 유지하는 **projection store**에서 읽음;
live Confluence API나 실행 중인 컨트롤 루프에서 읽지 않음. mount +
registry 편집은 recipe 5.14 참조.

## 8. `entry.py`에서 wiring

Recipe 참조:
[seam-recipes 5.15](downstream-fork-seam-recipes-ko.md#515-fork-진입점-entrypy).

Fork의 `entry.py`가 composition:

1. Base seam을 위해 `default_container_from_env()`.
2. Ontology concatenation (ObjectType + LinkType) - recipe 5.8a.
3. ActionType concatenation (upstream + `fork/action-types/`) -
   recipe 5.12.
4. Rule concatenation (upstream + `fork/rules/`) - recipe 5.8.
5. `_finalize_llm_bindings`를 통한 `wire_azure_container` - recipe 5.1.
6. Fork publisher (`ConfluencePagePublisher`) - recipe 5.13.
7. Fork HIL 채널 (`TeamsHilChannel`) - recipe 5.5.
8. Fork read panel (`GovernanceDecisionsPanel`) - recipe 5.14.
9. Kafka 이벤트 루프 실행을 위한 upstream의 `_consume`.

Entry-point recipe (5.15)가 skeleton을 제공; fork는 위 7 항목을
순서대로 그 skeleton에 wire.

**Composition-root 순서 중요**: ObjectType이 LinkType 전에 로드
MUST (LinkType이 ObjectType cross-reference), ActionType이 Rule 전에
로드 MUST (Rule이 `remediates`를 통해 ActionType cross-reference).
Recipe 5.15의 skeleton이 이 순서를 존중.

## 9. Shadow-first 승격 경로

두 fork ActionType 모두 `default_mode: shadow` 배포. Enforce로 승격은
`promotion_gate` 블록이 green인 것을 gate로 하는 **별도 PR**이고 한
필드를 flip.

**`governance.assign-reviewers`에 대한 구체 gate**:

- 14 shadow 일 observed.
- rule을 통해 라우팅된 proposal 최소 30개.
- rule이 생성한 reviewer 세트가 operator가 선택한 reviewer 세트와
  >= 98% 일치.
- 제로 policy-violation escape (shadow rule이 required scope가 없는
  reviewer를 배정하려 했던 proposal).

**측정 방법**: 배포된 audit log가 모든 shadow-mode verdict를
would-be action과 함께 기록. Fork의 측정 job (cron, Container App
Jobs, 처음 몇 번은 수동 notebook)이 각 shadow 창 끝에 비교 쿼리 실행.
4개 기준 모두 green -> 별도 PR이 `default_mode: enforce`로 flip 되고
shadow 증거에 대해 리뷰됨.

**Regression demote**: enforce 후, fork의 KPI 대시보드가 rule
정밀도가 promotion floor 아래로 떨어짐을 보이면, demote 경로는
mode를 다시 `shadow`로 flip 하는 same-shape PR. 오늘 auto-demote 없음;
fork의 on-call이 regression alert를 읽고 PR 제출.

## 10. Anti-pattern

- **Recipe 5.8a 건너뛰고 ObjectType을 rule parameter dict에 밀어
  넣기**. Rule은 여전히 fire 되지만 assurance twin, operator console,
  어떤 커스텀 delivery adapter도 그 오브젝트에 dispatch 불가.
  Ontology-first가 전체 요점.
- **`GovernanceProposal.state`를 audit-log 필드로 만들기**. Audit
  log는 append-only; state 전이는 오브젝트에 있고, 전이 자체가
  자체 audit row를 생성하는 signal로 emit.
- **T2 (LLM)를 통한 reviewer 라우팅**. 여기서 어떤 T2 호출도 red
  flag - 컴포넌트-오너 매핑은 결정론적 테이블 lookup이지 reasoning이
  아님. Reviewer 세트가 진짜로 모호하면 올바른 outcome은 HIL
  (`escalate`)이지 LLM 추측이 아님.
- **모든 것을 하나의 거대한 fork PR로 번들링**. §8 순서로 fork를
  shipping: ontology 먼저, ActionType 둘째, rule 셋째, delivery
  넷째, panel 다섯째, entry point 마지막. 각 PR은 recipe 5.11의
  통과하는 테스트 슬라이스를 carry.
- **Fork의 script 진입점을 `fdai` 이외로 rename 하고 컨테이너 CMD
  업데이트 잊음**. Recipe 5.15가 이를 커버; 실패 모드가 silent -
  컨테이너 이미지가 upstream의 `__main__`을 실행하고 fork wiring은
  하나도 실행되지 않음.
- **측정된 증거 없이 ActionType 자동-승격**. 모든 승격 PR은
  shadow-window 리포트를 참조; 증거 없는 승격 PR은 리뷰어가 반드시
  reject 해야 하는 policy bypass.
