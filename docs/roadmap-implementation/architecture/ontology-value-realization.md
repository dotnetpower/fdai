# Ontology Value Realization implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Assessment and decisions | not-applicable | [Assessment](../../roadmap/architecture/ontology-value-realization.md#assessment) | Design-only material from a static repository review. No live validation was run. |
| VR0 value claim settlement and ledger | implemented | `core/measurement/value_claim.py`; `core/measurement/value_claim_ledger.py`; `tests/core/measurement/test_value_claim.py`; `tests/core/measurement/test_value_claim_ledger.py` | Pure settlement requires independent, complete, scope-matched cohorts above the sample floor and reports the conservative 95% bound. The state-store ledger records each settlement once by digest, and the bridge reshapes it for Outcome Assurance without upgrading an unsettled claim. No producer feeds real cohorts, and no Operator or Console surface reads it yet. |
| VR1 ontology function gate and registry reader | implemented | `core/workflow/ontology_gate.py`; `core/ontology_platform/workflow_gate_reader.py`; `runtime/control_loop_support.py`; `tests/core/workflow/test_ontology_gate.py`; `tests/core/workflow/test_coordinator_wiring.py`; `tests/core/ontology_platform/test_decision_functions.py` | The gate opens only for a complete, fresh, receipted, exact-function reading. `RegistryOntologyGateReader` invokes a configured function through the registry with a server-built context, and the coordinator composes it only when a reader is supplied. The control loop composes it from `config/workflow-ontology-gates.yaml` and leaves the gate shut without that file, the graph, or the decision release. |
| VR1 decision functions | implemented | `core/ontology_platform/decision_functions.py`; `core/ontology_platform/operational_functions.py`; `tests/core/ontology_platform/test_decision_functions.py` | `decision.blast_radius`, `decision.change_risk`, and `decision.cost_of_delay` are deterministic, read-only, receipted through the registry, and part of the operational release. |
| VR1 evidence readers over the ontology graph | implemented | `core/ontology_platform/decision_evidence_readers.py`; `core/ontology_platform/workflow_gate_config.py`; `config/workflow-ontology-gates.yaml`; `runtime/control_loop_support.py`; `runtime/control_loop.py`; `tests/core/ontology_platform/test_decision_evidence_readers.py`; `tests/core/ontology_platform/test_workflow_gate_config.py` | Blast radius follows `depends_on` and `runtime_calls` dependents and weighs the reviewed criticality of the services that depend on each Resource. Change risk observes the change window, the provider change feed, a ready and rehearsed RecoveryPlan, and a recent accepted shadow ActionRun. Cost of delay derives an hourly rate from the newest complete, non-synthetic CostObservation. The runtime composes only the gates configured in `config/workflow-ontology-gates.yaml`. Verified against an in-memory graph built from the real catalog, not against a live deployment. |
| VR1 cost source projection | not-started | `core/ontology_platform/decision_evidence_readers.py` | No producer projects provider cost facts into `CostObservation` ontology objects, and the shipped configuration omits the cost gate. The cost gate stays closed until a producer and a business threshold exist. |
| VR1 gated shadow workflows | implemented | `rule-catalog/workflows/blast-radius-gated-service-restart.yaml`; `rule-catalog/workflows/change-risk-gated-scale-in.yaml`; `rule-catalog/workflows/cost-of-delay-gated-vm-deallocate.yaml`; `config/workflow-promotion-verdicts.json` | Three shadow workflows place an ontology function gate before approval and the action. Evidence for the first two comes from the ontology graph and the change feed. The cost-of-delay workflow stays closed until a cost source and threshold exist, which is the intended fail-closed shadow behavior. |
| VR1 causal mechanism catalog | implemented | `rule-catalog/vocabulary/causal-mechanisms.yaml`; `tests/conversation/test_causal_grade_receipts.py` | Eight reviewed mechanisms with at least two refutation reads each. The separate 55-scenario Azure catalog engine is not wired into a runtime path. |
| VR2 real-data evidence | not-started | [VR2](../../roadmap/architecture/ontology-value-realization.md#vr2---real-data-evidence); `core/rca/evaluation.py` | The offline typed scorer already exists. Retained sanitized cohorts, a labeled holdout, and the parity comparison require data and authorization that this repository cannot supply. |
| VR3 close the loop | not-started | [VR3](../../roadmap/architecture/ontology-value-realization.md#vr3---close-the-loop) | Needs real executor bindings, staging parity, human approval, and independent post-action observation. |
| VR4 consumption and reach | not-started | [VR4](../../roadmap/architecture/ontology-value-realization.md#vr4---consumption-and-reach) | The decision queue needs an Operator API and a live-verified Console route. Each non-Azure adapter needs explicit approval. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-11-04 | in-progress | Added the owning design, the typed value claim settlement, and the ontology function workflow gate. | `current change`; `uv run pytest -q --no-cov services/core-control-plane/tests/core/measurement/test_value_claim.py services/core-control-plane/tests/core/workflow` passed with 362 tests; Ruff and strict mypy passed on the new modules. | Bind a reader to the ontology query gateway, persist claims, add decision functions, and produce non-fixture evidence. |
| 2026-11-04 | in-progress | Added three decision FunctionTypes, a registry-backed gate reader with optional coordinator composition, three gated shadow workflows with their promotion verdict entries, seven reviewed causal mechanisms, and a durable settlement ledger with an Outcome Assurance bridge. | `current change`; `uv run pytest -q --no-cov` over `services/core-control-plane/tests/{core/workflow,core/ontology_platform,core/measurement,conversation,rule_catalog,composition,runtime}` and `tests/integration/scripts/test_workflow_promotion_verdicts.py` passed; Ruff and strict mypy passed on the new modules. | Bind evidence readers to live sources, wire the causal engine, expose claims through the Operator API, and produce real-data evidence. |
| 2026-11-04 | in-progress | Bound the three decision functions to the runtime ontology graph, the provider-observed change feed, and observed cost through read-only evidence readers, and composed them into the control loop from a reviewed gate configuration that omits the business-threshold cost gate. | `current change`; `uv run pytest -q --no-cov` over `services/core-control-plane/tests/{runtime,core/workflow,core/ontology_platform,core/measurement,composition,rule_catalog}` passed; Ruff and strict mypy passed on the new modules. | Verify the readers against a live inventory generation, project provider cost facts into `CostObservation`, and set the cost threshold in a deployment. |

### Remaining work

- [ ] Verify the evidence readers against a live inventory generation, change feed, and
  recovery history in a deployment, and retain a replay in which each shipped gate reaches an open
  state for complete evidence and stays shut for incomplete, stale, or unauthorized evidence.
- [ ] Project provider cost facts into `CostObservation` ontology objects with exact target
  identity, and let a deployment set the `decision.cost_of_delay` metric, delay, and threshold in
  `config/workflow-ontology-gates.yaml`.
- [ ] Wire the existing causal prediction engine behind the causal-grade evidence rules so a
  runtime path consumes it.
- [ ] Add a producer that feeds retained independent cohorts to `settle_value_claim`, and expose
  recorded settlements through the Outcome Assurance Operator API without a mutation path.
- [ ] Retain sanitized incident cohorts with a separate labeled holdout, and report root-cause
  accuracy, correct abstention, and wrong-action rate with intervals through the existing scorer.
- [ ] Promote one workflow per value loop through the normal gates and settle one value claim per
  loop from independent observation.
- [ ] Add the operator decision queue and obtain explicit approval for each non-Azure adapter.
