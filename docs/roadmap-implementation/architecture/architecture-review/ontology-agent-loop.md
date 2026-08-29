# Ontology-Grounded ARB Agent Loop implementation ledger

This ledger tracks the agent-owned review loop without treating shared ontology or pantheon
foundations as proof that ARB runs autonomously.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Planned-change ingest and revision retention | implemented | `agents/huginn.py`; `agents/muninn.py`; `tests/agents/test_change_management_chain.py` | Huginn publishes `Change` and Muninn retains revisions, but the complete ARB case is not assembled. |
| Fresh ontology context for planned change | implemented | `core/operational_context/`; `core/impact_analysis/`; `agents/{huginn,forseti}.py`; `runtime/bootstrap_pantheon.py`; focused context, impact, agent, layout, and bootstrap tests | Huginn preserves the requested ontology release digest. Production bootstrap binds the active release into the context materializer, and Forseti materializes verified links at the exact change cutoff before deriving graph revision, release match, freshness, authentication, conflict, and truncation evidence from that snapshot. Missing inputs still produce the fail-closed unavailable receipt. |
| Agent evidence fan-out and deterministic join | not-started | [Owner design](../../../roadmap/architecture/architecture-review/ontology-agent-loop.md#evidence-fan-out-and-join) | No ARB-specific typed join drives specialist evidence under deadlines. |
| DecisionCase, impact envelope, and arbitration | in-progress | `core/decision_case/`; `core/impact_analysis/`; `agents/forseti.py`; `agents/odin.py` | Shared slices exist, but ARB does not compose them from one verified evidence bundle and scenario branch. |
| Derived ReviewCase and ReviewCheck projection | not-started | `core/architecture_review/projection.py` | Current projection reads manifest state rather than authoritative agent decision lineage. |
| ARB pantheon integration evidence | in-progress | `core/architecture_review/observation_trace.py`; `tests/core/architecture_review/test_observation_trace.py` | The immutable observation-only replay projection converges across duplicate, reordered, and restarted delivery and holds on missing, conflicting, late, identity-mismatched, or incorrectly owned evidence. Runtime topic binding, backpressure, and degradation evidence remain open. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-29 | in-progress | Added a replay-stable, authority-free ARB observation trace over the fixed Huginn, Muninn, specialist, Forseti, and Saga boundaries. Duplicate, reordered, and restarted delivery converges; missing, conflicting, late, identity-mismatched, or incorrectly owned evidence produces an explicit hold. | `current change`; `core/architecture_review/observation_trace.py`; `tests/core/architecture_review/test_observation_trace.py`; focused pytest, Ruff, and strict mypy checks. | Bind the replay projection to owned runtime topics and retain provider-backed backpressure and degradation evidence before claiming a complete pantheon trace. |
| 2026-08-29 | in-progress | Replaced the planned-change `graph_fresh` boolean with a typed graph evidence receipt and added focused stale, mixed-release, conflict, and truncation coverage. | `current change`; `services/core-control-plane/src/fdai/core/impact_analysis/change_assessment.py`, `services/core-control-plane/src/fdai/agents/forseti.py`, `services/core-control-plane/tests/core/impact_analysis/test_change_assessment.py`, `services/core-control-plane/tests/agents/test_change_management_chain.py`; `./.venv/bin/pytest -q --no-cov services/core-control-plane/tests/core/impact_analysis/test_change_assessment.py services/core-control-plane/tests/core/impact_analysis/test_impact_analysis.py services/core-control-plane/tests/agents/test_change_management_chain.py services/core-control-plane/tests/agents/test_decision_case_e2e.py services/core-control-plane/tests/core/conversation_assurance/test_quality_sre_impact_observations.py services/core-control-plane/tests/core/change_lineage/test_models.py services/core-control-plane/tests/core/change_lineage/test_provider_compatibility.py` | Wire the receipt from one exact `OperationalContextSnapshot` so Forseti can carry authenticated graph evidence instead of the current unavailable placeholder. |
| 2026-08-29 | implemented | Wired planned-change assessment to one exact verified `OperationalContextSnapshot`. Huginn retains the requested ontology digest, bootstrap binds the active digest into the materializer, and Forseti derives the receipt without trusting caller booleans. | `current change`; context materializer, impact receipt projector, Huginn and Forseti wiring, bootstrap binding, and focused context, impact, agent, layout, and bootstrap tests (`103 passed`); targeted Ruff and strict mypy checks. | Compose the wider evidence bundle, scenario branch, and DecisionCase path without direct agent calls. |
| 2026-08-24 | in-progress | Split the ontology-agent loop into a focused owner and recorded the current foundation-to-runtime gap. | `current change`; owner document, paired translation, source paths, and focused documentation checks. | Implement the observation-mode vertical slice and prove it through owned topics. |

### Remaining work

- [x] Source `ChangeGraphEvidenceReceipt` from the exact `OperationalContextSnapshot` so Forseti
  carries graph revision, release match, freshness, authentication, conflict, and truncation
  evidence while missing inputs still fail closed (`103 passed` focused checks).
- [ ] Compose one `Change -> context -> evidence bundle -> scenario branch -> DecisionCase ->
  ImpactEnvelope` path without direct agent calls.
- [ ] Derive `ReviewCase` and `ReviewCheck` from authoritative lineage and reconcile expired or
  removed evidence.
- [ ] Bind `replay_architecture_review_trace` to owned runtime topics and retain provider-backed
  backpressure and degradation evidence; the focused replay test already covers duplicate,
  reordered, restarted, missing, conflicting, late, incorrectly owned, and no-mutation behavior.
