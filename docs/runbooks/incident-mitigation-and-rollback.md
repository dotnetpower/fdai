---
title: Incident Mitigation and Rollback Runbook
description: A template for applying a governed mitigation and verifying rollback or recovery.
---

# Incident Mitigation and Rollback Runbook

Use this runbook after an investigation produces an evidence-backed mitigation
proposal. It moves the proposal through deterministic checks, risk and approval
policy, authorized execution, effect verification, and rollback when needed.

> This template never grants execution authority. Environment-specific actions,
> identities, resource scopes, and rollback implementations belong in the
> downstream fork and must conform to the registered `ActionType`.

## Entry criteria

Start only when all of these inputs exist:

- **Incident**: current state, severity, affected scope, owner, and correlation ID.
- **Proposal**: intended effect, evidence citations, and the condition it mitigates.
- **Action contract**: registered `ActionType`, mode, preconditions, stop conditions,
  blast radius (the scope a change can affect), and rollback contract.
- **Authority**: expected judge, executor, approver, and auditor principals.
- **Verification plan**: health, SLO, dependency, and configuration checks that prove effect.

If evidence is still ambiguous, continue [RCA evidence
collection](rca-evidence-collection.md) instead of executing.

## Roles

| Role | Responsibility |
|------|----------------|
| Incident owner | Confirms the response objective and accepts the final incident state |
| Judge | Issues the typed verdict after required verification |
| Approver | Reviews human-in-the-loop actions and remains distinct from the executor |
| Executor | Applies the authorized action through its declared delivery path |
| Auditor | Records every decision, attempt, no-op, rollback, and terminal outcome |

## Preflight

1. Refresh the incident state and confirm the proposal still addresses the measured impact.
2. Revalidate evidence timestamps, target inventory, dependencies, and expected current state.
3. Run policy, what-if, security, and blast-radius checks.
4. Confirm the action is in the expected shadow or enforce mode.
5. Acquire the per-resource lock and verify the idempotency key has not completed before.
6. Confirm stop conditions, rollback preconditions, rollback owner, and recovery checks.
7. Verify the audit writer and delivery path are available.

Record a no-op and stop when preflight cannot establish a safe execution state.

## Mitigation procedure

1. **Submit the typed proposal.** Include the incident, action, target scope,
	evidence references, mode, idempotency key, and rollback reference.
2. **Obtain a verdict.** Continue only when the registered judge accepts the
	verified proposal. A deny or hold produces a terminal no-op audit record.
3. **Obtain approval when required.** Confirm the approver is authorized and is
	not the executor or requester where separation is required.
4. **Execute once.** The authorized executor uses only the declared delivery
	path. A retry reuses the same idempotency key.
5. **Watch stop conditions.** Monitor health, SLO, dependency, scope, and
	delivery state throughout the action.
6. **Verify the effect.** Compare post-action checks with the recorded baseline
	for the declared observation window.
7. **Choose the terminal branch.** Mark the mitigation successful, roll back,
	or escalate with the remaining impact and evidence.

## Decision branches

| Observed result | Required branch |
|-----------------|-----------------|
| Expected effect and all guard checks pass | Keep the action and update the incident state |
| No material effect but no new harm | Stop, record the no-effect result, and return to investigation |
| A stop condition or unexpected dependency impact appears | Begin rollback immediately |
| Delivery state is unknown | Hold the incident open and verify delivery before retrying |
| Rollback cannot run or does not restore state | Escalate as a recovery failure |

## Rollback procedure

1. Stop additional attempts and preserve the failed action reference.
2. Confirm the rollback still targets the exact applied version and scope.
3. Obtain any required rollback verdict and approval through the typed pipeline.
4. Execute the registered rollback contract with a distinct idempotency key.
5. Verify the prior configuration, health, dependencies, and SLO state.
6. Record whether rollback fully restored, partially restored, or failed to restore service.

Rollback does not erase the original action. Both records remain linked in the
append-only audit trail.

## Stop conditions

Stop before or during mitigation on stale evidence, lock failure, scope
expansion, policy denial, missing audit writer, unavailable rollback, or
unexpected dependency impact. Also stop when the incident state changes enough
that the proposal no longer matches the current condition.

## Verification

Verification should prove both action effect and system safety:

- **Effect**: the targeted error, saturation, drift, or unavailable dependency improves.
- **Scope**: only the approved resources and dependencies changed.
- **Service**: health, SLO, and user-impact indicators pass for the observation window.
- **State**: the expected configuration or delivery reference is active.
- **Audit**: proposal, verdict, approval, execution, verification, and rollback are linked.

## Evidence and completion

Record dry-run output, verdict, approval, executor, delivery reference, health
checks, rollback reference, and final incident state. Include timestamps and
the baseline used for comparison.

Complete the runbook only when the action has a terminal state, locks are
released, the remaining user impact is recorded, and the incident has either
moved to monitoring or returned to investigation with an owner and deadline.

## Related runbooks

| To continue with | Read |
|------------------|------|
| Re-establish incident scope and severity | [Incident triage](incident-triage.md) |
| Gather evidence for the next proposal | [RCA evidence collection](rca-evidence-collection.md) |
| Review the response after recovery | [Postmortem workflow](postmortem-workflow.md) |
