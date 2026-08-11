---
title: Action 온톨로지 라이프사이클
translation_of: action-ontology-lifecycle.md
translation_source_sha: a2a7f057c405c50a1b2fe902e47dfd4c98f05d70
translation_revised: 2026-08-11
---

# 액션 온톨로지 라이프사이클

이 companion 문서는 ActionType 온톨로지의 설계 경계, 라이프사이클 규칙, 실제 운영 소비자 상태를
정의합니다. 정본 스키마와 카탈로그는
[액션 온톨로지](action-ontology-ko.md)에 유지됩니다.

## 설계 경계와 라이프사이클

온톨로지 형태 에 대한 반복 질문에 명시적으로 답해, 리뷰어가 의도된
경계를 공백 으로 오인하지 않도록.

- **세 orthogonal 분류 축은 redundant 하지 않음** (#12). `category`
  (어떤 종류의 변경), `trigger_kind` (누가 initiate), `side_effect_class`
  (콘솔 도구 이 무엇을 함) 은 서로 다른 질문에 답하고 감사 항목 에 함께
  기록됨 (§4.3). 하나의 변경이 다른 것을 함의하지 않음.
- **두 자율성 출처 는 충돌 가 아니라 strictest-wins 로 compose**
  (#15). risk-classification 표 (축 A) 과 `ceiling_by_tier`
  (축 C) 둘 다 자율성 를 한계; RiskGate 는 6축 + 표 에 대해 `min`
  을 취하므로 어느 쪽도 다른 쪽 위로 raise 못 함. hand-tuned
  `ceiling_by_tier` 가 무시되는 것처럼 보이면 표 이 더 strict 한 룰 을
  일치 한 것 - 감사 `resolved_ceiling.winning_axis` 가 어느 쪽이
  이겼는지 이름 (§9), 그래서 상호작용은 항상 inspectable, silent 아님.
- **`argument_schema` 버전 관리** (#20). `argument_schema` 의 backward-
  incompatible 변경 (필드 제거, 타입 tightening) 은 ActionType `version`
  (semver major) bump MUST. 감사 항목 는 인자 를 받은 그대로 기록하니
  재생 는 전달 시점에 유효했던 버전 으로 읽음; 로더는 과거 인자
  블롭 을 새 스키마로 재해석 안 함.
- **ActionType 은퇴** (#21). ActionType 은퇴는 거버넌스 PR 로 (a) 그것을
  `remediates:` 하는 모든 룰을 제거하거나 shadow-only 로 pin 한 뒤 (안 그러면
  `remediates:` 교차 검증 가 로드 실패), (b) ActionType YAML 을 제거. 로더의
  dangling `remediates:` 체크가 룰이 아직 참조하는 동안 ActionType 제거를
  막으므로, 은퇴가 dangling 참조 를 남길 수 없음.
- **자기수정 거버넌스 는 범위가 제한된** (#24). `governance.*` ActionType
  (promote, retire, override-ceiling) 은 안전성 묶음 자체를 바꾸므로
  가장 strict 한 기본값 를 carry: `pr_native` 실행 (검토된 차이),
  `default_mode: shadow`, 서로 다른 승인자 (자기 승인 없음 - 승격
  PR 을 작성자 한 행위자 는 절대 그 승인자 아님). `governance.override-ceiling`
  은 downgrade-only 이고 time-boxed. 묶음 는 이 경로로 *narrow* 될 수
  있어도 검토된, quorum-approved PR 없이 *widen* 될 수 없음.
- **영향 탐색 깊이 는 tunable 한 safe 기본값** (#28).
  `graph_derived` 영향 범위 는 `contains` + `depends_on` 를
  `traversal_depth` (기본값 2, max 5) 까지 walk. depth-2 walk 는 깊이 2
  초과 transitive 체인 을 under-count; `RequiresInventoryFresh` 인터페이스
  와 `graph_fresh_within_seconds` precondition 이 stale 그래프 데이터 로 act
  하는 것을 막고, `max_affected_resources` 초과 인스턴스 는 HIL 로 escalate.
  deep 의존성 그래프 를 다루는 포크 는 ActionType 별로 `traversal_depth`
  를 raise.

### 소비자 구현 상태 (declared vs. 실제 운영)

온톨로지 는 의도적으로 런타임 이 오늘 consume 하는 것보다 많이 declare
한다. 이는 숨겨진 공백 이 아니라 명시적 경계 다: ActionType 은
디스패처 가 landing 하기 전에 catalog-as-code 로 존재할 수 있고, 그때까지
**구조적으로 inert** 하다. 아래 안전성 속성 는 어떤 소비자 가 실제 운영
인지와 무관하게 성립하므로, declare 됐지만 아직 전달 되지 않는
ActionType 은 act 할 수 없다.

- **Inert-by-default 는 assume 이 아니라 강제 적용 된다** (#5, #8, #9).
  shipped `ops.*` 와 `governance.*` ActionType 은 모두
  `default_mode: shadow` 로 ship 된다
  (`test_every_shipped_action_type_defaults_to_shadow` 로 검증). 실제 운영
  디스패처 가 없는 declare 된 ActionType 은 judge-and-log 만; 절대
  mutate 하지 않음. 강제 적용 로의 승격 은 별도 gated 거버넌스 PR.
- **`rule_violation` (교정) 이 실제 운영 경로.** T0Engine ->
  ActionBuilder -> RiskGate -> 실행기 루프 (§4.1) 이 오늘 교정
  ActionType 을 전달 한다. 이것이 기본 자율성 표면 이며 완전히
  wired 됨.
- **선언된 precondition은 불확실할 때 안전한 쪽을 선택합니다.** RiskGate는
  제한된 인벤토리 age로 그래프 최신성을 확인하고, 그 밖의 모든 선언된
  precondition에는 인덱스가 일치하는 `PreconditionEvaluation` 하나를 요구합니다.
  평가가 없거나 중복되거나 종류가 일치하지 않거나 실패하면 사람 승인으로
  라우팅합니다. 기본 `EventPreconditionEvaluator`는 정본 이벤트 스냅샷에서
  `resource_property_equals`와 `resource_tag_present`를 확인합니다. 조립은
  링크, conflicting-action, maintenance 구간 근거를 위한 `PreconditionEvaluator`를
  주입할 수 있으며, 연결되지 않은 조건은 사람 승인 상태로 유지됩니다.
- **`operator_request` -> 타입이 지정된 제안 전달은 실제 운영** (#6, #7).
  선택적 `/chat/action` 경로와 Bragi 제안 싱크는 등록된 운영자 명령을
  `ActionProposal`로 변환하고 server-derived RBAC를 강제한 뒤 정본 유입 토픽에
  publish합니다. 실행기를 직접 호출하지 않습니다. 카탈로그 로더가 `argument_schema`를
  검증하며 각 실제 운영 명령 표면은 범위가 제한된 서버가 소유한 인자 형태만 받습니다.
- **`governance.*` 디스패처 3 개는 P2 적체** (#8). `거버넌스.
  override-ceiling` 만 실제 운영 디스패처
  (`core/risk_gate/override_writer.py`) 를 가짐; `promote-action-type`,
  `retire-rule`, 런타임 `grant-exemption` 쓰기 담당 는 P2 PR-native 쓰기 담당
  와 함께 landing. 그때까지 YAML 항목 는 inert 카탈로그 데이터
  (shadow-default, 디스패처 없음 = side 효과 없음).
- **`live_probe_ref`는 선택된 ops 액션에서 실제 운영** (#9).
  `ops.restart-service`와 `ops.scale-in`은 shipped `vm_traffic_last_5m` 탐색을
  연결합니다. 탐색이 없는 액션은 static 영향 한계를 사용하며 참조된 탐색이
  없으면 카탈로그 부하가 실패합니다.
- **에이전트 는 온톨로지 를 읽기 하지, 그 위에서 free-form 사유 하지 않음**
  (#10, #11). 자율성 결정 은 procedural: RiskGate 가 ActionType
  필드 (`ceiling_by_tier`, `blast_radius`, `irreversible`, `operation`,
  `interfaces`) 를 결정론적 하게 읽기. ObjectType / LinkType
  선언 은 검증되고 codegen 및 `graph_derived` 영향 에 쓰이는
  인벤토리 그래프 를 구동하지만, pantheon 이 사유 하는 free-form
  knowledge 그래프 는 아님. 이는 design 상 의도 - determinism-first 가
  안전성 코어 를 inspectable 하게 유지. 미래의 graph-reasoning 소비자 는
  가산 이고 어떤 상한 도 바꾸지 않음.
