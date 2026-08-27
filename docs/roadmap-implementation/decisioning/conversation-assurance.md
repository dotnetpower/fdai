# Conversation Assurance implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Assessment contract and independent reduction | implemented | [`test_assessment.py`](../../../services/core-control-plane/tests/core/conversation_assurance/test_assessment.py), [`test_attribution.py`](../../../services/core-control-plane/tests/core/conversation_assurance/test_attribution.py) | Deterministic checks, independent evaluator reduction, attribution, and hold behavior have focused coverage. |
| Cost-aware runtime policy and lifecycle | implemented | [`test_runtime_policy.py`](../../../services/core-control-plane/tests/core/conversation_assurance/test_runtime_policy.py), [`test_lifecycle.py`](../../../services/core-control-plane/tests/core/conversation_assurance/test_lifecycle.py) | The cascade, candidate lifecycle, fail-closed promotion checks, and rollback mechanics exist in code; this does not prove an operational promotion. |
| Qualification contract and reduction runner | implemented | [`test_quality_scorecard.py`](../../../services/core-control-plane/tests/core/conversation_assurance/test_quality_scorecard.py), [`test_quality_qualification.py`](../../../services/core-control-plane/tests/core/conversation_assurance/test_quality_qualification.py), [`test_chatops_quality_qualification_cli.py`](../../../tests/integration/scripts/test_chatops_quality_qualification_cli.py) | The runner validates exact 50-item runs, derives hard caps from raw evidence state, selects the worst run, and emits a stable no-authority scorecard. |
| Hidden corpus manifest contract | implemented | [`chatops_quality_corpus.py`](../../../scripts/evaluation/chatops_quality_corpus.py), [`chatops_quality_corpus_manifest.py`](../../../scripts/evaluation/chatops_quality_corpus_manifest.py), [`test_chatops_quality_corpus_manifest.py`](../../../tests/integration/scripts/test_chatops_quality_corpus_manifest.py) | Repository tooling validates content commitments, bilingual and subset coverage, real multi-turn groups, all 50 rubric floors, and review protocol without loading hidden prompts or labels. No restricted corpus artifact has been retained by this change. |
| Completed-turn qualification observations | in-progress | [`quality_observation_models.py`](../../../services/core-control-plane/src/fdai/core/conversation_assurance/quality_observation_models.py), [`quality_observations.py`](../../../services/core-control-plane/src/fdai/core/conversation_assurance/quality_observations.py), [`test_quality_observations.py`](../../../services/core-control-plane/tests/core/conversation_assurance/test_quality_observations.py), [`test_quality_observation_contributions.py`](../../../services/core-control-plane/tests/core/conversation_assurance/test_quality_observation_contributions.py) | The content-free envelope exposes all 50 items and six dimension slots, hashes runtime references, maps only supported completed-turn evidence, and accepts contract-bound evidence-owner contributions without conflicts or overwrite. Planning, SRE, action, orchestration, context aggregate, channel, latency, and production adapters remain open. |
| Context and locale deterministic scorecard adapters | implemented | [`context_locale_scorecard.py`](../../../services/core-control-plane/src/fdai/core/conversation_assurance/context_locale_scorecard.py), [`test_context_locale_scorecard.py`](../../../services/core-control-plane/tests/core/conversation_assurance/test_context_locale_scorecard.py) | Items 41-45 now convert locale parity, persistence fidelity, personalization accuracy, context isolation, and screen awareness into content-free measurements with replayable provenance and fail-closed hard-cap triggers. |
| Qualification campaign evidence | in-progress | [`conversation-assurance-ledger.py`](../../../scripts/quality/conversation-assurance-ledger.py), [Issue #63](https://github.com/dotnetpower/fdai/issues/63), [Issue #299](https://github.com/dotnetpower/fdai/issues/299), [Issue #300](https://github.com/dotnetpower/fdai/issues/300) | The complete bilingual hidden cohort, three qualifying runs, live evidence, and soak records have not been retained. |
| Operator disputes and ontology adequacy review | implemented | [`test_learning.py`](../../../services/core-control-plane/tests/core/conversation_assurance/test_learning.py), [`test_state_store_ontology_adequacy.py`](../../../services/core-control-plane/tests/delivery/persistence/test_state_store_ontology_adequacy.py) | Disputes and reproduced adequacy gaps create bounded review evidence without changing execution authority. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-28 | implemented | Added deterministic adapters for scorecard items 41-45 and kept locale, persistence, personalization, isolation, and screen evidence content-free, replayable, and fail-closed under the existing quality contract. | `current change`; [`context_locale_scorecard.py`](../../../services/core-control-plane/src/fdai/core/conversation_assurance/context_locale_scorecard.py); [`test_context_locale_scorecard.py`](../../../services/core-control-plane/tests/core/conversation_assurance/test_context_locale_scorecard.py); focused scorecard, persistence, answer-plan, lifecycle, and Deck isolation checks plus task-scoped Ruff, strict mypy, translation, and roadmap verification. | Retain one governed 50-item bilingual qualification run on a pinned revision before raising this work from implemented to validated. |
| 2026-08-14 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance. | `current change`; current source and focused tests listed in the scope table. | Retain the qualification, blind-replay, and operational promotion or rollback evidence described below. |
| 2026-08-27 | implemented | Added the source-bound 50-item qualification reducer and deterministic scorecard CLI. The reducer derives hard caps from evidence instead of trusting submitted cap decisions and grants no qualification authority. | `current change`; `quality_qualification.py`, `chatops-quality-qualification.py`, and focused unit and CLI tests (`25 passed`). | Freeze the hidden corpus, connect measured observations, and retain three complete qualifying runs plus live and soak evidence under Issues #63 and #299. |
| 2026-08-27 | implemented | Added a content-free hidden corpus manifest contract and CLI validator. It verifies commitments, balanced locale and subset coverage, real multi-turn groups, all 50 rubric floors, and the predeclared statistical and prose-review protocol without reading hidden content. | `current change`; `chatops_quality_corpus.py`, `chatops_quality_corpus_manifest.py`, and focused manifest tests (`16 passed`). | Retain the restricted 500-turn artifact and its independent labels under Issue #300; the validator alone is not qualification evidence. |
| 2026-08-27 | in-progress | Added the shared completed-turn observation envelope and the first evidence-owned adapters. Unsupported dimensions remain explicitly unavailable and raw runtime references are replaced by content commitments. | `current change`; `quality_observation_models.py`, `quality_observations.py`, and focused observation tests (`12 passed`). | Add the remaining item 1-35 and 41-45 owner adapters and aggregate them with channel, latency, and production measurements under Issue #297. |
| 2026-08-27 | in-progress | Added the contract-bound contribution seam for independent evidence owners. Each contribution must match the fixed workstream and metric, cite evidence commitments, and target the same case; duplicate dimensions and measured-slot overwrite fail closed. | `current change`; observation and contribution tests (`16 passed`); Ruff and strict mypy. | Implement each remaining owner-specific measurement adapter and supply its contributions under Issue #297. |

### Remaining work

- [x] Generate a stable content-addressed scorecard from exact 50-item runs, apply the worst of at
   least three runs, and fail `--require-qualified` when any contract requirement is unmet. Focused
   unit and CLI tests passed 25 cases.
- [x] Validate a repository-safe hidden corpus manifest for 500 balanced turns, required subsets,
   real multi-turn groups, 50 rubric observation floors, and predeclared review controls without
   exposing prompts or labels. Focused manifest tests passed 16 cases.
- [ ] Populate every required dimension for items 1-35 and 41-45 from its authoritative owner. The
   completed-turn adapter currently maps only items 6, 9, 10, 11, 13, and 42 and leaves all other
   dimensions explicitly unavailable.
- [ ] Run the complete 50-item bilingual qualification scorecard on one pinned revision and retain
   per-item results that prove every hard-check and semantic-rubric threshold.
- [ ] Retain a blind holdout replay showing a statistically supported improvement with zero hard
   escapes and no locale regression before reporting a promoted policy.
- [ ] Exercise one governed automatic rollback after a measured regression and retain the policy
   transition, restored immutable version, and audit receipts.
