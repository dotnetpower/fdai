---
title: On-Call and Escalation
description: How FDAI selects the final owner for a response, escalates pending decisions, and fails closed when paging integrations are unavailable.
---

# On-Call and Escalation

On-call routing connects an incident to an accountable human without giving a
notification channel execution authority. FDAI resolves the current responder,
applies the configured escalation ladder, and records every timeout, reroute,
approval, and no-op.

> The upstream on-call schedule seam and fail-safe resolver are implemented.
> PagerDuty or Opsgenie adapters and channel-specific direct-message targeting
> remain deployment or fork bindings. Status-page broadcast is deferred.

## Resolve the responder

The resolver reads a time-bounded schedule and returns the principal on shift.
If the schedule is missing, stale, or unavailable, FDAI uses the configured
fail-safe route and records degraded routing. It does not guess an identity.

Approval and execution remain distinct principals. An on-call responder can
review or approve only within RBAC and policy; being on shift does not grant
executor credentials.

## Escalation ladder

An escalation ladder defines levels, wait periods, channels, roles, and stop
conditions. A pending decision can move from primary on-call to secondary,
incident commander, or owner according to scope and severity.

The slower supervisory loop never changes the underlying risk decision directly.
It can seek an accountable approver or expire the request, but cannot turn
`deny` into `auto` or approve on behalf of a person. A matching standing
authorization can only cause the typed proposal to re-enter the safety check for a
fresh decision after the ladder deadline.

## Distinguish delivery fallback from authority escalation

These mechanisms answer different failures and keep separate audit histories.

| Mechanism | Trigger | What changes |
|-----------|---------|--------------|
| Channel fallback | A channel cannot deliver to the same recipient | The delivery pipe |
| Escalation ladder | Delivery succeeded but no authorized decision arrived before the rung TTL | The human authority being asked |

Each ladder has a finite number of rungs and an overall deadline. Every rung
transition records the audience, category, start, expiry, and result. Later
rungs still enforce no self-approval and do not inherit executor identity.

## Compress time when a forecast is credible

For a forecast-backed incident, the supervisor recomputes urgency on each tick.
The effective rung window follows
`effective_ttl = min(rung.ttl, k * remaining_lead_time)`, so a closing breach
ETA can shorten but never lengthen the configured TTL. Impact can also select a
higher starting rung.

Only a forecast whose prediction interval clears the configured confidence
level may compress time. A noisy point estimate cannot accelerate escalation.
Urgency changes how quickly people are asked; it does not grant execution
authority.

## Use standing authority without bypassing review

A standing authorization is an operator-authored policy artifact. It identifies
a deterministic condition, a resource-group-equivalent or narrower envelope,
reversible action types, a tested rollback contract, and the unanswered-ladder
trigger. It starts in observation mode and follows its own promotion gate.

After the deadline, the supervisor verifies that the authorization is valid,
unexpired, in scope, and still contains the pending action. It then re-injects
the proposal into the typed pipeline. Forseti and the safety check re-evaluate
current inventory and policy; Thor executes only if the new decision is `auto`.
An irreversible action, stale evidence, widened impact scope, or envelope miss
ends as an audited no-op.

| Terminal state | Meaning |
|----------------|---------|
| Approved | An authorized human decided before expiry |
| Rejected | An authorized human rejected; no action |
| Standing-authority executed | Deadline passed and a fresh risk decision verified the envelope |
| Terminal no-op | Ladder ended without a valid human or standing decision |

## Operator checks

1. Confirm schedule freshness, timezone, and handoff boundary.
2. Confirm incident scope and severity select the expected ladder.
3. Verify the approver is distinct from the executor and requester where required.
4. Check notification delivery and durable retry state.
5. Treat expiration as an audited no-op.

## Communications

Operational alerts, approval requests, and incident lifecycle notices use
different message classes and RBAC floors. Channels receive the minimum context
needed to act: incident ID, scope, severity, evidence links, requested decision,
and expiry. Secrets and raw customer data stay out of messages.

## Next steps

| To learn about | Read |
|----------------|------|
| How approvals work | [Approvals and channels](../concepts/approvals-and-channels.md) |
| The escalation contract | [Escalation and Standing Authority](../../roadmap/decisioning/escalation-and-standing-authority.md) |
| Channel routing | [Channels and notifications](../../roadmap/interfaces/channels-and-notifications.md) |
| Incident ownership | [Incident management](incident-management.md) |
