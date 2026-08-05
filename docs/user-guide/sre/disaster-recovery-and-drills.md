---
title: Disaster Recovery and Drills
description: How FDAI proves recovery paths through scheduled, isolated, evidence-backed restore and failover exercises.
---

# Disaster Recovery and Drills

Disaster recovery (DR) is credible only when the recovery path is exercised and
measured before an outage. FDAI schedules bounded drills, restores into isolated
targets, verifies recovery objectives, and records cleanup and audit evidence.

## Plan the drill

A drill declares the protected workload, target RPO and RTO, exercise window,
isolated destination, owner, stop conditions, impact scope, cleanup plan, and
evidence requirements. Production data is not overwritten by a verification
restore.

## Drill lifecycle

1. Confirm backup readiness, restore window, identity, quota, and destination isolation.
2. Select a restore point and record the expected RPO.
3. Restore into a newly isolated resource group or equivalent scope.
4. Run connectivity, schema, integrity, and application-level verification.
5. Measure achieved RPO and RTO against the objectives.
6. Record evidence, remove temporary resources, and verify cleanup.

## Fail closed

The drill stops when source identity is ambiguous, the destination could touch
production, backup metadata is missing, verification is incomplete, or cleanup
cannot be guaranteed. A failed drill is evidence of a recovery gap, not a
reason to mark the workload healthy.

## Recovering FDAI itself

Everything above is about recovering your workloads. FDAI's own control plane is a separate recovery
problem, and the difference matters during a regional event.

If a workload restore fails, the control plane is still up to detect it, decide, and record what
happened. If the control plane is down, none of that happens: no new decisions, no audit writes, and
no measurement of whether your workload recovery worked. So the two paths have their own plans,
their own evidence, and their own drills.

Control-plane failover is fenced by a **recovery epoch**, a counter that increases every time a
failover assigns authority to a region. Think of it as a generation number. The new region holds
exclusive write authority for its epoch, and the old region is fenced out: a write that arrives
carrying an older epoch is rejected rather than applied. Combined with per-transition keys that are
safe to retry, that stops the failure mode operators fear most, where two regions both believe
they're in charge and execute the same recovery twice.

> **Current baseline:** One active region with zone redundancy, backup and availability gates,
> the recovery-plan reducer and coordinator, restore verification, and the scheduled drill job are
> in place. Alternate-region infrastructure, traffic failover, event-data continuity, and measured
> failover and failback evidence are deployment work that has to pass its gates before a
> cross-region failover is real. Plan your runbook around the single-region baseline until then.

## Promotion and cadence

New drill automation starts in shadow. A scheduler owns cadence, the safety check
owns scope and execution eligibility, and the audit log owns proof. Promotion
requires repeatable success and no policy-violation escape.

## Next steps

| To learn about | Read |
|----------------|------|
| The detailed database procedure | [Deep DB-DR restore drill](../../runbooks/db-dr-drill.md) |
| How failure injection complements DR | [Chaos engineering](chaos-engineering.md) |
| How recovery is measured | [Measuring SRE outcomes](measuring-sre-outcomes.md) |
| The Resilience capability | [Resilience](../capabilities/resilience.md) |
