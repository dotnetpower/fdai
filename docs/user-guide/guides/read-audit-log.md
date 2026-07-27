---
title: Read the audit log
description: What the append-only audit log records for every autonomous decision, and how to trace an incident back through it.
---

# Read the audit log

The audit log is FDAI's single source of truth for what happened. It is
append-only, immutable, and covers every autonomous decision the control plane
makes, including the ones that ended in a rejection, a timeout, or a no-op. This
guide covers what each entry contains and how to walk backwards from a symptom to
the root event.

## What an entry contains

Every entry records the full lifecycle of one decision. At minimum:

- **Event ID**: the stable identifier of the source event, safe to use as an
  idempotency key. Several decisions from the same event share this ID.
- **Tier**: T0, T1, or T2, so you can see at a glance whether the decision was
  deterministic or reached the reasoning tier.
- **Rule, policy, and model references**: the rule IDs for T0 and T1, and for T2
  the model identifier plus the evidence documents it cited.
- **Decision**: auto, human approval, or deny, plus the classification that
  produced it.
- **Decision evidence**: the matched risk rule, the catalog version, a feature
  snapshot, the required quorum, and the `resolved_ceiling` axis that limited
  autonomy.
- **Actor identities**: the initiator, the judge, the approver when there was
  one, the executor when something changed, and the auditor, each in its own
  field.
- **Timestamp**: RFC 3339, in UTC.
- **Observation or enforcement mode**: every entry marks which mode the
  capability was in. An observation entry carries the action that would have
  run.
- **Rollback reference**: the rollback plan or recovery evidence tied to an
  executed action. A no-op, deny, rejection, timeout, or observation-only record
  has no executed state to restore. That is different from an executable
  `ActionType` that is missing its required `rollback_contract`.

## Tracing an incident

Start with the symptom, such as a metric spike, an alert, or a resource that
changed unexpectedly, and work backwards:

1. Find the resource in the audit log. FDAI actions always write a record.
   External changes show up once an integrated activity or change feed observed
   and normalized them.
2. Read the latest relevant entry for that resource. It gives you the event ID
   and the decision chain that produced the change.
3. Follow the correlation ID across audit, logs, metrics, and traces. Inside the
   audit stream, use the event ID to order the tier, risk, approval, execution,
   delivery, rollback, and final records.
4. Inspect `resolved_ceiling` and the matched risk rule. Those fields explain
   which input forced auto, human approval, observation mode, or deny, using the
   configuration that existed when the decision was made.
5. Cross-reference the observation entries. Even actions that never ran appear
   with the decision they would have made, so you can compare what FDAI proposed
   with what a person actually did.

## Reading terminal outcomes

| Outcome | Mutation occurred? | What to verify |
|---------|--------------------|----------------|
| `auto` completed | Yes | Executor identity, delivery reference, stop-condition state, rollback reference |
| Approved and completed | Yes | Approval ID, approver, quorum, action hash, executor and delivery records |
| Rejected or timed out | No | Reason, deadline, approver when there was one, final no-op |
| `deny` | No | Matched hard rule, feature snapshot, catalog version |
| `abstain` or `shadow_only` | No | Missing evidence or the ceiling that won, and the action that would have run |
| Rolled back | Yes, then restored or compensated | Original action, rollback actor, recovery result, remaining impact |

## Replay and post-incident review

The audit log is built for **judge-only replay**. You can replay any event
through the control plane and see the decisions it would produce again, without
running the underlying action a second time. That is how you compare a proposed
rule change against last month's history before you promote it.

## What is not in the audit log

The audit log records decisions and actor references. It never records secrets,
tokens, customer identifiers, or the contents of user data. For diagnostic data,
use the observability stack of logs, metrics, and traces. Each audit entry
carries the correlation ID that ties back to those observations.

If an expected terminal record or correlation link is missing, treat that as
an audit-completeness failure. Do not infer success from the absence of an
error entry.

## Next steps

| To learn about | Read |
|----------------|------|
| The operator interaction that writes approval entries | [approve-change.md](approve-change.md) |
| Why some entries carry `would-have-been` decisions | [../concepts/shadow-then-enforce.md](../concepts/shadow-then-enforce.md) |
| How to narrow a rule that keeps auditing badly | [override-a-rule.md](override-a-rule.md) |
| The audit-log storage and retention design | [../../roadmap/rules-and-detection/observability-and-detection.md](../../roadmap/rules-and-detection/observability-and-detection.md) |
