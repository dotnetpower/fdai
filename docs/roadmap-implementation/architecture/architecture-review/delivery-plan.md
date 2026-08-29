# Ontology-Grounded ARB Delivery Plan implementation ledger

This ledger tracks the dependency-ordered delivery campaign and keeps observed implementation
evidence separate from the target sequence.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| ARB-1 Ontology truth | in-progress | `core/impact_analysis/change_assessment.py`; `agents/forseti.py`; `tests/core/impact_analysis/test_change_assessment.py`; `tests/agents/test_change_management_chain.py`; existing operating-context foundations | Planned-change assessment now consumes a typed graph evidence receipt and accepted blocker contracts now require a current risk or exception record. Runtime intent projection and exact `OperationalContextSnapshot` receipt sourcing remain incomplete. |
| ARB-2 Agent evidence loop | not-started | Existing pantheon and typed topics | No complete observation-mode ARB vertical slice is wired. |
| ARB-3 Decision authority | not-started | Generic workflow approval and audit foundations | No receipt binds the ARB case, evidence, conditions, and approvals. |
| ARB-4 Effect closure | in-progress | Shared operational lineage and independent observation foundations | The generic chain exists, but ARB decisions are not connected to it end to end. |
| ARB-5 Learning and rollout | not-started | Shared Muninn, Norns, Mimir, and promotion foundations | No ARB-specific retained cohort or promotion evidence exists. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-29 | in-progress | Recorded the new typed planned-change graph evidence receipt and accepted blocker contract checks while keeping exact context sourcing and immutable decision receipts open. | `current change`; `services/core-control-plane/src/fdai/core/impact_analysis/change_assessment.py`, `services/core-control-plane/src/fdai/core/architecture_review/readiness.py`; focused ARB impact and readiness checks in the preceding owner batches. | Finish ARB-1 exact context sourcing, then continue to ARB-2 through ARB-5 in order. |
| 2026-08-24 | in-progress | Defined five dependency-ordered work packages and an observation-mode first vertical slice. | `current change`; owner document, paired translation, current source evidence, and focused documentation checks. | Deliver ARB-1 through ARB-5 in order and retain executable evidence at each exit. |

### Remaining work

- [ ] Complete ARB-1 with one exact planned-change context that fails closed on stale, mixed,
  incomplete, conflicting, and truncated ontology evidence.
- [ ] Complete ARB-2 with one replayable observation-mode trace from Huginn through the derived
  review projection and no direct agent calls.
- [ ] Complete ARB-3 with an immutable decision receipt and provider-verified evidence.
- [ ] Complete ARB-4 with independent multi-effect closure and a recovery fixture.
- [ ] Complete ARB-5 with a pinned observation cohort and independently reviewed promotion
  evidence showing zero policy escapes.
