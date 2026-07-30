---
title: Action 온톨로지 라이프사이클
translation_of: action-ontology-lifecycle.md
translation_source_sha: 26cbbfca536704189f3193bae267cf62bdb1a8ec
translation_revised: 2026-07-31
---

# Action 온톨로지 라이프사이클

이 companion 문서는 ActionType 온톨로지의 설계 경계, 라이프사이클 규칙, live consumer 상태를
정의합니다. Canonical schema와 catalog는
[Action 온톨로지](action-ontology-ko.md)에 유지됩니다.

## 설계 경계와 라이프사이클

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

### Consumer 구현 상태 (declared vs. live)

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
- **선언된 precondition은 불확실할 때 안전한 쪽을 선택합니다.** RiskGate는
  제한된 inventory age로 graph freshness를 확인하고, 그 밖의 모든 선언된
  precondition에는 index가 일치하는 `PreconditionEvaluation` 하나를 요구합니다.
  평가가 없거나 중복되거나 종류가 일치하지 않거나 실패하면 사람 승인으로
  라우팅합니다. Composition이 condition kind의 deterministic evaluator를 연결하기
  전에는 해당 kind를 선언한 ActionType이 자동 실행되지 않습니다.
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
