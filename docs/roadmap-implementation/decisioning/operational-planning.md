# Operational Planning implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Migrated implementation notes

> **Implementation status:** P1-P4 core paths are implemented. Canonical releases pin function
> declarations; authorized invocation emits replay-stable receipts; operational planning applies
> hard constraints before Pareto pruning and weighted selection; and ordered planning phases append
> to the existing Process journal. Forseti can enrich the existing Cost and Capacity topics through
> an optional coordinator. A programmatic simulator runs exact reviewed sources through the bounded
> pipeline sandbox and treats timeout or malformed output as unscorable. P5 adds a read-only Twin
> adapter, exact selected-option MutationPlan compilation, and independent ResponseOutcome closure.
> P6 adds a strict, read-only Planning Room projection inside the existing Process detail route.
> P7 adds a durable Process recorder, a shadow-only planning Workflow, a nine-dimension frozen
> scenario manifest with eight verified dimensions and one explicit release-evidence proxy,
> deterministic constitutional constraint checks, and conditional production
> runtime binding. The runtime binds planning only when the exact ontology release, operational
> context, Process store, active effect-model reader, and causal verifier are available. Staging
> partial-execution proof and live graph shadow measurement remain release evidence, not completed
> live claims. Production graph evidence and the development `ops.scale-out` VM Scale Set executor
> bindings are implemented and covered by focused tests. Independent Core and Operator service
> HIL bindings, the Heimdall-owned verified independent effect observer, the protected-runner drill,
> independent closure, and the full recurrence window remain outstanding. Production Forseti
> prospective finalization, Muninn materialization, Saga sealing, and predispatch readiness are
> implemented.

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| P1-P7 operational-planning core | implemented | `services/core-control-plane/src/fdai/core/operational_planning/` and focused planning tests | Planning remains A0 and reuses existing Process and authority paths. |
| Production graph evidence and scale-out executor bindings | implemented | `services/core-control-plane/src/fdai/delivery/azure/` and focused composition/delivery tests | Code presence and tests don't count as live outcome evidence. |
| Argument-bound prospective lineage and verdict handoff | implemented | `core/decision_case/`; `core/operational_planning/prospective_lineage.py`; `delivery/prospective_lineage.py`; `agents/{forseti,muninn,saga,thor}.py`; focused finalization, materialization, and agent-chain tests | Typed arguments participate in DecisionCase identity. Forseti publishes the finalized content-addressed ProspectiveLineage before Verdict without changing quorum, mode, approval, or execution authority. |
| Exact kinetic handoff and independent effect-observation runtime binding | in-progress | `core/operational_planning/kinetic_safety.py`; `delivery/{kinetic_safety,reconciliation_artifacts,prospective_lineage}.py`; `runtime/{control_loop,bootstrap_pantheon}.py`; focused dispatch, HIL, artifact, and runtime tests | Core requires matching Muninn materialization and Saga sealing before a present proposal reaches any Thor-owned executor. The Heimdall-owned verified observer and governed runtime evidence remain open. |
| Independent-service HIL binding | in-progress | `config/ohl-scale-out-evidence.json` and the deployed Core/Operator environment contract | The service roots must bind the HIL channel and callback signing secret before approval can park and resolve the action. |
| OHL Lane F live evidence | in-progress | `docs/runbooks/ohl-scale-out-evidence.md` | Protected execution, independent closure, 100 samples, and the 14-day recurrence window remain open. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-30 | implemented | Bound canonical typed PlanCandidate and ActionOption arguments into DecisionCase identity, finalized Odin's winner before Process recording, and added Forseti ProspectiveLineage publication, Muninn exact-subgraph materialization, Saga digest sealing, Thor preservation, and predispatch readiness. Reconciliation remains the only observed multi-effect closure. | `current change`; focused planning, prospective materialization, agent-chain, kinetic readiness, and observed-lineage checks. | Bind the verified independent observer and retain a pinned prospective-to-observed replay. |
| 2026-08-13 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance and exposed the independent-service HIL binding residual. | current change; `services/core-control-plane/tests/scenarios/operational-planning/test_manifest.py` reports 7 passed. | Bind HIL in both service roots, deploy the exact revision, and complete the live evidence campaign. |
| 2026-08-14 | in-progress | Exposed the missing exact-plan writer and verified independent effect observer as separate Lane F runtime residuals. | `current change`; the Lane F contract, runbook gate, artifact-store tests, and manifest tests. | Bind both sources without reconstructing plans or substituting executor/provider receipts. |
| 2026-08-14 | implemented | Added an authority-free, argument-bound kinetic proposal contract and preserved valid proposals through Thor's durable ActionRun. | `current change`; focused kinetic-proposal, Thor dispatch, persistence, and role-invariant checks. | Add the Forseti-owned producer and Core pre-dispatch consumer before removing the runtime residual. |
| 2026-08-14 | implemented | Added delivery-owned exact proposal production and optional Forseti source resolution on both resolved and human-review arbitration verdicts. Missing proposals preserve the legacy verdict, while source failure, corruption, or lineage substitution lowers the verdict to deny. | `current change`; `kinetic_proposal.py`, `forseti.py`, `test_kinetic_proposal.py`, `test_decision_case_e2e.py`, and focused producer, Forseti, Thor, factory, and framework checks. | Bind the source in production composition, persist the pre-dispatch kinetic safety receipt, and retain governed live evidence. |
| 2026-08-14 | implemented | Bound an exact-proposal kinetic safety writer before every Core Thor executor without reconstructing an Action or plan. Missing proposals remain a legacy no-op; malformed, conflicting, orphaned, late, or substituted evidence returns an invariant rejection before provider dispatch. | `current change`; `core/operational_planning/kinetic_safety.py`, `delivery/kinetic_safety.py`, `delivery/kinetic_proposal.py`, `runtime/control_loop.py`, and focused dispatch, HIL, artifact, proposal, and runtime checks passed 115 cases. | Bind the proposal source in production Forseti composition, add the verified independent observer, and retain governed live evidence. |
| 2026-08-14 | implemented | Revalidated the durable OperationalPlan identity and its Process, selected option, correlation, target, selected ActionType, and plan lineage against the internally valid proposal body during dispatch-time resolution. | `current change`; `delivery/kinetic_proposal.py`, adversarial cross-record substitution tests, and the focused kinetic suite passed 119 cases. | Bind the proposal source in production Forseti composition, add the verified independent observer, and retain governed live evidence. |

### Remaining work

- [x] Produce `KineticActionProposal` only from a complete operational plan, resolve it through
  Forseti's optional source on the existing typed Verdict path, and prove missing proposals leave
  legacy Actions unchanged.
- [x] Persist an existing proposal's exact V2 plan before every Core Thor executor and prove
  missing proposals preserve legacy behavior while malformed or substituted evidence blocks
  dispatch.
- [x] Bind production Forseti prospective finalization, Muninn materialization, Saga sealing, and
  predispatch readiness without reconstructing a plan from an Action.
- [ ] Bind a Heimdall-owned verified independent effect observer, then retain governed end-to-end
  evidence without substituting an executor or provider receipt for the observed outcome.
- [ ] Bind and verify the Core HIL channel plus Operator callback signing secret so a distinct human
  approval parks, resolves, and resumes one `ops.scale-out` proposal.
- [ ] Complete the protected-runner drill and record independent graph closure, 100 live-shadow
  samples, zero policy escapes, rollback/cleanup, and the full 14-day recurrence window.
