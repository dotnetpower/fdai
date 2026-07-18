---
title: Postmortem Workflow Runbook
description: A template for reviewing a resolved incident and submitting evidence-backed follow-up.
---

# Postmortem Workflow Runbook

Use this runbook after service recovery is verified and before final incident
closure. It turns the incident timeline, decisions, actions, and recovery
evidence into an approved record with measurable follow-up.

> A postmortem explains what the evidence supports. Keep unsupported causes as
> hypotheses and preserve machine records rather than rewriting history to make
> the timeline cleaner.

## Entry criteria and roles

Start when service recovery has passed its observation window and the incident
owner can identify the authoritative audit and evidence references.

| Role | Responsibility |
|------|----------------|
| Incident owner | Owns impact, chronology, recovery status, and closure decision |
| Facilitator | Leads review and separates evidence from interpretation |
| Action owner | Accepts a follow-up with a due date and measurable completion evidence |
| Reviewer | Confirms the record is supported, complete, and safe to share |

The facilitator should not use the review to assign personal blame. The unit of
analysis is the system, decision context, and control that did or did not work.

## Required inputs

- **Incident record**: scope, severity history, members, owners, and state transitions.
- **Audit trail**: findings, verdicts, approvals, actions, no-ops, retries, and rollback.
- **Evidence set**: metrics, logs, traces, changes, notifications, and cited knowledge.
- **Impact record**: affected capability, duration, population, and SLO effect.
- **Recovery proof**: restored state, verification window, and residual risk.

Do not start from chat recollection when authoritative records exist. Recollection
can add context but should be labeled as a participant statement.

## Build the review

1. **Create the draft.** Generate an initial chronology from incident and
	append-only audit records without changing their timestamps or content.
2. **Verify impact.** Confirm the start, detection, mitigation, recovery, and end
	times, plus the affected capability and measured SLO effect.
3. **Reconstruct decisions.** For each key decision, record the evidence available
	at that time, the selected branch, and the resulting outcome.
4. **Separate causes.** Distinguish root cause, contributing conditions,
	detection gaps, response gaps, and recovery gaps.
5. **Test claims.** Link each causal statement to evidence and retain credible
	alternatives that were not disproved.
6. **Assess controls.** Record which detector, rule, approval, stop condition,
	rollback, notification, and audit controls worked or failed.
7. **Define follow-up.** Create corrective and preventive actions with owners,
	due dates, priority, and measurable completion evidence.
8. **Review and approve.** Resolve unsupported claims, confirm sensitive data is
	excluded, and obtain the required reviewer approval.
9. **Link and close.** Attach the approved postmortem to the incident and close
	only after unresolved risk and action ownership are explicit.

## Timeline checkpoints

| Checkpoint | What to capture |
|------------|-----------------|
| First impact | Earliest supported user or operation impact |
| Detection | First finding and when it reached a durable route |
| Triage | Severity, owner, scope, and first decision deadline |
| Mitigation | Proposal, verdict, approval, execution, and observed effect |
| Rollback or recovery | Trigger, action, verification, and residual impact |
| Stable service | Start and end of the recovery observation window |

## Follow-up quality

A useful follow-up changes a control or closes an evidence gap. Avoid actions
such as "be more careful" that have no owner or test.

| Required field | Example evidence target |
|----------------|-------------------------|
| Owner and due date | Named accountable role and review date |
| Control changed | Rule, runbook, test, alert, rollback, or provider reference |
| Completion proof | Passing scenario, drill record, or measured production signal |
| Safety mode | Shadow evidence before any enforcement change |
| Closure condition | Objective result that lets the action be closed |

Reusable rule, runbook, or knowledge improvements remain inert candidates until
their normal review and promotion path accepts them.

## Stop conditions

Do not close when impact, recovery, unresolved risk, owner, or required follow-up
is missing. Pause review when the evidence set changes materially, timestamps
conflict, a cited record cannot be verified, or sensitive data has entered the
draft. Keep unsupported causes labeled as hypotheses.

## Evidence and completion

The approved record should link the incident, evidence-set version, timeline,
RCA claims, response actions, approvals, rollback, recovery proof, reviewers,
and follow-up items. Record the postmortem version and approval in the incident
audit trail.

Complete the workflow when the reviewed postmortem is linked, residual risk is
accepted by the right owner, and every required follow-up has an owner, due date,
and evidence target. Follow-up completion can occur after incident closure.

## Related runbooks

| To continue with | Read |
|------------------|------|
| Recheck source evidence and causal claims | [RCA evidence collection](rca-evidence-collection.md) |
| Improve a detector with frozen scenarios | [Alert tuning](alert-tuning.md) |
| Validate a corrective resilience control | [Chaos game day](chaos-game-day.md) |
