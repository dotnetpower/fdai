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
