# Outcome Assurance implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Reused ontology, readiness, audit, and measurement sources | in-progress | `core/decision_case/`; `core/readiness/`; `core/measurement/`; `core/audit/`; current implementation ledgers in their owner documents | Source capabilities exist at different evidence levels, but they are not joined into one Outcome Assurance projection. |
| `OutcomeAssuranceProjection` typed read model | not-started | [Projection contract](../../roadmap/architecture/outcome-assurance.md#projection-contract); no matching implementation under `services/` | The design defines bounded groups and evidence states. No canonical contract, decoder, or replay implementation is present. |
| Objective attribution and aggregate evaluation | not-started | [Objective attribution](../../roadmap/architecture/outcome-assurance.md#objective-attribution) | No aggregator currently closes the complete event-to-objective-to-outcome chain or retains unattributed events in this projection's denominator. |
| Authenticated Operator API and Console experience | not-started | [Operator API and console](../../roadmap/architecture/outcome-assurance.md#operator-api-and-console); no matching route or Console module under `services/operator-service/` or `console/` | The proposed read-only endpoint, summaries, evidence drill-downs, and unavailable states are not implemented. |
| Change Safety pilot and vertical expansion | not-started | [Delivery sequence](../../roadmap/architecture/outcome-assurance.md#delivery-sequence) | OA0-OA2 must land before a non-synthetic OA3 pilot or OA4 expansion can produce evidence. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | not-started | Adopted the implementation ledger without reconstructing earlier provenance and recorded the projection as design-only over partially implemented source systems. | `current change`; repository search for the contract, API route, and Console surface plus the source owner documents cited above. | Deliver OA0 through OA2 before starting the pilot and vertical expansion. |

### Remaining work

- [ ] Define and test the typed `OutcomeAssuranceProjection`, bounded evidence states, correction rules, and deterministic replay without adding an authority object.
- [ ] Implement the complete objective-attribution join and keep unresolved finalized events in the denominator with explicit coverage.
- [ ] Bind authenticated authoritative sources, add the read-only Operator API and Console drill-downs, and prove missing or stale data renders unavailable rather than synthetic.
- [ ] Run the Change Safety pilot on one pinned service and scenario set, then expand only after the acceptance criteria have authoritative non-synthetic evidence.
