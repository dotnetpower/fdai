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
| P1 Production shadow wiring | in-progress | `current change`; [`semantic_question_form.py`](../../../packages/service-contracts/src/fdai_service_contracts/semantic_question_form.py); [`semantic_production_shadow.py`](../../../services/core-control-plane/src/fdai/core/conversation/semantic_production_shadow.py); [`semantic_planning.py`](../../../services/core-control-plane/src/fdai/core/conversation/semantic_planning.py); [`test_semantic_planning.py`](../../../services/core-control-plane/tests/conversation/test_semantic_planning.py); focused checks: `.venv/bin/python -m pytest -q --no-cov packages/service-contracts/tests/test_semantic_judgment.py services/core-control-plane/tests/conversation/test_semantic_judgment.py::test_invalid_carried_question_form_is_absent_and_keeps_judgment_accepted services/core-control-plane/tests/conversation/test_semantic_planning.py::test_production_shadow_records_linked_disposition_without_changing_plan services/core-control-plane/tests/conversation/test_semantic_planning.py::test_missing_carried_form_records_form_absent_without_changing_plan services/core-control-plane/tests/conversation/test_semantic_planning.py::test_production_shadow_has_no_answer_composition_import_path` | Local carry, linked content-free records, default-off schema exposure, and non-interference are implemented. Sampled production-window evidence remains live and open. |
| P2 Direction readers | in-progress | `current change`; [`semantic_direction_receipt.py`](../../../services/core-control-plane/src/fdai/core/conversation/semantic_direction_receipt.py); [`semantic_query_type_grounding.py`](../../../services/core-control-plane/src/fdai/composition/semantic_query_type_grounding.py); [`test_semantic_direction_receipt.py`](../../../services/core-control-plane/tests/conversation/test_semantic_direction_receipt.py); [`test_semantic_query_second_reader.py`](../../../services/core-control-plane/tests/composition/test_semantic_query_second_reader.py) | The majority protocol runs locally, every shadow turn records a direction cost receipt split by reader count, and production shadow composition binds the direction and tiebreaker readers observe-only when its setting is on. The sampled-window receipt is live. |
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
| 2026-10-01 | in-progress | Added the P2 direction cost receipt: each shadow turn records whether one or two blind readers ran, with the calls, input bytes, output tokens, and wall time its reservation ledger reconciled, and logs `semantic_direction_cost` for sampled windows. | `current change`; `semantic_direction_receipt.py`; `semantic_reasoning_shadow.py`; `test_semantic_direction_receipt.py` (4 passed) | Bind both readers in production composition with the P1 production shadow setting, and record a sampled production window per turn type. |
| 2026-10-01 | in-progress | Implemented local P1 production shadow wiring and the production half of P2. The judgment contract carries the closed question form under schema `1.4.0`, the Azure judgment schema exposes it only behind a default-off setting, invalid or missing carried forms record `form_absent` without changing the answer path, linked records retain only digests, and production shadow composition binds the direction readers and third-family tiebreaker observe-only. | `current change`; `packages/service-contracts/src/fdai_service_contracts/{semantic_question_form,semantic_judgment}.py`; `services/core-control-plane/src/fdai/core/conversation/{semantic_judgment,semantic_production_shadow,semantic_planning}.py`; `services/core-control-plane/src/fdai/composition/semantic_query_type_grounding.py`; focused checks listed in the P1 and P2 scope rows pass. | Sampled production-window evidence remains live; promotion and removal stay open for P5. |
| 2026-10-01 | in-progress | Hardened P0 through P3 in the 21 independent critique and hardening rounds of #1734 until only Low findings remained. Every High (2) and Medium (7) finding in these packages is fixed with a regression test: the model evidence view keeps reviewed ObjectSet and traversal properties; the question form moved to service contracts behind explicit re-exports, without replacing a module at import time; an unavailable entailment reviewer holds with a typed reason; a recorder or sink failure never turns a verified plan into a hold; the carried form never reaches the frame model, schema `1.4.0` accepts document queries, and the missing-query hold applies only when the field was offered; the state-store sink writes on its owner loop; and every judgment recovery path validates the carried form without interference. Four Low findings are fixed, and three are accepted below. | `current change`; `packages/service-contracts/src/fdai_service_contracts/{semantic_question_form,semantic_judgment}.py`; `services/core-control-plane/src/fdai/core/conversation/{model_evidence_view,verified_answer_authoring,semantic_production_shadow,semantic_reasoning_form,semantic_judgment,semantic_judgment_question_form,semantic_investigation,semantic_governed_document_planning,semantic_direction_receipt}.py`; `services/core-control-plane/src/fdai/delivery/azure/llm/semantic_judgment.py`; regression tests in `test_model_evidence_view.py`, `test_verified_answer_authoring.py`, `test_semantic_planning.py`, `test_semantic_judgment.py`, `test_semantic_governed_document_planning.py`, `test_semantic_direction_receipt.py`, and `tests/delivery/azure/llm/test_semantic_judgment.py`; full local suite at the final code snapshot: `bash scripts/automation/tests-for-diff.sh --run --allow-full-suite origin/main...HEAD` (39,708 passed, 147 skipped, 0 failed across four shards) | The accepted Low residuals and the live exits below. |

### Remaining work

- [ ] Complete R0: lock a holdout beside the committed bilingual cohort and fixture graph, keep
  function binding production-faithful in the harness, and record baseline L1, L2, and Azure SRE
  Agent parity receipts. The cohort, two locked holdouts, the fixture graph, and L2 tests exist;
  retained L1 receipts and the parity baseline do not.
  Status 2026-10-01: blocked on live evidence. The retained L1 receipts need repeated live model
  rounds, and the Azure SRE Agent parity baseline needs the Owner's browser session through the
  `sre-agent-parity` skill; no local action remains.
- [ ] Configure the direction reader's reasoning-model deployment in production composition, with
  its latency and cost measured per directional turn.
  Progress 2026-10-01: `FDAI_SEMANTIC_PRODUCTION_SHADOW=1` binds the direction and tiebreak readers
  in production composition without compiled answers, and every shadow turn records a direction
  cost receipt. Enabling the setting on a deployment and the sampled latency and cost window remain.
- [ ] Complete R3 through R8 with the exit evidence in the owner delivery-round table, including
  shadow wiring with a turn reservation, per-type holdout accuracy, reviewed trait and path grammar
  catalog changes, traversal root lineage, the location property, the link-evidence allowlist, a
  result-handle threat review, an answer author that emits claims, and V-CLAIM with zero escapes.
- [ ] Wire the shadow runner into the production semantic turn behind a turn budget reservation
  with telemetry export, and record a shadow disposition for every turn with unchanged answers.
  The form must first travel in the judgment call, and the wiring must meet the conditions in the
  owner design's production shadow wiring paragraph; fresh anchor-read cutoffs and structured
  cancellation are done.
  Progress 2026-10-01: P1 carries the closed form in the judgment call (schema 1.4.0, default off),
  records a content-free linked disposition per eligible turn, treats a missing or invalid form as
  `form_absent` with an unchanged answer, and passes the module-boundary and replay-equivalence
  tests; the shadow reserves from its own E5 ledger. A sampled production window remains.
- [x] Add an answer author that emits claims, a full proposition contract for V-CLAIM, and an
  independent entailment review that regenerates or holds an answer, with zero escapes on an
  adversarial claim suite. Evidence: `current change`; `test_answer_claims.py`,
  `test_semantic_reasoning_claims.py`, and `test_verified_answer_authoring.py` pass locally.
  The live R8 holdout with zero V-CLAIM escapes remains open below.
- [ ] Complete the R8 live holdout for verified answer authoring: zero V-CLAIM escapes and zero
  entailment-review escapes on the R8 holdout under approved model-family bindings.
  Status 2026-10-01: blocked on live evidence and on the Owner approval of model families below.
- [ ] Hold zero released wrong answers, a compiled and released answer whose executed rows differ
  from the gold rows, in every L1 round. The review-tightening row recorded three before its fixes
  and zero after them, and the two-reader review row recorded one from concept grounding; keep the
  metric in every round and treat any occurrence as a defect. Since the kind-grounding row the metric
  also counts a released answer where the gold expects none and a function answer whose calls differ
  from the gold form's compile, which earlier status-only counts missed.
  Status 2026-10-01: measured only in live L1 rounds, which this change did not run.
- [ ] Recover live L1 coverage from 84 of 120 runs toward the 108 recorded before the review, without
  a released over-compilation: schema goals given type filters of another domain, restating words
  such as declared that the extractor names as restrictions, extractor quotes that reach past the
  named thing, reach words left out of relation cues, and particles quoted inside resource names.
  Exit: at least 105 of 120 across two repeated rounds with zero released over-compilation.
  Status 2026-10-01: blocked on live L1 rounds; the local fixes for particles inside resource
  names now also cover current-path operand provenance (`test_an_identity_quoted_with_particles_or_spaces_is_not_invented`).
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
  Status 2026-10-01: blocked until production shadow windows and live parity receipts exist.
- [ ] Complete R10: remove lexical re-derivation and template renderers from promoted paths after
  replay equivalence and one stable rollback release.
  Status 2026-10-01: blocked until a family is promoted and one stable rollback release exists.
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
  Progress 2026-10-01: a grounded location, lifecycle, property, or time slot that covers a stated
  restriction now holds the turn unless the plan applies it
  (`test_a_slot_that_covered_a_restriction_must_restrict_the_plan`), beside the existing grouping
  and relation checks. The traced live questions remain.
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
- [ ] Close the three Low residuals accepted in the #1734 hardening rounds. Return typed per-claim
  reasons from the entailment reviewer instead of a boolean; expire production-shadow records and
  sample which turns are recorded; and make the direction cost receipt report an overrun call's
  actual usage and count a failed-over first call as one reader. Exit: a focused regression test for
  each passes.
