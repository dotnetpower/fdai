---
title: Read the audit log
description: What the append-only audit log records for every autonomous decision, and how to trace an incident back through it.
---

# Read the audit log

The audit log is FDAI's single source of truth for what happened. It
is append-only, immutable, and covers every autonomous decision the control
plane makes - including the ones that ended in a rejection, a timeout, or a
no-op. This guide covers what each entry contains and how to walk backwards
from a symptom to the root event.

## What an entry contains

Every entry records the full lifecycle of one decision. At minimum:

- **Event id** - the stable, idempotency-safe identifier of the source
  event. Multiple decisions from the same event share this id.
- **Tier** - T0 / T1 / T2, so you can tell at a glance whether the decision
  ran deterministically or reached the reasoning tier.
- **Rule / policy / model refs** - for T0 and T1 the rule ids, for T2 the
  model identifier and the cited evidence check documents.
- **Decision** - AUTO / human approval / DENY, plus the classification that produced it.
- **Decision evidence** - matched risk rule, catalog version, feature snapshot,
  required quorum, and the `resolved_ceiling` axis that limited autonomy.
- **Actor identities** - the initiator, judge, approver when present, executor
  when a mutation ran, and auditor remain distinct fields.
- **Timestamp** - RFC 3339, UTC.
- **Shadow vs enforcement mode** - every entry marks whether the capability was
  in shadow at the time. Shadow entries carry the *would-have-been*
  action.
- **Rollback reference** - the rollback plan or recovery evidence associated
  with an executed action. A no-op, deny, reject, timeout, or shadow-only
  terminal record has no executed state to restore; that is different from an
  executable `ActionType` omitting its required `rollback_contract`.

## Tracing an incident

Start with the symptom (a metric spike, an alert, a resource that changed
unexpectedly) and walk backwards:

1. Find the resource in the audit log. FDAI actions always write a record;
  external changes appear when an integrated activity or change feed observed
  and normalized them.
2. Read the latest relevant entry for that resource. It gives you the event id and
   the decision chain that produced the mutation.
3. Follow the correlation ID across audit, logs, metrics, and traces. Use the
  event ID inside the audit stream to order tier, risk, approval, execution,
  delivery, rollback, and terminal records.
4. Inspect `resolved_ceiling` and the matched risk rule. These fields explain
  which input forced auto, human approval, shadow, or deny using the configuration that
  existed at decision time.
5. Cross-reference the shadow entries. Even actions that were never
   executed show up in observation mode with their would-have-been decision, so
   you can see what FDAI proposed vs what a human actually did.

## Reading terminal outcomes

| Outcome | Mutation occurred? | What to verify |
|---------|--------------------|----------------|
| `auto` completed | Yes | Executor identity, delivery reference, stop-condition state, rollback reference |
| human approval approved and completed | Yes | Approval ID, approver, quorum, action hash, executor and delivery records |
| Rejected or timed out | No | Reason, TTL, approver when present, terminal no-op |
| `deny` | No | Matched hard rule, feature snapshot, catalog version |
| `abstain` or `shadow_only` | No | Missing evidence or winning ceiling, would-have-been action |
| Rolled back | Yes, then restored or compensated | Original action, rollback actor, recovery result, remaining impact |

## Replay and post-incident review

The audit log is designed for **judge-only replay**: you can replay any
event through the control plane and see the decisions it would produce
again, without re-executing the underlying action. This is how you compare a
proposed rule change against last month's history before promoting it.

## What is *not* in the audit log

The audit log records decisions and actor references - it never records
secrets, tokens, customer identifiers, or the payload of user data. If you
need diagnostic data, the observability stack (logs, metrics, traces) is
the correct place; each audit entry carries the correlation id that ties
back to those observations.

If an expected terminal record or correlation link is missing, treat that as
an audit-completeness failure. Do not infer success from the absence of an
error entry.

## Next steps

| To learn about | Read |
|----------------|------|
| The operator interaction that writes human approval entries | [approve-change.md](approve-change.md) |
| Why some entries carry `would-have-been` decisions | [../concepts/shadow-then-enforce.md](../concepts/shadow-then-enforce.md) |
| How to narrow a rule that keeps auditing badly | [override-a-rule.md](override-a-rule.md) |
| The audit-log storage and retention design | [../../roadmap/rules-and-detection/observability-and-detection.md](../../roadmap/rules-and-detection/observability-and-detection.md) |
