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
| 2026-08-24 | implemented | Moved forecast-outcome and provider-schema publication into focused private Heimdall mixins solely to restore the enforced agent file ceiling. AgentSpec, topics, ownership, model policy, and authority are unchanged. | `current change`; Heimdall is 789 lines; focused provider-schema, forecast-outcome, framework-layout, agent-import, LOC, Ruff, format, and strict mypy checks. | Runtime exit-gate and deployed provider-schema evidence remain unchanged. |
| 2026-08-24 | implemented | Replaced Heimdall's direct delivery import for provider-schema review with an injected shared provider Protocol. A missing projector holds publication; AgentSpec, topics, ownership, model policy, and authority are unchanged. | `current change`; provider-schema agent and watcher checks, agent import gate, Ruff, and strict mypy. | Retain the existing deployed shadow and Saga-audit evidence required by the provider-schema owner. |
| 2026-08-19 | implemented | Bounded repeated Pantheon handler-observer warnings without changing handler delivery, AgentSpec, topics, ownership, model policy, or authority. The first failure remains immediate, periodic summaries preserve suppressed counts, distinct failure episodes remain separate, and the next successful observation records the bridge-owned failure count. | `current change`; `bus_bridge.py`, telemetry logging, and focused provider-integration and framework-layout checks. | Runtime exit-gate evidence and independent promotion outcomes remain unchanged. |
| 2026-08-18 | implemented | Stopped the event bus bridge from notifying the Pantheon activity observer for principals outside the registry. The observer projects the fixed 15 agents only, so every internal framework subscription such as `runtime-observer` raised `ValueError: unknown Pantheon agent` and logged a warning per delivery. Handler delivery itself is unchanged for those principals. | `current change`; `bus_bridge.py`, `test_provider_integration.py`; agents suite `1165 passed` including a new non-Pantheon principal case, mutation-verified by removing the guard and observing `assert ['runtime-observer', 'runtime-observer'] == []`; Ruff passed. Measured on the deployed revision before the fix: 24 `pantheon_handler_observer_failed` warnings in 60 log lines, firing continuously. | Runtime exit-gate evidence and independent promotion outcomes remain unchanged. |
| 2026-08-13 | implemented | Adopted the implementation ledger and separated focused shadow-path implementation from operational rollout validation. Earlier implementation provenance was not reconstructed. | current change; focused workflow tests | Capture runtime exit-gate evidence and record independent promotion outcomes. |
| 2026-08-14 | implemented | Extracted Forseti's pure decision mapping, conflict, impact, and freshness helpers into the private framework without changing its judge role, topics, workflow modes, or promotion state. | `current change`; focused layout and Forseti judge checks passed 104 cases, and strict mypy and agent import gates passed. | Runtime exit-gate evidence and independent promotion outcomes remain unchanged. |
| 2026-08-17 | implemented | Extracted Heimdall's pure bounded-map, trace-evidence, and severity normalization helpers into the private framework. Its observer role, owned and subscribed topics, deterministic hot path, and incident handoff remain unchanged. | `current change`; `heimdall_helpers.py`, `heimdall.py`; 21 focused observer cases, 11 framework-layout cases, Ruff, format, and strict mypy passed. | Runtime exit-gate evidence and independent promotion outcomes remain unchanged. |
| 2026-08-17 | implemented | Extracted Norns' deterministic fingerprint, outcome, shadow-dwell, approval, and override state transitions into private framework functions. Norns retains all learner state, candidate construction, consensus, rate limiting, and sole publication on `object.rule-candidate`; no catalog or execution authority was added. | `current change`; `norns_learning.py`, `norns.py`; 97 focused learner cases, 11 framework-layout cases, Ruff, format, and strict mypy passed. | Runtime exit-gate evidence and independent promotion outcomes remain unchanged. |
| 2026-08-17 | implemented | Extracted Forseti's deterministic document, rule, RBAC, readiness, context-ceiling, and security judgment implementation into a private framework mixin. The Forseti instance remains the sole Verdict and SecurityEvent publisher; quorum, no-self-approval lineage, T2 abstention policy, and topic ownership are unchanged. | `current change`; `forseti_judgment.py`, `forseti.py`; 93 focused judgment cases, 11 framework-layout cases, Ruff, format, and strict mypy passed. | Runtime exit-gate evidence and independent promotion outcomes remain unchanged. |

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
