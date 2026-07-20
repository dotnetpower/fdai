---
translation_of: automation-blueprints.md
translation_source_sha: 0fe237978dea9c74dec33b6f9b9c8ac935629eb4
translation_revised: 2026-07-21
---
# Reviewable Automation Blueprints

Automation blueprint는 반복해서 성공한 operator work를 inert schedule suggestion으로 바꿉니다.
Candidate는 evidence-backed, disabled, shadow-only, reviewable 상태이며 authorized operator가
accept하고 명시적으로 materialize하기 전에는 scheduled task를 만들 수 없습니다.

> **범위:** Version 1은 scheduler task만 제안합니다. Schedule auto-activation, broad scope 추론,
> scheduled run 또는 review conversation의 recursive schedule suggestion은 지원하지 않습니다.

## Design at a glance

Deterministic aggregator는 completed-turn evidence를 normalized intent, principal, resource scope,
schedule class로 group합니다. Recurrence threshold를 충족하고 authority field가 동일하며 모든
outcome이 성공하고 같은 key의 scheduler history에 unresolved failure가 없어야 합니다.

Candidate는 source text 대신 evidence fingerprint를 저장하고 narrow scope, schedule, event type,
delivery intent, tool, default-deny isolation, estimated cost, confidence, proposer, expiry를 가집니다.
Optional off-path drafting은 bounded display text만 변경할 수 있습니다.

## Evidence and recurrence

`AutomationBlueprintEvidence`는 identity, schedule, event type, resource scope, delivery, tool,
isolation, outcome, cost, occurrence time, source를 기록합니다. `operator_turn` evidence만 count하고
`scheduled_run`과 `blueprint_review`는 count하지 않습니다. Scheduled failure는 matching key를 veto합니다.

Default threshold는 unique fingerprint 3개입니다. Mixed scope는 별도 group입니다. Candidate ID는
dedup key와 frozen evidence set을 bind하므로 order와 무관하고 rejection/expiry 후 실제 new evidence가
생기면 후속 candidate를 만들 수 있습니다.

## Inert contract

모든 candidate는 `state=draft`, `enabled=false`, `shadow_only=true`, mutation tool 없음, narrowest
observed scope, default-deny isolation, 30-day expiry로 시작합니다. Policy는 expiry를 1 hour부터
90 days로 제한합니다. Control character, unsafe ID, duplicate tool, negative cost, naive timestamp,
authority drift는 aggregation 전에 실패합니다.

## Review and materialization

```text
draft -> accepted -> materialized
  |          |
  +-> rejected
  +-> expired <-+
```

Review에는 authorized principal, reason, proposer와 다른 reviewer가 필요합니다. Reject와 expiry는
terminal입니다. Same-evidence 재제출은 terminal record를 반환하고 새 candidate에는 strict fingerprint
superset이 필요합니다.

Materialization은 reviewing principal로 `CreateScheduledTaskCommand`를 호출하며 scheduler store를
직접 쓰지 않습니다. Stable task ID가 retry idempotency를 제공하고 conflicting content는 실패합니다.
결과 task는 existing trust/risk path로 shadow-only event를 보냅니다.

## Text drafting

`AutomationBlueprintTextDrafter`는 2000-character budget에서 `name`과 `prompt`만 반환합니다. Typed
output은 control character와 empty/oversized text를 거부합니다. Scope, tool, schedule, isolation,
delivery, autonomy, risk는 deterministic field로 유지됩니다.

## Durability, expiry, and retention

Migration `20260720_0043`은 active-dedup partial unique index가 있는
`automation_blueprint_candidate`를 생성합니다. PostgreSQL은 authority field, fingerprint, state,
review reason, task ID, realized usage count를 저장하며 state change는 compare-and-swap입니다.

Expiry는 state를 바꾸고 evidence를 삭제하지 않습니다. Terminal row는 audit와 suppression을 위해
남고 source conversation이 아니라 hash와 bounded metadata만 포함합니다. Source turn은 별도
conversation retention을 따르며 deployment는 aggregate metric 보존 후 terminal row를 archive할 수 있습니다.

## Review surfaces and metrics

`GET /automation-blueprints`는 evidence, cost, scope, tool, isolation, confidence, expiry, state를
read-only card로 반환하며 review/materialize control이 없습니다. 별도 ChatOps route factory가 injected
principal authorizer 뒤에서 accept/reject 및 materialize를 제공합니다.

Metric은 proposed, accepted, rejected, expired, materialized, candidate precision, acceptance rate,
rejection reason, actual realized usage를 보고합니다. Usage는 materialized candidate의 scheduled
occurrence가 관찰된 뒤에만 증가합니다.

## Failure behavior

- Below-threshold, mixed-scope, unstable, unresolved, authority-drift group은 아무것도 만들지 않습니다.
- Scheduled run과 review conversation은 suggestion으로 recurse하지 않습니다.
- Unauthorized 또는 self-review는 state change 전에 실패합니다.
- Candidate는 accepted review와 explicit materialization 전에 task를 만들지 않습니다.
- Duplicate materialization은 existing candidate와 task를 반환합니다.

## Verification

Coverage는 recurrence, dedup, scope, outcome stability, scheduler veto, recursion, injection,
suppression/new evidence, authorization, no-self-review, expiry, text bounds, idempotent
materialization, PostgreSQL codec/CAS, review API, console decoding, metrics를 포함합니다.

## Related docs

| To learn about | Read |
|----------------|------|
| Scheduler execution과 isolation | [Process Automation](process-automation-ko.md) |
| Console 및 ChatOps boundary | [Operator Console](../interfaces/operator-console-ko.md) |
| Post-turn proposal eligibility | [Post-turn Improvement Review](post-turn-improvement-review-ko.md) |
