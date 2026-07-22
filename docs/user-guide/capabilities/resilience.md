---
title: Resilience
description: How FDAI proves recovery before you need it - scheduled DR drills, bounded chaos experiments, and self-healing for known failure patterns.
derives_from:
  - source: docs/roadmap/architecture/goals-and-metrics.md
    sha: eddf9552f2f88f4e1bec24b2521b7656ed87d103
---

# Resilience

FDAI keeps your workloads recoverable and proves it on a schedule, not during an
outage. It rehearses disaster recovery, exercises databases against their
recovery targets, runs impact scope-bounded chaos experiments, and self-heals the
failure patterns it has seen before - so the first time a recovery path runs is
never the real incident.

## What you get

- **Scheduled DR drills.** Disaster-recovery rehearsals run in a defined exercise
  window, not ad hoc, and record their outcome.
- **Recovery-target verification.** Database exercises restore against your target
  RPO and RTO and flag gaps (for example, a point-in-time-restore gap) before they
  matter.
- **Bounded chaos experiments.** Failure is injected within a strict impact scope
  limit, so an experiment can never exceed its declared scope.
- **Self-healing for known patterns.** Failures that match a resolved incident are
  remediated automatically; the novel minority escalates to you.

## How FDAI proves recovery

<!-- fdai:steps -->

1. **Find the gap.** A scheduled job detects a resilience gap - say, a
   point-in-time-restore gap on a critical database - and raises a detected issue.
2. **Schedule the drill.** The agent schedules a paired restore drill inside the
   defined exercise window, never against live traffic unbounded.
3. **Run within the impact scope.** The exercise executes under its scope, batch,
   and rate caps - the same safety invariants every autonomous action carries.
4. **Verify against targets.** The restore is checked against the target RPO and
   RTO; success and failure are both recorded.
5. **Audit the proof.** The outcome enters the append-only audit log as evidence
   that the recovery path works.

## Proof, not promises

Resilience is measured against a baseline, never asserted (see
[goals and metrics](../../roadmap/architecture/goals-and-metrics.md)):

- **MTTR** - mean time to resolve, reported as median and p90 alongside the mean -
  is a directional target to shorten.
- **Auto-resolution rate** - events resolved with zero human touchpoints and no
  rollback - is a directional target to raise.
- **Rollback rate** and **false-negative rate** are guard metrics: neither may
  regress past its baseline threshold.

Every drill and self-heal ships in [observation mode](../concepts/shadow-then-enforce.md)
first and is promoted only after its measured accuracy holds.

## Related

<!-- fdai:cards -->

- [Site Reliability Engineering](../sre/README.md) - The complete observe, respond, recover, and learn lifecycle.
- [Disaster recovery and drills](../sre/disaster-recovery-and-drills.md) - How recovery paths are isolated, measured, and audited.
- [Chaos engineering](../sre/chaos-engineering.md) - How bounded fault scenarios prove recovery behavior.
- [Agents and self-healing](../concepts/agents-and-self-healing.md) - How the agent organization resolves failures.
- [Risk tiers](../concepts/risk-tiers.md) - How a recovery action is routed to auto, human approval, or deny.
- [Operational Readiness](../../roadmap/operations/operational-readiness.md) - The dev-to-ops readiness gate.
- [Deploy and onboard](../../roadmap/deployment/deploy-and-onboard.md) - Bring FDAI into your environment.
