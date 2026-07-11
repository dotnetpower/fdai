---
title: Hallucination Rubric Gate
translation_of: hallucination-rubric-gate.md
translation_source_sha: d10ffd73f5d5c2422673bfb056b49f7e8b4aa9ad
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

## Next steps

| 학습 주제 | 읽을 문서 |
|-----------|-----------|
| T2 티어와 게이트가 지키는 leg | [llm-strategy-ko.md](llm-strategy-ko.md) |
| 페이즈 계획에서 게이트 위치 | [phases/phase-2-quality-and-t1-ko.md](phases/phase-2-quality-and-t1-ko.md) |
| 프롬프트 카탈로그와 role x layer 매트릭스 | [prompt-composition-ko.md](prompt-composition-ko.md) |
| untrusted-input 위협 모델 | [security-and-identity-ko.md](security-and-identity-ko.md) |
