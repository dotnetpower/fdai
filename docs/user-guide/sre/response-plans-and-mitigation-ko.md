---
title: 대응 계획과 완화
description: FDAI가 action pipeline을 우회하지 않고 incident response plan을 작성, 사전 테스트, 승인, 라우팅하는 방법입니다.
translation_of: response-plans-and-mitigation.md
translation_source_sha: 078a0b69b0c79ce9a379d2b10eec9de15baf0b4c
translation_revised: 2026-07-20
---

# 대응 계획과 완화

인시던트 대응 계획(Incident Response Plan, IRP)은 특정 alert class에 대한 사전 작성된
gated response입니다. Trigger, ordered response step, activation requirement, approver role,
notification channel을 선언합니다. Plan은 mitigation을 제안하고 라우팅할 수 있지만 직접
실행하지 않습니다.

## 작성 게이트

모든 plan은 draft로 시작합니다. Activation은 stop condition, rollback, 영향 범위(blast
radius), approver, notification channel이 모두 선언되고 충족됐는지 확인합니다. Requirement를
생략해도 gate를 우회할 수 없으며 plan은 inactive 상태로 남습니다.

Pretest는 resolved historical incident에 대해 plan을 결정론적으로 평가합니다. Plan의 trigger
signal을 포함한 incident만 denominator에 들어갑니다. 과거에 기록된 resolving action이 plan의
response step에 있으면 해당 case가 covered 상태가 됩니다. Report는 matched count, total count,
unmatched incident reference를 기록합니다. Coverage는 검토 증거이며 자동 activation이 아닙니다.

Plan activation과 action promotion은 별개의 판단입니다. Plan을 activate한다는 것은 trigger와
response structure를 사용할 준비가 됐다는 뜻입니다. 참조된 `ActionType`을 promotion하거나
risk tier를 낮추거나 실행 권한을 부여하지 않습니다.

| Plan 관심사 | 소유 판단 | 안전한 실패 |
|-------------|-----------|-------------|
| Stop, rollback, 영향 범위, approver, channel | Plan readiness gate | Plan을 inactive로 유지 |
| Historical coverage | Pretest review | Gap 기록, 자동 activate 금지 |
| Action safety 및 promotion | Action registry 및 risk-gate | Shadow, HIL 또는 deny |
| Runtime mutation | Executor 검사 | No-op, 중지 또는 rollback |

## Alert 대응 흐름

1. Alert가 시간 제한이 있는 investigation을 시작합니다.
2. Investigation이 finding과 prioritized recommendation을 반환합니다.
3. Coordinator가 grounded actionable recommendation 중 우선순위가 가장 높은 항목을 선택합니다.
4. Mitigation proposal을 설정된 approval gate로 보냅니다.
5. 승인된 proposal이 typed trust 및 risk pipeline에 다시 들어갑니다.
6. Teams 또는 Slack이 governed outcome을 받습니다.

기본 approval gate는 deny합니다. Approval binding이 없거나 고장 나면 action이 발생하지
않습니다.

## 직무 분리 유지

Plan coordinator는 근거 있는 recommendation을 선택하지만 judge, approve, execute를 모두
수행하지 않습니다. Forseti는 verdict를 만들고, Var는 approval record를 전달하며, Thor는
privileged executor이고, Vidar는 rollback을 소유하며, Saga는 audit evidence를 append합니다.
Policy가 요구하는 경우 requester, approver, executor는 서로 다른 principal로 유지됩니다.
Chat message나 성공한 notification delivery는 authenticated approval decision이 아닙니다.

## 완화는 실행이 아님

Response step은 `ActionType`을 지정하며 executor를 호출하지 않습니다. 일반 pipeline이
precondition, stop condition, blast radius, rollback, mode, lock, identity, policy를 계속
검증합니다. Reject와 timeout은 감사되는 no-op으로 종료됩니다.

## 실패 동작

| 실패 지점 | 최종 동작 | 유지되는 증거 |
|-----------|-----------|---------------|
| Grounded actionable finding 없음 | Proposal 없음 | Investigation result 및 gap |
| Investigation timeout 또는 exception | Action 없음 | Partial report 및 unavailable evidence |
| Approval reject | 감사되는 no-op | Rejecting principal 및 reason |
| Approval timeout | 감사되는 no-op 또는 escalation | Expiry 및 ladder state |
| Routing 또는 notification failure | Durable retry 또는 escalation | Delivery attempt, approval 아님 |
| 실행 중 stop condition | 중지 후 compensation policy 적용 | Step outcome 및 rollback reference |

응답 없는 escalation deadline 이후 유효한 standing authorization이 적용되더라도 plan이 직접
실행하지 않습니다. Supervisor는 pending typed action을 새 risk-gate 판단에 제출합니다.
Expired authorization, stale inventory, 넓어진 blast radius, envelope mismatch는 no-op으로
종료됩니다.

## 다음 단계

| 학습 대상 | 문서 |
|-----------|------|
| 증거를 수집하는 방법 | [분류와 조사](triage-and-investigation-ko.md) |
| 승인 경로를 선택하는 방법 | [온콜과 에스컬레이션](on-call-and-escalation-ko.md) |
| Typed action이 안전을 유지하는 방법 | [온톨로지 기반 자동화](../concepts/ontology-driven-automation-ko.md) |
| 운영자 절차 | [SRE runbook](../../runbooks/README-ko.md) |
