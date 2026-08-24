# Post-Turn Improvement Review implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Eligibility and bounded input contract | implemented | [`test_eligibility.py`](../../../services/core-control-plane/tests/core/learning/test_eligibility.py), [`test_norns_post_turn.py`](../../../services/core-control-plane/tests/agents/test_norns_post_turn.py) | Consent, producer ownership, evidence bounds, and deterministic eligibility have focused coverage. |
| Independent review and governed routing | implemented | [`test_consensus.py`](../../../services/core-control-plane/tests/core/learning/test_consensus.py), [`test_routing.py`](../../../services/core-control-plane/tests/core/learning/test_routing.py) | Exact mixed-family agreement routes only inert memory, skill, or rule-hint drafts. |
| Durable deduplication and runtime wiring | implemented | [`test_service.py`](../../../services/core-control-plane/tests/core/learning/test_service.py), [`test_post_turn_review.py`](../../../services/core-control-plane/tests/runtime/test_post_turn_review.py) | Terminal records and duplicate suppression are tested without delaying the response path. |
| Operational scenario evidence | in-progress | [Verification](../../roadmap/decisioning/post-turn-improvement-review.md#verification) | Focused mechanics exist, but the three end-to-end learning scenarios and deployed multi-service receipts are not retained here. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance. | `current change`; current source and focused tests listed in the scope table. | Retain end-to-end scenario and deployed transport evidence. |

### Remaining work

- [ ] Retain end-to-end evidence for complex-tool recovery, explicit-correction discovery, and
  repeated-procedure rule-hint routing with no active-policy mutation.
- [ ] Retain a deployed Bragi-to-Norns transport and restart receipt proving duplicate delivery
  produces one terminal review record.
