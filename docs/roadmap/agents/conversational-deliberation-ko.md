---
title: 판테온 대화형 숙의
translation_of: conversational-deliberation.md
translation_source_sha: d3455f947d5f8846a0ab30646b51a77fa912bbfd
translation_revised: 2026-07-28
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
| `audience_peer` | Turn이 agent-to-agent port로 도착했습니다. Bragi의 contributor 호출도 포함합니다. |
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
  grounding, security instruction을 약화시킬 수 없습니다. Baseline은 4,096자이고 *framing*
  situational layer가 별도의 1,024자 예산을 공유합니다. Constraint layer(`action_intent`,
  `tool_scope`, `budget_denied`, `evidence_gap`, `handoff_pending`)는 순위가 아니라 구조적으로
  이 예산에서 면제됩니다. Constraint를 떨어뜨릴 수 있는 예산은 부하가 걸릴수록 prompt를 덜
  안전하게 만들며, 그것은 거꾸로 된 설계이기 때문입니다. 경쟁하는 것은 framing뿐이고 baseline은
  절대 비용을 치르지 않습니다. 면제는 대신 각 constraint 자체에 한도를 둡니다. Tool-scope layer는
  fact key를 앞의 12개만 나열하고 나머지는 개수로 요약하므로, 어떤 charter도 잘라낼 수 없는
  layer를 무한히 키울 수 없고, composed 상한에 닿으면 조립이 크게 실패합니다.
- **Server-owned text.** Situation은 신뢰할 수 없는 turn context에서 파싱하지만 그 context는
  layer를 선택만 합니다. 자유 형식 값은 제거되거나 bounded identifier로 축약되므로 위조된
  context가 instruction을 주입할 수 없습니다. Agent 이름은 형태만이 아니라 고정 roster와
  대조합니다. 판테온은 닫힌 집합이므로 그 밖의 이름은 위조이며, server-owned layer에
  렌더링하지 않고 버립니다.

조립은 deterministic하므로 기록된 turn은 정확히 replay됩니다. 각 response는 layer id, situation
key, 조립된 prompt digest를 전달하고 console evidence도 같은 manifest를 실어 나르므로, 답변이
어떤 constraint 아래 만들어졌는지가 end-to-end로 관측됩니다. 어느 쪽도 prompt text 자체는 절대
전달하지 않습니다. 이를 위해 `BASELINE_LAYER_IDS`와 `ConversationSituation`은 `fdai.agents`
facade에서 export합니다.

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

## 도구 계획

Charter는 에이전트에게 "allowed tools를 통해" 답하라고 지시하며, 이제 grounding layer가 그
도구들을 이름으로 나열합니다. 그전까지 이 지시는 어떤 turn도 도달할 수 없는 표면을 가리켰습니다.
Registry는 있었지만 읽기 경로에서 도구를 dispatch하는 곳이 없었으므로, 그 문장은 에이전트에게
주어진 적 없는 것을 통해 일하라고 요구한 셈입니다.

선택은 에이전트 바깥에서, 에이전트가 답하기 전에 두 계층으로 일어납니다. Agent router가 이미
질문에서 담당자를 고를 때 쓰는 것과 같은 형태입니다.

어느 계층이 앞설지는 가정이 아니라 측정으로 정했습니다. 운영자가 실제로 묻는 방식으로 쓴 질문
14개("why did we get billed so much", "어제 되돌린 작업 뭐였지")에 대한 결과입니다.

| 계층 | 상위 3개 안에 정답 도구 |
|------|------|
| T0 어휘만 | 3 / 14 |
| T0 우선, 놓친 것만 T1 | 11 / 14 |
| T1 우선, T0는 강등 경로 | **13 / 14** |

어휘 계층은 단순히 약한 것이 아닙니다. 더 나은 답을 거부할 만큼 자신 있게 틀립니다. 점수가 용어
중복 개수일 뿐이어서, 두 단어가 맞았다는 사실이 그 둘이 맞는 단어였는지는 말해주지 않기
때문입니다. 그래서 임베딩이 바인딩된 곳에서는 의미가 앞서고, 어휘 계층은 강등 경로가 됩니다.
모델 미바인딩, provider 실패, 확신 임계 미달이 모두 어휘 계층으로 떨어집니다. 임베딩 모델이 없는
배포는 이전과 정확히 같게 동작합니다.

**T0, 어휘.** `plan_conversation_tools`는 질문을 도구가 선언한 것 - id, purpose, 산출하는 fact
key - 과 대조하고 선택 근거가 된 용어와 함께 반환합니다. 운영자 어휘는 선언된 영어 용어로
번역됩니다. 도구 id와 fact key는 기계 기록 키이므로 영어로 유지하며, 그 유계 카탈로그가 없으면
한국어 질문은 아무것도 매칭하지 못합니다.

**T1, 의미.** `SemanticToolPlanner`는 각 도구를 한 번 임베딩해 캐시한 뒤, cosine 하한과 margin을
두고 질문을 그 벡터들과 대조합니다. 선언만 임베딩했을 때는 어휘와 똑같은 3 / 14였습니다. 선언과
질문은 서로 다른 어투이기 때문입니다. 그래서 각 도구는 그 질문이 실제로 어떻게 물어지는지를 담은
이중언어 예문을 갖고, 그 앵커가 계층을 끌어올립니다. 예문은 검색 앵커일 뿐이며 prompt에 들어가지
않고 근거가 되지도 않습니다.

이 계층을 생성형 모델이 아니라 임베딩으로 둔 것은 의도입니다. 도구 선택은 근거 추적의 일부이므로
재현되어야 합니다. 같은 질문, 같은 카탈로그, 같은 모델이면 같은 벡터가 나오고 따라서 같은 계획이
나옵니다. 벤더 버전마다 순서가 바뀌는 생성형은 그 약속을 할 수 없습니다.

각 plan은 자신을 만든 계층을 이름으로 밝힙니다. 두 점수는 비교할 수 없기 때문입니다. 하나는 일치한
용어 수이고 다른 하나는 cosine을 배율한 값이므로, 읽는 쪽이 숫자만 보고 어느 쪽인지 추측하게 두어선
안 됩니다.

벡터 캐시는 전부 아니면 무효입니다. 순위는 상대적이므로 도구 하나가 빠진 카탈로그는 그 도구를 잃는
것이 아니라, 그 도구의 질문을 그다음으로 가까운 도구로 조용히 보내며 캐시가 사는 동안 계속 그렇게
합니다. 그래서 불완전한 빌드는 캐시하지 않고 거부한 뒤 다음 질문이 재시도하며, provider가 다른
차원을 보고하면 기존 캐시를 버립니다. 다른 공간의 벡터와 대조한 점수는 의미 없는 확신에 찬 숫자일
뿐이기 때문입니다.

예문은 검색 앵커일 뿐입니다. Charter digest에 포함되지 않으므로 검색을 튜닝해도 감사 기록이 흔들리지
않고, prompt나 답변에도 들어가지 않습니다.

도구 선택은 누가 답할지를 정하지 않습니다. 계획은 turn 전에 결정론적으로 라우팅된 owner를 기준으로
돌지만 turn은 다른 에이전트에게 갈 수 있으며, 답변에는 답한 owner 자신의 읽기만 첨부됩니다. 답하지
않은 에이전트의 증거는 그 답변의 근거가 아니기 때문입니다.

Dispatch는 네 가지로 유계입니다. 운영자 질문 하나가 열 수 있는 읽기 표면은 이 중 하나라도 없으면
서비스 거부 표면이 되기 때문입니다.

| 경계 | 값 | 이유 |
|------|-----|------|
| 질문당 plan | `MAX_TOOL_PLANS` (3) | 수십 건의 읽기를 원하는 질문은 보고서를 원하는 것입니다. |
| 깊이 | 1단계 | 에이전트는 registry 참조를 갖지 않으므로 turn이 도구를 부를 수 없습니다. Registry가 중첩 호출을 거부하는 것이 두 번째 잠금입니다. |
| 단일 dispatch | registry timeout, 출력 상한, 민감도 스캔 | Registry가 그대로 소유합니다. |
| 전체 prefetch | `PREFETCH_BUDGET_SECONDS` (5) | 도구별 timeout은 합계를 제한하지 못합니다. 다음 도구를 *시작하지 않는* 것만으로는 dispatch 하나만큼 초과하므로, 예산은 취소하고 완료된 것만 반환합니다. |

Prefetch된 증거는 보조적입니다. Abstain하거나 timeout되거나 예산에 의해 취소된 도구는 아무것도
기여하지 않고 답변 turn은 그대로 진행됩니다. Abstain 경로에서도 함께 전달되는데, 답이 없는 turn이
바로 미리 모아둔 범위 한정 증거가 가장 값진 경우이기 때문입니다.

소유 판정은 선택보다 먼저 이루어지며, 유사도로 하지 않습니다. 랭커는 언제나 순위를 매깁니다. 시스템이
전혀 소유하지 않은 질문에도 가장 가까운 도구는 매칭처럼 점수가 나오며, 그런 질문 8개로 측정했을 때 의미
계층은 매번 도구 3개를 골랐습니다. 절대 점수, margin, 상위 3개의 agent 합의를 모두 측정했지만 소유한 질문과
소유하지 않은 질문을 가르는 지표는 없었습니다. 그래서 판정은 route가 합니다. 답변 turn이 타는 것과 같은
route이며, 키워드 우선 후 튜닝된 floor와 margin을 가진 semantic router로 이어집니다. Owner가 없으면 prefetch도
없습니다. 이 route도 유계입니다. Turn 전에 돌기 때문에, 응답하지 않는 임베딩 provider는 곁의 증거가 아니라
답변 자체를 붙잡게 되기 때문입니다.

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

Operator 경로의 contributor는 사람과의 대화가 아니라 handoff입니다. Bragi가 자신을 requester로,
primary agent를 handoff owner로 전달하므로 contributor는 peer-audience와 handoff layer를
조립하고, 소유하지 않은 답변을 서술하는 대신 owned evidence를 반환합니다.

`cost-model.md`는 model 예산을 천장으로 요구합니다. 초과분은 더 싼 경로로 강등할 뿐 절대
uncapped inference로 가지 않습니다. `EscalationBudget`은 그 천장을 microUSD로 선언하며,
이는 `TaskWorkerBudget`이 이미 쓰는 단위와 같습니다. Deliberator는 synthesizer를 호출하기 전에
동봉된 pricing table로 이를 집행합니다.

| 한도 | 기본값 | 이유 |
|------|--------|------|
| `max_cost_microusd_per_correlation` | 50,000 (0.05 USD) | 항상 적용. 실제 천장이며 대화 하나가 쓸 수 있는 금액입니다. |
| `max_calls_per_correlation` | 1 | 항상 적용되는 fail-safe. 가격이 없는 model은 비용이 0이므로, 비용만 보는 천장은 하필 아무도 가격을 매기지 않은 model에 대해 천장이 아닙니다. |
| `max_cost_microusd_total` | 미선언 | Fleet 천장은 배포가 선언했을 때만 존재합니다. |
| `max_cost_microusd_per_correlation` | 50,000 (0.05 USD) | 운영자가 실제로 신경 쓰는 한도는 금액입니다. 비용을 관측할 수 없는 caller에게는 `None`입니다. 결코 소모될 수 없는 limb는 천장이 아니면서 천장처럼 읽히기 때문입니다. |
| `max_calls_total` | 미선언 | 마찬가지입니다. 리셋되지 않는 총량은 예산이 아니라 kill switch입니다. 이후 모든 turn이 영원히 사람에게 넘어가며, 아무도 그것을 요청하지 않았습니다. |

지출은 caller가 correlation id를 제공하면 그 id에 차감합니다. 제공하지 않으면 질문과 primary
owner의 안정적 digest로 대체합니다. 그렇지 않으면 모든 deliberation이 빈 문자열 하나를
공유해서, 첫 synthesis가 그 뒤의 무관한 모든 질문의 예산까지 써버립니다. 같은 owner에게 같은
질문을 다시 하는 것은 같은 작업 단위이므로 추가 비용이 들지 않습니다.

두 한도 중 하나만 걸려도 거부하며, 호출 전에 둘 다 검사합니다. 지출을 차감하는 지점은 정확히
하나이며, 그것은 deliberator가 아닙니다.

1. **호출 전 시도 예약.** Round는 provider에게 묻기 전에 call 1건만 가져가고 금액은 차감하지
   않습니다. 이 예약은 읽고 나서 쓰는 두 단계가 아니라 단일 원자적 단계입니다. 같은 correlation의
   두 turn이 남은 허용량을 각각 읽으면 둘 다 통과해버려서, call 1건짜리 천장이 겹친 수만큼
   허용됩니다. 이후 실패한 provider도 부여받은 시도를 소모한 것이 되므로, 실패한 provider를
   무제한 재시도할 수 없습니다.
2. **호출이 기록되는 곳에서 금액 차감.** `SynthesisOutcome`이 실측 `TokenUsage`와 model key를
   보고합니다. Provider가 알려주지 않는 것을 예산이 계량할 수는 없기 때문입니다. 가격이 매겨진
   `LlmInvocation`이 `usage_scope: operator_chat`으로, 가정한 통화가 아니라 가격표가 정한 통화를
   명시해 metering에 기록되고, `BudgetChargingMeteringSink`가 방금 기록한 그 비용을 ledger에
   차감합니다. Ledger는 microUSD로 계산하므로 다른 통화로 매겨진 기록은 기록만 되고 차감되지
   않습니다. 환산하려면 아무도 선언하지 않은 환율이 필요하고, 그 숫자를 달러로 차감하면 원화
   가격을 달러 가격이라고 말하는 셈이기 때문입니다.

따라서 비용은 추정되지도, 두 번 차감되지도 않습니다. 예산이 쓴 금액이 곧 감사 기록에 남은
금액이므로 천장이 주장이 아니라 감사 가능해집니다. Usage를 보고하지 않는 provider는 정직하게
미계량 상태로 남습니다. 아무것도 metering하지 않고 금액도 차감하지 않으며 call 한도가 경계로
남습니다. Metering 기록이 *실패한* 경우는 애초에 일어나지 않은 경우와 다릅니다. 돈은 이미 나갔으므로
charging sink는 그대로 차감하고 실패는 예외 대신 로그로 남깁니다. Metering은 side-channel이며, 이미
답을 받은 운영자가 장부 문제로 그 답을 잃어서는 안 됩니다. 차감 지점이 개별 호출 지점이 아니라 metering 기록이므로, composition root가 이 charging
sink를 바인딩하면 각 seam에 예산을 가르치지 않고도 metering되는 모든 model 호출이 같은 천장 아래
놓입니다.

Deliberator는 전달받은 sink를 스스로 charging sink로 감싸므로, composition root가 metering만
바인딩하고 천장을 잊는 일이 생길 수 없습니다. 반대 방향도 fail-loud입니다. `LlmBindings`는 metering,
pricing, model key 없이 바인딩된 대화 synthesizer를 거부합니다. 가격을 매길 수 없는 호출은 한도를
걸 수도 없기 때문입니다.

예산이 소진되면 round는 T1에 머물고 `t2_status: budget_denied`와 한도를 기록하며, 해당 turn은
같은 한도를 담은 `budget_denied` prompt layer를 조립하므로 답변이 그 한도를 직접 밝힐 수
있습니다. 거부는 결과를 강등시킬 뿐 예외를 일으키지 않습니다.

`BudgetLedger`는 판테온의 다른 durable-state seam과 마찬가지로 Protocol입니다. 상류 기본값인
`InMemoryBudgetLedger`는 프로세스 범위이며 deterministic하므로 재시작하면 천장이
초기화됩니다. 재시작을 넘어서는 천장이 필요한 배포는 composition root에서 durable 구현을
바인딩합니다. Ledger는 correlation별 지출을 상한이 있는 map으로 추적하므로 그 상한보다 큰 총 call
예산은 생성 시점에 거부합니다. 축출이 일어나면 이미 소모한 correlation이 조용히 환불되고,
스스로 환불하는 천장은 천장이 아니기 때문입니다.

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
