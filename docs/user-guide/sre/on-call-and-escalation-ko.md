---
title: 온콜과 에스컬레이션
description: FDAI가 대응의 최종 책임자를 선택하고 대기 중인 결정을 에스컬레이션하며 페이징 연동이 없을 때 안전하게 중단하는 방법입니다.
translation_of: on-call-and-escalation.md
translation_source_sha: 7f8474eff0520df0c0be4029bb8e41842095abd3
translation_revised: 2026-07-20
---

# 온콜과 에스컬레이션

온콜 라우팅은 notification channel에 실행 권한을 주지 않으면서 인시던트를 책임 있는
사람과 연결합니다. FDAI는 현재 responder를 확인하고 설정된 escalation ladder를 적용하며,
모든 timeout, reroute, approval, no-op을 기록합니다.

> Upstream on-call schedule seam과 fail-safe resolver는 구현되어 있습니다. PagerDuty 또는
> Opsgenie adapter와 channel별 DM targeting은 배포 또는 fork binding으로 남아 있습니다.
> Status-page broadcast는 Deferred입니다.

## 대응자 확인

Resolver는 시간 범위가 있는 schedule을 읽고 현재 shift의 principal을 반환합니다.
Schedule이 없거나 오래됐거나 unavailable이면 FDAI는 설정된 fail-safe route를 사용하고
degraded routing을 기록합니다. Identity를 추측하지 않습니다.

Approval과 execution은 서로 다른 principal로 유지됩니다. On-call responder는 RBAC와 policy
범위에서만 검토 또는 승인할 수 있으며, shift 중이라는 이유로 executor credential을 받지
않습니다.

## 에스컬레이션 단계

Escalation ladder는 level, wait period, channel, role, stop condition을 정의합니다. Pending
decision은 scope와 severity에 따라 primary on-call에서 secondary, incident commander,
owner로 이동할 수 있습니다.

느린 supervisory loop는 기저 risk verdict를 직접 변경하지 않습니다. 책임 있는 approver를
찾거나 request를 expire할 수 있지만 `deny`를 `auto`로 바꾸거나 사람 대신 승인할 수 없습니다.
일치하는 standing authorization은 ladder deadline 이후 typed proposal을 새 판단을 위해
risk-gate에 다시 넣을 수만 있습니다.

## Delivery fallback과 authority escalation 구분

두 mechanism은 서로 다른 실패에 답하며 별개의 audit history를 유지합니다.

| Mechanism | Trigger | 변경되는 내용 |
|-----------|---------|---------------|
| Channel fallback | 동일 recipient에게 channel이 전달하지 못함 | Delivery pipe |
| Escalation ladder | 전달은 성공했지만 rung TTL 전에 authorized decision이 없음 | 요청 대상 human authority |

각 ladder는 유한한 rung 수와 overall deadline을 가집니다. 모든 rung transition은 audience,
category, start, expiry, result를 기록합니다. 이후 rung도 no self-approval을 적용하며 executor
identity를 상속하지 않습니다.

## 신뢰할 수 있는 forecast에 따른 시간 단축

Forecast-backed incident에서 supervisor는 tick마다 urgency를 다시 계산합니다. Effective rung
window는 `effective_ttl = min(rung.ttl, k * remaining_lead_time)`을 따르므로 가까워지는 breach
ETA가 configured TTL을 줄일 수는 있지만 늘릴 수는 없습니다. Impact에 따라 더 높은 시작
rung을 선택할 수도 있습니다.

Prediction interval이 configured confidence level을 통과한 forecast만 시간을 줄일 수 있습니다.
Noisy point estimate는 escalation을 가속할 수 없습니다. Urgency는 사람에게 요청하는 속도만
바꾸며 실행 권한을 주지 않습니다.

## 검토를 우회하지 않는 standing authority

Standing authorization은 operator-authored policy artifact입니다. Deterministic condition,
resource-group-equivalent 이하 envelope, reversible action type, tested rollback contract,
unanswered-ladder trigger를 식별합니다. Shadow mode에서 시작하고 자체 promotion gate를 따릅니다.

Deadline 이후 supervisor는 authorization이 valid, unexpired, in-scope 상태이며 pending action을
계속 포함하는지 확인합니다. 그런 다음 proposal을 typed pipeline에 다시 주입합니다. Forseti와
risk-gate가 현재 inventory 및 policy를 다시 평가하고, 새 verdict가 `auto`인 경우에만 Thor가
실행합니다. Irreversible action, stale evidence, 넓어진 blast radius, envelope miss는 감사되는
no-op으로 종료됩니다.

| 최종 상태 | 의미 |
|-----------|------|
| Approved | Authorized human이 expiry 전에 결정 |
| Rejected | Authorized human이 reject, action 없음 |
| Standing-authority executed | Deadline 통과 후 새 risk decision이 envelope 검증 |
| Terminal no-op | Valid human 또는 standing decision 없이 ladder 종료 |

## 운영자 확인 사항

1. Schedule freshness, timezone, handoff boundary를 확인합니다.
2. Incident scope와 severity가 예상 ladder를 선택하는지 확인합니다.
3. 필요한 경우 approver가 executor 및 requester와 다른지 검증합니다.
4. Notification delivery와 durable retry state를 확인합니다.
5. Expiration을 감사되는 no-op으로 처리합니다.

## 커뮤니케이션

Operational alert, approval request, incident lifecycle notice는 서로 다른 message class와
RBAC floor를 사용합니다. Channel은 incident ID, scope, severity, evidence link, requested
decision, expiry처럼 행동에 필요한 최소 context만 받습니다. Secret과 raw customer data는
message에 포함하지 않습니다.

## 다음 단계

| 학습 대상 | 문서 |
|-----------|------|
| 승인이 작동하는 방법 | [승인과 채널](../concepts/approvals-and-channels-ko.md) |
| 에스컬레이션 계약 | [에스컬레이션과 Standing Authority](../../roadmap/decisioning/escalation-and-standing-authority-ko.md) |
| 채널 라우팅 | [채널과 알림](../../roadmap/interfaces/channels-and-notifications-ko.md) |
| Incident ownership | [인시던트 관리](incident-management-ko.md) |
