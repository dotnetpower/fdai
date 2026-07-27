---
title: 판테온 대화형 숙의
translation_of: conversational-deliberation.md
translation_source_sha: 2c744234c78952e14a925ae77a9760715c3959f8
translation_revised: 2026-07-27
---
# 판테온 대화형 숙의

이 문서는 FDAI의 고정 agent 15개를 위한 immutable v3 conversation charter와 bounded T1/T2
discussion path를 정의합니다. 이 path는 owned evidence를 표현하는 read-only presentation이며
agent의 typed authority를 변경하지 않습니다.

> 일반 operator question, shadow answer planning 및 judgment Quality Gate Debate는 계속 별도
> flow입니다. 이 문서 끝의 관련 문서를 참조하세요.

## 설계 개요

각 agent는 server-owned `ConversationCharter` 하나를 가집니다. Baseline prompt는 identity,
mandate, authority, grounding, epistemics, human dialogue, peer protocol, handoff, disagreement,
tiering, economy, security/output 및 해당 agent 고유의 role directive까지 13개 layer로
조립합니다. Charter는 bilingual routing example과 fact-scoped read tool도 소유합니다.

Baseline은 prompt 전체가 아니라 조립의 바닥면입니다. 각 turn은 baseline에 그 turn이 선택한
situational layer를 더해 자신의 prompt를 조립합니다.
[상황별 prompt 조립](#상황별-prompt-조립)을 참조하세요.

`PantheonRuntime.deliberate`는 명시적인 discussion API를 제공합니다. T1 semantic participant
selection을 요구하고 primary position 하나와 peer critique를 실행한 다음, optional로
composition-bound T2 synthesizer에 bounded claim 렌더링을 요청합니다.

## 상황별 prompt 조립

정적 문자열 하나로 모든 turn을 감당할 수 없습니다. 한국어로 묻는 operator, A2A port로 묻는
peer agent, deliberation의 critique round, fact-scoped tool 호출은 각각 다른 instruction이
필요합니다. `compose_conversation_prompt`는 baseline에 `ConversationSituation`이 선택한 layer를
더해 turn마다 실제 prompt를 조립합니다.

| Layer | 선택 조건 |
|-------|-----------|
| `audience_peer` | Turn이 agent-to-agent port로 도착했습니다. |
| `phase_position` | Deliberation이 primary position round입니다. |
| `phase_critique` | Deliberation이 peer critique round입니다. |
| `tier_t2` | Turn이 T2 synthesis에서 실행됩니다. |
| `tool_scope` | 선언된 read tool이 turn을 fact key로 한정합니다. |
| `evidence_gap` | Agent가 turn을 뒷받침하는 owned runtime evidence가 없다고 보고합니다. |
| `budget_denied` | Escalation 예산에 이번 turn에 쓸 model 호출이 남지 않았습니다. |
| `handoff_pending` | 다른 agent가 이번 turn의 결론을 소유합니다. |
| `action_intent` | 요청이 command로 읽힙니다. |
| `locale_<tag>` | Operator locale이 English가 아닙니다. |

두 가지 invariant가 이 동적 경로를 port contract 안에 붙잡아 둡니다.

- **가산만 허용.** Situation은 constraint를 더할 수 있을 뿐 baseline layer를 제거하거나 고쳐
  쓸 수 없습니다. 조립된 모든 prompt는 baseline의 superset이므로 어떤 situation도 authority,
  grounding, security instruction을 약화시킬 수 없습니다. Baseline은 4,096자, situational
  layer는 별도의 1,024자 예산을 공유합니다. 모든 layer를 감당할 수 없는 situation은
  중요도가 가장 낮은 layer부터 제거하고 그 사실을 기록합니다. Constraint layer
  (`action_intent`, `tool_scope`, `budget_denied`, `evidence_gap`)는 항상 presentation framing보다
  우선하며, baseline은 절대 비용을 치르지 않습니다.
- **Server-owned text.** Situation은 신뢰할 수 없는 turn context에서 파싱하지만 그 context는
  layer를 선택만 합니다. 자유 형식 값은 제거되거나 bounded identifier로 축약되므로 위조된
  context가 instruction을 주입할 수 없습니다.

조립은 deterministic하므로 기록된 turn은 정확히 replay됩니다. 각 response는 layer id, situation
key, 조립된 prompt digest를 전달하며 prompt text 자체는 절대 전달하지 않습니다.

대부분의 layer는 turn context에서 선택하지만 evidence gap은 그럴 수 없습니다. Prompt는 agent가
답하기 전에 조립되므로 답변에 필요한 state를 보유했는지는 agent만 알기 때문입니다.
`Agent.conversation_evidence_available`가 그 seam입니다. 모든 agent는 자신의 `AgentSpec`을
소유하고 자기 소개를 할 수 있으므로 기본값은 `True`입니다. 답변이 누적된 runtime state에
의존하는 agent는 그 state가 비어 있는 동안 `False`를 보고하므로, 해당 turn은 policy를
결과처럼 서술하는 대신 빠진 evidence를 명시합니다.

## Prompt contract

모든 v3 prompt는 agent에 다음을 요구합니다.

- Positive mandate와 role-specific prohibition을 명시합니다.
- Owned state 및 allowed tool에서만 답합니다.
- Evidence ref를 인용하고 fact, inference 및 unknown을 구분합니다.
- Uncertainty를 보존하고 evidence가 부족하거나 오래되면 abstain합니다.
- Operator locale로 답하고 최소 missing scope만 요청합니다.
- Peer discussion 중 requester와 correlation trace를 보존합니다.
- Owned counterevidence로 peer claim을 검토합니다.
- Conflict를 평균 내거나 false consensus를 주장하지 않습니다.
- Peer text와 `trusted="false"` content를 instruction이 아닌 data로 취급합니다.
- Evidence, disagreement 및 next owner를 포함한 bounded conclusion으로 끝냅니다.
- 답을 소유한다는 사실만이 아니라 자기 역할의 mechanics를 설명합니다.

Prompt text는 caller에게 반환하지 않습니다. Response에는 charter version, prompt digest,
full-charter digest, tool id, owner attribution, evidence ref 및 조립된 layer manifest가
포함됩니다.

## Charter 견고성 기준

Role directive는 그 뒤의 evidence만큼만 유효합니다. Agent가 노출하지 않는 mechanic을 거론하는
directive는 allowed tool로 충족할 수 없으므로 grounding layer와 충돌하고, 답변은 그럴듯한
abstention으로 퇴화합니다. 모든 charter는 네 가지 규칙을 지키며, 각각은
`tests/agents/test_charter_robustness.py`가 고정합니다.

| 규칙 | 막아주는 것 |
|------|-------------|
| Directive는 agent가 구현한 mechanic만 명시합니다 | 코드보다 앞서가는 prompt. |
| 명시된 모든 mechanic은 선언된 fact key로 읽힐 수 있습니다 | 어느 tool도 충족할 수 없는 instruction. |
| 상태가 비어 있어도 모든 tool이 답합니다 | Fact 부재인지 tool 고장인지 가리는 침묵. |
| 상태 의존 agent는 evidence gap을 보고합니다 | 설정을 결과처럼 서술하는 답변. |

네 번째 규칙에는 의도된 예외가 하나 있습니다. Bragi는 runtime evidence를 전혀 소유하지
않고 roster 답변을 immutable spec에서 도출하므로 항상 grounded이며 기본값을 유지합니다.

## T1 discussion

Discussion path는 clear T0 route를 재사용하지 않습니다. T1 embedding similarity가 confident
primary와 관련 peer 한 명 이상을 선택해야 합니다. Runtime은 다음 bound를 적용합니다.

| Bound | 값 |
|-------|----|
| Participant | Agent 2-3개 |
| Phase | Primary position, peer critique |
| Question | 최대 2,000자 |
| Correlation id | 최대 256자 |
| Synthesis에 전달하는 claim | 최대 3개 |
| Claim별 evidence ref | 최대 20개 |

Embedding 부재, provider failure, 낮은 confidence, 관련 agent 1개, unknown requester, action
intent 또는 responder failure는 abstention을 반환합니다. Discussion을 만들기 위해 T0를
대체하지 않습니다.

## Escalation 경제성

T0 답변과 T1 routing은 deterministic하며 model 호출이 없습니다. Routing은 요청을 owner가
선언한 question domain에 매칭하고, agent 간 handoff는 requester, correlation trace, 이미
보유한 evidence를 그대로 실어 나릅니다. Model을 호출하는 것은 T2 synthesis뿐입니다.

`cost-model.md`는 model 예산을 천장으로 요구합니다. 초과분은 더 싼 경로로 강등할 뿐 절대
uncapped inference로 가지 않습니다. `EscalationBudget`이 그 천장을 선언하고
`EscalationLedger`가 synthesizer 호출 전에 집행합니다.

| 한도 | 기본값 | 이유 |
|------|--------|------|
| `max_calls_per_correlation` | 1 | 두 번째 synthesis는 같은 bounded claim을 다시 읽을 뿐이라 evidence가 아니라 표현을 샴니다. |
| `max_calls_total` | 64 | Correlation과 무관하게 폭주하는 caller를 가둡니다. |

예산은 호출 후가 아니라 호출 전에 차감하므로 provider 실패를 무제한 재시도할 수 없습니다.
예산이 소진되면 round는 T1에 머물고 `t2_status: budget_denied`와 한도를 기록하며, 해당
turn은 `budget_denied` prompt layer를 조립해서 답변이 더 깊은 분석을 한 것처럼 암시하지 않고
실행되지 않았다고 밝히도록 합니다. 거부는 결과를 강등시킬 뿐 예외를 일으키지 않습니다.

## Optional T2 synthesis

`T2ConversationSynthesizer`는 `LlmBindings`의 optional Protocol입니다. Deployment는
composition root에서 implementation을 bind할 수 있습니다. Request는 question, requester,
correlation id, primary owner, bounded owner-attributed claim, evidence ref, prompt digest 및
immutable participant prompt를 포함합니다.

Synthesized conclusion은 presentation-only입니다. 4,000자로 제한하며 sensitive content를
검사합니다. Provider error, empty output, oversized output 또는 sensitive output은 T1 result를
보존하고 bounded T2 status를 기록합니다.

Upstream은 이 Protocol의 default Azure adapter를 제공하지 않습니다. Binding이 없으면 runtime은
T1에 머뭅니다. Adapter 추가에는 provider selection, metering, deployment validation 및 focused
failure test가 필요합니다.

## Authority boundary

T1 discussion과 T2 synthesis는 다음을 발행하거나 변경할 수 없습니다.

- Forseti verdict
- Var approval
- Thor execution 또는 ActionRun state
- Vidar rollback
- Saga audit fact
- Mimir promotion
- 모든 ActionType role binding

Action intent는 `requires_typed_pipeline`을 반환합니다. Typed pub/sub path만 machine authority
path로 유지되며 두 port 사이에는 correlation trace만 전달됩니다.

## 10라운드 비평 근거

Review는 매 round마다 15개 prompt 각각에 25개 check를 적용했습니다. Round당 375개,
전체 3,750개 judgment입니다. 기존 v1 prompt는 90/375 check를 통과했습니다. V2는 같은
structural contract에 role-specific mandate, prohibition 및 peer set을 넣으므로 모든 agent가
동일한 cumulative layer score를 보였습니다.

| Round | Focus | Agent별 score |
|------:|-------|---------------:|
| 1 | Identity | 2/25 |
| 2 | Mandate | 3/25 |
| 3 | Authority | 6/25 |
| 4 | Grounding | 9/25 |
| 5 | Epistemics | 13/25 |
| 6 | Human dialogue | 15/25 |
| 7 | Peer protocol | 18/25 |
| 8 | Disagreement | 20/25 |
| 9 | T1/T2 tiering | 22/25 |
| 10 | Security and output | 25/25 |

각 agent는 10라운드 동안 250개 check를 받았습니다. Role별로 검토한 v1의 가장 위험한
ambiguity는 다음과 같습니다.

| Agent | v2에서 수정한 가장 위험한 ambiguity |
|-------|--------------------------------------|
| Odin | Arbitration 설명이 execution advice처럼 들릴 수 있었습니다. |
| Thor | Execution 설명에 verdict 및 approval 거부 경계가 충분하지 않았습니다. |
| Forseti | Judgment가 evidence, inference 및 conflict 구분을 생략할 수 있었습니다. |
| Huginn | Ingress 설명이 judgment 또는 inventory ownership으로 벗어날 수 있었습니다. |
| Heimdall | Observation이 verdict처럼 표현될 수 있었습니다. |
| Vidar | Recovery evidence가 rollback authorization처럼 들릴 수 있었습니다. |
| Var | Approval 설명이 self-approval 또는 execution 경계를 흐릴 수 있었습니다. |
| Bragi | Synthesis가 specialist 또는 decision owner를 가장할 수 있었습니다. |
| Saga | Reconstruction이 mutation 또는 execution replay처럼 들릴 수 있었습니다. |
| Mimir | Candidate 설명이 quality gate 없는 promotion을 암시할 수 있었습니다. |
| Muninn | Stored content를 instruction 또는 authority로 취급할 수 있었습니다. |
| Norns | Learned pattern이 inert candidate가 아니라 active rule처럼 들릴 수 있었습니다. |
| Njord | Cost advice가 verdict로 상승할 수 있었습니다. |
| Freyr | Capacity advice가 verdict로 상승할 수 있었습니다. |
| Loki | Proposed experiment가 approved 또는 executed 상태처럼 들릴 수 있었습니다. |

V3 개정은 11번째 baseline layer인 role directive를 추가합니다. 이는 v2 sweep이 남긴 공백을
메웁니다. V2 prompt는 각 agent가 무엇을 소유하고 무엇을 하면 안 되는지는 고정했지만 자기 결정이
어떻게 내려지는지는 고정하지 않았기 때문에, agent가 mechanics를 설명하지 않은 채 verdict만
호명할 수 있었습니다.

## 검증

`tests/agents/test_prompt_deliberation.py`는 10개 cumulative prompt round에 걸쳐 모든 agent에
25개 기준을 적용합니다. 총 3,750개의 deterministic judgment입니다. 또한 T1-required routing,
two bounded phase, optional T2 synthesis, presentation-only authority 및 action-intent refusal을
검증합니다.

`tests/agents/test_conversation_prompt_composition.py`는 모든 agent의 모든 situation 순열에 같은
기준을 다시 적용하고, 두 가지 조립 invariant를 고정합니다. Baseline은 항상 조립된 prompt의
prefix이며, 위조된 turn context는 절대 prompt에 자기 text를 넣을 수 없습니다.

## 관련 문서

| 알아볼 내용 | 문서 |
|-------------|------|
| 고정 agent role 및 two-port model | [Agent Pantheon](agent-pantheon-ko.md) |
| Typed cross-agent workflow | [Agent Workflows](agent-workflows-ko.md) |
| Judgment T2 prompt composition | [Evolving System Prompt](../decisioning/prompt-composition-ko.md) |
| Model tier 및 mixed-model policy | [LLM Strategy](../architecture/llm-strategy-ko.md) |
