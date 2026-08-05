---
title: Agent Workflow Shadow Rollout
---
# Agent Workflow Shadow Rollout

This document owns the rollout order and shared exit gate for cross-agent workflows. Each workflow
remains independently reviewable and starts in shadow mode before any enforcement promotion.

## Workflow order

Each of the 13 workflows in [agent-workflows.md](agent-workflows.md) lands as its own PR with its
own shadow-mode gate. The rough sequence is:

1. Cost-aware remediation (Njord + Forseti + Thor)
2. Predictive scale (Freyr + Heimdall + Njord)
3. DR drill orchestration (Loki + Vidar + Heimdall + Norns)
4. Override -> Discovery (Var + Saga + Norns + Mimir)
5. Security escalation (formalized after Wave 6 into a workflow object)
6. Handoff -> Capability (Saga + Norns + Mimir)
7. Agent health degradation (Heimdall + Odin + Bragi)
8. Judgment coherence audit (Forseti + Norns + Mimir)
9. Rollback rehearsal (Loki + Vidar + Heimdall + Saga)
10. Retrospective what-if (Saga + Forseti + Norns + Mimir)
11. Operational readiness handoff (Forseti)
12. Scheduled governed Python task (Forseti + Thor)
13. Detection readiness assurance (Huginn + Heimdall + Muninn + Forseti + Saga + Bragi)

## Per-workflow exit gate

- End-to-end trace in shadow with all participating agents.
- KPI baseline captured before promotion-gate evaluation.
- Zero policy-violation escapes in shadow.

## Dependencies and anti-scope

Wave 6 must be complete. No workflow is promoted to enforce during this rollout wave. Promotion
happens after Wave 8, independently per workflow and gated on its measured KPI thresholds.

## Related docs

| To learn about | Read |
|----------------|------|
| Workflow definitions and agent participation | [Agent workflows](agent-workflows.md) |
| Implementation waves and shared invariants | [Agent Pantheon implementation](agent-pantheon-implementation.md) |
| Promotion metrics and guard thresholds | [Goals and metrics](../architecture/goals-and-metrics.md) |
