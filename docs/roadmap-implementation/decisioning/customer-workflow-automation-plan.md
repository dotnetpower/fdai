# Customer Workflow Automation Delivery Plan implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Waves 0-2 catalog, observation, journal, and approval | implemented | [`test_workflow_catalog.py`](../../../services/core-control-plane/tests/rule_catalog/test_workflow_catalog.py), [`test_orchestrator.py`](../../../services/core-control-plane/tests/core/workflow/test_orchestrator.py), [`test_workflow_approval.py`](../../../services/core-control-plane/tests/delivery/persistence/test_workflow_approval.py) | Structural validation, shadow execution, durable Process state, and approval mechanics have focused coverage. |
| Wave 3 behavior simulation and bounded mutation | not-started | [Wave 3](../../roadmap/decisioning/customer-workflow-automation-plan.md#wave-3---add-bounded-substrate-mutations) | Structural validation exists, but behavior-delta simulation and staging comparison are not implemented. |
| Wave 4 authoring and operating experience | in-progress | [`workflow-builder.structure.ts`](../../../console/src/routes/workflow-builder.structure.ts), [`workflow-builder-control-steps.spec.ts`](../../../console/tests/e2e/workflow-builder-control-steps.spec.ts), [Wave 4](../../roadmap/decisioning/customer-workflow-automation-plan.md#wave-4---complete-the-authoring-and-operating-experience) | Action and all five runtime control-step kinds support authoring, validation, and private drafts. Reviewed catalog proposal and complete operating transitions remain open. |
| Wave 5 scale, SLIs, and automated demotion | not-started | [Wave 5](../../roadmap/decisioning/customer-workflow-automation-plan.md#wave-5---scale-and-hand-over-operations) | No retained distributed-lock, per-scope backpressure, operational SLI, or automated-demotion evidence exists. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance and aligned the current posture with wave evidence. | `current change`; current source and focused tests listed in the scope table. | Complete Waves 3-5 and retain promotion evidence per process. |
| 2026-08-31 | in-progress | Added catalog-backed `WAIT` and `APPROVAL` authoring with required timeout, authority, quorum, anti-self-approval, lossless clone and session recovery, localized guidance, and typed preview. Private drafts remain shadow and non-runnable. | `current change`; [`workflow-builder.model.ts`](../../../console/src/routes/workflow-builder.model.ts), [`workflow-builder.session.ts`](../../../console/src/routes/workflow-builder.session.ts), [`workflow-builder-control-steps.spec.ts`](../../../console/tests/e2e/workflow-builder-control-steps.spec.ts); 72 focused Vitest checks, 12 server contract checks, Console typecheck and build, catalog parity, readable Hangul, punctuation, and desktop, constrained, and mobile Playwright checks passed. | Complete structural authoring in #396 and authoritative operator transitions in #397. |
| 2026-08-31 | in-progress | Added lossless `DECISION`, `PARALLEL`, and `GATE` authoring. The builder rejects duplicate or malformed outcomes and branches, fewer than two parallel branches, unknown or backward failure targets, and gate references absent from the reviewed workflow catalog. Parallel join remains the runtime's fixed fail-closed all-branches behavior. | `current change`; [`workflow-builder.structure.ts`](../../../console/src/routes/workflow-builder.structure.ts), [`workflow-builder.structure.test.ts`](../../../console/src/routes/workflow-builder.structure.test.ts), [`workflow-builder-control-steps.spec.ts`](../../../console/tests/e2e/workflow-builder-control-steps.spec.ts); 81 focused Vitest checks, Console typecheck and build, localization gates, and desktop, constrained, and mobile Playwright checks passed. | Complete principal-scoped authoritative operator transitions in #397. |

### Remaining work

- [ ] Implement a read-only behavior simulator that returns exact targets and expected state deltas,
  then retain parity evidence against a staging execution.
- [x] Completed #396 with lossless `DECISION`, `PARALLEL`, and `GATE` authoring plus focused
  structural, restore, accessibility, typecheck, build, and three-viewport evidence.
- [ ] Complete #397 by rendering principal-scoped authoritative step state and proving guarded
  transition denial for stale, unavailable, unauthorized, self-approval, timeout, and invalid cases.
- [ ] Complete reviewed catalog proposal and deep-link review from the authoring surface without
  granting the draft execution authority.
- [ ] Demonstrate distributed locking, bounded backpressure, process SLIs, and automatic demotion
  on a multi-replica shadow campaign before Wave 5 exits.
