---
title: Resilience
description: >-
  How FDAI proves recovery before you need it, using scheduled DR drills,
  bounded chaos experiments, and self-healing for known failure patterns.
derives_from:
  - source: docs/roadmap/architecture/goals-and-metrics.md
    sha: a75593fff77569c7074a7c0f84504a198cfdb955
---

# Resilience

FDAI keeps your workloads recoverable and proves it on a schedule, not during
an outage. It rehearses disaster recovery, exercises databases against their
recovery targets, runs chaos experiments inside a bounded impact scope, and heals
the failure patterns it has seen before. The first time a recovery path runs is
never the real incident.

## What you get

- **Scheduled DR drills.** Disaster-recovery rehearsals run inside a defined
  exercise window rather than ad hoc, and they record their outcome.
- **Recovery-target verification.** Database exercises restore against your target
  RPO and RTO and flag gaps, such as a point-in-time-restore gap, before they
  matter.
- **Bounded chaos experiments.** Failure is injected inside a strict impact scope
  limit, so an experiment can never go beyond its declared scope.
- **Self-healing for known patterns.** A failure that matches a resolved incident
  is fixed automatically. The novel minority comes to you.

## How agents deliver resilience

Huginn normalizes signals; Heimdall detects gaps and independently verifies outcomes; Loki proposes
bounded experiments; Forseti judges; Odin arbitrates cross-objective conflicts; Var owns required
human approval; Thor executes; Vidar controls rollback and recovery; Saga records the immutable
trace. Norns may propose an inert learning candidate after closure, but cannot change policy.

## How FDAI proves recovery

<!-- fdai:steps -->

1. **Find the gap.** A scheduled job detects a resilience gap, such as a
   point-in-time-restore gap on a critical database, and raises a detected issue.
2. **Schedule the drill.** An agent schedules a paired restore drill inside the
   defined exercise window. It never runs unbounded against live traffic.
3. **Run inside the impact scope.** The exercise runs under its scope, batch, and
   rate caps, the same safety controls every autonomous action carries.
4. **Verify against targets.** FDAI checks the restore against the target RPO and
   RTO, and records both success and failure.
5. **Audit the proof.** The outcome enters the append-only audit log as evidence
   that the recovery path works.

## Proof, not promises

Resilience is measured against a baseline, never asserted (see
[goals and metrics](../../roadmap/architecture/goals-and-metrics.md)):

- **MTTR**, the mean time to resolve, is a target to shorten. FDAI reports the
  median and p90 alongside the mean.
- **Auto-resolution rate**, meaning events resolved with no human touchpoints and
  no rollback, is a target to raise.
- **Rollback rate** and **false-negative rate** are guard metrics. Neither should
  get worse than its baseline threshold.

Every drill and every self-heal ships in [observation
mode](../concepts/shadow-then-enforce.md) first, and it is promoted only after
its measured accuracy holds up.

## Related

<!-- fdai:cards -->

- [Site Reliability Engineering](../sre/README.md) - The complete observe, respond, recover, and learn lifecycle.
- [Disaster recovery and drills](../sre/disaster-recovery-and-drills.md) - How recovery paths are isolated, measured, and audited.
- [Chaos engineering](../sre/chaos-engineering.md) - How bounded fault scenarios prove recovery behavior.
- [Agents and self-healing](../concepts/agents-and-self-healing.md) - How the agent organization resolves failures.
- [Risk tiers](../concepts/risk-tiers.md) - How a recovery action becomes auto, human approval, or deny.
- [Operational readiness](../../roadmap/operations/operational-readiness.md) - The readiness gate between development and operations.
- [Deploy and onboard](../../roadmap/deployment/deploy-and-onboard.md) - Bring FDAI into your environment.
