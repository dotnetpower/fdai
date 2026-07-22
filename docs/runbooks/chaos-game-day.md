---
title: Chaos Game Day Runbook
description: A template for planning, approving, running, and recovering from a bounded chaos experiment.
---

# Chaos Game Day Runbook

Use this runbook to plan, approve, run, and recover from a bounded chaos
experiment. A game day validates one resilience hypothesis with a promoted
scenario, a frozen target set, continuous probes, and a tested rollback path.

> Run environment-specific fault injection only from the downstream fork. This
> upstream procedure defines the safety and evidence contract, not live targets
> or provider commands.

## When to use this runbook

Use a game day when a scenario has already passed schema, policy, regression,
and shadow review, and the team needs controlled evidence from a live-like
environment. Do not use a game day to diagnose an unexplained active incident.

Common goals include:

- **Failover validation**: prove a dependency or replica can take over within the objective.
- **Detection validation**: prove the expected detected issue, incident, and notification appear.
- **Rollback validation**: prove the injected fault can be removed and steady state restored.
- **Human response validation**: prove owners receive evidence and follow the expected handoff.

## Roles and required inputs

| Role or input | Responsibility |
|---------------|----------------|
| Exercise owner | Owns the hypothesis, schedule, coordination, and final record |
| Approver | Reviews scope, risk, stop conditions, and rollback independently |
| Operator | Starts and stops the approved scenario through the authorized provider |
| Observer | Watches probes and can call an immediate stop |
| Scenario | Versioned fault, target selectors, duration, and impact scope limit |
| Steady state | Measurable conditions that should remain true during the experiment |
| Rollback | Tested action that removes the fault and restores the prior state |

The operator and approver should be distinct. Every participant can call a stop
when a declared condition fires or the observed state becomes ambiguous.

## Preflight

Complete preflight before the exercise window opens:

1. Confirm the scenario version and its shadow evidence.
2. Write one falsifiable hypothesis and the expected probe movement.
3. Freeze the exact target set and verify protected dependencies are excluded.
4. Record baseline probe values and confirm telemetry freshness.
5. Verify the stop conditions, maximum duration, concurrency, and affected scope.
6. Test the rollback path or attach recent evidence from the same scenario version.
7. Confirm the operator identity, required locks, audit writer, and notification route.
8. Announce the exercise window and identify who has stop authority.

If any preflight item is unavailable, record a no-op outcome and reschedule.

## Execution procedure

1. **Open the exercise.** Record the scenario, target set, participants,
	approvals, baseline samples, and planned end time.
2. **Acquire safeguards.** Take the required resource locks and verify no
	conflicting change or active incident overlaps the targets.
3. **Start the scenario.** Inject only through the approved provider and record
	the provider operation reference and start time.
4. **Observe continuously.** Evaluate steady-state, detection, dependency, and
	scope probes throughout the experiment. Missing or stale samples are failures,
	not healthy values.
5. **Hold or stop.** Continue only while all guard conditions remain valid.
	Any authorized observer can trigger the stop branch.
6. **Remove the fault.** Run the declared rollback at the duration limit, after
	the hypothesis is observed, or immediately when a stop condition fires.
7. **Verify recovery.** Confirm the target set returns to steady state and no
	injected resource, lock, or temporary permission remains.
8. **Close the exercise.** Record the hypothesis result, unexpected impact,
	recovery time, and follow-up owners.

## Stop conditions

Stop injection immediately when any of these conditions occurs:

- **Scope expansion**: a target outside the frozen set is affected.
- **Protected impact**: a protected dependency or control-plane component degrades.
- **Stale observation**: a required probe, inventory snapshot, or audit writer is unavailable.
- **Safety limit**: duration, concurrency, error rate, latency, or affected-resource cap is reached.
- **Conflicting operation**: an incident response or deployment begins on the same target.
- **Rollback uncertainty**: the rollback path becomes unavailable or its preconditions change.

Stopping is a valid experiment outcome. Do not extend the duration or target set
inside the active run.

## Recovery and escalation

Run rollback in the documented order and continue sampling until every required
steady-state condition passes for the configured recovery window. If recovery
does not complete, transition to [incident triage](incident-triage.md), preserve
the experiment correlation ID, and treat the exercise as an incident source.

Do not start a second injection to compensate for the first. Recovery actions
must follow their own approved path and leave separate audit records.

## Evidence and audit

Record the following evidence:

- **Plan**: scenario and catalog versions, hypothesis, target hash, and exercise window.
- **Authority**: owner, approver, operator, observers, and approval reference.
- **Baseline**: pre-exercise probe values and telemetry timestamps.
- **Execution**: lock references, provider operation, injection and stop times, and stop reason.
- **Observations**: steady-state, detection, dependency, and scope samples.
- **Recovery**: rollback reference, recovery samples, recovery time, and residual impact.
- **Outcome**: supported, disproved, or inconclusive hypothesis and owned follow-up.

## Completion criteria

Close the game day only after rollback is complete, steady state is verified,
temporary access is removed, locks are released, and every follow-up has an
owner and evidence target. Submit newly discovered detection or response gaps
through the [postmortem workflow](postmortem-workflow.md).

## Related runbooks

| To continue with | Read |
|------------------|------|
| Triage unexpected service impact | [Incident triage](incident-triage.md) |
| Apply a governed recovery action | [Incident mitigation and rollback](incident-mitigation-and-rollback.md) |
| Turn exercise detected issues into owned improvements | [Postmortem workflow](postmortem-workflow.md) |
