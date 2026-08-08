"""In-memory fakes for the quality gate seams - used by tests + local dev."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fdai.core.quality_gate.gate import (
    CrossCheckModel,
    GroundingSource,
    QualityCandidate,
    VerifierPolicy,
)
from fdai.core.quality_gate.rag_grounding import HashedRuleEmbeddingIndex
from fdai.core.quality_gate.rubric import (
    RubricEvaluator,
    RubricOutput,
    RubricScore,
)
from fdai.shared.contracts.models import Rule


class StaticVerifier(VerifierPolicy):
    """Deterministic verifier that returns a preconfigured outcome."""

    def __init__(self, *, outcome: bool | None) -> None:
        self._outcome = outcome

    def verify(self, candidate: QualityCandidate) -> bool | None:
        del candidate
        return self._outcome


class MatchTypeCrossCheckModel(CrossCheckModel):
    """A cross-check model that always agrees on the candidate's action_type."""

    def __init__(self, *, model_id: str = "fake-agree") -> None:
        self._id = model_id

    async def propose(self, candidate: QualityCandidate) -> tuple[str, Mapping[str, Any]]:
        return candidate.action_type, dict(candidate.params)


class MismatchCrossCheckModel(CrossCheckModel):
    """A cross-check model that always disagrees on the action_type."""

    def __init__(self, *, model_id: str = "fake-disagree") -> None:
        self._id = model_id

    async def propose(self, candidate: QualityCandidate) -> tuple[str, Mapping[str, Any]]:
        return f"{candidate.action_type}::other", {}


class SequenceCrossCheckModel(CrossCheckModel):
    """A cross-check model that returns a preset sequence of action types.

    Each ``propose`` call returns the next action type from ``sequence``
    (params always empty), cycling back to the start once exhausted.
    Drives the self-consistency sampler deterministically: a uniform
    sequence yields ``stability == 1.0``; a varied one yields a lower
    stability.
    """

    def __init__(self, *, sequence: tuple[str, ...], model_id: str = "fake-sequence") -> None:
        if not sequence:
            raise ValueError("sequence MUST be non-empty")
        self._sequence = sequence
        self._id = model_id
        self._idx = 0

    async def propose(self, candidate: QualityCandidate) -> tuple[str, Mapping[str, Any]]:
        del candidate
        value = self._sequence[self._idx % len(self._sequence)]
        self._idx += 1
        return value, {}


class InMemoryGroundingSource(GroundingSource):
    """A grounding source backed by an in-process rule map."""

    def __init__(self, rules: Mapping[str, Rule]) -> None:
        self._rules = dict(rules)

    def known_rule_ids(self) -> set[str]:
        return set(self._rules.keys())

    def get(self, rule_id: str) -> Rule | None:
        return self._rules.get(rule_id)


class StaticRubricEvaluator(RubricEvaluator):
    """A rubric evaluator that returns a preconfigured output.

    Used by tests to drive each :class:`RubricVerdict` branch
    deterministically without an LLM. ``raises`` lets a test exercise
    the gate's fail-closed path when the evaluator errors.
    """

    def __init__(
        self,
        *,
        output: RubricOutput | None = None,
        raises: Exception | None = None,
    ) -> None:
        self._output = output if output is not None else RubricOutput()
        self._raises = raises

    async def score(self, candidate: QualityCandidate) -> RubricOutput:
        del candidate
        if self._raises is not None:
            raise self._raises
        return self._output


class UniformRubricEvaluator(RubricEvaluator):
    """A rubric evaluator that scores every criterion at one value.

    Convenience for property tests: a single ``score`` applied to every
    criterion in ``criteria`` at a shared ``threshold``, grounded on
    ``supporting_rule_ids`` (empty by default, which passes grounding).
    """

    def __init__(
        self,
        *,
        criteria: tuple[str, ...],
        score: float,
        threshold: float = 0.7,
        supporting_rule_ids: tuple[str, ...] = (),
    ) -> None:
        self._criteria = criteria
        self._score = score
        self._threshold = threshold
        self._supporting = supporting_rule_ids

    async def score(self, candidate: QualityCandidate) -> RubricOutput:
        del candidate
        return RubricOutput(
            scores=tuple(
                RubricScore(
                    criterion=c,
                    score=self._score,
                    threshold=self._threshold,
                    rationale=f"uniform score for {c}",
                    supporting_rule_ids=self._supporting,
                )
                for c in self._criteria
            )
        )


__all__ = [
    "HashedRuleEmbeddingIndex",
    "InMemoryGroundingSource",
    "MatchTypeCrossCheckModel",
    "MismatchCrossCheckModel",
    "SequenceCrossCheckModel",
    "StaticRubricEvaluator",
    "StaticVerifier",
    "UniformRubricEvaluator",
]
