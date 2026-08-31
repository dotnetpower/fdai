# Outcome Assurance implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Reused ontology, readiness, audit, and measurement sources | in-progress | `core/decision_case/`; `core/readiness/`; `core/measurement/`; `core/audit/`; current implementation ledgers in their owner documents | Source capabilities exist at different evidence levels, but they are not joined into one Outcome Assurance projection. |
| Cost Governance effect settlement source | implemented | `core/measurement/cost_effect_settlement.py`; `core/measurement/cost_retention.py`; focused Cost Governance settlement tests | Cost, capacity, service, and recovery effects remain separate and close only from independent observations bound to the exact expected-effect source revision. This source does not complete the broader `OutcomeAssuranceProjection`. |
| Phase 4 measured policy source | implemented | `core/measurement/{pattern_growth,model_tracking,latency_budget}.py`; `delivery/measurement/{holdout,measured_policy}.py`; focused Core and delivery tests | Complete holdout gates shadow pattern write. Paired model evidence produces review-only recommendations, while per-tier latency preserves server-owned budgets, reported values, volume, percentiles, and unavailable state. Malformed evidence is rejected once without blocking later batches. Durable processing grants no promotion or execution authority. |
| `OutcomeAssuranceProjection` typed read model | implemented | [Projection contract](../../roadmap/architecture/outcome-assurance.md#projection-contract); `core/measurement/outcome_assurance.py`; focused Outcome Assurance contract tests | Typed scope, window, readiness, alignment, outcome, guard, and provenance models now exist with deterministic JSON replay and latest-authoritative correction reduction. The contract remains read-only and adds no authority object. |
| Objective attribution and aggregate evaluation | implemented | [Objective attribution](../../roadmap/architecture/outcome-assurance.md#objective-attribution); `core/measurement/outcome_assurance.py`; focused Outcome Assurance tests | The pure reducer accepts an explicit finalized-event universe, requires the complete decision, objective, workflow, action, run, outcome, and measurement chain, uses only the latest authoritative observation, and retains every unresolved event in the denominator. Authoritative source binding remains open. |
| Authenticated Operator API and Console experience | not-started | [Operator API and console](../../roadmap/architecture/outcome-assurance.md#operator-api-and-console); no matching route or Console module under `services/operator-service/` or `console/` | The proposed read-only endpoint, summaries, evidence drill-downs, and unavailable states are not implemented. |
| Change Safety pilot and vertical expansion | not-started | [Delivery sequence](../../roadmap/architecture/outcome-assurance.md#delivery-sequence) | OA0-OA2 must land before a non-synthetic OA3 pilot or OA4 expansion can produce evidence. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-31 | implemented | Added durable Phase 4 holdout, model-swap, and latency source processing to the scheduled measurement composition. Restart, duplicate, partial, stale, future, rollback, and unavailable evidence stay explicit, and positive model comparison requires separate promotion review. | `current change`; measurement reducers, delivery runners, CLI composition, and focused Core/delivery/CLI checks. | Bind authenticated authoritative source receipts into the broader Outcome Assurance projection and retain a governed live cohort. |
| 2026-08-29 | implemented | Added a Cost Governance source that separates estimated savings from independently verified effect settlement and retains failed, censored, unscorable, and rollback outcomes. | `current change`; focused Cost Governance settlement, retention, and campaign tests. | Join this source through the still-open `OutcomeAssuranceProjection` work. |
| 2026-08-29 | implemented | Added the OA0 typed read model, bounded evidence states, deterministic replay JSON, and latest-authoritative correction reduction without introducing an authority object. | `current change`; `core/measurement/outcome_assurance.py`, `core/measurement/__init__.py`, and focused `uv run --extra dev python -m pytest -q --no-cov --noconftest services/core-control-plane/tests/core/measurement/test_outcome_assurance.py` (`7 passed`) plus targeted Ruff checks. | Bind authoritative readiness, guard, and measurement sources through OA1. |
| 2026-08-29 | implemented | Added the objective-attribution reducer over an explicit finalized-event universe. It rejects duplicate event identities and observations outside that universe, never infers an objective from names, joins only a complete typed chain to the latest matching observation, and keeps incomplete or mismatched events in coverage. | `current change`; `core/measurement/outcome_assurance.py`; `core/measurement/__init__.py`; focused Outcome Assurance tests (`13 passed`); targeted Ruff and strict mypy checks. | Bind authenticated finalized-event, objective, audit, and measurement sources before exposing the read model. |
| 2026-08-14 | not-started | Adopted the implementation ledger without reconstructing earlier provenance and recorded the projection as design-only over partially implemented source systems. | `current change`; repository search for the contract, API route, and Console surface plus the source owner documents cited above. | Deliver OA0 through OA2 before starting the pilot and vertical expansion. |

### Remaining work

- [x] Define and test the typed `OutcomeAssuranceProjection`, bounded evidence states, correction rules, and deterministic replay without adding an authority object (`core/measurement/outcome_assurance.py`; focused Outcome Assurance contract tests: `7 passed`).
- [x] Implement the complete objective-attribution join and keep unresolved finalized events in the denominator with explicit coverage (`summarize_objective_attribution`; focused Outcome Assurance tests: `13 passed`).
- [ ] Bind authenticated authoritative sources, add the read-only Operator API and Console drill-downs, and prove missing or stale data renders unavailable rather than synthetic.
- [ ] Run the Change Safety pilot on one pinned service and scenario set, then expand only after the acceptance criteria have authoritative non-synthetic evidence.
