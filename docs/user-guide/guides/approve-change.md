---
title: Approve a change
description: How to review and approve or reject a change FDAI has queued for human approval.
---

# Approve a change

When a proposed change lands in the human approval tier, FDAI pauses execution and
asks a human. This guide walks through the operator's side of that
interaction - what the request looks like, what to check before approving,
and what happens after each decision.

## What a human approval request looks like

You may receive an alert through any configured notification channel. The
approval decision itself must return through an A1-capable, identity-verified
surface such as a Teams Adaptive Card, configured Slack flow with
re-authentication, or fix PR review. Email, SMS, and paging systems can
tell you that a request is waiting, but they cannot submit the approval.

Every human approval request presents the same core information regardless of surface:

- **Event summary** - what triggered the change (drift, cost anomaly, DR
  drill, etc.) and which resource is affected.
- **Proposed action** - the exact change FDAI would apply, either as a
  ready-to-review PR or as a serialised action envelope.
- **Risk classification** - why this landed in human approval rather than AUTO: the
  specific dimension (impact scope, novelty, reversibility, signal source)
  that raised the tier.
- **Rollback preview** - the pre-computed rollback path that would run if
  the change is approved and later needs to be reverted.
- **Stop-condition** - the measurable state that will halt the change if the
  world reacts badly after approval.
- **Audit link** - a deep link to the audit-log entry so you can see the
  event chain that produced this decision.
- **Approval integrity** - the request TTL, required quorum, action hash,
  idempotency key, and confirmation that requester and approver must differ.

## What to check before approving

Six checks in order of importance:

1. **Does the risk classification look right?** If the proposed action feels
   too aggressive for the stated risk, the classification rule may need
  attention. Reject and escalate rather than approving around the rule.
2. **Impact scope** - confirm the scope cap ("this resource group only",
   "batch of 5 VMs", etc.) matches what you actually want to change.
3. **Rollback path** - the rollback preview should be non-empty and
  executable. An empty or vague rollback is a design defect in the action,
   not something to approve around.
4. **Stop-condition** - should be observable in the metrics you already
  watch. If it references a metric you cannot observe, reject.
5. **Evidence check (T2 only)** - if this was a T2 decision, verify the cited
   rules or documents in the audit-log entry actually support the proposed
   action.
6. **Is the approval still bound to this action?** Confirm the version, target
  scope, TTL, action hash, and quorum. If the payload changed after review,
  require a new approval request.

## Decisions and their consequences

- **Approve** - once identity, role, hash, TTL, no-self-approval, and quorum
  checks pass, the parked change resumes with all its safety invariants
  (stop-condition, rollback path, impact scope cap, audit entry). The audit
  log records who approved, when, and any comment you left.
- **Reject** - the change is discarded. An audit entry is still written
  (approver, reason, event id) so the discovery loop can learn from the
  pattern.
- **Timeout** - human approval requests carry a configurable timeout. On expiry the
  change is discarded exactly as if it were rejected; there is no
  auto-approve on timeout, ever.

Duplicate approval submissions are idempotent and cannot replay execution.
Conflicting responses are rejected and surfaced for review.

## Break-glass approvals

BreakGlass is a separate, time-limited emergency role. It can make an otherwise
ineligible caller eligible to participate in an emergency human approval where
policy permits. It does **not** convert DENY to human approval, raise an action to AUTO, or
remove quorum and no-self-approval checks.

Every BreakGlass use records the grant, reason, approver, expiry, and affected
action, and alerts the on-call team. The operator must add the post-incident
justification. BreakGlass is not an alternative to fixing the underlying rule
or safety contract.

## Next steps

| To learn about | Read |
|----------------|------|
| How the classification in front of you was produced | [../concepts/risk-tiers.md](../concepts/risk-tiers.md) |
| How to trace what happened after your decision | [read-audit-log.md](read-audit-log.md) |
| What to do if a rule keeps producing bad human approval cards | [override-a-rule.md](override-a-rule.md) |
| The channels that carry human approval requests | [../../roadmap/interfaces/channels-and-notifications.md](../../roadmap/interfaces/channels-and-notifications.md) |
