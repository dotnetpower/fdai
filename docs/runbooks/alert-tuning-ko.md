---
title: Alert Tuning Runbook
description: 측정된 rule 및 routing change로 alert noise와 missed detection을 줄이는 템플릿입니다.
translation_of: alert-tuning.md
translation_source_sha: f285f73b104ed60d0d538a3ea0fe4eb44e41f366
translation_revised: 2026-07-22
---

# Alert Tuning Runbook

False positive, false negative, duplicate incident 또는 오래된 routing으로 alert의
유용성이 떨어질 때 이 runbook을 사용합니다. FDAI가 관찰하고 기록하지만 조치하지 않는
관찰 모드에서 동결된 baseline과 하나의 변경 제안을 비교해 tuning을 측정 가능하게
유지합니다.

> 환경별 detector 이름, dashboard query, notification destination, promotion command는
> downstream fork에 보관하세요. 이 upstream 템플릿에 customer value를 넣지 않습니다.

## 이 runbook을 사용하는 경우

다음 signal 중 하나 이상이 정상 observation window보다 오래 지속되면 이 runbook을
시작합니다.

- **False positive**: Alert가 발생하지만 labeled evidence에는 조치 가능한 상태가 없습니다.
- **False negative**: 확인된 incident에 일치하는 detector 또는 route event가 없습니다.
- **Duplicate**: 하나의 상태가 여러 incident 또는 반복 notification을 만듭니다.
- **Late delivery**: Detector는 제때 발생하지만 correlation 또는 routing이 deadline을 놓칩니다.
- **Stale routing**: Delivery target, ownership 또는 escalation policy가 service와 더 이상 일치하지 않습니다.

현재 활성 incident를 숨기기 위한 tuning에는 사용하지 않습니다. 먼저 [incident
triage](incident-triage-ko.md)를 완료한 다음 labeled case를 가지고 돌아옵니다.

## 역할과 입력

| 항목 | 필요한 입력 |
|------|-------------|
| Owner | 검토 대상 detector 또는 route를 책임지는 사람 |
| Reviewer | Promotion 또는 rollback을 승인하는 owner 이외의 사람 |
| Scenario set | 동결된 positive, negative, duplicate, delivery-failure case |
| Baseline | Detector, correlation, routing, catalog, configuration version |
| Guard metric | Missed incident, notification latency, duplicate ratio, policy escape |
| Observation window | Baseline과 treatment에 사용하는 고정된 기간 또는 event 수 |

Owner는 비교를 준비하고 실행할 수 있습니다. Alert volume을 최적화하는 사람이 약해진
safety signal을 혼자 승인하지 않도록 promotion에는 독립적인 review가 필요합니다.

## 사전 검사

Configuration을 변경하기 전에 다음 단계를 완료합니다.

1. Scenario label에 evidence source와 review date가 있는지 확인합니다.
2. 현재 detector, correlation, routing, catalog version을 기록합니다.
3. Baseline과 treatment run이 동일한 scenario와 observation window를 사용하는지 확인합니다.
4. Shadow result가 incident를 생성, 종료 또는 변경하지 않고 audit record를 쓰는지 검증합니다.
5. 현재 configuration을 rollback reference로 저장합니다.
6. 활성 incident가 변경 대상 detector에 의존하면 tuning을 일시 중지합니다.

## Failure 진단

변경을 선택하기 전에 관찰된 defect를 분류합니다. 하나의 defect에 여러 symptom이 있을 수
있지만, 각 treatment run에서는 axis 하나만 변경합니다.

| Symptom | 먼저 검사할 항목 | 일반적인 treatment axis |
|---------|-------------------|-------------------------|
| 모든 시간대에 일정한 noise | Baseline과 threshold | Baseline window 또는 threshold |
| 예측 가능한 시간대의 noise | Seasonality model | Seasonal window 또는 schedule |
| 하나의 상태에 반복되는 alert | Deduplication과 debounce | Correlation key 또는 debounce interval |
| 관련 signal이 여러 incident로 분리됨 | Correlation evidence | Correlation rule 또는 time window |
| 확인된 incident에 alert가 없음 | Coverage와 missing-data 처리 | Detector condition 또는 data-quality route |
| 올바른 alert가 잘못된 responder에게 전달됨 | Ownership과 channel policy | Route mapping 또는 escalation policy |
| 올바른 route가 늦거나 실패함 | Delivery outcome과 retry audit | Delivery retry 또는 fallback route |

## 절차

1. **Baseline을 측정합니다.** 동결된 scenario set을 실행하고 fire rate, precision,
	recall, duplicate ratio, cold-start hold, delivery latency, terminal delivery outcome을
	수집합니다.
2. **하나의 treatment를 선택합니다.** Defect 분류, 변경할 하나의 configuration axis,
	예상되는 metric 변화를 명시합니다.
3. **Shadow에서 실행합니다.** Treatment를 shadow evaluator에만 적용하고 동일한
	observation window에서 같은 scenario set을 다시 실행합니다.
4. **결과를 비교합니다.** 모든 primary 및 guard metric의 baseline과 treatment 값을
	계산합니다. Missing sample을 0으로 처리하지 말고 이유를 설명합니다.
5. **Failure를 검토합니다.** Promotion을 고려하기 전에 새로 누락된 incident, policy
	escape, correlation되지 않은 duplicate, failed delivery를 모두 검사합니다.
6. **결정합니다.** Target metric이 개선되고 guard metric이 선언된 범위를 유지하며
	독립 reviewer가 evidence를 수락할 때만 promote합니다.
7. **Rollout을 관찰합니다.** 이전 configuration을 사용할 수 있게 유지하고 선언된
	observation window 동안 promoted version을 모니터링합니다.

## 결정 분기

| 결과 | 조치 |
|------|------|
| Target metric이 개선되고 모든 guard metric이 통과함 | 설정된 promotion path를 승인합니다. |
| Target metric은 개선되지만 guard metric이 회귀함 | Treatment를 거부하고 baseline을 복원합니다. |
| 결과를 판단할 수 없음 | Scenario set을 확장하거나 label을 수정한 후 baseline부터 다시 시작합니다. |
| Policy-violation escape가 나타남 | Promotion을 차단하고 safety review로 라우팅합니다. |
| Live observation이 shadow와 크게 다름 | Rollback하고 두 result set을 review용으로 보존합니다. |

## 중지 조건

다음 조건이 발생하면 run을 중지합니다.

- **신뢰할 수 없는 label**: Evidence가 없거나 오래됐거나 합의되지 않았습니다.
- **유효하지 않은 비교**: Baseline과 treatment가 다른 scenario 또는 window를 사용합니다.
- **Safety regression**: Missed incident 또는 policy-violation escape가 증가합니다.
- **숨겨진 scope 변경**: 둘 이상의 configuration axis가 변경됐습니다.
- **활성 dependency**: 진행 중인 incident가 현재 형태의 detector를 필요로 합니다.

Volume을 줄이기 위해서만 alert를 억제하지 않습니다. Detection 또는 delivery 품질이
저하되면 낮은 alert count는 개선이 아닙니다.

## Rollback과 recovery

Promotion guard metric이 실패하거나 live observation이 shadow와 다르면 기록된 baseline
version을 복원합니다. Rollback 후 작은 canary subset을 다시 실행하고 detector,
correlation, delivery outcome이 이전 baseline과 일치하는지 확인합니다. 실패한 treatment를
evidence로 유지하고 rollback run으로 덮어쓰지 않습니다.

## Evidence와 audit

다음 record를 tuning decision에 첨부합니다.

- **Identity**: Owner, reviewer, detector 또는 route ID, change reference입니다.
- **Version**: Detector, correlation, routing, catalog, baseline, treatment version입니다.
- **Dataset**: Scenario-set hash, label provenance, observation window입니다.
- **Measurement**: 모든 primary 및 guard metric의 baseline과 treatment 값입니다.
- **Exception**: Missed case, duplicate, failed delivery, policy escape입니다.
- **Decision**: Approving principal과 함께 promote, reject, extend, rollback 중 하나를 기록합니다.
- **Outcome**: Rollout window, rollback reference, final configuration version입니다.

## 완료 기준

Decision이 audit되고 active configuration version을 알 수 있으며 promoted treatment 또는
복원된 baseline이 observation window를 통과한 뒤에만 tuning 작업을 종료합니다. 새로 발견한
response gap은 이 변경을 확장하지 말고 [postmortem workflow](postmortem-workflow-ko.md)로
보냅니다.

## 관련 runbook

| 다음 작업 | 문서 |
|-----------|------|
| 활성 incident의 scope와 severity 분류 | [Incident triage](incident-triage-ko.md) |
| Service-level objective burn 검증 | [SLO burn 대응](slo-burn-response-ko.md) |
| Response gap을 owner가 있는 follow-up으로 전환 | [Postmortem workflow](postmortem-workflow-ko.md) |
