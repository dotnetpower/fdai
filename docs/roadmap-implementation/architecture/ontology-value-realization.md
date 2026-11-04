# Ontology Value Realization implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Assessment and decisions | not-applicable | [Assessment](../../roadmap/architecture/ontology-value-realization.md#assessment) | Design-only material from a static repository review. No live validation was run. |
| VR0 value claim ledger | implemented | `core/measurement/value_claim.py`; `tests/core/measurement/test_value_claim.py` | Pure settlement requires independent, complete, scope-matched cohorts above the sample floor and reports the conservative 95% bound. No persistence, catalog binding, or Console surface exists yet. |
| VR1 ontology function gate | in-progress | `core/workflow/ontology_gate.py`; `tests/core/workflow/test_ontology_gate.py` | The evaluator opens only for a complete, fresh, receipted, exact-function reading and otherwise stays shut. No reader backed by the ontology query gateway, no decision function, no causal-engine wiring, and no catalog workflow uses it yet. |
| VR2 real-data evidence | not-started | [VR2](../../roadmap/architecture/ontology-value-realization.md#vr2---real-data-evidence) | Retained sanitized cohorts and a labeled holdout do not exist. |
| VR3 close the loop | not-started | [VR3](../../roadmap/architecture/ontology-value-realization.md#vr3---close-the-loop) | Depends on VR1 and VR2 evidence and on the workflow Wave 3 to 5 gates. |
| VR4 consumption and reach | not-started | [VR4](../../roadmap/architecture/ontology-value-realization.md#vr4---consumption-and-reach) | Each non-Azure adapter needs explicit approval. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-11-04 | in-progress | Added the owning design, the typed value claim settlement, and the ontology function workflow gate. | `current change`; `uv run pytest -q --no-cov services/core-control-plane/tests/core/measurement/test_value_claim.py services/core-control-plane/tests/core/workflow` passed with 362 tests; Ruff and strict mypy passed on the new modules. | Bind a reader to the ontology query gateway, persist claims, add decision functions, and produce non-fixture evidence. |

### Remaining work

- [ ] Implement an `OntologyGateReader` backed by the governed ontology query gateway, and prove an
  incomplete, stale, or unauthorized result keeps the gate shut in a focused composition test.
- [ ] Add at least three read-only decision functions (blast radius, change risk, cost of delay)
  with replay tests, and bind at least three catalog workflows to ontology function gates in shadow.
- [ ] Wire the existing causal prediction engine behind the evidence rules and grow the catalog to
  at least eight causal mechanisms with refutation reads.
- [ ] Persist value claims and settlements, and expose them through the Outcome Assurance
  projection without adding a mutation path.
- [ ] Retain sanitized incident cohorts with a separate labeled holdout, and report root-cause
  accuracy, correct abstention, and wrong-action rate with intervals.
- [ ] Promote one workflow per value loop through the normal gates and settle one value claim per
  loop from independent observation.
