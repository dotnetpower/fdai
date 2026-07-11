"""Rubric evaluator - the multi-dimensional hallucination filter for T2.

The rubric is a **subtractive** quality-gate leg: an independent judge
model scores a :class:`~fdai.core.quality_gate.gate.QualityCandidate`
against a fixed set of hallucination-relevant criteria (faithfulness,
evidence-action alignment, completeness, reasoning coherence). The pure
:func:`evaluate_rubric_output` reduces those scores to a single
:class:`RubricDecision` the :class:`~fdai.core.quality_gate.gate.QualityGate`
folds into confidence via ``min()``.

Design invariants
-----------------
- **Subtractive only.** The gate applies :attr:`RubricDecision.min_score`
  through ``min(aggregate_confidence, min_score)`` - a rubric can only
  *lower* confidence or add an abstain reason, NEVER raise eligibility
  above what the deterministic verifier already allows. The verifier
  stays the sole execution authority.
- **Grounded.** Every :class:`RubricScore` carries the rule ids that
  support it; the evaluator refuses a score whose citation is not in the
  known rule set (a fabricated citation is a prompt-injection / halluc-
  ination signal, same rule as the Critic and Judge evaluators).
- **No model self-report.** The scores are the judge's assessment of the
  proposer's answer against explicit criteria, not the proposer's own
  confidence - the anti-pattern the whole gate closes. The judge MUST be
  a different model than the proposer (mixed-model), enforced at the
  composition root, not here.
- **Coverage guard.** ``required_criteria`` names the dimensions that
  MUST be present; a truncated evaluator response that skips one
  collapses to :attr:`RubricVerdict.ABSTAIN` so a missing dimension can
  never silently pass.
- **``core/``-safe.** Imports only from ``fdai.core.quality_gate`` and
  stdlib. No LLM SDK, no ``delivery.*`` import; the concrete Azure
  adapter lands in ``delivery/azure/llm/rubric.py``.
- **Shadow-first.** The shipped catalog seed
  (``rule-catalog/prompts/base/t2-rubric.v1.yaml``) is
  ``default_mode: shadow`` and :class:`QualityGateConfig.rubric_shadow`
  defaults to ``True``; the rubric is judge-and-log until a fork meets
  the promotion gate on a labeled scenario set.

See also
--------
- ``docs/roadmap/hallucination-rubric-gate.md``
- ``docs/roadmap/llm-strategy.md`` § T2 - Reasoning Tier
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

from fdai.core.quality_gate.gate import QualityCandidate


class RubricCriterion(StrEnum):
    """The hallucination-relevant dimensions a judge scores.

    Kept a closed enum so the confidence math and the catalog prompt
    describe the same dimensions. Adding a criterion is an explicit,
    reviewable change (new enum member + catalog prompt + doc), never an
    ad-hoc string a model can invent.
    """

    FAITHFULNESS = "faithfulness"
    """Every claim in the candidate's ``reasoning_trace`` is supported by
    a cited rule (NLI-style entailment). The primary hallucination
    dimension - unsupported assertions score low."""

    EVIDENCE_ACTION_ALIGNMENT = "evidence_action_alignment"
    """The proposed ``action_type`` / ``params`` actually follow from the
    cited rules, not merely from plausible-sounding prose."""

    COMPLETENESS = "completeness"
    """The reasoning addresses the safety-critical dimensions (blast
    radius, rollback, stop-condition) rather than silently omitting
    them."""

    REASONING_COHERENCE = "reasoning_coherence"
    """The reasoning is internally consistent - no self-contradiction or
    logical leap between the cited evidence and the conclusion."""


class RubricVerdict(StrEnum):
    """Reduction of a :class:`RubricOutput` to one gate action."""

    PASS = "pass"  # noqa: S105 - verdict value, not a credential
    """Every scored criterion cleared its threshold and coverage was
    satisfied. The gate MAY proceed (the verifier still decides)."""

    FAIL = "fail"
    """At least one scored criterion fell below its threshold. Route to
    HIL; the candidate is a likely hallucination."""

    ABSTAIN = "abstain"
    """The rubric could not render a verdict - no scores, a missing
    required criterion, or an ungrounded (fabricated) citation. Route to
    HIL; never honored as a pass."""


@dataclass(frozen=True, slots=True)
class RubricScore:
    """One criterion's score, its threshold, and its grounding.

    ``score`` and ``threshold`` are both in ``[0.0, 1.0]``. ``score`` is
    the judge's assessment of how well the candidate satisfies
    ``criterion``; ``threshold`` is the configured floor below which the
    criterion is considered failed. ``supporting_rule_ids`` are the rule
    ids the judge grounded the score on - validated against the known
    rule set by :func:`evaluate_rubric_output`.
    """

    criterion: str
    score: float
    threshold: float
    rationale: str
    supporting_rule_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not 0.0 <= self.score <= 1.0:
            raise ValueError(f"RubricScore.score MUST be in [0.0, 1.0], got {self.score}")
        if not 0.0 <= self.threshold <= 1.0:
            raise ValueError(f"RubricScore.threshold MUST be in [0.0, 1.0], got {self.threshold}")
        if not self.criterion or not self.criterion.strip():
            raise ValueError("RubricScore.criterion MUST be non-empty")
        if not self.rationale or not self.rationale.strip():
            raise ValueError(
                "RubricScore.rationale MUST be non-empty - the audit trail "
                "requires a rendered reason for each rubric score"
            )

    @property
    def passed(self) -> bool:
        """``True`` when the score clears (>=) its threshold."""
        return self.score >= self.threshold


@dataclass(frozen=True, slots=True)
class RubricOutput:
    """Structured judge response: a set of per-criterion scores."""

    scores: tuple[RubricScore, ...] = ()


@dataclass(frozen=True, slots=True)
class RubricDecision:
    """The evaluator's reduction of a :class:`RubricOutput`.

    ``min_score`` is the value the gate folds into confidence via
    ``min()``. It is ``1.0`` for an empty-but-not-required score set only
    when the verdict is not ABSTAIN; an ABSTAIN always carries
    ``min_score = 0.0`` so a shadow-to-enforce flip fails closed.
    """

    verdict: RubricVerdict
    min_score: float
    failed_criteria: tuple[str, ...] = field(default_factory=tuple)
    scores: tuple[RubricScore, ...] = field(default_factory=tuple)
    reasons: tuple[str, ...] = field(default_factory=tuple)


@runtime_checkable
class RubricEvaluator(Protocol):
    """DI seam for a rubric judge.

    A real evaluator calls an LLM under a bounded timeout, scores the
    candidate against the rubric criteria, and returns a
    :class:`RubricOutput`. The judge MUST be a different model than the
    proposer (mixed-model, enforced at the composition root). The fake
    in :mod:`~fdai.core.quality_gate.testing` returns a deterministic
    output seeded by the candidate so tests are reproducible. Kept
    ``async`` so a remote model call slots in without changing callers.
    """

    async def score(self, candidate: QualityCandidate) -> RubricOutput: ...


# ---------------------------------------------------------------------------
# Pure evaluator
# ---------------------------------------------------------------------------


def evaluate_rubric_output(
    output: RubricOutput,
    *,
    known_rule_ids: Iterable[str],
    required_criteria: Iterable[str] = (),
) -> RubricDecision:
    """Reduce a :class:`RubricOutput` to a :class:`RubricDecision`.

    ``known_rule_ids`` is the rule set the proposer (and the judge) could
    have cited - typically :meth:`GroundingSource.known_rule_ids`. Any
    score grounded on a rule id outside that set is treated as a
    fabricated citation and collapses the verdict to
    :attr:`RubricVerdict.ABSTAIN`.

    ``required_criteria`` names the dimensions that MUST be present; a
    missing one is an ABSTAIN (a truncated evaluator response cannot
    silently skip a hallucination dimension).

    Rules (in order):

    - No scores at all -> ``ABSTAIN`` (nothing to judge).
    - Any required criterion absent from the scores -> ``ABSTAIN``.
    - Any score grounded on an unknown rule id -> ``ABSTAIN``.
    - Any score below its threshold -> ``FAIL`` (list the failed
      criteria).
    - Otherwise -> ``PASS``.

    ``min_score`` is the minimum score across all criteria for ``PASS`` /
    ``FAIL``, and ``0.0`` for ``ABSTAIN`` (fail closed on a shadow ->
    enforce flip).
    """
    known = frozenset(known_rule_ids)
    required = tuple(required_criteria)
    scores = output.scores

    if not scores:
        return RubricDecision(
            verdict=RubricVerdict.ABSTAIN,
            min_score=0.0,
            scores=scores,
            reasons=("no_scores",),
        )

    present = {s.criterion for s in scores}
    missing = tuple(c for c in required if c not in present)
    if missing:
        return RubricDecision(
            verdict=RubricVerdict.ABSTAIN,
            min_score=0.0,
            scores=scores,
            reasons=tuple(f"missing_criterion:{c}" for c in missing),
        )

    ungrounded = tuple(
        s.criterion for s in scores for rule_id in s.supporting_rule_ids if rule_id not in known
    )
    if ungrounded:
        return RubricDecision(
            verdict=RubricVerdict.ABSTAIN,
            min_score=0.0,
            scores=scores,
            reasons=tuple(f"ungrounded_score:{c}" for c in ungrounded),
        )

    min_score = min(s.score for s in scores)
    failed = tuple(s.criterion for s in scores if not s.passed)
    if failed:
        return RubricDecision(
            verdict=RubricVerdict.FAIL,
            min_score=min_score,
            failed_criteria=failed,
            scores=scores,
            reasons=tuple(f"below_threshold:{c}" for c in failed),
        )

    return RubricDecision(
        verdict=RubricVerdict.PASS,
        min_score=min_score,
        scores=scores,
    )


__all__ = [
    "RubricCriterion",
    "RubricDecision",
    "RubricEvaluator",
    "RubricOutput",
    "RubricScore",
    "RubricVerdict",
    "evaluate_rubric_output",
]
