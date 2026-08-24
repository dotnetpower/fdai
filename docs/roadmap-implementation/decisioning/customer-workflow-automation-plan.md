# Customer Workflow Automation Delivery Plan implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Waves 0-2 catalog, observation, journal, and approval | implemented | [`test_workflow_catalog.py`](../../../services/core-control-plane/tests/rule_catalog/test_workflow_catalog.py), [`test_orchestrator.py`](../../../services/core-control-plane/tests/core/workflow/test_orchestrator.py), [`test_workflow_approval.py`](../../../services/core-control-plane/tests/delivery/persistence/test_workflow_approval.py) | Structural validation, shadow execution, durable Process state, and approval mechanics have focused coverage. |
| Wave 3 behavior simulation and bounded mutation | not-started | [Wave 3](../../roadmap/decisioning/customer-workflow-automation-plan.md#wave-3---add-bounded-substrate-mutations) | Structural validation exists, but behavior-delta simulation and staging comparison are not implemented. |
| Wave 4 authoring and operating experience | in-progress | [`workflow-builder.chat.ts`](../../../console/src/routes/workflow-builder.chat.ts), [Wave 4](../../roadmap/decisioning/customer-workflow-automation-plan.md#wave-4---complete-the-authoring-and-operating-experience) | Authoring, validation, and private drafts exist; reviewed catalog proposal and complete operating workflow remain open. |
| Wave 5 scale, SLIs, and automated demotion | not-started | [Wave 5](../../roadmap/decisioning/customer-workflow-automation-plan.md#wave-5---scale-and-hand-over-operations) | No retained distributed-lock, per-scope backpressure, operational SLI, or automated-demotion evidence exists. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance and aligned the current posture with wave evidence. | `current change`; current source and focused tests listed in the scope table. | Complete Waves 3-5 and retain promotion evidence per process. |

### Remaining work

- [ ] Implement a read-only behavior simulator that returns exact targets and expected state deltas,
  then retain parity evidence against a staging execution.
- [ ] Complete reviewed catalog proposal and deep-link review from the authoring surface without
  granting the draft execution authority.
- [ ] Demonstrate distributed locking, bounded backpressure, process SLIs, and automatic demotion
  on a multi-replica shadow campaign before Wave 5 exits.
