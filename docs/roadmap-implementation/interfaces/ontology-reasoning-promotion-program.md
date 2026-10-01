# Ontology Reasoning Promotion Program implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

The [owner design](../../roadmap/interfaces/ontology-reasoning-promotion-program.md) was recorded
on 2026-10-01 after an independent critique, and its decisions await Owner approval. No package is
implemented for production: the shadow runner isn't wired into the production turn, the direction
readers run only locally, and answers still come from the current path. The local compiled path,
its variance sampling, and the closed ambiguity reader exist and await live rounds, as the
[compiler ledger](ontology-reasoning-compiler.md) records. The open items below moved here from the
compiler ledger with their progress notes; their earlier history stays in that ledger.

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| P0 Model evidence view | implemented | `current change`; [`model_evidence_view.py`](../../../services/core-control-plane/src/fdai/core/conversation/model_evidence_view.py); [`semantic_runtime.py`](../../../services/core-control-plane/src/fdai/core/conversation/semantic_runtime.py); [`test_model_evidence_view.py`](../../../services/core-control-plane/tests/conversation/test_model_evidence_view.py); [`test_adaptive_runtime.py`](../../../services/core-control-plane/tests/conversation/test_adaptive_runtime.py); focused checks: `.venv/bin/python -m pytest -q --no-cov services/core-control-plane/tests/conversation/test_model_evidence_view.py services/core-control-plane/tests/conversation/test_adaptive_runtime.py`, `.venv/bin/python -m pytest -q --no-cov services/core-control-plane/tests/conversation` | Builder and adaptive evidence boundary are local and enforced. Owner approval for model families that may read the view remains open; proposed default is no model family reads it until approved. |
| P1 Production shadow wiring | not-started | Local compiled answers and decision events only | Carry, reservation, linked records, and non-interference |
| P2 Direction readers | not-started | The majority protocol runs locally | Production composition and the latency and cost receipt |
| P3 Verified answer authoring | implemented | `current change`; [`answer_claims.py`](../../../packages/service-contracts/src/fdai_service_contracts/answer_claims.py); [`semantic_reasoning_claims.py`](../../../services/core-control-plane/src/fdai/core/conversation/semantic_reasoning_claims.py); [`verified_answer_authoring.py`](../../../services/core-control-plane/src/fdai/core/conversation/verified_answer_authoring.py); [`test_answer_claims.py`](../../../packages/service-contracts/tests/test_answer_claims.py); [`test_semantic_reasoning_claims.py`](../../../services/core-control-plane/tests/conversation/test_semantic_reasoning_claims.py); [`test_verified_answer_authoring.py`](../../../services/core-control-plane/tests/conversation/test_verified_answer_authoring.py); focused checks: `.venv/bin/python -m pytest -q --no-cov packages/service-contracts/tests`, `.venv/bin/python -m pytest -q --no-cov services/core-control-plane/tests/conversation` | Local proposition contract, deterministic V-CLAIM adversarial checks, and default-off author/reviewer ports are implemented. Live R8 holdout evidence remains open. |
| P4 Validation program | not-started | Session-local rounds are summarized, not retained | Baselines, per-wave validation, and final evidence |
| P5 Promotion and removal | not-started | Design only | Per-family promotion and parity receipts, then R10 |
| P6 Secret detection decision | implemented | The [decision](../../roadmap/interfaces/ontology-reasoning-promotion-program.md#p6-secret-detection-decision) and the encoded-shape suite in `test_semantic_reasoning_masking.py` | Defense in depth; revisable by the Owner |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-10-01 | in-progress | Recorded the design after an independent critique, moved fifteen open items here from the compiler ledger with their progress notes, and added the model evidence view, decision approval, and document split items. | `current change`; `docs/roadmap/interfaces/ontology-reasoning-promotion-program.md`; `docs/roadmap/interfaces/ontology-reasoning-promotion-program-ko.md` | Wave 0: R0 baselines, the P6 decision, and P0. |
| 2026-10-01 | in-progress | Recorded the P6 decision: pattern-based secret detection stays as defense in depth for the in-tenant model deployment, adopted under the Owner's instruction to implement all waves and revisable by the Owner. The encoded-shape regression suite passes against it. | `current change`; `docs/roadmap/interfaces/ontology-reasoning-promotion-program.md`; `docs/roadmap/interfaces/ontology-reasoning-promotion-program-ko.md`; `pytest -q services/core-control-plane/tests/conversation/test_semantic_reasoning_masking.py` passed (262) | Wave 0: P0 and the R0 baselines. |
| 2026-10-01 | implemented | Implemented the local P0 model evidence view builder and routed adaptive evidence reads through it instead of raw query tables. The view keeps only allowlisted cells, restricts link evidence to the reviewed link-evidence allowlist, suppresses hidden endpoints, and excludes provider bodies, handle metadata, and retained snapshot cells. | `current change`; `services/core-control-plane/src/fdai/core/conversation/model_evidence_view.py`; `services/core-control-plane/src/fdai/core/conversation/semantic_runtime.py`; `services/core-control-plane/tests/conversation/test_model_evidence_view.py`; `services/core-control-plane/tests/conversation/test_adaptive_runtime.py`; focused checks listed in the P0 scope row pass. | Owner approval for model families that may read the view remains open. Proposed default: no model family reads the view until explicitly approved; the builder exists and is enforced at the adaptive evidence boundary. |
| 2026-10-01 | implemented | Implemented the local P3 verified-answer authoring foundation: the shared versioned proposition contract moved to service contracts, V-CLAIM checks the owner-design proposition fields deterministically, and default-off author/reviewer ports enforce independent model families, one regeneration, and fail-closed holds. | `current change`; `packages/service-contracts/src/fdai_service_contracts/answer_claims.py`; `packages/service-contracts/src/fdai_service_contracts/__init__.py`; `services/core-control-plane/src/fdai/core/conversation/semantic_reasoning_claims.py`; `services/core-control-plane/src/fdai/core/conversation/verified_answer_authoring.py`; `packages/service-contracts/tests/test_answer_claims.py`; `services/core-control-plane/tests/conversation/test_semantic_reasoning_claims.py`; `services/core-control-plane/tests/conversation/test_verified_answer_authoring.py`; focused checks listed in the P3 scope row pass. | Production composition remains default-off, and the live R8 V-CLAIM holdout exit remains open. |

### Remaining work

- [ ] Complete R0: lock a holdout beside the committed bilingual cohort and fixture graph, keep
  function binding production-faithful in the harness, and record baseline L1, L2, and Azure SRE
  Agent parity receipts. The cohort, two locked holdouts, the fixture graph, and L2 tests exist;
  retained L1 receipts and the parity baseline do not.
- [ ] Configure the direction reader's reasoning-model deployment in production composition, with
  its latency and cost measured per directional turn.
- [ ] Complete R3 through R8 with the exit evidence in the owner delivery-round table, including
  shadow wiring with a turn reservation, per-type holdout accuracy, reviewed trait and path grammar
  catalog changes, traversal root lineage, the location property, the link-evidence allowlist, a
  result-handle threat review, an answer author that emits claims, and V-CLAIM with zero escapes.
- [ ] Wire the shadow runner into the production semantic turn behind a turn budget reservation
  with telemetry export, and record a shadow disposition for every turn with unchanged answers.
  The form must first travel in the judgment call, and the wiring must meet the conditions in the
  owner design's production shadow wiring paragraph; fresh anchor-read cutoffs and structured
  cancellation are done.
- [x] Add an answer author that emits claims, a full proposition contract for V-CLAIM, and an
  independent entailment review that regenerates or holds an answer, with zero escapes on an
  adversarial claim suite. Evidence: `current change`; `test_answer_claims.py`,
  `test_semantic_reasoning_claims.py`, and `test_verified_answer_authoring.py` pass locally.
  The live R8 holdout with zero V-CLAIM escapes remains open below.
- [ ] Complete the R8 live holdout for verified answer authoring: zero V-CLAIM escapes and zero
  entailment-review escapes on the R8 holdout under approved model-family bindings.
- [ ] Hold zero released wrong answers, a compiled and released answer whose executed rows differ
  from the gold rows, in every L1 round. The review-tightening row recorded three before its fixes
  and zero after them, and the two-reader review row recorded one from concept grounding; keep the
  metric in every round and treat any occurrence as a defect. Since the kind-grounding row the metric
  also counts a released answer where the gold expects none and a function answer whose calls differ
  from the gold form's compile, which earlier status-only counts missed.
- [ ] Recover live L1 coverage from 84 of 120 runs toward the 108 recorded before the review, without
  a released over-compilation: schema goals given type filters of another domain, restating words
  such as declared that the extractor names as restrictions, extractor quotes that reach past the
  named thing, reach words left out of relation cues, and particles quoted inside resource names.
  Exit: at least 105 of 120 across two repeated rounds with zero released over-compilation.
- [x] Record an Owner decision that either replaces best-effort pattern detection of secrets in
  operator-typed model input with a reviewed detector, or accepts it as defense in depth for the
  in-tenant model deployment. Exit: the decision is linked here, and the encoded-shape regression
  suite in `test_semantic_reasoning_masking.py` passes against the chosen detector. Evidence: the
  [P6 decision](../../roadmap/interfaces/ontology-reasoning-promotion-program.md#p6-secret-detection-decision)
  keeps the patterns as defense in depth, adopted under the Owner's 2026-10-01 instruction to
  implement all waves and revisable by the Owner, and the suite passed (262 tests), in the
  2026-10-01 P6 row.
- [ ] Complete R9: record one promotion receipt and one SRE Agent parity receipt per operation
  family, and retire frame and plan prompts only for promoted families.
- [ ] Complete R10: remove lexical re-derivation and template renderers from promoted paths after
  replay equivalence and one stable rollback release.
- [ ] Before promoting any operation family in R9, record the coverage-lane exits that gate it in
  the [coverage ledger](ontology-reasoning-coverage.md).
- [ ] Verify coverage on the compiled plan instead of only the judgment: every hard, measure, group,
  quantity, or relation role that the blind reading names maps to a plan predicate, measure, or path,
  or the turn returns a typed unknown. This complements the answer-kind hold above. Exit: the traced
  per-group count and region questions never release a list or candidate answer.
  Progress 2026-09-30: a current-path plan that reads only a filtered list is now held whenever a
  parsed form reading asks more than such a list, whatever builder produced it, and a stated grouping
  or relation in the blind reading holds a plan without a grouped aggregate or beyond a list as
  `semantic_plan_constraint_uncovered`; `test_semantic_plan_coverage.py` and
  `test_a_stated_grouping_or_relation_holds_a_plan_that_reads_only_a_list` pass. A restriction
  such as a region is checked only through the form reading, and the exit needs a live traced round.
- [ ] Treat a clarification or ambiguous judgment as terminal on the current path: the frame model may
  not reinterpret the utterance without the judgment and its coverage review. Exit: the traced
  incident and ordinal follow-up questions return a clarification, never a verified unrelated list.
  Progress 2026-09-30: `test_an_ambiguous_judgment_keeps_its_clarification_unless_one_reading_is_found`
  shows that no frame call follows an ambiguous judgment and that only the closed ambiguity reader's
  `one` verdict lets a released reading answer instead; the traced live questions remain.
- [ ] Reduce single-sample release variance in the local compiled path: when a compilable reading
  fails release only through a competing reading, an unfaithful review, or a review repair that drops
  an operand, take one bounded second form sample before the turn falls back. Exit: the deallocated
  VM, recent change, and containing-group questions answer in three repeated 20-question rounds.
  Progress 2026-09-30: the bounded second sample is implemented; the three-round exit remains open.
  Progress 2026-09-30: a direction majority, quote relocation, measure-cue normalization, one
  re-extraction, and resampling of an unmatched concept are implemented; rounds T8 to T11 still
  held about five answerable questions each on form-only failures, so the exit remains open.
- [ ] Resolve a judgment clarification that disagrees with a released reading through a closed
  ambiguity reader of a third model family instead of letting either reader decide alone. Exit: the
  traced why questions answer in three repeated rounds, and a question with two plausible readings
  still clarifies.
  Progress 2026-09-30: the closed ambiguity reader is implemented with
  `test_a_released_reading_answers_a_clarified_question_only_with_one_reading`,
  `test_an_ambiguous_judgment_keeps_its_clarification_unless_one_reading_is_found`, and
  `test_the_third_family_reads_only_the_masked_question`; the three live rounds remain.
- [x] Build the `ModelEvidenceView` of P0 through the secured gateway, with the link-evidence
  allowlist, hidden-endpoint suppression, and no provider bodies, handle metadata, or snapshot cells.
  Exit: tests show that hidden endpoints and non-allowlisted fields never reach any model call.
  Evidence: `test_model_evidence_view_excludes_hidden_endpoints_and_unreviewed_fields` and
  `test_adaptive_model_receives_model_evidence_view_not_raw_query_rows` pass in `current change`.
- [ ] Record Owner approval for which model families may read the P0 `ModelEvidenceView`. Proposed
  default: no model family reads the view until approved; local code provides the builder and
  boundary enforcement only.
- [ ] Record Owner approval or revision of the decisions listed in the result-handles,
  coverage-expansion, and promotion-program designs. Exit: each decision links its approval record.
- [ ] After the first operation family is promoted, move the owner design's typed-only, causal
  context, and review sections into focused documents. Exit: `check-document-size.py` reports no
  advisory for `docs/roadmap/interfaces/ontology-reasoning-compiler.md`.
