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
> HIL bindings, production Forseti proposal-source composition, the Heimdall-owned verified
> independent effect observer, the protected-runner drill, independent closure, and the full
> recurrence window remain outstanding. The Core runtime now stores an exact kinetic safety receipt
> before every Thor-owned executor when a proposal exists, and preserves the legacy path when it does
> not.

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| P1-P7 operational-planning core | implemented | `services/core-control-plane/src/fdai/core/operational_planning/` and focused planning tests | Planning remains A0 and reuses existing Process and authority paths. |
| Production graph evidence and scale-out executor bindings | implemented | `services/core-control-plane/src/fdai/delivery/azure/` and focused composition/delivery tests | Code presence and tests don't count as live outcome evidence. |
| Argument-bound kinetic proposal production and verdict lineage | implemented | `services/core-control-plane/src/fdai/core/operational_planning/kinetic_proposal.py`, `services/core-control-plane/src/fdai/delivery/kinetic_proposal.py`, `services/core-control-plane/src/fdai/agents/forseti.py`, `services/core-control-plane/src/fdai/agents/thor.py`, and focused producer and agent tests | The delivery-owned producer accepts only a complete plan plus an existing exact V2 plan. Forseti resolves it through an optional source and preserves it on the existing Verdict without changing quorum, mode, approval, or execution authority. |
| Exact kinetic handoff and independent effect-observation runtime binding | in-progress | `services/core-control-plane/src/fdai/core/operational_planning/kinetic_safety.py`, `services/core-control-plane/src/fdai/delivery/kinetic_safety.py`, `services/core-control-plane/src/fdai/delivery/reconciliation_artifacts.py`, `services/core-control-plane/src/fdai/runtime/control_loop.py`, `config/ohl-scale-out-evidence.json`, and focused dispatch, HIL, artifact, and runtime tests (`119 passed`) | Core resolves an indexed existing proposal, revalidates its OperationalPlan identity and Process, selection, correlation, target, ActionType, and plan lineage, then stores its exact V2 plan before every Thor-owned executor. Missing proposals preserve legacy behavior, while malformed, ambiguous, orphaned, or substituted evidence blocks dispatch. Production Forseti source composition and the Heimdall-owned verified observer remain unbound. |
| Independent-service HIL binding | in-progress | `config/ohl-scale-out-evidence.json` and the deployed Core/Operator environment contract | The service roots must bind the HIL channel and callback signing secret before approval can park and resolve the action. |
| OHL Lane F live evidence | in-progress | `docs/runbooks/ohl-scale-out-evidence.md` | Protected execution, independent closure, 100 samples, and the 14-day recurrence window remain open. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
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
- [ ] Bind the proposal source in production Forseti composition and a Heimdall-owned verified
  independent effect observer, then retain governed end-to-end evidence without substituting an
  executor or provider receipt for the observed outcome.
- [ ] Bind and verify the Core HIL channel plus Operator callback signing secret so a distinct human
  approval parks, resolves, and resumes one `ops.scale-out` proposal.
- [ ] Complete the protected-runner drill and record independent graph closure, 100 live-shadow
  samples, zero policy escapes, rollback/cleanup, and the full 14-day recurrence window.
