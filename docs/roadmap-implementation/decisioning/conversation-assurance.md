# Conversation Assurance implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Assessment contract and independent reduction | implemented | [`test_assessment.py`](../../../services/core-control-plane/tests/core/conversation_assurance/test_assessment.py), [`test_attribution.py`](../../../services/core-control-plane/tests/core/conversation_assurance/test_attribution.py) | Deterministic checks, independent evaluator reduction, attribution, and hold behavior have focused coverage. |
| Cost-aware runtime policy and lifecycle | implemented | [`test_runtime_policy.py`](../../../services/core-control-plane/tests/core/conversation_assurance/test_runtime_policy.py), [`test_lifecycle.py`](../../../services/core-control-plane/tests/core/conversation_assurance/test_lifecycle.py) | The cascade, candidate lifecycle, fail-closed promotion checks, and rollback mechanics exist in code; this does not prove an operational promotion. |
| Qualification scorecard and campaign ledger | in-progress | [`test_quality_scorecard.py`](../../../services/core-control-plane/tests/core/conversation_assurance/test_quality_scorecard.py), [`conversation-assurance-ledger.py`](../../../scripts/quality/conversation-assurance-ledger.py) | The scorecard and bounded result format are implemented, but the complete bilingual qualification cohort has not been retained as governed evidence. |
| Context and locale deterministic scorecard adapters | implemented | [`context_locale_scorecard.py`](../../../services/core-control-plane/src/fdai/core/conversation_assurance/context_locale_scorecard.py), [`test_context_locale_scorecard.py`](../../../services/core-control-plane/tests/core/conversation_assurance/test_context_locale_scorecard.py) | Items 41-45 now convert locale parity, persistence fidelity, personalization accuracy, context isolation, and screen awareness into content-free measurements with replayable provenance and fail-closed hard-cap triggers. |
| Operator disputes and ontology adequacy review | implemented | [`test_learning.py`](../../../services/core-control-plane/tests/core/conversation_assurance/test_learning.py), [`test_state_store_ontology_adequacy.py`](../../../services/core-control-plane/tests/delivery/persistence/test_state_store_ontology_adequacy.py) | Disputes and reproduced adequacy gaps create bounded review evidence without changing execution authority. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-28 | implemented | Added deterministic adapters for scorecard items 41-45 and kept locale, persistence, personalization, isolation, and screen evidence content-free, replayable, and fail-closed under the existing quality contract. | `current change`; [`context_locale_scorecard.py`](../../../services/core-control-plane/src/fdai/core/conversation_assurance/context_locale_scorecard.py); [`test_context_locale_scorecard.py`](../../../services/core-control-plane/tests/core/conversation_assurance/test_context_locale_scorecard.py); focused scorecard, persistence, answer-plan, lifecycle, and Deck isolation checks plus task-scoped Ruff, strict mypy, translation, and roadmap verification. | Retain one governed 50-item bilingual qualification run on a pinned revision before raising this work from implemented to validated. |
| 2026-08-14 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance. | `current change`; current source and focused tests listed in the scope table. | Retain the qualification, blind-replay, and operational promotion or rollback evidence described below. |

### Remaining work

- [ ] Run the complete 50-item bilingual qualification scorecard on one pinned revision and retain
   per-item results that prove every hard-check and semantic-rubric threshold.
- [ ] Retain a blind holdout replay showing a statistically supported improvement with zero hard
   escapes and no locale regression before reporting a promoted policy.
- [ ] Exercise one governed automatic rollback after a measured regression and retain the policy
   transition, restored immutable version, and audit receipts.
