# Ontology-Grounded ARB Agent Loop implementation ledger

This ledger tracks the agent-owned review loop without treating shared ontology or pantheon
foundations as proof that ARB runs autonomously.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Planned-change ingest and revision retention | implemented | `agents/huginn.py`; `agents/muninn.py`; `tests/agents/test_change_management_chain.py` | Huginn publishes `Change` and Muninn retains revisions, but the complete ARB case is not assembled. |
| Fresh ontology context for planned change | in-progress | `core/operational_context/`; `core/impact_analysis/`; `agents/forseti.py`; `tests/core/impact_analysis/test_change_assessment.py`; `tests/agents/test_change_management_chain.py` | `ChangeAssessmentService` now requires a typed graph evidence receipt and covers fresh, stale, mixed-release, conflict, and truncation outcomes. Forseti still injects `ChangeGraphEvidenceReceipt.unavailable()` until Muninn supplies a verified receipt from the exact context snapshot. |
| Agent evidence fan-out and deterministic join | not-started | [Owner design](../../../roadmap/architecture/architecture-review/ontology-agent-loop.md#evidence-fan-out-and-join) | No ARB-specific typed join drives specialist evidence under deadlines. |
| DecisionCase, impact envelope, and arbitration | in-progress | `core/decision_case/`; `core/impact_analysis/`; `agents/forseti.py`; `agents/odin.py` | Shared slices exist, but ARB does not compose them from one verified evidence bundle and scenario branch. |
| Derived ReviewCase and ReviewCheck projection | not-started | `core/architecture_review/projection.py` | Current projection reads manifest state rather than authoritative agent decision lineage. |
| ARB pantheon integration evidence | not-started | Existing topic and role tests | No retained ARB trace proves duplicate, reorder, restart, deadline, degradation, and replay behavior. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-29 | in-progress | Replaced the planned-change `graph_fresh` boolean with a typed graph evidence receipt and added focused stale, mixed-release, conflict, and truncation coverage. | `current change`; `services/core-control-plane/src/fdai/core/impact_analysis/change_assessment.py`, `services/core-control-plane/src/fdai/agents/forseti.py`, `services/core-control-plane/tests/core/impact_analysis/test_change_assessment.py`, `services/core-control-plane/tests/agents/test_change_management_chain.py`; `./.venv/bin/pytest -q --no-cov services/core-control-plane/tests/core/impact_analysis/test_change_assessment.py services/core-control-plane/tests/core/impact_analysis/test_impact_analysis.py services/core-control-plane/tests/agents/test_change_management_chain.py services/core-control-plane/tests/agents/test_decision_case_e2e.py services/core-control-plane/tests/core/conversation_assurance/test_quality_sre_impact_observations.py services/core-control-plane/tests/core/change_lineage/test_models.py services/core-control-plane/tests/core/change_lineage/test_provider_compatibility.py` | Wire the receipt from one exact `OperationalContextSnapshot` so Forseti can carry authenticated graph evidence instead of the current unavailable placeholder. |
| 2026-08-24 | in-progress | Split the ontology-agent loop into a focused owner and recorded the current foundation-to-runtime gap. | `current change`; owner document, paired translation, source paths, and focused documentation checks. | Implement the observation-mode vertical slice and prove it through owned topics. |

### Remaining work

- [ ] Source `ChangeGraphEvidenceReceipt` from the exact `OperationalContextSnapshot` so Forseti no
  longer falls back to `ChangeGraphEvidenceReceipt.unavailable()` and the planned-change path carries
  an authenticated graph revision, release match, freshness, conflict, and truncation receipt.
- [ ] Compose one `Change -> context -> evidence bundle -> scenario branch -> DecisionCase ->
  ImpactEnvelope` path without direct agent calls.
- [ ] Derive `ReviewCase` and `ReviewCheck` from authoritative lineage and reconcile expired or
  removed evidence.
- [ ] Retain one replayable ARB pantheon trace covering duplicate, reorder, restart, deadline,
  backpressure, degradation, and no-mutation behavior.
