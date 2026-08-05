---
title: Chaos Engineering
description: How FDAI runs catalog-driven fault experiments with bounded targets, stop conditions, and recovery evidence.
---

# Chaos Engineering

Chaos engineering tests whether a workload and its recovery controls behave as
expected under a known fault. FDAI represents experiments as catalog entries
with explicit targets, probes, impact scope, stop conditions, rollback, and
audit evidence.

## Scenario contract

A fault scenario declares the hypothesis, supported resource type, injector,
steady-state probe, approved targets, maximum duration, stop conditions,
rollback, and promotion gate. Catalog schema validation rejects an incomplete
scenario before it can run.

## Safe experiment flow

1. Select a promoted scenario and verify target eligibility.
2. Run preflight and steady-state probes without injecting a fault.
3. Confirm the bounded target set and required approval.
4. Inject through the configured provider, never from the console identity.
5. Continuously evaluate stop conditions and health probes.
6. Roll back, verify recovery, and record the outcome.

## Shadow before fault injection

In shadow, FDAI evaluates target selection, policy, expected probes, and the
action it would take without injecting a fault. Promotion is per scenario and
scope. A new scenario does not inherit another scenario's evidence.

## Stop and recovery rules

Stop immediately when the target set expands, a protected dependency degrades,
the probe loses freshness, the experiment exceeds its duration, rollback becomes
unavailable, or audit writing fails. Recovery verification is part of the
experiment outcome, not an optional cleanup task.

## The impact envelope and pre-authorized recovery

Stop conditions tell an experiment when to quit. An **impact envelope** tells it how far it was ever
allowed to go. The envelope is fixed at approval time and covers how many resources may be affected,
how deep through dependencies the fault may travel, how long it may run, how far objectives may
degrade, and which signals mean stop immediately.

A recovery plan has to be ready before injection starts. An experiment can't enter fault injection
while its recovery plan is still a draft or its rehearsal has gone stale. This is the part operators
most often expect to be optional and it isn't: you rehearse the way out before you create the
problem.

When a guard sees a forbidden signal or the envelope being exceeded, the sequence runs without
waiting for a fresh approval, because recovery was authorized alongside the experiment:

1. The guard publishes a stop with the reason that triggered it.
2. Vidar claims the pre-authorized recovery plan.
3. Thor executes each recovery step through the normal executor path, with audit per step.
4. Heimdall verifies independently that the fault is gone, targets are back in range, and objectives
   recovered within the target time.

The verifier is deliberately not the agent that injected the fault or the one that decided to stop.
The outcome is recorded as recovered, partially recovered, not recovered, or unscorable when the
telemetry needed to judge it wasn't available.

As an approver, the envelope is the thing to read carefully. An explicit target list, a duration you
could tolerate, forbidden signals that match what you actually care about, and a rehearsed recovery
plan are what separate an experiment from an outage you scheduled.

> **Current status:** Impact analysis, recovery plans, continuous guards, durable run state,
> pre-authorized recovery, and independent verification are implemented. The default runtime stays
> in observation mode, and enforcement requires an injected governed chaos executor. If enforcement
> is enabled without that binding, startup blocks rather than running unguarded.

## Coverage and evidence

Track scenario coverage by failure mode and resource type, probe reliability,
abort rate, rollback success, recovery time, and unexpected impact. A successful
injection without verified recovery is not a successful experiment.

The [scenario validation inventory](scenario-validation-inventory.md) separates
all 132 catalog entries from the 18-scenario shadow-coverage pack, the 10 live
enforce validations, and the independent frozen control-loop scenarios.

## Next steps

| To learn about | Read |
|----------------|------|
| How recovery is rehearsed | [Disaster recovery and drills](disaster-recovery-and-drills.md) |
| Every scenario and its evidence level | [Scenario validation inventory](scenario-validation-inventory.md) |
| How impact scope is governed | [Risk tiers](../concepts/risk-tiers.md) |
| The operator procedure | [Chaos game day runbook](../../runbooks/chaos-game-day.md) |
| The Resilience capability | [Resilience](../capabilities/resilience.md) |
