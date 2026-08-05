---
title: Response Plans and Mitigation
description: How FDAI authors, pretests, approves, and routes an incident response plan without bypassing the action pipeline.
---

# Response Plans and Mitigation

An incident response plan (IRP) is a pre-authored, gated response to a class of
alert. It declares the trigger, ordered response steps, activation
requirements, approver role, and notification channels. A plan can propose and
route a mitigation, but it never executes one directly.

## Authoring gate

Every plan starts as a draft. Activation checks that stop conditions, rollback,
impact-scope bounds (impact scope), an approver, and a notification channel are
all declared and satisfied. Omitting a requirement does not bypass the gate; it
leaves the plan inactive.

Pretesting evaluates the plan deterministically against resolved historical
incidents. Only incidents containing the plan's trigger signal enter the
denominator. A case is covered when its recorded resolving action appears in
the plan's response steps. The report records matched count, total count, and
unmatched incident references. Coverage is evidence for review, not automatic
activation.

Plan activation and action promotion are separate decisions. Activating a plan
means its trigger and response structure are ready to use. It does not promote
any referenced `ActionType`, lower its risk tier, or grant execution authority.

| Plan concern | Owning decision | Safe failure |
|--------------|-----------------|--------------|
| Stop, rollback, impact scope, approver, channel | Plan readiness gate | Keep the plan inactive |
| Historical coverage | Pretest review | Record gaps; don't activate automatically |
| Action safety and promotion | Action registry and safety check | Shadow, human approval, or deny |
| Runtime mutation | Executor checks | No-op, stop, or rollback |

## Alert response flow

1. An alert starts a time-bounded investigation.
2. The investigation returns detected issues and prioritized recommendations.
3. The coordinator selects the highest grounded actionable recommendation.
4. A mitigation proposal is sent to the configured approval gate.
5. An approved proposal re-enters the typed trust and risk pipeline.
6. Teams or Slack receives the governed outcome.

The default approval gate denies. A missing or broken approval binding therefore
produces no action.

## Compare options before you mitigate

When more than one mitigation is defensible, FDAI can assemble the comparison for you instead of
leaving it to whoever is on call at 3am. Specialists contribute what they own: Heimdall supplies
observation and forecast evidence, Freyr capacity and sizing, Njord bounded cost, Loki resilience
scenarios when they're asked for, and Mimir validates that the rules and action types involved are
real and current.

The result is a comparison rather than a recommendation you have to take on faith. It includes doing
nothing as an explicit baseline, the candidate options, the hard constraints that excluded the ones
that aren't there, simulated effects with their receipts, and the reason each rejected option was
rejected. Comparing a candidate against no-action is usually the most useful thing on the page.

Planning holds instead of picking when no option is eligible, when nothing safe survives the
constraints, or when the context it needs is stale, incomplete, conflicting, or truncated. A hold
here is a real answer: it tells you the deterministic path couldn't justify any of the choices.

> **Planning is read-only.** It produces evidence and proposals. It can't approve, execute, promote,
> or claim an external effect, and a selected option still travels the same path as any other
> proposal. Planning also binds only when your deployment supplies the ontology release, operational
> context, process store, effect-model reader, and causal verifier it depends on, so treat it as an
> optional capability rather than one that's always present.

## Preserve separation of duties

The plan coordinator selects a supported recommendation, but does not judge,
approve, and execute it. Forseti produces the decision, Var carries the approval
record, Thor is the privileged executor, Vidar owns rollback, and Saga appends
the audit evidence. The requester, approver, and executor remain distinct where
policy requires it. A chat message or successful notification delivery is not
an authenticated approval decision.

## Mitigation is not execution

A response step names an `ActionType`; it does not call an executor. The normal
pipeline still validates preconditions, stop conditions, impact scope,
rollback, mode, lock, identity, and policy. Rejection and timeout terminate as
audited no-ops.

## Failure behavior

| Failure point | Terminal behavior | Evidence retained |
|---------------|-------------------|-------------------|
| No grounded actionable detected issue | No proposal | Investigation result and gaps |
| Investigation timeout or exception | No action | Partial report and unavailable evidence |
| Approval rejection | Audited no-op | Rejecting principal and reason |
| Approval timeout | Audited no-op or escalation | Expiry and ladder state |
| Routing or notification failure | Durable retry or escalation | Delivery attempt, never approval |
| Stop condition during execution | Stop and follow compensation policy | Step outcomes and rollback reference |

When a valid standing authorization applies after an unanswered escalation
deadline, the plan still does not execute directly. The supervisor submits the
pending typed action for a fresh safety check decision. An expired authorization,
stale inventory, wider impact scope, or envelope mismatch ends as a no-op.

## Next steps

| To learn about | Read |
|----------------|------|
| How evidence is gathered | [Triage and investigation](triage-and-investigation.md) |
| How approval routes are selected | [On-call and escalation](on-call-and-escalation.md) |
| How typed actions remain safe | [Agent-driven automation](../concepts/ontology-driven-automation.md) |
| Operator procedures | [SRE runbooks](../../runbooks/README.md) |
