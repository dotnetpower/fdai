---
title: Cost Governance
description: How FDAI detects spend anomalies, recommends right-sizing, and runs the low-risk cleanup on its own, while risky cost changes wait for approval.
derives_from:
  - source: docs/roadmap/architecture/goals-and-metrics.md
    sha: 5374da7c73ebdecae18f16115c0b0b3822104fa7
  - source: docs/roadmap/interfaces/cost-model.md
    sha: 6c77bb278a9517139d7be7c17b6c779fa5773645
---

# Cost Governance

FDAI watches your cloud spend the way it watches everything else. Detection is
deterministic first, autonomous action covers only the low-risk majority, and
anything that could hurt waits for human approval. FDAI finds waste, proposes
right-sizing, and cleans up the safe subset on its own. Changes with a real impact
scope wait for you.

## What you get

- **Spend anomaly detection.** A cost signal that drifts from the expected
  baseline raises a detected issue. Detection runs in observation mode and never
  acts on its own.
- **Right-sizing recommendations.** FDAI flags an over-provisioned resource with a
  concrete, reversible fix.
- **Safe cleanup, automatically.** The low-risk subset, such as idle disk cleanup,
  unused public IP release, and orphan NIC removal, runs on its own with a
  rollback path.
- **Risky cost changes wait for you.** Anything above the safe threshold goes to
  human approval and is never applied automatically.

## How a cost action reaches enforcement

<!-- fdai:steps -->

1. **Detect the anomaly.** A cost-anomaly detector fires on, say, an
   over-provisioned cache tier and raises a normalized detected issue.
2. **Match a rule.** The deterministic tier (T0) matches the detected issue to a
   right-sizing or cleanup rule.
3. **Prove it in observation mode.** The rule runs in
   [observation mode](../concepts/shadow-then-enforce.md), judging and logging
   without changing anything, until it clears its promotion gate.
4. **Promote to enforcement.** The action becomes autonomous only after the
   measured accuracy holds up.
5. **Ship with a rollback.** The right-size or cleanup lands as a fix pull
   request that carries its own rollback reference and audit entry.

## Proof, not promises

Cost governance is measured against a baseline, never asserted (see
[goals and metrics](../../roadmap/architecture/goals-and-metrics.md) and the
illustrative [cost model](../../roadmap/interfaces/cost-model.md)):

- **Cost per unit**, reported as `$/optimization` for cost actions, is a target
  to lower. FDAI states it only once the baseline and the treatment have been
  measured on the same scenario set.
- **Rollback rate** is a guard metric and should not rise above the baseline.
- FDAI never claims a cost multiplier without a paired measurement.

## Related

<!-- fdai:cards -->

- [Deterministic first](../concepts/deterministic-first.md) - Why detection stays rule-driven and reviewable.
- [Risk tiers](../concepts/risk-tiers.md) - How a cost change becomes auto, human approval, or deny.
- [Observe, then enable changes](../concepts/shadow-then-enforce.md) - How a cost action earns autonomy.
- [Cost model](../../roadmap/interfaces/cost-model.md) - The illustrative Azure cost envelope.
- [Deploy and onboard](../../roadmap/deployment/deploy-and-onboard.md) - Bring FDAI into your environment.
