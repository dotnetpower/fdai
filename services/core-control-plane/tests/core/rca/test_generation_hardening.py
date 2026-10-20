"""Generation-boundary tests for injected T2 and historical T1 evidence."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

import pytest
from fdai.core.rca import (
    Citation,
    CitationKind,
    RcaCoordinator,
    RcaOutcome,
    RcaTier,
    RootCauseHypothesis,
    enforce_grounding,
)

_RULE = Citation(CitationKind.RULE, "rule-one")
_EVENT = Citation(CitationKind.EVENT, "event-one")
_PRIOR = RootCauseHypothesis(RcaTier.T1, "synthetic candidate", 0.8, (_RULE, _EVENT))


class _Reasoner:
    def __init__(self, result: RootCauseHypothesis) -> None:
        self.result = result
        self.calls = 0

    async def reason(
        self, *, incident_summary: str, candidate_citations: Sequence[Citation]
    ) -> RootCauseHypothesis:
        self.calls += 1
        return self.result


@pytest.mark.parametrize("current", ((_RULE,), (_EVENT,), ()))
def test_prior_reuse_requires_complete_current_support(current: tuple[Citation, ...]) -> None:
    result = RcaCoordinator().analyze_t1(prior_hypothesis=_PRIOR, current_citations=current)
    assert result.outcome is RcaOutcome.ABSTAINED
    assert result.hypothesis is None


def test_prior_reuse_rejects_changed_facts_under_same_reference() -> None:
    changed = replace(_RULE, facts=("signal:changed",))
    result = RcaCoordinator().analyze_t1(
        prior_hypothesis=_PRIOR, current_citations=(changed, _EVENT)
    )
    assert result.outcome is RcaOutcome.ABSTAINED


@pytest.mark.parametrize("confidence", (1.5, -0.5, float("nan"), float("inf"), True, False))
def test_prior_confidence_is_validated_before_decay(confidence: float) -> None:
    result = RcaCoordinator().analyze_t1(
        prior_hypothesis=replace(_PRIOR, confidence=confidence),
        current_citations=(_RULE, _EVENT),
        reuse_confidence_factor=0.5,
    )
    assert result.outcome is RcaOutcome.ABSTAINED


def test_valid_prior_reuse_drops_uncited_historical_evidence() -> None:
    result = RcaCoordinator().analyze_t1(
        prior_hypothesis=replace(_PRIOR, evidence_refs=("historical-only",)),
        current_citations=(_EVENT, _RULE),
    )
    assert result.is_grounded
    assert result.hypothesis is not None
    assert set(result.hypothesis.citations) == {_RULE, _EVENT}
    assert result.hypothesis.evidence_refs == ()
    assert result.hypothesis.confidence == pytest.approx(0.72)


def test_current_conflicting_facts_hold_prior_reuse() -> None:
    result = RcaCoordinator().analyze_t1(
        prior_hypothesis=_PRIOR,
        current_citations=(_RULE, _EVENT, replace(_RULE, facts=("signal:changed",))),
    )
    assert result.outcome is RcaOutcome.ABSTAINED


@pytest.mark.parametrize(
    "candidate",
    (
        replace(_PRIOR, tier=RcaTier.T0),
        replace(_PRIOR, tier=RcaTier.T1),
        replace(_PRIOR, tier=RcaTier.T2, cause=" "),
        replace(_PRIOR, tier=RcaTier.T2, cause="x" * 4097),
        replace(_PRIOR, tier=RcaTier.T2, cause=chr(0xD800)),
        replace(_PRIOR, tier=RcaTier.T2, remediation_ref="ops.restart-service"),
        replace(_PRIOR, tier=RcaTier.T2, evidence_refs=("fabricated-lineage",)),
        replace(
            _PRIOR,
            tier=RcaTier.T2,
            citations=(replace(_RULE, facts=("signal:fabricated",)),),
        ),
    ),
)
async def test_injected_t2_cannot_bypass_generation_contract(
    candidate: RootCauseHypothesis,
) -> None:
    result = await RcaCoordinator(reasoner=_Reasoner(candidate)).analyze_t2(
        incident_summary="synthetic incident", candidate_citations=(_RULE, _EVENT)
    )
    assert result.outcome is RcaOutcome.ABSTAINED
    assert result.hypothesis is None


@pytest.mark.parametrize(
    "candidates",
    (
        (),
        (_RULE, replace(_RULE, facts=("signal:conflicting",))),
        tuple(Citation(CitationKind.EVENT, f"event-{index}") for index in range(101)),
    ),
)
async def test_unusable_candidates_hold_before_reasoner(candidates: tuple[Citation, ...]) -> None:
    reasoner = _Reasoner(replace(_PRIOR, tier=RcaTier.T2))
    result = await RcaCoordinator(reasoner=reasoner).analyze_t2(
        incident_summary="synthetic incident", candidate_citations=candidates
    )
    assert result.outcome is RcaOutcome.ABSTAINED
    assert reasoner.calls == 0


async def test_injected_fabricated_reference_is_not_copied_into_reason() -> None:
    reasoner = _Reasoner(
        replace(_PRIOR, tier=RcaTier.T2, citations=(replace(_RULE, ref="private-marker"),))
    )
    result = await RcaCoordinator(reasoner=reasoner).analyze_t2(
        incident_summary="synthetic incident", candidate_citations=(_RULE,)
    )
    assert result.outcome is RcaOutcome.ABSTAINED
    assert "private-marker" not in result.reason


@pytest.mark.parametrize("confidence", (True, False, float("nan"), float("inf"), -float("inf")))
def test_grounding_rejects_boolean_and_non_finite_confidence(confidence: float) -> None:
    assert enforce_grounding(replace(_PRIOR, confidence=confidence)).outcome is RcaOutcome.ABSTAINED


@pytest.mark.parametrize("floor", (True, False, float("nan"), float("inf"), -0.1, 1.1))
@pytest.mark.parametrize("citations", ((), (_RULE,)))
def test_invalid_grounding_configuration_cannot_hide_behind_no_evidence(
    floor: float, citations: tuple[Citation, ...]
) -> None:
    with pytest.raises(ValueError, match="min_confidence"):
        enforce_grounding(replace(_PRIOR, citations=citations), min_confidence=floor)


@pytest.mark.parametrize("floor", (True, False, float("nan"), float("inf"), -0.1, 1.1))
def test_coordinator_rejects_invalid_confidence_configuration(floor: float) -> None:
    with pytest.raises(ValueError, match="min_confidence"):
        RcaCoordinator(min_confidence=floor)


@pytest.mark.parametrize("factor", (True, False, float("nan"), float("inf"), -0.1, 1.1))
def test_reuse_rejects_invalid_confidence_factor(factor: float) -> None:
    with pytest.raises(ValueError, match="reuse_confidence_factor"):
        RcaCoordinator().analyze_t1(
            prior_hypothesis=_PRIOR,
            current_citations=(_RULE, _EVENT),
            reuse_confidence_factor=factor,
        )
