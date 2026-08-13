---
title: Reviewable Automation Blueprints
---
# Reviewable Automation Blueprints

Automation blueprints turn repeated successful operator work into inert schedule suggestions. A
candidate is evidence-backed, disabled, shadow-only, and reviewable. It cannot create a scheduled
task until an authorized operator accepts and explicitly materializes it.

> **Scope:** Version 1 suggests scheduler tasks only. It doesn't auto-activate schedules, infer a
> broader scope, or let a scheduled run or review conversation suggest another schedule.

## Design at a glance

The deterministic aggregator groups completed-turn evidence by normalized intent, principal,
resource scope, and schedule class. A group qualifies only when it reaches the recurrence
threshold, authority fields stay identical, every outcome succeeds, and scheduler history contains
no unresolved failure for the same key.

The candidate stores evidence fingerprints instead of source text and carries the narrow scope,
schedule, event type, delivery intent, tools, default-deny isolation, estimated cost, confidence,
proposer, and expiry. Optional off-path drafting can change bounded display text only.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Evidence contract and deterministic recurrence aggregation | implemented | `services/core-control-plane/src/fdai/core/scheduler/blueprints/models.py`; `services/core-control-plane/src/fdai/core/scheduler/blueprints/aggregator.py`; `services/core-control-plane/tests/core/scheduler/test_blueprint_aggregator.py` | Focused tests cover inert defaults, threshold and order independence, deduplication, scope and authority separation, outcome stability, scheduler-failure veto, recursion blocking, and input validation. |
| Review, materialization, bounded drafting, audit events, and metric bookkeeping | implemented | `services/core-control-plane/src/fdai/core/scheduler/blueprints/review.py`; `services/core-control-plane/src/fdai/core/scheduler/blueprints/text.py`; `services/core-control-plane/tests/core/scheduler/test_blueprint_review.py` | Focused tests prove authorization, no self-review, terminal suppression, expiry, bounded text, command-mediated and safe-to-retry materialization, audit events, and realized-usage counters. |
| Suggestion orchestration and configuration-review projection | in-progress | `services/core-control-plane/src/fdai/core/scheduler/blueprints/suggestion.py`; `services/core-control-plane/src/fdai/core/scheduler/blueprints/configuration_review.py` | The off-path service and inert configuration-review projection exist, but no production evidence feed, composition binding, or focused orchestration test is present. |
| PostgreSQL durability and compare-and-swap transitions | in-progress | `alembic/versions/20260720_0043_automation_blueprint.py`; `services/core-control-plane/src/fdai/delivery/persistence/postgres_automation_blueprint.py`; `services/core-control-plane/tests/persistence/test_automation_blueprint.py` | The migration, store, and codec exist and the codec test passes. The database-backed persistence and compare-and-swap test was skipped because `FDAI_DATABASE_URL` was unset, so durable behavior is not yet claimed as implemented. |
| Read-only Console route and response decoder | implemented | `console/src/routes/automation-blueprints.tsx`; `console/src/routes/automation-blueprints.test.ts`; `console/src/panel-sources.ts` | The route renders inert candidate and metric fields, rejects contradictory responses, and exposes no mutation controls. This state does not claim an end-to-end Operator API source. |
| Operator API projection and authorized ChatOps review routes | not-started | `console/src/panel-sources.ts`; `services/operator-service/src/fdai_operator_service/` | The Console declares `GET /automation-blueprints`, but no matching Operator Service projection or ChatOps accept, reject, and materialize route factory is present. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance. Recorded the focused-test-backed aggregation, review, materialization, drafting, metrics, and Console decoder as implemented while separating unbound orchestration, unproved PostgreSQL durability, and missing operator surfaces. | `current change`; source and focused tests listed in the scope table; `uv run pytest -q --no-cov services/core-control-plane/tests/core/scheduler/test_blueprint_aggregator.py services/core-control-plane/tests/core/scheduler/test_blueprint_review.py services/core-control-plane/tests/persistence/test_automation_blueprint.py` (`12 passed, 1 skipped` because `FDAI_DATABASE_URL` was unset); `npm --prefix console test -- --run src/routes/automation-blueprints.test.ts` (`2 passed`) | Bind the production services, prove database-backed transitions, expose governed Operator API and ChatOps routes, and collect runtime evidence before claiming `validated`. |

### Remaining work

- [ ] Bind the production evidence feed, suggestion service, PostgreSQL store, authorizer, audit
  publisher, and `CreateScheduledTaskCommand`, then pass an integration test that turns three
  qualifying completed operator turns into one inert durable candidate without recursive input.
- [ ] Run the migration against a disposable PostgreSQL database and pass
  `test_postgres_blueprint_store_persists_and_cas_transitions` with `FDAI_DATABASE_URL` set,
  including concurrent or stale-state compare-and-swap rejection.
- [ ] Add the Reader-gated Operator Service `GET /automation-blueprints` projection and the
  separately authorized ChatOps accept, reject, and materialize routes, then pass API integration
  tests and the Console decoder test against the authoritative response.
- [ ] Export the documented blueprint metrics from the production binding and record governed
  runtime evidence for proposal, review, materialization, scheduled occurrence, and realized-usage
  attribution before changing any scope row to `validated`.

## Evidence and recurrence

`AutomationBlueprintEvidence` records identity, schedule, event type, resource scope, delivery,
tools, isolation, outcome, cost, occurrence time, and source. Only `operator_turn` evidence counts.
`scheduled_run` and `blueprint_review` records never count, and a scheduled failure vetoes its key.

The default threshold is three unique fingerprints. Mixed scopes form separate groups. Candidate
IDs bind the dedup key and frozen evidence set, so order does not matter and genuinely new evidence
can create a later candidate after rejection or expiry.

## Inert contract

Every candidate starts with `state=draft`, `enabled=false`, `shadow_only=true`, no mutation tools,
the narrowest observed scope, default-deny isolation, and a 30-day expiry. Policy bounds expiry to
1 hour through 90 days. Control characters, unsafe IDs, duplicate tools, negative cost, naive
timestamps, and authority drift fail before aggregation.

## Review and materialization

```text
draft -> accepted -> materialized
  |          |
  +-> rejected
  +-> expired <-+
```

Review requires an authorized principal, a reason, and a reviewer distinct from the proposer.
Reject and expiry are terminal. Same-evidence re-submission returns the terminal record; a new
candidate requires a strict fingerprint superset.

Materialization calls `CreateScheduledTaskCommand` with the reviewing principal. It never writes
the scheduler store directly. A stable task ID makes retry idempotent and conflicting content
fails. The resulting task emits shadow-only events into the existing trust and risk path.

A configuration review campaign uses the same path. Three exact, cited runs submit a disabled,
shadow-only candidate with zero mutation tools and one fingerprint per run. A separate Approver or
Owner must accept it before the reviewing principal can materialize the strict weekly task. Drift
evidence never writes the scheduler store directly.

## Text drafting

`AutomationBlueprintTextDrafter` returns only `name` and `prompt` under a 2000-character budget.
Typed output rejects control characters and empty or oversized text. Scope, tools, schedule,
isolation, delivery, autonomy, and risk remain deterministic fields.

## Durability, expiry, and retention

Migration `20260720_0043` creates `automation_blueprint_candidate` with an active-dedup partial
unique index. PostgreSQL stores authority fields, fingerprints, state, review reason, task ID, and
realized usage count. State changes use compare-and-swap.

Expiry changes state but does not delete evidence. Terminal rows remain for audit and suppression.
They contain hashes and bounded metadata, not source conversations. Source turns follow separate
conversation retention; deployments can archive terminal rows after preserving aggregate metrics.

## Review surfaces and metrics

`GET /automation-blueprints` returns read-only cards for evidence, cost, scope, tools, isolation,
confidence, expiry, and state. It has no review or materialize controls. A separate ChatOps route
factory exposes accept/reject and materialize behind an injected principal authorizer.

Metrics report proposed, accepted, rejected, expired, materialized, candidate precision,
acceptance rate, rejection reasons, and actual realized usage. Usage increments only after a
materialized candidate's scheduled occurrence is observed.

## Failure behavior

- Below-threshold, mixed-scope, unstable, unresolved, or authority-drift groups produce nothing.
- Scheduled runs and review conversations cannot recurse into suggestions.
- Unauthorized or self-review attempts fail before state change.
- No candidate creates a task before accepted review and explicit materialization.
- Duplicate materialization returns the existing candidate and task.

## Verification

Coverage includes recurrence, dedup, scope, outcome stability, scheduler veto, recursion,
injection, suppression/new evidence, authorization, no-self-review, expiry, text bounds,
idempotent materialization, PostgreSQL codec/CAS, review APIs, console decoding, and metrics.

## Related docs

| To learn about | Read |
|----------------|------|
| Scheduler execution and isolation | [Process Automation](process-automation.md) |
| Console and ChatOps boundary | [Operator Console](../interfaces/operator-console.md) |
| Post-turn proposal eligibility | [Post-turn Improvement Review](post-turn-improvement-review.md) |
