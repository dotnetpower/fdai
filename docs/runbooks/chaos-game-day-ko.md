---
title: Chaos Game Day Runbook
description: 범위가 제한된 chaos experiment를 계획, 승인, 실행, 복구하는 템플릿입니다.
translation_of: chaos-game-day.md
translation_source_sha: 524a3237130a5075baf472f394e8ab3f8f905d6d
translation_revised: 2026-07-22
---

# Chaos Game Day Runbook

범위가 제한된 chaos experiment를 계획, 승인, 실행하고 복구할 때 이 runbook을 사용합니다.
Game day는 promoted scenario, 동결된 target set, 지속적인 probe, 검증된 rollback path를
사용해 하나의 resilience hypothesis를 검증합니다.

> 환경별 fault injection은 downstream fork에서만 실행하세요. 이 upstream 절차는 live target
> 또는 provider command가 아니라 safety 및 evidence contract를 정의합니다.

## 이 runbook을 사용하는 경우

Scenario가 schema, policy, regression, shadow review를 이미 통과했고 팀이 live-like
environment에서 통제된 evidence를 확보해야 할 때 game day를 사용합니다. 설명되지 않은
active incident를 진단하기 위해 game day를 사용하지 않습니다.

일반적인 목표는 다음과 같습니다.

- **Failover validation**: Dependency 또는 replica가 objective 안에 takeover할 수 있음을 입증합니다.
- **Detection validation**: 예상 발견된 문제, incident, notification이 나타남을 입증합니다.
- **Rollback validation**: Injected fault를 제거하고 steady state를 복원할 수 있음을 입증합니다.
- **Human response validation**: Owner가 evidence를 받고 예상 handoff를 따름을 입증합니다.

## 역할과 필수 입력

| 역할 또는 입력 | 책임 |
|----------------|------|
| Exercise owner | Hypothesis, schedule, coordination, final record를 책임집니다. |
| Approver | Scope, risk, stop condition, rollback을 독립적으로 검토합니다. |
| Operator | Authorized provider를 통해 approved scenario를 시작하고 중지합니다. |
| Observer | Probe를 관찰하고 즉시 중지를 요청할 수 있습니다. |
| Scenario | Versioned fault, target selector, duration, 영향 범위 limit입니다. |
| Steady state | Experiment 중 유지돼야 하는 측정 가능한 상태입니다. |
| Rollback | Fault를 제거하고 prior state를 복원하는 검증된 action입니다. |

Operator와 approver는 구분하는 것이 좋습니다. 선언된 condition이 발생하거나 observed state가
불명확해지면 모든 participant가 중지를 요청할 수 있습니다.

## 사전 검사

Exercise window가 열리기 전에 preflight를 완료합니다.

1. Scenario version과 shadow evidence를 확인합니다.
2. 하나의 반증 가능한 hypothesis와 예상 probe movement를 작성합니다.
3. 정확한 target set을 동결하고 protected dependency가 제외됐는지 확인합니다.
4. Baseline probe value를 기록하고 telemetry freshness를 확인합니다.
5. Stop condition, maximum duration, concurrency, affected scope를 검증합니다.
6. Rollback path를 test하거나 동일 scenario version의 최근 evidence를 첨부합니다.
7. Operator identity, required lock, audit writer, notification route를 확인합니다.
8. Exercise window를 알리고 stop authority가 있는 사람을 식별합니다.

Preflight 항목을 사용할 수 없으면 no-op outcome을 기록하고 일정을 다시 잡습니다.

## 실행 절차

1. **Exercise를 엽니다.** Scenario, target set, participant, approval, baseline sample,
	planned end time을 기록합니다.
2. **Safeguard를 획득합니다.** 필요한 resource lock을 획득하고 conflicting change 또는
	active incident가 target과 겹치지 않는지 확인합니다.
3. **Scenario를 시작합니다.** Approved provider를 통해서만 inject하고 provider operation
	reference와 start time을 기록합니다.
4. **계속 관찰합니다.** Experiment 동안 steady-state, detection, dependency, scope probe를
	평가합니다. Missing 또는 stale sample은 healthy value가 아니라 failure입니다.
5. **Hold 또는 stop합니다.** 모든 guard condition이 유효한 동안에만 계속합니다.
	Authorized observer는 누구나 stop branch를 시작할 수 있습니다.
6. **Fault를 제거합니다.** Duration limit, hypothesis 관찰 또는 stop condition 발생 시
	선언된 rollback을 실행합니다.
7. **Recovery를 검증합니다.** Target set이 steady state로 돌아오고 injected resource,
	lock, temporary permission이 남지 않았는지 확인합니다.
8. **Exercise를 종료합니다.** Hypothesis result, unexpected impact, recovery time,
	follow-up owner를 기록합니다.

## 중지 조건

다음 조건이 발생하면 injection을 즉시 중지합니다.

- **Scope expansion**: 동결된 set 외부의 target이 영향을 받습니다.
- **Protected impact**: Protected dependency 또는 control-plane component가 저하됩니다.
- **Stale observation**: Required probe, inventory snapshot 또는 audit writer를 사용할 수 없습니다.
- **Safety limit**: Duration, concurrency, error rate, latency 또는 affected-resource cap에 도달합니다.
- **Conflicting operation**: 동일 target에서 incident response 또는 deployment가 시작됩니다.
- **Rollback uncertainty**: Rollback path를 사용할 수 없거나 precondition이 변경됩니다.

중지는 유효한 experiment outcome입니다. Active run 안에서 duration 또는 target set을
확장하지 않습니다.

## Recovery와 escalation

문서화된 순서로 rollback을 실행하고 모든 required steady-state condition이 설정된 recovery
window 동안 통과할 때까지 sampling을 계속합니다. Recovery가 완료되지 않으면 [incident
triage](incident-triage-ko.md)로 전환하고 experiment correlation ID를 보존하며 exercise를
incident source로 취급합니다.

첫 injection을 보상하려고 두 번째 injection을 시작하지 않습니다. Recovery action은 자체
approved path를 따라야 하며 별도의 audit record를 남겨야 합니다.

## Evidence와 audit

다음 evidence를 기록합니다.

- **Plan**: Scenario 및 catalog version, hypothesis, target hash, exercise window입니다.
- **Authority**: Owner, approver, operator, observer, approval reference입니다.
- **Baseline**: Pre-exercise probe value와 telemetry timestamp입니다.
- **Execution**: Lock reference, provider operation, injection 및 stop time, stop reason입니다.
- **Observation**: Steady-state, detection, dependency, scope sample입니다.
- **Recovery**: Rollback reference, recovery sample, recovery time, residual impact입니다.
- **Outcome**: Supported, disproved 또는 inconclusive hypothesis와 owned follow-up입니다.

## 완료 기준

Rollback이 완료되고 steady state가 검증되며 temporary access가 제거되고 lock이 해제되며
모든 follow-up에 owner와 evidence target이 지정된 뒤에만 game day를 종료합니다. 새로
발견한 detection 또는 response gap은 [postmortem workflow](postmortem-workflow-ko.md)를
통해 제출합니다.

## 관련 runbook

| 다음 작업 | 문서 |
|-----------|------|
| 예상하지 못한 service impact 분류 | [Incident triage](incident-triage-ko.md) |
| Governed recovery action 적용 | [Incident mitigation과 rollback](incident-mitigation-and-rollback-ko.md) |
| Exercise 발견된 문제를 owner가 있는 개선으로 전환 | [Postmortem workflow](postmortem-workflow-ko.md) |
