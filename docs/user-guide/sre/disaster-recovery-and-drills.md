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
