---
title: 인시던트 완화와 Rollback Runbook
description: Governed mitigation을 적용하고 rollback 또는 recovery를 검증하는 템플릿입니다.
translation_of: incident-mitigation-and-rollback.md
translation_source_sha: f5d1d8c4d7588b56c422f3eb83db5301e888b50e
translation_revised: 2026-07-22
---

# 인시던트 완화와 Rollback Runbook

Investigation이 evidence-backed mitigation proposal을 생성한 뒤 이 runbook을 사용합니다.
Proposal을 deterministic check, risk 및 approval policy, authorized execution, effect
verification, 필요한 경우 rollback까지 이동합니다.

> 이 템플릿은 execution authority를 부여하지 않습니다. 환경별 action, identity, resource
> scope, rollback implementation은 downstream fork에 두고 등록된 `ActionType`을 따라야 합니다.

## 진입 기준

다음 입력이 모두 있을 때만 시작합니다.

- **Incident**: Current state, severity, affected scope, owner, correlation ID입니다.
- **Proposal**: Intended effect, evidence citation, 완화하려는 condition입니다.
- **Action contract**: Registered `ActionType`, mode, precondition, stop condition,
  영향 범위, rollback contract입니다.
- **Authority**: Expected judge, executor, approver, auditor principal입니다.
- **Verification plan**: Effect를 입증하는 health, SLO, dependency, configuration check입니다.

Evidence가 여전히 모호하면 실행하지 말고 [RCA evidence
collection](rca-evidence-collection-ko.md)을 계속합니다.

## 역할

| 역할 | 책임 |
|------|------|
| Incident owner | Response objective를 확인하고 final incident state를 수락합니다. |
| Judge | Required verification 후 typed 결정을 발행합니다. |
| Approver | 사람 승인 action을 검토하며 executor와 구분됩니다. |
| Executor | 선언된 delivery path를 통해 authorized action을 적용합니다. |
| Auditor | 모든 decision, attempt, no-op, rollback, terminal outcome을 기록합니다. |

## 사전 검사

1. Incident state를 refresh하고 proposal이 여전히 measured impact를 다루는지 확인합니다.
2. Evidence timestamp, target inventory, dependency, expected current state를 다시 검증합니다.
3. Policy, what-if, security, 영향 범위 check를 실행합니다.
4. Action이 예상된 shadow 또는 적용 모드인지 확인합니다.
5. Per-resource lock을 획득하고 idempotency key가 이전에 완료되지 않았는지 확인합니다.
6. Stop condition, rollback precondition, rollback owner, recovery check를 확인합니다.
7. Audit writer와 delivery path를 사용할 수 있는지 확인합니다.

Preflight에서 safe execution state를 확정할 수 없으면 no-op을 기록하고 중지합니다.

## Mitigation 절차

1. **Typed proposal을 제출합니다.** Incident, action, target scope, evidence reference,
	mode, idempotency key, rollback reference를 포함합니다.
2. **결정을 받습니다.** Registered judge가 verified proposal을 수락할 때만 계속합니다.
	Deny 또는 hold는 terminal no-op audit record를 생성합니다.
3. **필요한 approval을 받습니다.** Approver가 authorized 상태이며 separation이 필요한
	경우 executor 또는 requester가 아닌지 확인합니다.
4. **한 번 실행합니다.** Authorized executor는 선언된 delivery path만 사용합니다.
	Retry는 동일한 idempotency key를 재사용합니다.
5. **Stop condition을 관찰합니다.** Action 전체에서 health, SLO, dependency, scope,
	delivery state를 모니터링합니다.
6. **Effect를 검증합니다.** 선언된 observation window에서 post-action check를 기록된
	baseline과 비교합니다.
7. **Terminal branch를 선택합니다.** Mitigation 성공을 기록하거나 rollback하거나
	remaining impact와 evidence를 포함해 escalate합니다.

## 결정 분기

| 관찰된 결과 | 필요한 분기 |
|-------------|-------------|
| 예상 effect와 모든 guard check가 통과함 | Action을 유지하고 incident state를 갱신합니다. |
| 새로운 harm은 없지만 material effect가 없음 | 중지하고 no-effect result를 기록한 뒤 investigation으로 돌아갑니다. |
| Stop condition 또는 예상하지 못한 dependency impact가 나타남 | 즉시 rollback을 시작합니다. |
| Delivery state를 알 수 없음 | Incident를 open으로 유지하고 retry 전에 delivery를 검증합니다. |
| Rollback을 실행할 수 없거나 state를 복원하지 못함 | Recovery failure로 escalate합니다. |

## Rollback 절차

1. 추가 attempt를 중지하고 failed action reference를 보존합니다.
2. Rollback이 정확한 applied version과 scope를 대상으로 하는지 확인합니다.
3. Typed pipeline을 통해 필요한 rollback 결정과 approval을 받습니다.
4. Distinct idempotency key로 registered rollback contract를 실행합니다.
5. Prior configuration, health, dependency, SLO state를 검증합니다.
6. Rollback이 service를 fully, partially 또는 failed to restore했는지 기록합니다.

Rollback은 original action을 지우지 않습니다. 두 record는 append-only audit trail에서
연결된 상태로 유지됩니다.

## 중지 조건

Mitigation 전이나 중에 stale evidence, lock failure, scope expansion, policy denial,
missing audit writer, unavailable rollback 또는 unexpected dependency impact가 있으면
중지합니다. Incident state가 크게 변경되어 proposal이 current condition과 더 이상 일치하지
않는 경우에도 중지합니다.

## 검증

Verification은 action effect와 system safety를 모두 입증하는 것이 좋습니다.

- **Effect**: Target error, saturation, drift 또는 unavailable dependency가 개선됩니다.
- **Scope**: Approved resource와 dependency만 변경됩니다.
- **Service**: Health, SLO, user-impact indicator가 observation window 동안 통과합니다.
- **State**: Expected configuration 또는 delivery reference가 active 상태입니다.
- **Audit**: Proposal, 결정, approval, execution, verification, rollback이 연결됩니다.

## Evidence와 완료

Dry-run output, 결정, approval, executor, delivery reference, health check,
rollback reference, final incident state를 기록합니다. 비교에 사용한 timestamp와 baseline도
포함합니다.

Action에 terminal state가 있고 lock이 해제되며 remaining user impact가 기록되고 incident가
monitoring으로 이동했거나 owner와 deadline이 있는 investigation으로 돌아간 경우에만
runbook을 완료합니다.

## 관련 runbook

| 다음 작업 | 문서 |
|-----------|------|
| Incident scope와 severity 재확인 | [Incident triage](incident-triage-ko.md) |
| 다음 proposal을 위한 evidence 수집 | [RCA evidence collection](rca-evidence-collection-ko.md) |
| Recovery 후 response 검토 | [Postmortem workflow](postmortem-workflow-ko.md) |
