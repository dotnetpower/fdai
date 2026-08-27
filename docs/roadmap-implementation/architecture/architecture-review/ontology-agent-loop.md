# Ontology-Grounded ARB Agent Loop implementation ledger

This ledger tracks the agent-owned review loop without treating shared ontology or pantheon
foundations as proof that ARB runs autonomously.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Planned-change ingest and revision retention | implemented | `agents/huginn.py`; `agents/muninn.py`; `tests/agents/test_change_management_chain.py` | Huginn publishes the exact `Change` revision and Muninn retains it for the observation-mode ARB path. |
| Fresh ontology context for planned change | implemented | `core/impact_analysis/change_assessment.py`; `delivery/persistence/postgres_graph_freshness.py`; focused context, impact, persistence-decoder, and change-chain tests | Forseti resolves a content-addressed exact-release receipt from the active PostgreSQL inventory generation. Only a fresh, complete, exact-target observed generation can preserve automatic review eligibility. |
| Agent evidence fan-out and deterministic join | implemented | `core/architecture_review/observation_loop.py`; `tests/core/architecture_review/test_observation_loop.py` | Deadline-bound context and evidence collection records unavailable or late branches as holds. |
| DecisionCase, impact envelope, and arbitration | implemented | `core/architecture_review/observation_loop.py`; `agents/forseti.py`; focused observation tests | Forseti publishes one JSON-safe observation-only verdict containing bundle, scenario, DecisionCase, and ImpactEnvelope lineage. Thor ignores it before action dispatch, Odin excludes it from action-portfolio counts, and Saga audits it. No arbitration or execution authority is added. |
| Derived ReviewCase and ReviewCheck projection | implemented | `core/architecture_review/projection.py`; focused projection tests | The new projection path reads observation lineage and marks removed evidence checks instead of treating manifest status as authority. |
| ARB pantheon integration evidence | implemented | `tests/core/architecture_review/test_observation_loop.py` | The retained trace covers duplicate, reorder/restart reuse, deadline, backpressure, Saga audit, replay identity, and no mutation. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-24 | in-progress | Split the ontology-agent loop into a focused owner and recorded the current foundation-to-runtime gap. | `current change`; owner document, paired translation, source paths, and focused documentation checks. | Implement the observation-mode vertical slice and prove it through owned topics. |
| 2026-08-27 | implemented | Replaced the caller-supplied freshness boolean with an authoritative active-inventory receipt that binds target, release, generation, graph revision, temporal validity, completeness, and zero execution authority. | `current change`; focused impact, persistence-decoder, change-chain, lineage, and pantheon-layout checks (`64 passed`); Ruff and strict mypy. | Retain deployed receipt evidence separately and continue composing the remaining observation-mode ARB slice. |
| 2026-08-27 | implemented | Closed review findings in the freshness boundary by binding persisted ontology and operating-model manifests, rejecting all pending overlays, double-reading around graph traversal, and routing configured PostgreSQL failures to explicit review. | `current change`; focused freshness and change-chain checks within the 49-case slice; Ruff and strict mypy. | Continue the remaining evidence join and lineage-derived projection work. |
| 2026-08-27 | implemented | Required the operating-model status and manifest to share one projected source revision before planned-change freshness can remain complete. | `current change`; focused freshness and pantheon checks (`52 passed`). | Continue the remaining ARB evidence join. |
| 2026-08-27 | implemented | Added the observation-mode vertical slice: Huginn `Change` -> authenticated context -> `OperationalEvidenceBundle` -> bounded scenario -> Forseti-owned observation verdict with `DecisionCase` and `ImpactEnvelope`, plus lineage-derived projection and duplicate/restart-safe trace handling. | `current change`; `test_observation_loop.py` and `test_projection.py` pass (`7 passed`); focused Ruff, format, and strict mypy pass. | Retain deployed evidence and complete the separate authority-bearing decision and effect-closure work. |
| 2026-08-27 | implemented | Isolated observation-only ARB verdicts from Thor action dispatch and Odin action-portfolio accounting, while preserving Saga audit and JSON-safe Change timestamps. | `current change`; observation loop and pantheon role checks; Ruff and strict mypy. | Retain deployed typed-bus evidence separately; no action authority was added. |

### Remaining work

- [x] Replace the planned-change freshness boolean with an authenticated graph revision and
  freshness receipt. Focused tests cover fresh, stale, mixed-release, conflict, target mismatch,
  future time, truncation, pending overlay, and source unavailability.
- [x] Compose one `Change -> context -> evidence bundle -> scenario branch -> DecisionCase ->
  ImpactEnvelope` path without direct agent calls.
- [x] Derive `ReviewCase` and `ReviewCheck` from authoritative lineage and reconcile expired or
  removed evidence.
- [x] Retain one replayable ARB pantheon trace covering duplicate, reorder, restart, deadline,
  backpressure, degradation, and no-mutation behavior.
