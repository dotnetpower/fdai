# Ontology-Grounded ARB Agent Loop implementation ledger

This ledger tracks the agent-owned review loop without treating shared ontology or pantheon
foundations as proof that ARB runs autonomously.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Planned-change ingest and revision retention | implemented | `agents/huginn.py`; `agents/muninn.py`; `tests/agents/test_change_management_chain.py` | Huginn publishes `Change` and Muninn retains revisions, but the complete ARB case is not assembled. |
| Fresh ontology context for planned change | implemented | `core/impact_analysis/change_assessment.py`; `delivery/persistence/postgres_graph_freshness.py`; focused context, impact, persistence-decoder, and change-chain tests | Forseti resolves a content-addressed exact-release receipt from the active PostgreSQL inventory generation. Only a fresh, complete, exact-target observed generation can preserve automatic review eligibility. |
| Agent evidence fan-out and deterministic join | not-started | [Owner design](../../../roadmap/architecture/architecture-review/ontology-agent-loop.md#evidence-fan-out-and-join) | No ARB-specific typed join drives specialist evidence under deadlines. |
| DecisionCase, impact envelope, and arbitration | in-progress | `core/decision_case/`; `core/impact_analysis/`; `agents/forseti.py`; `agents/odin.py` | Shared slices exist, but ARB does not compose them from one verified evidence bundle and scenario branch. |
| Derived ReviewCase and ReviewCheck projection | not-started | `core/architecture_review/projection.py` | Current projection reads manifest state rather than authoritative agent decision lineage. |
| ARB pantheon integration evidence | not-started | Existing topic and role tests | No retained ARB trace proves duplicate, reorder, restart, deadline, degradation, and replay behavior. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-24 | in-progress | Split the ontology-agent loop into a focused owner and recorded the current foundation-to-runtime gap. | `current change`; owner document, paired translation, source paths, and focused documentation checks. | Implement the observation-mode vertical slice and prove it through owned topics. |
| 2026-08-27 | implemented | Replaced the caller-supplied freshness boolean with an authoritative active-inventory receipt that binds target, release, generation, graph revision, temporal validity, completeness, and zero execution authority. | `current change`; focused impact, persistence-decoder, change-chain, lineage, and pantheon-layout checks (`64 passed`); Ruff and strict mypy. | Retain deployed receipt evidence separately and continue composing the remaining observation-mode ARB slice. |
| 2026-08-27 | implemented | Closed review findings in the freshness boundary by binding persisted ontology and operating-model manifests, rejecting all pending overlays, double-reading around graph traversal, and routing configured PostgreSQL failures to explicit review. | `current change`; focused freshness and change-chain checks within the 49-case slice; Ruff and strict mypy. | Continue the remaining evidence join and lineage-derived projection work. |
| 2026-08-27 | implemented | Required the operating-model status and manifest to share one projected source revision before planned-change freshness can remain complete. | `current change`; focused freshness and pantheon checks (`52 passed`). | Continue the remaining ARB evidence join. |

### Remaining work

- [x] Replace the planned-change freshness boolean with an authenticated graph revision and
  freshness receipt. Focused tests cover fresh, stale, mixed-release, conflict, target mismatch,
  future time, truncation, pending overlay, and source unavailability.
- [ ] Compose one `Change -> context -> evidence bundle -> scenario branch -> DecisionCase ->
  ImpactEnvelope` path without direct agent calls.
- [ ] Derive `ReviewCase` and `ReviewCheck` from authoritative lineage and reconcile expired or
  removed evidence.
- [ ] Retain one replayable ARB pantheon trace covering duplicate, reorder, restart, deadline,
  backpressure, degradation, and no-mutation behavior.
