# Post-Turn Improvement Review implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Eligibility and bounded input contract | implemented | [`test_eligibility.py`](../../../services/core-control-plane/tests/core/learning/test_eligibility.py), [`test_norns_post_turn.py`](../../../services/core-control-plane/tests/agents/test_norns_post_turn.py) | Consent, producer ownership, evidence bounds, and deterministic eligibility have focused coverage. |
| Independent review and governed routing | implemented | [`test_consensus.py`](../../../services/core-control-plane/tests/core/learning/test_consensus.py), [`test_routing.py`](../../../services/core-control-plane/tests/core/learning/test_routing.py), [`test_workshop.py`](../../../services/core-control-plane/tests/core/skills/test_workshop.py), [`test_postgres_skill_proposal.py`](../../../services/core-control-plane/tests/persistence/test_postgres_skill_proposal.py) | Exact mixed-family agreement routes only inert memory, skill, or rule-hint drafts. Skill drafts bind canonical verified evidence references into proposal identity, durable storage, and audit events. |
| Durable deduplication and runtime wiring | implemented | [`test_service.py`](../../../services/core-control-plane/tests/core/learning/test_service.py), [`test_post_turn_review.py`](../../../services/core-control-plane/tests/runtime/test_post_turn_review.py) | Terminal records and duplicate suppression are tested without delaying the response path. |
| Operational scenario evidence | in-progress | [Verification](../../roadmap/decisioning/post-turn-improvement-review.md#verification) | Focused mechanics exist, but the three end-to-end learning scenarios and deployed multi-service receipts are not retained here. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-12 | implemented | Added the legacy Alembic compatibility migration for skill proposal evidence and advanced every service-adoption baseline to the same canonical legacy head. | `current change`; `20260912_0090_skill_proposal_evidence.py`; service-migration inventory checks (`67 passed`). | No schema-lineage work remains for evidence references; deployed duplicate-delivery evidence remains open. |
| 2026-09-12 | implemented | Extracted and tested the production bootstrap binding that places Norns post-turn rule hints behind the current discovery-activation publication gate. | `current change`; focused bootstrap binding checks (`2 passed`). | Retain the full Bragi envelope scenario and deployed duplicate-delivery receipt. |
| 2026-09-12 | implemented | Bound verified post-turn evidence references into runtime skill draft identity, Operator-owned PostgreSQL persistence, restart readback, and audit metadata without activating the skill. | `current change`; migration `operator_skill_proposal_evidence_20260912`; focused skill, routing, and PostgreSQL checks (`12 passed`). | Retain bootstrap-composed scenario evidence and deployed duplicate-delivery receipts. |
| 2026-08-14 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance. | `current change`; current source and focused tests listed in the scope table. | Retain end-to-end scenario and deployed transport evidence. |

### Remaining work

- [ ] Retain end-to-end evidence for complex-tool recovery, explicit-correction discovery, and
  repeated-procedure rule-hint routing with no active-policy mutation.
- [ ] Retain a deployed Bragi-to-Norns transport and restart receipt proving duplicate delivery
  produces one terminal review record.
