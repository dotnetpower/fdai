---
title: 분류와 조사
description: FDAI가 범위가 제한된 cross-resource 증거를 수집하고 감사 가능한 investigation report를 만드는 방법입니다.
translation_of: triage-and-investigation.md
translation_source_sha: 749debc12028111a458999366aa1073a593b10b4
translation_revised: 2026-07-22
---

# 분류와 조사

Triage는 ownership, impact, urgency를 확정합니다. Investigation은 read operation을 숨겨진
mutation path로 만들지 않으면서 incident를 설명할 수 있는 최소 증거 세트를 수집합니다.

## 조사 계약

Investigation request는 incident, target resource, time range, latency budget을 지정합니다.
Resource analyzer는 provider evidence를 읽고 structured 발견된 문제를 반환합니다. Coordinator는
timeline, correlation, optional root-cause hypothesis, prioritized recommendation을 만듭니다.

Report는 read-only입니다. 수정을 지정하는 recommendation도 제안일 뿐이며 typed
action pipeline에 다시 들어가야 합니다.

## 범위가 제한된 증거 수집

- **Resource scope**는 analyzer가 검사할 수 있는 resource를 제한합니다.
- **Time range**는 무제한 history query를 방지합니다.
- **Latency budget**은 조사가 정해진 시간 안에 완료됐는지 기록합니다.
- **Provider failure**는 unavailable evidence가 되며 사실을 만들어내지 않습니다.
- **Priority**는 recommendation을 P1, P2, P3로 정렬하지만 실행 권한을 주지 않습니다.

Evidence availability는 누락된 field에서 추론하지 않고 명시적으로 기록합니다. Priority는
report 내부의 local ordering입니다. 별도 policy가 정의하지 않는 한 severity, confidence,
autonomy 결정이 아닙니다.

| Evidence state | 의미 | Downstream 동작 |
|----------------|------|-----------------|
| Available | Provider가 범위가 제한된 fresh data 반환 | 발견된 문제 및 hypothesis 근거로 사용 가능 |
| Empty | Query 성공, 일치하는 record 없음 | Query scope와 함께 부재 보고 |
| Unavailable | Provider 실패 또는 dependency unhealthy | Gap 표시 및 의존 claim 억제 |
| Stale | Data는 있지만 freshness policy 초과 | 의존 conclusion을 검토 보류 |

## 분류 워크플로

1. Incident severity, owner, affected resource, user impact를 확인합니다.
2. Telemetry와 inventory가 조사에 충분히 최신인지 확인합니다.
3. 선언된 resource type에 해당하는 analyzer만 실행합니다.
4. 인과관계를 주장하기 전에 ordered timeline을 만듭니다.
5. Correlated observation과 grounded root-cause hypothesis를 구분합니다.
6. Actionable recommendation을 incident response plan 또는 일반 action proposal로 보냅니다.

## 리포트 읽기

| 섹션 | 답하는 질문 |
|------|-------------|
| 발견된 문제 | 각 resource analyzer가 무엇을 관찰했나요? |
| Timeline | Change와 symptom이 어떤 순서로 발생했나요? |
| Correlations | 어떤 observation이 함께 움직이나요? |
| RCA hypothesis | 인용된 증거가 어떤 원인을 뒷받침하나요? |
| Recommendations | 다음에 무엇을 검사, simulate, propose해야 하나요? |
| Budget result | 증거 수집이 선언된 제한 안에 완료됐나요? |

## 실패 동작

멈춘 analyzer는 시간 제한을 받고 no-action 결과를 생성합니다. Exception은 unavailable
evidence로 기록되며 response를 crash시켜 audit trail을 잃지 않습니다. Cancellation은
조사를 정상적으로 중단합니다.

Analyzer는 서로 독립적으로 실패합니다. 완료된 analyzer result는 partial report에 남고,
실패하거나 timeout된 analyzer는 명시적인 gap을 추가합니다. 전체 latency budget이 만료되면
coordinator는 새 evidence 수집을 중지하고 budget 충족 여부를 기록하며 근거가 있는 observation만
반환합니다. 누락된 section을 model prose로 채우거나 partial report를 action으로 바꾸지 않습니다.

Recommendation을 사용하기 전에 supporting analyzer가 완료됐는지, cited evidence가 fresh인지,
recommendation이 선언된 resource 및 time scope 안에 있는지 확인합니다. 높은 report priority는
검토를 앞당길 수 있지만 RCA 근거 확인, risk classification, approval을 우회할 수 없습니다.

## 다음 단계

| 학습 대상 | 문서 |
|-----------|------|
| Incident record가 변경되는 방법 | [인시던트 관리](incident-management-ko.md) |
| 인용된 hypothesis가 gate를 통과하는 방법 | [근본 원인 분석](root-cause-analysis-ko.md) |
| Recommendation이 proposal이 되는 방법 | [대응 계획과 완화](response-plans-and-mitigation-ko.md) |
| Supporting record를 검사하는 방법 | [감사 로그 읽기](../guides/read-audit-log-ko.md) |
