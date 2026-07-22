---
title: SRE 성과 측정
description: 자동화량을 신뢰성과 혼동하지 않고 paired baseline을 기준으로 FDAI SRE 성과를 측정하는 방법입니다.
translation_of: measuring-sre-outcomes.md
translation_source_sha: b0fa546247f5409d2b24e8243e9c8152321f82a8
translation_revised: 2026-07-22
---

# SRE 성과 측정

FDAI는 자동으로 판단한 비율이 아니라 outcome과 guard metric으로 SRE 개선을 측정합니다.
모든 비교는 동일한 scenario set, 명시된 measurement window, paired baseline 및 treatment
evidence를 사용합니다.

## 결과 지표

| 지표 | 답하는 질문 |
|------|-------------|
| MTTR distribution | Mean, median, p90에서 해결에 얼마나 걸리나요? |
| Auto-resolution rate | 사람 접점과 사후 rollback 없이 올바른 terminal outcome에 도달한 event는 무엇인가요? |
| Human touchpoints | Incident당 운영자 작업이 얼마나 남았나요? |
| Change lead time | Governed change가 request에서 merge까지 얼마나 걸리나요? |
| Cost per resolved event | 각 결과에 귀속되는 platform 및 inference 비용은 얼마인가요? |

## 보호 지표

Change-failure rate, false positive, false negative, rollback rate, policy-violation escape,
audit gap, verifier failure, mixed-model disagreement를 추적합니다. Guard metric이 threshold를
넘어 회귀하면 outcome 개선으로 인정하지 않습니다.

## 측정 계약

1. Scenario-set version과 input distribution을 고정합니다.
2. Baseline model, rule, threshold, adapter, catalog version을 기록합니다.
3. 동일한 scenario 및 observation window에 treatment를 실행합니다.
4. 평균뿐 아니라 sample size, missing data, confidence, distribution을 보고합니다.
5. Shadow outcome과 enforce outcome을 구분합니다.
6. 측정된 guard metric이 회귀하면 capability를 강등합니다.

## 오해를 만드는 주장 방지

- Paired measurement 없이 multiplier를 주장하지 않습니다.
- 누락된 projection을 0으로 취급하지 않습니다.
- Mean과 p90을 하나의 latency 문장으로 합치지 않습니다.
- 나중에 rollback된 결과를 성공한 auto-resolution으로 세지 않습니다.
- 서로 다른 scenario set을 비교할 때 변경 사실을 숨기지 않습니다.

## 다음 단계

| 학습 대상 | 문서 |
|-----------|------|
| 표준 공식과 window | [목표와 메트릭](../../roadmap/architecture/goals-and-metrics-ko.md) |
| 이름이 있는 scenario set과 evidence level | [시나리오 검증 인벤토리](scenario-validation-inventory-ko.md) |
| SLO burn이 workload impact를 측정하는 방법 | [SLO와 오류 예산](slos-and-error-budgets-ko.md) |
| Shadow evidence가 승격을 제어하는 방법 | [Shadow 후 enforce](../concepts/shadow-then-enforce-ko.md) |
| Audit evidence를 재구성하는 방법 | [감사 로그 읽기](../guides/read-audit-log-ko.md) |
