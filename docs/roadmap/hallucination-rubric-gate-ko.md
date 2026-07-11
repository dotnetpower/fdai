---
title: Hallucination Rubric Gate
translation_of: hallucination-rubric-gate.md
translation_source_sha: 92995c2863cdb9a19253e16c5aa4d6ef2deedc9c
translation_revised: 2026-07-11
---
# Hallucination Rubric Gate (환각 루브릭 게이트)

루브릭 게이트는 T2 quality gate 위에 얹는 **빼기 전용(subtractive) 환각 필터** 다.
독립 judge 모델이 T2 후보의 추론을 고정 기준으로 채점하고, 게이트는 그 최소 점수를
`min()` 으로 confidence에 반영한다 - 자격을 낮출 수만 있고 절대 올리지 못한다. 결정론
verifier가 유일한 실행 권위로 남는다. 이 문서는 설계와 DI seam을 규정하며,
[llm-strategy-ko.md](llm-strategy-ko.md) 와
[phase-2-quality-and-t1-ko.md](phases/phase-2-quality-and-t1-ko.md) 의 T2 게이트 규칙을
확장한다.

## 왜 루브릭 leg인가

기존 quality gate는 이미 네 개 leg로 대부분의 환각을 막는다: 결정론 verifier(권위),
RAG grounding(인용 유효성), mixed-model 교차 검사(구조적 합의), Proposer/Critic/Judge
debate. 두 가지 빈틈이 남아 있었다:

1. **추론 채점 대상이 없음.** `QualityCandidate` 는 제안 액션과 인용은 들고 있었지만
   모델의 자연어 정당화는 없었다. 그래서 faithfulness(모든 주장이 인용 근거에서
   도출되는가?)를 채점할 수 없었다.
2. **다차원 점수화가 없음.** Critic은 objection을, Judge는 verdict을 내지만, 임계로
   거를 수 있는 차원별 점수를 산출하는 장치는 없었다.

루브릭 게이트는 기존 불변식을 하나도 약화하지 않고 이 둘을 메운다.

## 핵심 원칙: 빼기 전용

루브릭은 **빼기만** 할 수 있는 필터다. 이것이 "verifier가 권위, 절대 모델이 아님"과
정합성을 유지하는 불변식이다:

- 게이트는 enforce 모드에서 `confidence = min(aggregate_confidence,
  rubric_min_score)` 로 루브릭을 반영한다. `min()` 이므로 루브릭은 confidence를 **아래로**
  만 밀 수 있고 절대 위로 올리지 못한다.
- 루브릭 실패는 abstain 이유를 추가한다(HIL로 라우팅); eligible 이유는 절대 추가하지
  않는다.
- 루브릭은 verifier deny를 우회하지 못하며, abstain 될 후보를 eligible로 뒤집지 못한다.
- 이는 **모든** outcome 경로에서 성립하며, debate orchestrator가 cross-check 불일치를
  해소하는 경로도 포함한다: 루브릭 reason이 있으면 debate가 proceed 하려 해도 outcome은
  abstain으로 유지된다.

프로퍼티 테스트가 이를 직접 단언한다: 최대 루브릭 점수도 저-confidence 후보를 구제하지
못하고, debate PROCEED 후에도 루브릭 FAIL은 존중된다.

## Works with

- `QualityCandidate.reasoning_trace` - 채점 대상(T2 모델의 정당화), proposer 어댑터가
  전달.
- 규칙 카탈로그 - 모든 루브릭 점수는 supporting 규칙 id를 인용하고, known 규칙 집합에
  대해 검증(fabricated 인용은 abstain).
- `rule-catalog/llm-registry.yaml` capability `t2.rubric.judge` -
  `t2.reasoner.primary` 와 다른 publisher(모델이 자기 답을 채점하면 안 됨),
  `llm_resolver.py` 의 config 로드 시 강제.
- `rule-catalog/prompts/base/t2-rubric.v1.yaml` - catalog-as-code로서의 루브릭 프롬프트,
  `default_mode: shadow`.

## 루브릭 기준

네 개 기준, 닫힌 enum(`RubricCriterion`) - confidence 계산과 카탈로그 프롬프트가 동일한
차원을 기술하도록. 일부는 결정론으로 검사하는 게 최선이라 verifier / grounding leg에
남고, 루브릭 judge는 진짜 semantic 차원만 채점한다.

| 기준 | 잡는 것 | 레이어 |
|------|---------|--------|
| `faithfulness` | 인용 규칙으로 지지되지 않는 추론 주장(NLI식) | LLM judge |
| `evidence_action_alignment` | 액션이 인용 규칙에서 도출되지 않음 | LLM judge |
| `completeness` | blast radius / rollback / stop-condition 누락 | LLM judge |
| `reasoning_coherence` | 자기모순 또는 논리 비약 | LLM judge + self-consistency |

결정론 차원(스키마 적합성, 인용 존재, blast-radius 수치 상한)은 LLM 루브릭이 아니라
verifier와 grounding leg가 처리한다. 그래서 LLM judge는 진짜 모델이 필요한 것에만
쓰인다.

차원별 **통과 임계는 설정** 이며, delivery 어댑터가 `AzureOpenAIRubricEvaluatorConfig`
에서 주입한다 - 모델에서 읽지 않는다. 모델이 자기 통과 기준을 정해선 안 된다. 카탈로그
프롬프트는 모델에게 threshold나 verdict을 내지 말라고 명시한다.

## 동작 방식

루브릭은 교차 검사 후(구조적 검사가 이미 기각하지 않은 후보에만 judge 토큰을 쓰도록),
confidence 임계 전에 실행된다:

1. **Score** - judge가 후보의 `reasoning_trace` 를 각 기준으로 채점하고, 각 점수를
   supporting 규칙 id에 grounding.
2. **Reduce** - 순수 `evaluate_rubric_output` 이 점수를 `RubricDecision`
   (`pass` / `fail` / `abstain`) + `min_score` 로 축약.
3. **Fold** - enforce 모드에서 게이트가 `min(aggregate_confidence, min_score)` 를
   적용하고 `fail` / `abstain` 시 abstain 이유 추가. shadow 모드에서는 점수를
   기록하되 outcome과 confidence는 건드리지 않음.

```text
T2 candidate (+ reasoning_trace)
  -> verifier (deny short-circuits)
  -> grounding (citation validity)
  -> cross-check + debate
  -> rubric judge (score) -> evaluate_rubric_output -> RubricDecision
  -> confidence = min(aggregate, rubric_min_score)   [enforce only]
  -> verifier is still the sole execution authority
```

### 축약 규칙

`evaluate_rubric_output` 은 신뢰할 verdict을 낼 수 없을 때 abstain(HIL 라우팅), 임계
미달 기준이 있으면 fail, 그 외엔 pass:

- 점수 없음 -> `abstain`.
- 같은 기준이 두 번 이상 채점됨 -> `abstain` (자기모순 응답은 신뢰 신호가 아님).
- unknown 기준(`RubricCriterion` 집합 밖) 이름의 점수 -> `abstain` (환각/잘못된 차원).
- 필수 기준 누락(`rubric_required_criteria`) -> `abstain` (잘린 응답이 환각 차원을
  조용히 건너뛰지 못하도록).
- unknown 규칙 id에 grounding된 점수 -> `abstain` (fabricated 인용).
- 임계 미달 점수 존재 -> `fail` (실패 기준 나열).
- 그 외 -> `pass`.

`min_score` 는 `pass` / `fail` 시 기준 전체의 최소값, `abstain` 시 `0.0` - shadow에서
enforce로 전환 시 fail-closed 되도록.

**빈 `reasoning_trace`** 는 judge 호출 전에 short-circuit 된다: faithfulness를 채점할
추론 대상이 없으므로 enforce 모드는 judge 호출 없이 abstain(`rubric_no_reasoning_trace`)
하고, shadow 모드는 outcome을 안 바꾸고 abstain을 기록한다.

## Fail-closed

평가기 예외(전송 실패, 잘못된 응답)는 절대 eligible로 fail-open 하지 않는다. enforce
모드에서는 `rubric_evaluator_error:<Type>` abstain 이유를 추가하고 `min_score` 를
`0.0` 으로; shadow 모드에서는 기록만 하고 outcome은 안 바꾼다.

## Self-consistency (보완)

루브릭이 한 답의 품질을 채점한다면, `SelfConsistencySampler` 는 reasoner가 자기 자신과
합의하는지를 측정한다: 같은 proposer를 N회 샘플(temperature > 0)해 `action_stability`
값(`[0.0, 1.0]`)으로 축약한다. composition root가 이 값을 후보의 `confidence_signals`
에 병합하며, aggregate가 평균이므로 불안정한 proposer는 confidence를 낮춘다. 샘플링은
토큰 비용을 배가하므로 **cascade** 로 - 더 저렴한 신호가 약할 때만 - 실행되고, 매 T2
호출마다 돌지 않는다. 단독으로 자격을 부여하지 않는다.

## Shadow before enforce

루브릭은 shadow-first로 출시한다. `QualityGateConfig.rubric_shadow` 가 기본 `True` 이고
카탈로그 시드가 `default_mode: shadow` 라, 배선된 평가기는 judge-and-log만 한다:
`rubric_scores`, `rubric_verdict`, `rubric_min_score` 가 매 `QualityDecision` 에
측정용으로 기록되지만 outcome과 confidence는 건드리지 않는다. 포크는 라벨된 시나리오
세트에서 승격 게이트를 충족한 뒤에만 enforce로 승격한다.

### 승격 지표

고정 시나리오 세트에서 baseline(루브릭 off) 대 treatment로 측정, 한쪽만 재지 않는다:

- **hallucination-catch rate** - 루브릭이 잡은 라벨된 환각.
- **false-positive rate** - 루브릭이 잘못 HIL로 보낸 정상 후보.
- T2 호출당 **추가 지연 / 토큰 비용**.

승격은 catch rate가 목표 이상, policy-violation escape 0, false-positive rate가 허용
상한 이하일 것을 요구한다. 회귀 시 shadow로 강등한다.

## DI seam

전부 `src/fdai/core/quality_gate/` (core는 LLM-SDK-free 유지); 구체 어댑터는
`delivery/` 에.

| Seam | 위치 | 역할 |
|------|------|------|
| `RubricEvaluator` | `rubric.py` | 포크가 실제 judge 모델로 구현하는 Protocol |
| `evaluate_rubric_output` | `rubric.py` | `RubricDecision` 로의 순수 축약 |
| `SelfConsistencySampler` | `self_consistency.py` | proposer를 N회 샘플해 안정성 측정 |
| `AzureOpenAIRubricEvaluator` | `delivery/azure/llm/rubric.py` | httpx judge 클라이언트, config 주입 임계 |

## 안전 불변식

- **Verifier가 권위.** 루브릭은 자격을 부여하지 않는다.
- **빼기 전용.** confidence는 `min()` 으로 반영, 절대 더하지 않음.
- **Grounded.** 모든 점수는 supporting 규칙 id를 인용하고 카탈로그에 대해 검증;
  fabricated 인용은 abstain.
- **모델 self-report 금지.** 점수는 명시 기준에 대한 judge의 평가이고, judge는
  proposer와 다른 모델.
- **Fail-closed.** 평가기 오류는 HIL로 abstain.
- **Shadow-first.** 승격 게이트 충족까지 judge-and-log.

## 한계 (하지 못하는 것)

천장을 정직하게 밝힌다. 루브릭 judge 자체가 LLM이므로, 이것은 환각의 **확률적 감소** 이지
원천 제거가 아니다. judge는 미묘하게 잘못된 정당화를 놓칠 수 있고, 더 나쁘게는 높은 점수를
환각할 수 있다. 설계는 이를 완화한다 - mixed-model 독립성(judge != proposer), grounded
인용, fail-closed 기본값, shadow-before-enforce 계측 - 그러나 모든 환각을 잡는다고
주장하지 않는다. 유일한 **강한** 보장은 결정론 verifier다: policy-as-code와 what-if가
승인하지 않으면 아무것도 실행되지 않는다. 루브릭은 confidence를 낮추고 더 많은 케이스를
HIL로 보낼 수 있지만, ungrounded 액션을 안전하게 만들 수는 없다. 남은 약점(일부는 이제
완화됨):

- **Grounding entailment는 opt-in이다.** 루브릭 점수의 `supporting_rule_ids` 는 항상
  카탈로그 존재 여부를 확인한다. 배선된 `GroundingSource` 가 `supports()` 를 노출하면
  (예: `RagGroundingSource`), 게이트가 이제 entailment predicate도 전달해, 존재하지만
  후보를 topically 지지하지 않는 인용은 abstain(`off_topic_score`) 시킨다. `supports()`
  없는 평범한 grounding source에서는 id 존재만 확인되어 judge가 실재하지만 무관한 규칙을
  인용할 여지가 남는다.
- **Self-consistency: 평균 신호 OR 빼기 gate.** `action_stability` 를 평균
  `confidence_signals` 에 병합하면 희석된다(낮은 값이 가려질 수 있음). 이를 피하려면
  `run_consistency_cascade` 를 써라 - 저렴한 신호가 약할 때만 샘플하고 호출자가 HIL로
  보내는 강한 `stable` verdict을 반환한다(희석 평균이 아니라 빼기 gate).
- **`min()` 은 서로 다른 두 축을 합친다.** 루브릭 `min_score`(judge의 기준 평가)와 후보
  `aggregate_confidence`(retrieval / verifier-margin 신호)는 서로 다른 척도인데 하나의
  threshold로 비교된다. 이는 의도된 단순화다: `min()` 은 낮추기만 하므로 축 불일치가
  자격을 올릴 수 없다 - 다만 threshold를 튜닝하는 포크는 둘 다 이 값에 들어감을 알아야
  한다.
- **자동 승격 registry가 없다.** ActionType(=`promotion_gate` 를 `ActionPromotionRegistry`
  가 평가)과 달리, 루브릭의 shadow -> enforce 전환은 수동 `QualityGateConfig.rubric_shadow`
  플립이다. 지표 기반 자동 승격/강등은 향후 작업이다.
- **실모델 계약은 스키마가 아니라 프롬프트로 강제된다.** 테스트는 httpx mock을 쓰고,
  `response_format=json_object` 는 유효 JSON을 보장하지 유효 루브릭 스키마를 보장하지
  않는다. 어댑터의 엄격 파서 + `RubricScore` 검증이 잘못된 실모델 응답을 잡아 fail-closed
  하지만, 형태는 카탈로그 프롬프트에 의존하므로 프롬프트/enum 드리프트는 shipped
  catalog-seed 테스트만이 방어한다.

## 통합 상태

**이 leg는 아직 upstream 제어 루프에 배선되지 않았다.** 현재 시점에 upstream은 live
`QualityGate` 를 제어 루프에 조립하지 않는다 - T2 통합 자체가 shadow-only backlog다
(`tests/scenarios/test_v2026_07_replay.py` 의 xfail 마커 참조). 루브릭은 그 seam 위에 얹힌,
완전히 테스트된 고립 라이브러리다. 실제로 돌게 하려면 포크가 반드시:

1. `QualityGate` 를 조립하고 바인딩된 `RubricEvaluator` 를 전달한다(`t2.rubric.judge`
   capability에서 resolve해 `LlmBindings.rubric_evaluator` 에 바인딩).
2. 자신의 `T2Proposer` 에서 `QualityCandidate.reasoning_trace` 를 채운다 - 빈 trace는
   채점 대상이 없어 루브릭을 abstain시킨다.
3. `QualityDecision.rubric_*` 필드를 audit 로그에 직렬화해 shadow 모드 catch /
   false-positive 지표를 실제로 측정할 수 있게 한다. `quality_decision_audit_fields()`
   헬퍼가 이를 JSON-safe하게 flatten한다; 포크의 제어 루프 audit writer가 그 출력을
   per-decision 엔트리에 병합한다. 모든 필드는 구조화된 id / score / enum / 리소스
   참조이며, 예외는 루브릭 `rationale`(untrusted LLM 자유텍스트)로 기본 제외된다
   (`include_rationale=True` 로 opt-in, 길이 제한, 포크는 저장 전 반드시 secret-scan -
   L0 audit는 시크릿/고객값을 기록하지 않는다). upstream 제어 루프는 아직 이 헬퍼를
   호출하지 않는다(T2 미배선); 그 호출 없이는 shadow 모드가 승격할 데이터를 기록하지
   못한다.

이 셋이 완료되기 전까지 루브릭은 런타임에서 아무것도 바꾸지 않는다. 이는 의도된 것이지만
(shadow-first), 현재 가치는 live 환각 감소가 아니라 테스트된 계약과 seam이라는 뜻이다.

## Next steps

| 학습 주제 | 읽을 문서 |
|-----------|-----------|
| T2 티어와 게이트가 지키는 leg | [llm-strategy-ko.md](llm-strategy-ko.md) |
| 페이즈 계획에서 게이트 위치 | [phases/phase-2-quality-and-t1-ko.md](phases/phase-2-quality-and-t1-ko.md) |
| 프롬프트 카탈로그와 role x layer 매트릭스 | [prompt-composition-ko.md](prompt-composition-ko.md) |
| untrusted-input 위협 모델 | [security-and-identity-ko.md](security-and-identity-ko.md) |
