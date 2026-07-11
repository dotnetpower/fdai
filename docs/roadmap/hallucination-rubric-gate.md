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

A property test asserts this directly: a maximal rubric score cannot rescue a
low-confidence candidate.

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
- A required criterion is missing (`rubric_required_criteria`) -> `abstain` (a
  truncated response cannot silently skip a hallucination dimension).
- A score grounded on an unknown rule id -> `abstain` (fabricated citation).
- Any score below its threshold -> `fail` (list the failed criteria).
- Otherwise -> `pass`.

`min_score` is the minimum across criteria for `pass` / `fail`, and `0.0` for
`abstain` so a shadow-to-enforce flip fails closed.

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

## Next steps

| To learn about | Read |
|----------------|------|
| The T2 tier and the gate legs it guards | [llm-strategy.md](llm-strategy.md) |
| Where the gate sits in the phase plan | [phases/phase-2-quality-and-t1.md](phases/phase-2-quality-and-t1.md) |
| The prompt catalog and role x layer matrix | [prompt-composition.md](prompt-composition.md) |
| The untrusted-input threat model | [security-and-identity.md](security-and-identity.md) |
