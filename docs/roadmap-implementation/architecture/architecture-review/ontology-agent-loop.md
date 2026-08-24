# Ontology-Grounded ARB Agent Loop implementation ledger

This ledger tracks the agent-owned review loop without treating shared ontology or pantheon
foundations as proof that ARB runs autonomously.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Planned-change ingest and revision retention | implemented | `agents/huginn.py`; `agents/muninn.py`; `tests/agents/test_change_management_chain.py` | Huginn publishes `Change` and Muninn retains revisions, but the complete ARB case is not assembled. |
| Fresh ontology context for planned change | in-progress | `core/operational_context/`; `core/impact_analysis/`; focused context and impact tests | Core foundations exist, but Forseti currently supplies `graph_fresh=False` to planned-change assessment. |
| Agent evidence fan-out and deterministic join | not-started | [Owner design](../../../roadmap/architecture/architecture-review/ontology-agent-loop.md#evidence-fan-out-and-join) | No ARB-specific typed join drives specialist evidence under deadlines. |
| DecisionCase, impact envelope, and arbitration | in-progress | `core/decision_case/`; `core/impact_analysis/`; `agents/forseti.py`; `agents/odin.py` | Shared slices exist, but ARB does not compose them from one verified evidence bundle and scenario branch. |
| Derived ReviewCase and ReviewCheck projection | not-started | `core/architecture_review/projection.py` | Current projection reads manifest state rather than authoritative agent decision lineage. |
| ARB pantheon integration evidence | not-started | Existing topic and role tests | No retained ARB trace proves duplicate, reorder, restart, deadline, degradation, and replay behavior. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-24 | in-progress | Split the ontology-agent loop into a focused owner and recorded the current foundation-to-runtime gap. | `current change`; owner document, paired translation, source paths, and focused documentation checks. | Implement the observation-mode vertical slice and prove it through owned topics. |

### Remaining work

- [ ] Replace the planned-change freshness boolean with an authenticated graph revision and
  freshness receipt, then pass fresh, stale, mixed-release, conflict, and truncation tests.
- [ ] Compose one `Change -> context -> evidence bundle -> scenario branch -> DecisionCase ->
  ImpactEnvelope` path without direct agent calls.
- [ ] Derive `ReviewCase` and `ReviewCheck` from authoritative lineage and reconcile expired or
  removed evidence.
- [ ] Retain one replayable ARB pantheon trace covering duplicate, reorder, restart, deadline,
  backpressure, degradation, and no-mutation behavior.
