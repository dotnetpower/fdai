---
title: Hallucination Rubric Gate
---
# Hallucination Rubric Gate

The rubric gate is a **subtractive hallucination filter** layered onto the T2
quality gate. An independent judge model scores a T2 candidate's reasoning
against fixed criteria, and the gate folds the minimum score into confidence
with `min()` - it can only lower eligibility, never raise it. The deterministic
verifier stays the sole execution authority. This doc specifies the design and
its DI seams; it extends the T2 gate rules in
[llm-strategy.md](llm-strategy.md) and
[phase-2-quality-and-t1.md](phases/phase-2-quality-and-t1.md).

## Why a rubric leg

The existing quality gate already blocks most hallucination with four legs:
deterministic verifier (the authority), RAG grounding (citation validity),
mixed-model cross-check (structural agreement), and the Proposer/Critic/Judge
debate. Two gaps remained:

1. **No reasoning target.** The `QualityCandidate` carried the proposed action
   and its citations but not the model's natural-language justification, so
   faithfulness (does every claim follow from the cited evidence?) could not be
   scored.
2. **No multi-dimensional scoring.** The Critic emits objections and the Judge
   emits a verdict, but nothing produced a per-dimension score that could be
   thresholded into a hallucination signal.

The rubric gate closes both without weakening any existing invariant.

## Core principle: subtractive only

The rubric is a filter that can only **subtract**. This is the invariant that
keeps it consistent with "the verifier is the authority, never the model":

- The gate applies the rubric through `confidence = min(aggregate_confidence,
  rubric_min_score)` in enforce mode. Because it is a `min()`, the rubric can
  only push confidence **down**, never up.
- A rubric failure adds an abstain reason (route to HIL); it never adds an
  eligible reason.
- The rubric never short-circuits a verifier deny and never converts a
  would-be-abstain into eligible.
- This holds on **every** outcome path, including the one where the debate
  orchestrator resolves a cross-check disagreement: a rubric reason keeps the
  outcome at abstain even when the debate would otherwise proceed.

A property test asserts this directly: a maximal rubric score cannot rescue a
low-confidence candidate, and a rubric FAIL is honored even after a debate
PROCEED.

## Works with

- `QualityCandidate.reasoning_trace` - the scoring target (the T2 model's
  justification), forwarded by the proposer adapter.
- The rule catalog - every rubric score cites supporting rule ids, validated
  against the known rule set (fabricated citations abstain).
- `rule-catalog/llm-registry.yaml` capability `t2.rubric.judge` - a distinct
  publisher from `t2.reasoner.primary` (a model must not grade its own answer),
  enforced at config load in `llm_resolver.py`.
- `rule-catalog/prompts/base/t2-rubric.v1.yaml` - the rubric prompt as
  catalog-as-code, `default_mode: shadow`.

## Rubric criteria

Four criteria, a closed enum (`RubricCriterion`), so the confidence math and the
catalog prompt describe the same dimensions. Some are best checked
deterministically and stay in the verifier / grounding legs; the rubric judge
scores only the genuinely semantic dimensions.

| Criterion | Catches | Layer |
|-----------|---------|-------|
| `faithfulness` | Claims in the reasoning not supported by a cited rule (NLI-style) | LLM judge |
| `evidence_action_alignment` | The action does not follow from the cited rules | LLM judge |
| `completeness` | Blast radius / rollback / stop-condition ignored | LLM judge |
| `reasoning_coherence` | Self-contradiction or a logical leap | LLM judge + self-consistency |

Deterministic dimensions (schema conformance, citation-exists, blast-radius
numeric bounds) are handled by the verifier and grounding legs, not the LLM
rubric, so the LLM judge is spent only on what genuinely needs a model.

The per-criterion **pass threshold is configuration**, injected by the delivery
adapter from `AzureOpenAIRubricEvaluatorConfig`, never read from the model - a
model must not set its own passing bar. The catalog prompt explicitly instructs
the model not to emit a threshold or a verdict.

## How it works

The rubric runs after the cross-check (so it only spends judge tokens on
candidates the structural checks did not already reject) and before the
confidence threshold:

1. **Score** - the judge scores the candidate's `reasoning_trace` against each
   criterion, grounding each score on supporting rule ids.
2. **Reduce** - the pure `evaluate_rubric_output` reduces the scores to a
   `RubricDecision` (`pass` / `fail` / `abstain`) with a `min_score`.
3. **Fold** - in enforce mode the gate applies `min(aggregate_confidence,
   min_score)` and adds an abstain reason on `fail` / `abstain`. In shadow mode
   the scores are recorded but the outcome and confidence are untouched.

```text
T2 candidate (+ reasoning_trace)
  -> verifier (deny short-circuits)
  -> grounding (citation validity)
  -> cross-check + debate
  -> rubric judge (score) -> evaluate_rubric_output -> RubricDecision
  -> confidence = min(aggregate, rubric_min_score)   [enforce only]
  -> verifier is still the sole execution authority
```

### Reduction rules

`evaluate_rubric_output` abstains (route to HIL) when it cannot render a trusted
verdict, fails on any below-threshold criterion, and passes otherwise:

- No scores -> `abstain`.
- A criterion scored more than once -> `abstain` (a self-contradictory response
  is not a trusted signal).
- A score naming an unknown criterion (outside the `RubricCriterion` set) ->
  `abstain` (a hallucinated / malformed dimension).
- A required criterion is missing (`rubric_required_criteria`) -> `abstain` (a
  truncated response cannot silently skip a hallucination dimension).
- A score grounded on an unknown rule id -> `abstain` (fabricated citation).
- Any score below its threshold -> `fail` (list the failed criteria).
- Otherwise -> `pass`.

`min_score` is the minimum across criteria for `pass` / `fail`, and `0.0` for
`abstain` so a shadow-to-enforce flip fails closed.

A **blank `reasoning_trace`** short-circuits before the judge is called: there is
no reasoning target to score for faithfulness, so enforce mode abstains
(`rubric_no_reasoning_trace`) without spending a judge call, and shadow mode
records the abstain without changing the outcome.

## Fail-closed

An evaluator exception (transport failure, malformed response) never fails open
into eligible. In enforce mode it adds a `rubric_evaluator_error:<Type>` abstain
reason and drives `min_score` to `0.0`; in shadow mode it is recorded but does
not change the outcome.

## Self-consistency (complement)

Where the rubric scores the quality of one answer, `SelfConsistencySampler`
measures whether the reasoner agrees with itself: sample the same proposer N
times (temperature > 0) and reduce to an `action_stability` value in
`[0.0, 1.0]`. The composition root merges that value into the candidate's
`confidence_signals`; because the aggregate is a mean, an unstable proposer
lowers confidence. Sampling multiplies token cost, so it runs in a **cascade** -
only when a cheaper signal is weak - not on every T2 call. It never grants
eligibility on its own.

## Shadow before enforce

The rubric ships shadow-first. `QualityGateConfig.rubric_shadow` defaults to
`True` and the catalog seed is `default_mode: shadow`, so a wired evaluator is
judge-and-log only: `rubric_scores`, `rubric_verdict`, and `rubric_min_score`
are recorded on every `QualityDecision` for measurement, but the outcome and
confidence are untouched. A fork promotes to enforce only after the promotion
gate is met on a labeled scenario set.

### Promotion metrics

Measure on the frozen scenario set, baseline (rubric off) vs treatment, never
one without the other:

- **hallucination-catch rate** - labeled hallucinations the rubric flags.
- **false-positive rate** - clean candidates the rubric wrongly routes to HIL.
- **added latency / token cost** per T2 call.

Promotion requires catch rate at or above the target, zero policy-violation
escapes, and false-positive rate at or below the allowed ceiling. A regression
demotes back to shadow.

## DI seams

All in `src/fdai/core/quality_gate/` (core stays LLM-SDK-free); the concrete
adapter is in `delivery/`.

| Seam | Where | Role |
|------|-------|------|
| `RubricEvaluator` | `rubric.py` | Protocol a fork implements with a real judge model |
| `evaluate_rubric_output` | `rubric.py` | Pure reduction to a `RubricDecision` |
| `SelfConsistencySampler` | `self_consistency.py` | Sample a proposer N times for stability |
| `AzureOpenAIRubricEvaluator` | `delivery/azure/llm/rubric.py` | httpx judge client, config-injected thresholds |

## Safety invariants

- **Verifier is the authority.** The rubric never grants eligibility.
- **Subtractive only.** Confidence is folded with `min()`, never added to.
- **Grounded.** Every score cites supporting rule ids, validated against the
  catalog; a fabricated citation abstains.
- **No model self-report.** Scores are the judge's assessment against explicit
  criteria, and the judge is a different model than the proposer.
- **Fail-closed.** An evaluator error abstains to HIL.
- **Shadow-first.** Judge-and-log until the promotion gate is met.

## Limits (what this does NOT do)

Be honest about the ceiling. The rubric judge is itself an LLM, so this is a
**probabilistic reduction** of hallucination, not elimination at the source. A
judge can miss a subtly wrong justification or, worse, hallucinate a high score.
The design mitigates that - mixed-model independence (judge != proposer),
grounded citations, fail-closed defaults, and shadow-before-enforce measurement -
but it never claims to catch every hallucination. The only **hard** guarantee is
the deterministic verifier: nothing executes unless policy-as-code and what-if
approve it. The rubric can lower confidence and route more cases to HIL; it
cannot make an ungrounded action safe. Residual softness (some now mitigated):

- **Grounding entailment is opt-in.** A rubric score's `supporting_rule_ids` are
  always checked to exist in the catalog. When the wired `GroundingSource`
  exposes `supports()` (e.g. `RagGroundingSource`), the gate now also passes an
  entailment predicate so a citation that exists but does not topically support
  the candidate abstains (`off_topic_score`). With a plain grounding source that
  has no `supports()`, only id-existence is checked - a judge could still cite a
  real-but-off-topic rule.
- **Self-consistency: mean signal OR subtractive gate.** Merging
  `action_stability` into the mean `confidence_signals` dilutes it (a low value
  can be masked). To avoid that, use `run_consistency_cascade`, which samples
  only when the cheap signal is weak and returns a hard `stable` verdict the
  caller routes to HIL - a subtractive gate, not a diluting average.
- **`min()` folds two different axes.** The rubric `min_score` (a judge's
  criterion assessment) and the candidate `aggregate_confidence` (retrieval /
  verifier-margin signals) are different measures compared against one
  threshold. This is a deliberate simplification: `min()` only ever lowers, so
  the axis mismatch cannot raise eligibility - but a fork tuning the threshold
  should know both feed it.
- **No automatic promotion registry.** Unlike ActionTypes (which have a
  `promotion_gate` evaluated by `ActionPromotionRegistry`), the rubric's
  shadow -> enforce transition is a manual `QualityGateConfig.rubric_shadow`
  flip. Automatic, metric-driven promotion / demotion is future work.
- **Real-model contract is prompt-enforced, not schema-enforced.** Tests use
  httpx mocks; `response_format=json_object` guarantees valid JSON, not the
  rubric schema. The adapter's strict parser + `RubricScore` validation catch a
  malformed real-model response and fail closed, but the shape depends on the
  catalog prompt, so a prompt / enum drift is guarded only by the shipped
  catalog-seed test.

## Integration status

**This leg is not yet wired into the upstream control loop.** As of this
writing, upstream does not assemble a live `QualityGate` into the control loop
at all - T2 integration is shadow-only backlog (see the xfail markers in
`tests/scenarios/test_v2026_07_replay.py`). The rubric is a fully tested,
isolated library on top of that seam. To make it run, a fork MUST:

1. Assemble a `QualityGate` and pass its bound `RubricEvaluator` (bind it on
   `LlmBindings.rubric_evaluator`, resolved from the `t2.rubric.judge`
   capability).
2. Populate `QualityCandidate.reasoning_trace` in its `T2Proposer` - a blank
   trace makes the rubric abstain for lack of a scoring target.
3. Serialize the `QualityDecision.rubric_*` fields into the audit log so the
   shadow-mode catch / false-positive metrics can actually be measured. The
   `quality_decision_audit_fields()` helper flattens them JSON-safely; a fork's
   control-loop audit writer merges its output into the per-decision entry.
   Every field is a structured id / score / enum / resource reference except the
   rubric `rationale`, which is untrusted LLM free-text and is EXCLUDED by
   default (`include_rationale=True` opts in, capped, and a fork MUST secret-scan
   it before persisting - L0 audit records no secrets / customer values).
   Upstream's control loop does not yet call the helper (T2 is unwired); without
   that call, shadow mode records nothing to promote on.

Until those three are done, the rubric changes nothing at runtime. This is by
design (shadow-first), but it means the current value is the tested contract and
the seam, not a live hallucination reduction.

## Next steps

| To learn about | Read |
|----------------|------|
| The T2 tier and the gate legs it guards | [llm-strategy.md](llm-strategy.md) |
| Where the gate sits in the phase plan | [phases/phase-2-quality-and-t1.md](phases/phase-2-quality-and-t1.md) |
| The prompt catalog and role x layer matrix | [prompt-composition.md](prompt-composition.md) |
| The untrusted-input threat model | [security-and-identity.md](security-and-identity.md) |
