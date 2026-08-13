---
title: Hallucination Rubric Gate
translation_of: hallucination-rubric-gate.md
translation_source_sha: 937e800606931dd6db90fb5fd90e0b9cefa7e64c
translation_revised: 2026-08-13
---
# Hallucination 평가 기준 게이트 (환각 루브릭 게이트)

루브릭 게이트는 T2 quality 게이트 위에 얹는 **빼기 전용(subtractive) 환각 필터** 다.
독립 판정자 모델이 T2 후보의 추론을 고정 기준으로 채점하고, 게이트는 그 최소 점수를
`min()` 으로 확신도에 반영한다 - 자격을 낮출 수만 있고 절대 올리지 못한다. 결정론
검증기가 유일한 실행 권위로 남는다. 이 문서는 설계와 DI 경계를 규정하며,
[llm-strategy-ko.md](../architecture/llm-strategy-ko.md) 와
[phase-2-quality-and-t1-ko.md](../phases/phase-2-quality-and-t1-ko.md) 의 T2 게이트 규칙을
확장한다.

## 구현 상태

### 구현 범위

| 영역 | 상태 | 근거 | 참고 |
|------|------|------|------|
| 루브릭 축약 및 빼기 전용 게이트 동작 | implemented | [`rubric.py`](../../../services/core-control-plane/src/fdai/core/quality_gate/rubric.py), [`gate.py`](../../../services/core-control-plane/src/fdai/core/quality_gate/gate.py), [`test_rubric_gate.py`](../../../services/core-control-plane/tests/core/quality_gate/test_rubric_gate.py) | 집중 검사는 전체 기준 포함, 실패 시 차단 결과, shadow 격리 및 `min()`만 사용하는 확신도 반영을 증명합니다. |
| 독립 판정자 및 프롬프트 카탈로그 제약 | implemented | [`llm_resolver.py`](../../../services/core-control-plane/src/fdai/rule_catalog/schema/llm_resolver.py), [`t2-rubric.v1.yaml`](../../../rule-catalog/prompts/base/t2-rubric.v1.yaml), [`test_mixed_model_cross_check.py`](../../../services/core-control-plane/tests/quality_gate/test_mixed_model_cross_check.py) | 해석된 루브릭 판정자가 기본 추론기와 같은 제공자를 사용하지 못하도록 해석기가 검사하며, 카탈로그 검사는 프롬프트를 루브릭 기능에 결속합니다. |
| 런타임 바인딩 및 컨트롤 루프 감사 변환 결과 | implemented | [`control_loop.py`](../../../services/core-control-plane/src/fdai/runtime/control_loop.py), [`_audit_helpers.py`](../../../services/core-control-plane/src/fdai/core/control_loop/_audit_helpers.py), [`_audit.py`](../../../services/core-control-plane/src/fdai/core/quality_gate/_audit.py) | 런타임은 선택적 평가기를 quality 게이트에 전달하고 T2 quality 판정이 있으면 범위가 제한된 루브릭 출처를 직렬화합니다. 이는 실제 평가기가 바인딩되었음을 증명하지 않습니다. |
| Azure 판정자 어댑터 및 엄격한 응답 파싱 | implemented | [`rubric.py`](../../../services/core-control-plane/src/fdai/delivery/azure/llm/rubric.py), [`test_rubric.py`](../../../services/core-control-plane/tests/delivery/azure/llm/test_rubric.py) | 모의 전송 검사는 구성에서 소유하는 임계값, 엄격한 파싱 및 잘못된 응답 실패를 다룹니다. 실제 모델 근거는 아닙니다. |
| Self-consistency cascade 통합 | in-progress | [`self_consistency.py`](../../../services/core-control-plane/src/fdai/core/quality_gate/self_consistency.py), [`test_self_consistency.py`](../../../services/core-control-plane/tests/core/quality_gate/test_self_consistency.py) | 범위가 제한된 cascade와 엄격한 안정성 판정은 구현 및 검사됐지만, 프로덕션 T2 호출자는 cascade를 호출하지 않습니다. |
| 지표 기반 승격 및 운영 검증 | not-started | [승격 지표](#승격-지표), [한계](#한계-하지-못하는-것) | 저장소에는 자동 루브릭 승격 레지스트리나 고정된 리비전에서 포착률, 오탐률, 지연 시간, 토큰 비용 및 정책 위반 우회 0건을 증명하는 관리되는 shadow 증적이 없습니다. |

### 구현 이력

| 날짜 | 상태 | 변경 | 근거 | 남은 작업 |
|------|------|------|------|-----------|
| 2026-08-13 | in-progress | 이전 전달 이력을 재구성하지 않고 근거 범위 안에서 구현 원장을 도입했습니다. | `current change`; 범위 테이블에 나열된 현재 소스 및 집중 검사; 루브릭 관련 집중 검사 103건이 통과했습니다. | Self-consistency cascade를 연결하고, 종단 간 감사 영속성을 증명하며, 관리되는 shadow 및 승격 근거를 보존해야 합니다. |

### 남은 작업

- [ ] 프로덕션 T2 경로에서 self-consistency cascade를 호출하고, 불안정한 결과가 자격을 부여하지 않은 채 quality 판정 및 감사 기록에 도달함을 집중 검사로 증명합니다.
- [ ] 루브릭 평가기를 바인딩하고 범위가 제한된 `rubric_*` 출처는 영속화하되 신뢰할 수 없는 근거 설명은 제외함을 증명하는 종단 간 컨트롤 루프 검사를 추가합니다.
- [ ] 고정된 레이블 시나리오 집합에서 고정된 기준선과 처리를 평가한 뒤 환각 포착률, 오탐률, 추가 지연 시간, 토큰 비용 및 정책 위반 우회 0건에 대한 관리되는 증적을 보존합니다.
- [ ] 기본 shadow 상태를 변경하기 전에 지표 기반 shadow 승격 및 회귀 시 강등을 구현하거나, 이 전환을 수동으로 유지한다는 승인된 결정을 기록합니다.

## 왜 루브릭 leg인가

기존 quality 게이트는 이미 네 개 leg로 대부분의 환각을 막는다: 결정론 검증기(권위),
RAG grounding(인용 유효성), mixed-model 교차 검사(구조적 합의), 제안자/비평자/Judge
토론. 두 가지 빈틈이 남아 있었다:

1. **추론 채점 대상이 없음.** `QualityCandidate` 는 제안 액션과 인용은 들고 있었지만
   모델의 자연어 정당화는 없었다. 그래서 faithfulness(모든 주장이 인용 근거에서
   도출되는가?)를 채점할 수 없었다.
2. **다차원 점수화가 없음.** 비평자는 이의를, Judge는 판정을 내지만, 임계로
   거를 수 있는 차원별 점수를 산출하는 장치는 없었다.

루브릭 게이트는 기존 불변식을 하나도 약화하지 않고 이 둘을 메운다.

## 핵심 원칙: 빼기 전용

루브릭은 **빼기만** 할 수 있는 필터다. 이것이 "검증기가 권위, 절대 모델이 아님"과
정합성을 유지하는 불변식이다:

- 게이트는 강제 적용 모드에서 `확신도 = min(aggregate_confidence,
  rubric_min_score)` 로 루브릭을 반영한다. `min()` 이므로 루브릭은 확신도를 **아래로**
  만 밀 수 있고 절대 위로 올리지 못한다.
- 루브릭 실패는 abstain 이유를 추가한다(HIL로 라우팅); 조건을 충족한 이유는 절대 추가하지
  않는다.
- 루브릭은 검증기 거부를 우회하지 못하며, abstain 될 후보를 조건을 충족한으로 뒤집지 못한다.
- 이는 **모든** 결과 경로에서 성립하며, 토론 오케스트레이터가 교차 검증 불일치를
  해소하는 경로도 포함한다: 루브릭 사유가 있으면 토론이 proceed 하려 해도 결과는
  abstain으로 유지된다.

프로퍼티 테스트가 이를 직접 단언한다: 최대 루브릭 점수도 저-confidence 후보를 구제하지
못하고, 토론 PROCEED 후에도 루브릭 FAIL은 존중된다.

## Works with

- `QualityCandidate.reasoning_trace` - 채점 대상(T2 모델의 정당화), 제안자 어댑터가
  전달.
- 규칙 카탈로그 - 모든 루브릭 점수는 supporting 규칙 id를 인용하고, known 규칙 집합에
  대해 검증(fabricated 인용은 abstain).
- `rule-catalog/llm-registry.yaml` 기능 `t2.rubric.judge` -
  `t2.reasoner.primary` 와 다른 발행기(모델이 자기 답을 채점하면 안 됨),
  `llm_resolver.py` 의 구성 로드 시 강제.
- `rule-catalog/prompts/base/t2-rubric.v1.yaml` - catalog-as-code로서의 루브릭 프롬프트,
  `default_mode: shadow`.

## 루브릭 기준

네 개 기준, 닫힌 enum(`RubricCriterion`) - 확신도 계산과 카탈로그 프롬프트가 동일한
차원을 기술하도록. 일부는 결정론으로 검사하는 게 최선이라 검증기 / grounding leg에
남고, 루브릭 판정자는 진짜 의미 차원만 채점한다.

| 기준 | 잡는 것 | 레이어 |
|------|---------|--------|
| `faithfulness` | 인용 규칙으로 지지되지 않는 추론 주장(NLI식) | LLM 판정자 |
| `evidence_action_alignment` | 액션이 인용 규칙에서 도출되지 않음 | LLM 판정자 |
| `completeness` | 영향 범위 / 롤백 / stop-condition 누락 | LLM 판정자 |
| `reasoning_coherence` | 자기모순 또는 논리 비약 | LLM 판정자 + self-consistency |

결정론 차원(스키마 적합성, 인용 존재, blast-radius 수치 상한)은 LLM 루브릭이 아니라
검증기와 grounding leg가 처리한다. 그래서 LLM 판정자는 진짜 모델이 필요한 것에만
쓰인다.

차원별 **통과 임계는 설정** 이며, 전달 어댑터가 `AzureOpenAIRubricEvaluatorConfig`
에서 주입한다 - 모델에서 읽지 않는다. 모델이 자기 통과 기준을 정해선 안 된다. 카탈로그
프롬프트는 모델에게 임계값나 판정을 내지 말라고 명시한다.

## 동작 방식

루브릭은 교차 검사 후(구조적 검사가 이미 기각하지 않은 후보에만 판정자 토큰을 쓰도록),
확신도 임계 전에 실행된다:

1. **점수** - 판정자가 후보의 `reasoning_trace` 를 각 기준으로 채점하고, 각 점수를
   supporting 규칙 id에 grounding.
2. **Reduce** - 순수 `evaluate_rubric_output` 이 점수를 `RubricDecision`
   (`pass` / `fail` / `abstain`) + `min_score` 로 축약.
3. **접기** - 강제 적용 모드에서 게이트가 `min(aggregate_confidence, min_score)` 를
   적용하고 `fail` / `abstain` 시 abstain 이유 추가. shadow 모드에서는 점수를
   기록하되 결과와 확신도는 건드리지 않음.

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

`evaluate_rubric_output` 은 신뢰할 판정을 낼 수 없을 때 abstain(HIL 라우팅), 임계
미달 기준이 있으면 fail, 그 외엔 통과:

- 점수 없음 -> `abstain`.
- 같은 기준이 두 번 이상 채점됨 -> `abstain` (자기모순 응답은 신뢰 신호가 아님).
- 알 수 없음 기준(`RubricCriterion` 집합 밖) 이름의 점수 -> `abstain` (환각/잘못된 차원).
- 필수 기준 누락(`rubric_required_criteria`) -> `abstain` (잘린 응답이 환각 차원을
  조용히 건너뛰지 못하도록).
- 알 수 없음 규칙 id에 grounding된 점수 -> `abstain` (fabricated 인용).
- 임계 미달 점수 존재 -> `fail` (실패 기준 나열).
- 그 외 -> `pass`.

`min_score` 는 `pass` / `fail` 시 기준 전체의 최소값, `abstain` 시 `0.0` - shadow에서
강제 적용으로 전환 시 실패 시 차단 되도록.

**빈 `reasoning_trace`** 는 판정자 호출 전에 short-circuit 된다: faithfulness를 채점할
추론 대상이 없으므로 강제 적용 모드는 판정자 호출 없이 abstain(`rubric_no_reasoning_trace`)
하고, shadow 모드는 결과를 안 바꾸고 abstain을 기록한다.

## 실패 시 차단

평가기 예외(전송 실패, 잘못된 응답)는 절대 조건을 충족한으로 fail-open 하지 않는다. 강제 적용
모드에서는 `rubric_evaluator_error:<Type>` abstain 이유를 추가하고 `min_score` 를
`0.0` 으로; shadow 모드에서는 기록만 하고 결과는 안 바꾼다.

## Self-consistency (보완)

루브릭이 한 답의 품질을 채점한다면, `SelfConsistencySampler` 는 reasoner가 자기 자신과
합의하는지를 측정한다: 같은 제안자를 N회 샘플(temperature > 0)해 `action_stability`
값(`[0.0, 1.0]`)으로 축약한다. 조립 루트가 이 값을 후보의 `confidence_signals`
에 병합하며, 집계가 평균이므로 불안정한 제안자는 확신도를 낮춘다. 샘플링은
토큰 비용을 배가하므로 **cascade** 로 - 더 저렴한 신호가 약할 때만 - 실행되고, 매 T2
호출마다 돌지 않는다. 단독으로 자격을 부여하지 않는다.

## 관찰 모드

루브릭은 shadow-first로 출시한다. `QualityGateConfig.rubric_shadow` 가 기본 `True` 이고
카탈로그 시드가 `default_mode: shadow` 라, 배선된 평가기는 judge-and-log만 한다:
`rubric_scores`, `rubric_verdict`, `rubric_min_score` 가 매 `QualityDecision` 에
측정용으로 기록되지만 결과와 확신도는 건드리지 않는다. 포크는 라벨된 시나리오
세트에서 승격 게이트를 충족한 뒤에만 강제 적용으로 승격한다.

### 승격 지표

고정 시나리오 세트에서 기준선(루브릭 off) 대 처리로 측정, 한쪽만 재지 않는다:

- **hallucination-catch 비율** - 루브릭이 잡은 라벨된 환각.
- **false-positive 비율** - 루브릭이 잘못 HIL로 보낸 정상 후보.
- T2 호출당 **추가 지연 / 토큰 비용**.

승격은 catch 비율이 목표 이상, policy-violation escape 0, false-positive 비율이 허용
상한 이하일 것을 요구한다. 회귀 시 shadow로 강등한다.

## DI 경계

전부 `services/core-control-plane/src/fdai/core/quality_gate/` (코어는 LLM-SDK-free 유지); 구체 어댑터는
`delivery/` 에.

| 경계 | 위치 | 역할 |
|------|------|------|
| `RubricEvaluator` | `rubric.py` | 포크가 실제 판정자 모델로 구현하는 프로토콜 |
| `evaluate_rubric_output` | `rubric.py` | `RubricDecision` 로의 순수 축약 |
| `SelfConsistencySampler` | `self_consistency.py` | 제안자를 N회 샘플해 안정성 측정 |
| `AzureOpenAIRubricEvaluator` | `delivery/azure/llm/rubric.py` | httpx 판정자 클라이언트, 구성 주입 임계 |

## 안전 불변식

- **검증기가 권위.** 루브릭은 자격을 부여하지 않는다.
- **빼기 전용.** 확신도는 `min()` 으로 반영, 절대 더하지 않음.
- **근거에 기반한.** 모든 점수는 supporting 규칙 id를 인용하고 카탈로그에 대해 검증;
  fabricated 인용은 abstain.
- **모델 self-report 금지.** 점수는 명시 기준에 대한 판정자의 평가이고, 판정자는
  제안자와 다른 모델.
- **실패 시 차단.** 평가기 오류는 HIL로 abstain.
- **Shadow-first.** 승격 게이트 충족까지 judge-and-log.

## 한계 (하지 못하는 것)

천장을 정직하게 밝힌다. 루브릭 판정자 자체가 LLM이므로, 이것은 환각의 **확률적 감소** 이지
원천 제거가 아니다. 판정자는 미묘하게 잘못된 정당화를 놓칠 수 있고, 더 나쁘게는 높은 점수를
환각할 수 있다. 설계는 이를 완화한다 - mixed-model 독립성(판정자 != 제안자), 근거에 기반한
인용, 실패 시 차단 기본값, shadow-before-enforce 계측 - 그러나 모든 환각을 잡는다고
주장하지 않는다. 유일한 **강한** 보장은 결정론 검증기다: policy-as-code와 what-if가
승인하지 않으면 아무것도 실행되지 않는다. 루브릭은 확신도를 낮추고 더 많은 케이스를
HIL로 보낼 수 있지만, ungrounded 액션을 안전하게 만들 수는 없다. 남은 약점(일부는 이제
완화됨):

- **Grounding entailment는 명시적 선택이다.** 루브릭 점수의 `supporting_rule_ids` 는 항상
  카탈로그 존재 여부를 확인한다. 배선된 `GroundingSource` 가 `supports()` 를 노출하면
  (예: `RagGroundingSource`), 게이트가 이제 entailment 조건식도 전달해, 존재하지만
  후보를 topically 지지하지 않는 인용은 abstain(`off_topic_score`) 시킨다. `supports()`
  없는 평범한 grounding 출처에서는 id 존재만 확인되어 판정자가 실재하지만 무관한 규칙을
  인용할 여지가 남는다.
- **Self-consistency: 평균 신호 OR 빼기 게이트.** `action_stability` 를 평균
  `confidence_signals` 에 병합하면 희석된다(낮은 값이 가려질 수 있음). 이를 피하려면
  `run_consistency_cascade` 를 써라 - 저렴한 신호가 약할 때만 샘플하고 호출자가 HIL로
  보내는 강한 `stable` 판정을 반환한다(희석 평균이 아니라 빼기 게이트).
- **`min()` 은 서로 다른 두 축을 합친다.** 루브릭 `min_score`(판정자의 기준 평가)와 후보
  `aggregate_confidence`(수집 / verifier-margin 신호)는 서로 다른 척도인데 하나의
  임계값으로 비교된다. 이는 의도된 단순화다: `min()` 은 낮추기만 하므로 축 불일치가
  자격을 올릴 수 없다 - 다만 임계값을 튜닝하는 포크는 둘 다 이 값에 들어감을 알아야
  한다.
- **자동 승격 레지스트리가 없다.** ActionType(=`promotion_gate` 를 `ActionPromotionRegistry`
  가 평가)과 달리, 루브릭의 shadow -> 강제 적용 전환은 수동 `QualityGateConfig.rubric_shadow`
  플립이다. 지표 기반 자동 승격/강등은 향후 작업이다.
- **실모델 계약은 스키마가 아니라 프롬프트로 강제된다.** 테스트는 httpx mock을 쓰고,
  `response_format=json_object` 는 유효 JSON을 보장하지 유효 루브릭 스키마를 보장하지
  않는다. 어댑터의 엄격 파서 + `RubricScore` 검증이 잘못된 실모델 응답을 잡아 실패 시 차단
  하지만, 형태는 카탈로그 프롬프트에 의존하므로 프롬프트/enum 드리프트는 shipped
  catalog-seed 테스트만이 방어한다.

## 통합 상태

업스트림 제어 루프는 이제 T1, shadow-only T2 제안자, mixed-model
`QualityGate`, 결정론적 룰 검증기, 카탈로그 grounding 을 조립합니다. 조건을 충족한 T2
후보 는 감사 되지만 실행 가능한 `Action` 으로 변환되지 않습니다. 해당 다운스트림
브리지 는 계속 게이트 된 작업입니다. 포크가 `LlmBindings.rubric_evaluator` 를 바인딩하면
루브릭 leg 가 실행됩니다. 이를 활성화하려면 포크에서 다음을 권장합니다.

1. `QualityGate` 를 조립하고 바인딩된 `RubricEvaluator` 를 전달한다(`t2.rubric.judge`
   기능에서 해석해 `LlmBindings.rubric_evaluator` 에 바인딩). 판정자의 시스템
   프롬프트는 `t2-rubric` 카탈로그 시드에서 오며, 이는 `rubric` 역할 레이어로 배포된다 -
   작성기의 BASE/묶음 조립 경로가 다루지 않는 레이어다(`get_base` 는 `PromptLayer.BASE`
   만 필터). 그래서 포크가 비평자/Judge 배선이 `t2-critic` / `t2-judge` 를 로드하듯 id/계층으로
   직접 로드한다. CI 게이트(`services/core-control-plane/tests/rule_catalog/test_prompt_registry_consistency.py`)가 모든
   프롬프트 `applies_to` 기능이 `llm-registry.yaml` 에 존재함을 단언하므로, 오타난
   `t2.rubric.judge` 가 프롬프트를 조용히 고아시킬 수 없다.
2. `QualityCandidate.reasoning_trace` 를 계속 채웁니다. 배포된 로컬/Azure 제안자 는
  이를 채우며, 빈 추적 를 반환하는 포크 제안자 는 채점 대상이 없어 루브릭을
  abstain시킵니다.
3. `QualityDecision.rubric_*` 필드를 감사 로그에 직렬화해 shadow 모드 catch /
   false-positive 지표를 실제로 측정할 수 있게 한다. `quality_decision_audit_fields()`
   헬퍼가 이를 JSON-safe하게 flatten한다; 포크의 제어 루프 감사 쓰기 담당이 그 출력을
   per-decision 엔트리에 병합한다. 모든 필드는 구조화된 id / 점수 / enum / 리소스
   참조이며, 예외는 루브릭 `rationale`(신뢰할 수 없는 LLM 자유텍스트)로 기본 제외된다
   (`include_rationale=True` 로 명시적 선택, 길이 제한, 포크는 저장 전 반드시 secret-scan -
  L0 감사는 시크릿/고객값을 기록하지 않습니다). 업스트림 제어 루프는 모든 T2 quality
  결정 에 이 헬퍼를 호출합니다.

루브릭 평가기 가 바인딩되지 않으면 런타임 동작을 바꾸지 않습니다. 바인딩되면 shadow
측정값을 기록하지만 실행 권한 를 높이지 않습니다. 이 방식은 통합을 shadow-first로
유지하면서 이후 승격 결정에 필요한 근거 를 생성합니다.

## Next 단계

| 학습 주제 | 읽을 문서 |
|-----------|-----------|
| T2 티어와 게이트가 지키는 leg | [llm-strategy-ko.md](../architecture/llm-strategy-ko.md) |
| 페이즈 계획에서 게이트 위치 | [phases/phase-2-quality-and-t1-ko.md](../phases/phase-2-quality-and-t1-ko.md) |
| 프롬프트 카탈로그와 역할 x 계층 매트릭스 | [prompt-composition-ko.md](prompt-composition-ko.md) |
| untrusted-input 위협 모델 | [security-and-identity-ko.md](../architecture/security-and-identity-ko.md) |
