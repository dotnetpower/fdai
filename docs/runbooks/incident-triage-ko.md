---
title: 인시던트 분류 Runbook
description: Incident scope, severity, ownership, investigation readiness를 확인하는 customer-neutral 템플릿입니다.
translation_of: incident-triage.md
translation_source_sha: 96e3fd9447f463962906d33fe02f02e03d8061cf
translation_revised: 2026-07-22
---

# 인시던트 분류 Runbook

Incident가 생성되거나 severity, scope 또는 ownership이 크게 변경될 때 이 runbook을
사용합니다. Triage는 영향을 받는 대상, impact의 긴급도, 다음 decision을 책임지는 사람,
bounded investigation을 시작할 만큼 evidence가 최신인지 확정합니다.

> Triage는 root cause를 확정하지 않으며 mitigation을 authorize하지 않습니다. 신뢰할 수
> 있는 incident boundary와 next decision deadline을 만듭니다.

## Triage를 시작하거나 반복하는 경우

다음 event에서 triage를 실행합니다.

- **New incident**: Correlation이 하나 이상의 발견된 문제에서 incident를 생성합니다.
- **Material update**: Affected resource, user impact 또는 SLO burn이 변경됩니다.
- **Ownership failure**: Delivery가 실패하거나 assigned responder가 incident를 수락할 수 없습니다.
- **Merged 또는 split evidence**: Correlation membership이 scope를 바꿀 만큼 변경됩니다.
- **Recovery signal**: Impact가 해결된 것으로 보이며 incident를 monitoring으로 이동할 수 있습니다.

## 전제 조건

- **Identity**: Incident ID, correlation key, current state, member count입니다.
- **Freshness**: Telemetry, inventory, deployment, notification timestamp입니다.
- **Ownership**: 최종 책임자 owner와 사용된 on-call schedule 또는 route입니다.
- **Impact input**: Affected user 또는 operation, SLO state, duration, bounded scope입니다.
- **Concurrency**: 모든 incident transition의 expected current state입니다.

Source를 사용할 수 없으면 unavailable로 표시합니다. Missing data에서 healthy state를
추론하지 않습니다.

## 역할

| 역할 | 책임 |
|------|------|
| Triage owner | Scope, severity basis, unknown, next decision time을 유지합니다. |
| Responder | Notification을 수락하고 bounded investigation을 시작합니다. |
| Service owner | 가능한 경우 service context와 business impact를 확인합니다. |
| Auditor | Membership, severity, ownership, state transition을 기록합니다. |

## Severity 설정

Measured impact와 repository에 설정된 severity policy를 사용합니다. 다음 표는 evidence
수집을 안내하지만 해당 policy를 대체하지 않습니다.

| Signal | 기록할 evidence |
|--------|-----------------|
| User 또는 operation impact | 사용할 수 없거나 저하된 capability와 observed population |
| SLO impact | Objective, window, burn value, remaining error budget |
| Scope | Affected resource, region, dependency, exclusion |
| Duration | First observed time, confirmation time, impact 진행 여부 |
| Recoverability | Known workaround, rollback readiness, protected dependency |

## 절차

1. **Incident record를 확인합니다.** Identity, correlation key, current state, member
	count, newest member timestamp를 검증합니다.
2. **Membership을 검증합니다.** Affected resource를 확인하고 reason이 있는 audited
	correction으로만 member를 추가하거나 제거합니다.
3. **Impact 범위를 정합니다.** Affected capability, resource scope, start time, SLO
	state, dependency, known exclusion을 기록합니다.
4. **Severity를 설정합니다.** Configured policy를 measured impact에 적용합니다.
	Uncertainty를 포함해 사용된 evidence와 rule을 기록합니다.
5. **Ownership을 지정합니다.** Configured route에서 responder를 선택하고 next decision
	deadline을 설정하며 가능한 경우 service owner를 식별합니다.
6. **안전하게 transition합니다.** Concurrent update를 덮어쓰지 않도록 expected current
	state를 사용해 incident를 `triaging`으로 이동합니다.
7. **Investigation을 시작합니다.** Time range, resource scope, evidence budget, 먼저
	답할 질문을 정의합니다.
8. **알리고 검증합니다.** Durable notification을 보내고 성공으로 가정하지 말고
	accepted, failed 또는 fallback delivery를 확인합니다.

## 결정 분기

| Condition | 다음 단계 |
|-----------|-----------|
| Scope와 severity가 확정됨 | [RCA evidence collection](rca-evidence-collection-ko.md)을 시작합니다. |
| Known, verified mitigation이 준비됨 | [Incident mitigation과 rollback](incident-mitigation-and-rollback-ko.md)으로 라우팅합니다. |
| Evidence source를 사용할 수 없음 | Severity를 보수적으로 유지하고 source recovery를 escalate합니다. |
| 관련 없는 여러 cause가 있음 | Audited correlation correction으로 split합니다. |
| Impact는 없지만 recovery가 아직 안정적이지 않음 | Review deadline이 있는 monitoring으로 이동합니다. |
| Notification이 수락되지 않음 | Configured fallback을 사용하고 모든 attempt를 기록합니다. |

## 중지 조건

Identity, ownership, scope, evidence freshness를 확정할 수 없으면 중지하고 에스컬레이션합니다.
Expected incident state가 변경되면 transition을 중지하고 refresh한 뒤 triage를 반복합니다.
데이터가 없다는 이유로 severity를 낮추지 않습니다.

## Evidence와 audit

Transition audit ID, owner, severity basis, member reference, investigation ID,
notification result, next review time을 기록합니다. Source freshness, unknown, exclusion,
모든 membership correction도 기록합니다.

## 완료 기준

Incident에 validated boundary, severity basis, accountable owner, accepted notification 또는
소진된 fallback, bounded investigation, next decision deadline이 있으면 triage가 완료됩니다.
이러한 사실 중 하나가 크게 변경될 때마다 triage를 반복합니다.

## 관련 runbook

| 다음 작업 | 문서 |
|-----------|------|
| Burn-rate trigger 검증 | [SLO burn 대응](slo-burn-response-ko.md) |
| Evidence-backed chronology 구성 | [RCA evidence collection](rca-evidence-collection-ko.md) |
| Governed response 실행 또는 rollback | [Incident mitigation과 rollback](incident-mitigation-and-rollback-ko.md) |
