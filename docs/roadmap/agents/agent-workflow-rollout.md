---
title: Agent Workflow Shadow Rollout
---
# Agent Workflow Shadow Rollout

This document owns the rollout order and shared exit gate for cross-agent workflows. Each workflow
remains independently reviewable and starts in shadow mode before any enforcement promotion.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Thirteen-workflow rollout inventory | implemented | `docs/roadmap/agents/agent-workflows.md`; `services/core-control-plane/src/fdai/agents/_framework/workflows.py`; `services/core-control-plane/tests/agents/test_wave7_workflows.py` | The registry and tests preserve the documented workflow count and shadow defaults. |
| Focused shadow-path evidence | implemented | `services/core-control-plane/tests/agents/test_wave7_workflows.py`; registered `trace_ref` targets | Focused tests establish implementation behavior only; they are not retained runtime rollout traces. |
| Shared operational exit gate | not-started | Exit criteria in this document | No retained evidence establishes KPI baselines, required shadow durations, or zero policy-violation escapes for all workflows. |
| Independent enforce promotion | not-started | Promotion gates in `docs/roadmap/agents/agent-workflows.md` | All registry entries remain in `shadow`; retrospective what-if remains permanently shadow. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-13 | implemented | Adopted the implementation ledger and separated focused shadow-path implementation from operational rollout validation. Earlier implementation provenance was not reconstructed. | current change; focused workflow tests | Capture runtime exit-gate evidence and record independent promotion outcomes. |
| 2026-08-14 | implemented | Extracted Forseti's pure decision mapping, conflict, impact, and freshness helpers into the private framework without changing its judge role, topics, workflow modes, or promotion state. | `current change`; focused layout and Forseti judge checks passed 104 cases, and strict mypy and agent import gates passed. | Runtime exit-gate evidence and independent promotion outcomes remain unchanged. |

### Remaining work

- [ ] Capture durable per-workflow shadow traces, KPI baselines, and policy-escape observations from an operating environment.
- [ ] Evaluate promotion only after the applicable duration and threshold evidence exists.
- [ ] Record promotion or continued-shadow outcomes separately for every eligible workflow.

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
