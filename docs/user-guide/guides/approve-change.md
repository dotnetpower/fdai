---
title: Approve a change
description: How to review and approve or reject a change FDAI has queued for human approval.
---

# Approve a change

When a proposed change needs human approval, FDAI pauses execution and asks a
person. This guide walks through your side of that interaction: what the request
looks like, what to check before you approve, and what happens after each
decision.

## What an approval request looks like

An alert can reach you through any configured notification channel. The approval
decision itself has to come back through an A1-capable, identity-verified
surface, such as a Teams Adaptive Card, a configured Slack flow with
re-authentication, or a review on a fix pull request. Email, SMS, and paging
systems can tell you that a request is waiting, but they cannot submit the
approval.

Every request shows the same core information, no matter which surface it
arrives on:

- **Event summary**: what triggered the change, such as drift, a cost anomaly, or
  a DR drill, and which resource is affected.
- **Proposed action**: the exact change FDAI would apply, either as a pull
  request you can review or as a serialized action envelope.
- **Risk classification**: why this needs approval instead of running
  automatically. It names the dimension that raised the tier, such as impact
  scope, novelty, reversibility, or the signal source.
- **Rollback preview**: the pre-computed rollback path that would run if the
  change is approved and later has to be reverted.
- **Stop condition**: the measurable state that halts the change if the world
  reacts badly after approval.
- **Audit link**: a deep link to the audit-log entry, so you can follow the event
  chain that produced this decision.
- **Approval integrity**: the request deadline, the required quorum, the action
  hash, the idempotency key, and confirmation that the requester and the
  approver have to be different people.

## What to check before approving

Six checks, in order of importance:

1. **Does the risk classification look right?** If the proposed action feels too
   aggressive for the stated risk, the classification rule probably needs
   attention. Reject and escalate rather than approving around the rule.
2. **Impact scope.** Confirm that the scope cap, such as "this resource group
   only" or "a batch of 5 VMs", matches what you actually want to change.
3. **Rollback path.** The rollback preview should be non-empty and runnable. An
   empty or vague rollback is a defect in the action design, not something to
   approve around.
4. **Stop condition.** It should be visible in metrics you already watch. If it
   references a metric you cannot observe, reject it.
5. **Evidence check, for T2 only.** If this was a T2 decision, confirm that the
   rules or documents cited in the audit-log entry really support the proposed
   action.
6. **Is the approval still bound to this action?** Check the version, the target
   scope, the deadline, the action hash, and the quorum. If the payload changed
   after review, ask for a new approval request.

## Decisions and their consequences

- **Approve**: once the identity, role, hash, deadline, no-self-approval, and
  quorum checks pass, the parked change resumes with all its safety controls in
  place: the stop condition, the rollback path, the impact scope cap, and the
  audit entry. The audit log records who approved, when, and any comment you
  left.
- **Reject**: the change is discarded. FDAI still writes an audit entry with the
  approver, the reason, and the event ID, so the discovery loop can learn from
  the pattern.
- **Timeout**: every request carries a configurable deadline. When it expires,
  the change is discarded exactly as if you had rejected it. A timeout never
  approves anything.

Duplicate approval submissions are safe to retry and cannot replay the
execution. Conflicting responses are rejected and raised for review.

## Break-glass approvals

BreakGlass is a separate, time-limited emergency role. It can make an otherwise
ineligible caller eligible to take part in an emergency approval where policy
allows it. It does **not** turn a denial into an approval request, raise an
action to automatic execution, or remove the quorum and no-self-approval
checks.

Every BreakGlass use records the grant, the reason, the approver, the expiry,
and the affected action, and it alerts the on-call team. You still have to add
the post-incident justification. BreakGlass is not a substitute for fixing the
underlying rule or safety contract.

## Next steps

| To learn about | Read |
|----------------|------|
| How the classification in front of you was produced | [../concepts/risk-tiers.md](../concepts/risk-tiers.md) |
| How to trace what happened after your decision | [read-audit-log.md](read-audit-log.md) |
| What to do when a rule keeps producing bad approval cards | [override-a-rule.md](override-a-rule.md) |
| The channels that carry approval requests | [../../roadmap/interfaces/channels-and-notifications.md](../../roadmap/interfaces/channels-and-notifications.md) |
