from __future__ import annotations

import hashlib

from fdai.core.conversation_assurance.quality_sre_observations import (
    RcaScenarioResult,
    observe_rca_scenario,
)
from fdai.core.rca.contract import (
    Citation,
    CitationKind,
    RcaCausalChain,
    RcaOutcome,
    RcaResult,
    RcaTier,
    RootCauseHypothesis,
)

_EVIDENCE = "a" * 64


def _grounded() -> RcaResult:
    hypothesis = RootCauseHypothesis(
        tier=RcaTier.T1,
        cause="A deployment changed the configuration.",
        confidence=0.9,
        citations=(Citation(CitationKind.CHANGE, "change-1"),),
        causal_chain=RcaCausalChain("event-1", "event-2", (), 0.9, 0),
    )
    return RcaResult(RcaOutcome.GROUNDED, hypothesis, "grounded")


def test_grounded_rca_matches_triage_timeline_and_cause() -> None:
    actual = _grounded()
    contributions = observe_rca_scenario(
        RcaScenarioResult(
            "case-1",
            RcaOutcome.GROUNDED,
            hashlib.sha256(actual.hypothesis.cause.encode()).hexdigest(),  # type: ignore[union-attr]
            ("event-1", "event-2"),
            actual,
            _EVIDENCE,
        )
    )
    assert [item.item_id for item in contributions] == [16, 17, 18]
    assert all(item.value == 1.0 for item in contributions)


def test_safe_abstention_counts_as_supported_rca_outcome() -> None:
    contributions = observe_rca_scenario(
        RcaScenarioResult(
            "case-1",
            RcaOutcome.ABSTAINED,
            None,
            None,
            RcaResult(RcaOutcome.ABSTAINED, None, "insufficient_evidence"),
            _EVIDENCE,
        )
    )
    assert [item.item_id for item in contributions] == [16, 18]
    assert all(item.value == 1.0 for item in contributions)


def test_unsupported_or_wrong_cause_scores_zero() -> None:
    actual = _grounded()
    contributions = observe_rca_scenario(
        RcaScenarioResult(
            "case-1",
            RcaOutcome.GROUNDED,
            "b" * 64,
            ("event-9", "event-2"),
            actual,
            _EVIDENCE,
        )
    )
    assert [item.value for item in contributions] == [1.0, 0.0, 0.0]
