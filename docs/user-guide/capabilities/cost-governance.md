---
title: Cost Governance
description: How FDAI detects spend anomalies, recommends right-sizing, and auto-executes the low-risk cleanup - while risky cost changes wait for approval.
derives_from:
  - source: docs/roadmap/architecture/goals-and-metrics.md
    sha: eddf9552f2f88f4e1bec24b2521b7656ed87d103
  - source: docs/roadmap/interfaces/cost-model.md
    sha: fedc2158a8cc055dfbd21076986a0991660cccf0
---

# Cost Governance

FDAI watches your cloud spend the way it watches everything else: deterministic
detection first, autonomous action only for the low-risk majority, and human
approval for anything that could hurt. It finds waste, proposes right-sizing, and
cleans up the safe subset on its own - while the changes that carry real blast
radius wait for you.

## What you get

- **Spend anomaly detection.** Cost signals that deviate from the expected
  baseline raise a finding. Detection runs in shadow and never auto-acts on its
  own.
- **Right-sizing recommendations.** Over-provisioned resources are flagged with a
  concrete, reversible remediation.
- **Safe cleanup, automatically.** The low-risk subset - idle disk cleanup,
  unused public IP release, orphan NIC removal - auto-executes with a rollback
  path.
- **Risky cost changes pause for you.** Anything above the safe threshold routes
  to human-in-the-loop (HIL) approval, never auto-applied.

## How a cost action reaches enforce

<!-- fdai:steps -->

1. **Detect the anomaly.** A cost-anomaly detector fires on, say, an
   over-provisioned cache tier and raises a normalized finding.
2. **Match a rule.** The deterministic tier (T0) matches the finding to a
   right-sizing or cleanup rule.
3. **Prove it in shadow.** The rule runs in
   [shadow mode](../concepts/shadow-then-enforce.md), judging and logging without
   mutating, until it clears its promotion gate.
4. **Promote to enforce.** Only after the measured accuracy holds does the action
   become autonomous.
5. **Ship with a rollback.** The right-size or cleanup lands as a remediation pull
   request that carries its own rollback reference and audit entry.

## Proof, not promises

Cost governance is measured against a baseline, never asserted (see
[goals and metrics](../../roadmap/architecture/goals-and-metrics.md) and the
illustrative [cost model](../../roadmap/interfaces/cost-model.md)):

- **Cost per unit** - reported as `$/optimization` for cost actions - is a
  directional target to lower, stated only once baseline and treatment are
  measured on the same scenario set.
- **Rollback rate** is a guard metric: it MUST NOT increase over baseline.
- FDAI never claims a cost multiplier without a paired measurement.

## Related

<!-- fdai:cards -->

- [Deterministic first](../concepts/deterministic-first.md) - Why detection stays rule-driven and reviewable.
- [Risk tiers](../concepts/risk-tiers.md) - How a cost change is routed to auto, HIL, or deny.
- [Shadow, then enforce](../concepts/shadow-then-enforce.md) - How a cost action earns autonomy.
- [Cost model](../../roadmap/interfaces/cost-model.md) - The illustrative Azure cost envelope.
- [Deploy and onboard](../../roadmap/deployment/deploy-and-onboard.md) - Bring FDAI into your environment.
