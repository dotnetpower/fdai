---
title: Change Safety
description: How FDAI keeps every proposed change safe. Each one is policy-gated, risk-classified, and delivered as an auditable pull request.
derives_from:
  - source: docs/roadmap/architecture/goals-and-metrics.md
    sha: ca0edfb8b3fa597631bc78696268634f320be697
---

# Change Safety

Every change to your cloud is evaluated before it can reach production, whether
it is an infrastructure-as-code pull request, a drifted configuration, or a policy
violation. FDAI treats change safety as a deterministic gate first. It only falls
back to a judgment call when the deterministic tier cannot decide, so the
repeatable majority of changes resolve without a person and without a model.

## What you get

- **Policy gates on every change.** FDAI dry-runs each proposed change against
  policy-as-code, a what-if evaluation, before anything is applied.
- **Drift caught and fixed.** Configuration that drifts from its declared state is
  detected, classified, and either corrected automatically or raised for review.
- **High-risk changes wait for you.** The safety check sends low-risk changes to
  auto-merge and high-risk changes to human approval.
- **Audit and rollback for free.** Actions ship as fix pull requests, so the
  change record and the rollback path already live in Git.

## How FDAI keeps a change safe

<!-- fdai:steps -->

1. **Detect.** A resource change, an activity-log event, or a drift signal enters
   the control loop as one normalized event.
2. **Dry-run against policy.** The deterministic tier evaluates the change with
   what-if against policy-as-code. Nothing changes yet.
3. **Classify the risk.** The safety check places the change on the
   [risk-classification](../../roadmap/decisioning/risk-classification.md) table
   as auto, human approval, or deny.
4. **Auto-merge or ask.** Low-risk changes merge automatically. High-risk changes
   wait for [approval](../guides/approve-change.md) in your channel.
5. **Deliver and audit.** The change ships as a pull request with a rollback
   reference, and every decision is recorded, including denials and no-ops.

## Proof, not promises

Change safety is measured, never asserted. FDAI reports these numbers against a
measured baseline on a frozen scenario set (see
[goals and metrics](../../roadmap/architecture/goals-and-metrics.md)):

- **Change lead time**, the time from change request to merge, is a target to
  shorten. It is reported as a median and a p90, not only as a mean.
- **Change failure rate** is a guard metric that should not increase. If it rises,
  the action drops from enforcement mode back to observation mode automatically.
- **Policy escapes** have to be exactly zero. An autonomous change that violates
  policy and still reaches enforcement blocks the release.

A new gate always ships in [observation
mode](../concepts/shadow-then-enforce.md) first, where it judges and logs but
changes nothing. It moves to enforcement mode only after it clears its promotion
gate.

## Related

<!-- fdai:cards -->

- [Deterministic first](../concepts/deterministic-first.md) - Why the repeatable majority stays rule-driven.
- [Risk tiers](../concepts/risk-tiers.md) - How a change becomes auto, human approval, or deny.
- [Ontology-driven automation](../concepts/ontology-driven-automation.md) - The typed actions a change instantiates.
- [Approve a change](../guides/approve-change.md) - The operator view of an approval request.
- [Deploy and onboard](../../roadmap/deployment/deploy-and-onboard.md) - Bring FDAI into your environment.
