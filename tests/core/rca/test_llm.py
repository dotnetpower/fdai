"""LlmRcaReasoner + parse_rca_response - deterministic parse + grounding.

The security-critical assertions: a fabricated citation (not in the
supplied evidence) is refused, and a model transport error becomes an
abstain rather than a crash.
"""

from __future__ import annotations

import json

import pytest

from fdai.core.rca import (
    Citation,
    CitationKind,
    LlmRcaReasoner,
    RcaCoordinator,
    RcaOutcome,
    RcaReasoner,
    RcaTier,
    parse_rca_response,
)

_CANDIDATES = (
    Citation(kind=CitationKind.RULE, ref="object-storage.owner-tag.required"),
    Citation(kind=CitationKind.EVENT, ref="e-1"),
)


def _answer(**fields: object) -> str:
    base: dict[str, object] = {
        "cause": "runaway writer saturated the volume",
        "confidence": 0.85,
        "citations": ["object-storage.owner-tag.required"],
    }
    base.update(fields)
    return json.dumps(base)


class _FakeModel:
    def __init__(self, *, response: str | None = None, error: BaseException | None = None) -> None:
        self._response = response
        self._error = error
        self.calls = 0

    async def propose_cause(self, *, incident_summary: str, candidate_citations: object) -> str:
        self.calls += 1
        if self._error is not None:
            raise self._error
        assert self._response is not None
        return self._response


# ---------------------------------------------------------------------------
# parse_rca_response
# ---------------------------------------------------------------------------


def test_parse_valid_answer() -> None:
    h = parse_rca_response(_answer(), candidate_citations=_CANDIDATES)
    assert h is not None
    assert h.tier is RcaTier.T2
    assert h.cause == "runaway writer saturated the volume"
    assert h.confidence == pytest.approx(0.85)
    assert len(h.citations) == 1
    assert h.citations[0].ref == "object-storage.owner-tag.required"


def test_parse_exact_kind_qualified_candidate() -> None:
    hypothesis = parse_rca_response(
        _answer(citations=["event:e-1"]),
        candidate_citations=_CANDIDATES,
    )

    assert hypothesis is not None
    assert hypothesis.citations == (_CANDIDATES[1],)


@pytest.mark.parametrize("citation", ("rule:e-1", "event:missing"))
def test_parse_rejects_mismatched_or_missing_qualified_candidate(citation: str) -> None:
    assert (
        parse_rca_response(
            _answer(citations=[citation]),
            candidate_citations=_CANDIDATES,
        )
        is None
    )


def test_parse_malformed_json_abstains() -> None:
    assert parse_rca_response("{not json", candidate_citations=_CANDIDATES) is None


def test_parse_non_object_abstains() -> None:
    assert parse_rca_response("[1, 2, 3]", candidate_citations=_CANDIDATES) is None


@pytest.mark.parametrize("cause", ["", "   ", None, 42])
def test_parse_missing_or_blank_cause_abstains(cause: object) -> None:
    assert parse_rca_response(_answer(cause=cause), candidate_citations=_CANDIDATES) is None


@pytest.mark.parametrize("confidence", [-0.1, 1.5, "high", None, True])
def test_parse_bad_confidence_abstains(confidence: object) -> None:
    assert (
        parse_rca_response(_answer(confidence=confidence), candidate_citations=_CANDIDATES) is None
    )


def test_parse_fabricated_citation_is_refused() -> None:
    # A ref the caller never supplied -> prompt-injection defense.
    answer = _answer(citations=["fabricated.rule.id"])
    assert parse_rca_response(answer, candidate_citations=_CANDIDATES) is None


def test_parse_non_string_citation_abstains() -> None:
    assert parse_rca_response(_answer(citations=[123]), candidate_citations=_CANDIDATES) is None


def test_parse_citations_not_a_list_abstains() -> None:
    assert parse_rca_response(_answer(citations="r1"), candidate_citations=_CANDIDATES) is None


def test_parse_empty_citations_is_ungrounded() -> None:
    assert parse_rca_response(_answer(citations=[]), candidate_citations=_CANDIDATES) is None


def test_parse_tier_override() -> None:
    h = parse_rca_response(_answer(), candidate_citations=_CANDIDATES, tier=RcaTier.T1)
    assert h is not None
    assert h.tier is RcaTier.T1


# ---------------------------------------------------------------------------
# LlmRcaReasoner
# ---------------------------------------------------------------------------


def test_reasoner_satisfies_protocol() -> None:
    assert isinstance(LlmRcaReasoner(model=_FakeModel(response=_answer())), RcaReasoner)


@pytest.mark.asyncio
async def test_reasoner_parses_grounded_hypothesis() -> None:
    reasoner = LlmRcaReasoner(model=_FakeModel(response=_answer()))
    h = await reasoner.reason(incident_summary="disk near full", candidate_citations=_CANDIDATES)
    assert h is not None
    assert h.tier is RcaTier.T2
    assert h.citations[0].ref == "object-storage.owner-tag.required"


@pytest.mark.asyncio
async def test_reasoner_malformed_answer_abstains() -> None:
    reasoner = LlmRcaReasoner(model=_FakeModel(response="{broken"))
    h = await reasoner.reason(incident_summary="x", candidate_citations=_CANDIDATES)
    assert h is None


@pytest.mark.asyncio
async def test_reasoner_model_error_abstains_without_crash() -> None:
    reasoner = LlmRcaReasoner(model=_FakeModel(error=RuntimeError("transport down")))
    h = await reasoner.reason(incident_summary="x", candidate_citations=_CANDIDATES)
    assert h is None


@pytest.mark.asyncio
async def test_reasoner_plugs_into_coordinator() -> None:
    coordinator = RcaCoordinator(reasoner=LlmRcaReasoner(model=_FakeModel(response=_answer())))
    result = await coordinator.analyze_t2(
        incident_summary="disk near full", candidate_citations=_CANDIDATES
    )
    assert result.outcome is RcaOutcome.GROUNDED
    assert result.hypothesis is not None
    assert result.hypothesis.tier is RcaTier.T2


@pytest.mark.asyncio
async def test_reasoner_fabricated_citation_abstains_via_coordinator() -> None:
    model = _FakeModel(response=_answer(citations=["fabricated.rule.id"]))
    coordinator = RcaCoordinator(reasoner=LlmRcaReasoner(model=model))
    result = await coordinator.analyze_t2(
        incident_summary="disk near full", candidate_citations=_CANDIDATES
    )
    assert result.outcome is RcaOutcome.ABSTAINED
