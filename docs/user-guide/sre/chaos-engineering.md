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
