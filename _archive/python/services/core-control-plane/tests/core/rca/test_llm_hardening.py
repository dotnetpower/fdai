"""Adversarial model-output and exact-citation regression tests."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from itertools import permutations

import pytest
from fdai.core.rca import Citation, CitationKind, LlmRcaReasoner, parse_rca_response

_RULE = Citation(CitationKind.RULE, "shared")
_EVENT = Citation(CitationKind.EVENT, "shared")


def _answer(**fields: object) -> str:
    payload: dict[str, object] = {
        "cause": "synthetic candidate",
        "confidence": 0.8,
        "citations": ["shared"],
    }
    payload.update(fields)
    return json.dumps(payload)


@pytest.mark.parametrize("candidates", tuple(permutations((_RULE, _EVENT))))
def test_bare_reference_collision_holds(candidates: tuple[Citation, ...]) -> None:
    assert parse_rca_response(_answer(), candidate_citations=candidates) is None


def test_qualified_reference_disambiguates_kinds() -> None:
    result = parse_rca_response(
        _answer(citations=["rule:shared"]), candidate_citations=(_EVENT, _RULE)
    )
    assert result is not None
    assert result.citations == (_RULE,)


@pytest.mark.parametrize(
    "candidates",
    tuple(permutations((_RULE, Citation(CitationKind.EVENT, "rule:shared")))),
)
def test_literal_reference_cannot_shadow_qualified_alias(candidates: tuple[Citation, ...]) -> None:
    assert (
        parse_rca_response(_answer(citations=["rule:shared"]), candidate_citations=candidates)
        is None
    )


@pytest.mark.parametrize(
    "candidates",
    tuple(
        permutations(
            (
                Citation(CitationKind.TELEMETRY, "sample", ("signal:healthy",)),
                Citation(CitationKind.TELEMETRY, "sample", ("signal:failed",)),
            )
        )
    ),
)
def test_conflicting_candidate_facts_hold(candidates: tuple[Citation, ...]) -> None:
    assert parse_rca_response(_answer(citations=["sample"]), candidate_citations=candidates) is None


def test_repeated_candidate_and_output_aliases_do_not_multiply_support() -> None:
    result = parse_rca_response(
        _answer(citations=["shared", "rule:shared", "shared"]),
        candidate_citations=(_RULE, _RULE),
    )
    assert result is not None
    assert result.citations == (_RULE,)


def test_output_citation_order_is_replay_stable() -> None:
    first = parse_rca_response(
        _answer(citations=["rule:shared", "event:shared"]),
        candidate_citations=(_RULE, _EVENT),
    )
    second = parse_rca_response(
        _answer(citations=["event:shared", "rule:shared"]),
        candidate_citations=(_EVENT, _RULE),
    )
    assert first is not None
    assert first == second


@pytest.mark.parametrize(
    "raw",
    (
        '{"cause":"first","cause":"second","confidence":0.8,"citations":["shared"]}',
        '{"cause":"candidate","confidence":0.1,"confidence":0.9,"citations":["shared"]}',
        '{"cause":"candidate","confidence":0.8,"citations":[],"citations":["shared"]}',
        '{"cause":"candidate","confidence":' + "1" + "0" * 400 + ',"citations":["shared"]}',
        '{"cause":' + "[" * 1500 + "0" + "]" * 1500 + "}",
    ),
)
def test_malformed_json_semantics_hold_without_raising(raw: str) -> None:
    assert parse_rca_response(raw, candidate_citations=(_RULE,)) is None


@pytest.mark.parametrize("confidence", (True, False, float("nan"), float("inf"), -float("inf")))
def test_non_numeric_or_non_finite_confidence_holds(confidence: float) -> None:
    assert parse_rca_response(_answer(confidence=confidence), candidate_citations=(_RULE,)) is None


@pytest.mark.parametrize(
    "fields",
    (
        {"remediation_ref": "ops.restart-service"},
        {"evidence_refs": ["invented"]},
        {"cause": "a" * 4097},
        {"cause": "가" * 1366},
        {"cause": chr(0xD800)},
        {"citations": ["shared"] * 101},
        {"unexpected": "a" * (64 * 1024)},
    ),
)
def test_unsupported_or_oversized_output_holds(fields: dict[str, object]) -> None:
    assert parse_rca_response(_answer(**fields), candidate_citations=(_RULE,)) is None


@pytest.mark.parametrize("ref", ("", " padded", "padded ", "x" * 1025, "line\nbreak", chr(0xD800)))
def test_invalid_candidate_reference_holds(ref: str) -> None:
    assert (
        parse_rca_response(
            _answer(citations=[ref]), candidate_citations=(Citation(CitationKind.RULE, ref),)
        )
        is None
    )


def test_candidate_count_overflow_holds_without_truncation() -> None:
    candidates = tuple(Citation(CitationKind.EVENT, f"event-{index}") for index in range(101))
    assert (
        parse_rca_response(_answer(citations=["event-0"]), candidate_citations=candidates) is None
    )


@pytest.mark.parametrize("cause", ("a" * 4096, "가" * 1365 + "a"))
def test_cause_byte_limit_is_inclusive(cause: str) -> None:
    result = parse_rca_response(_answer(cause=cause), candidate_citations=(_RULE,))
    assert result is not None
    assert result.cause == cause


def test_response_limit_counts_utf8_bytes_without_truncation() -> None:
    raw = json.dumps(
        {"cause": "가설", "confidence": 0.8, "citations": ["shared"]}, ensure_ascii=False
    )
    exact = " " * (64 * 1024 - len(raw.encode("utf-8"))) + raw
    assert len(exact.encode("utf-8")) == 64 * 1024
    assert parse_rca_response(exact, candidate_citations=(_RULE,)) is not None
    assert parse_rca_response(exact + " ", candidate_citations=(_RULE,)) is None


def test_reference_length_limit_is_inclusive() -> None:
    citation = Citation(CitationKind.RULE, "a" * 1024)
    result = parse_rca_response(_answer(citations=[citation.ref]), candidate_citations=(citation,))
    assert result is not None
    assert result.citations == (citation,)


def test_candidate_and_output_count_limits_are_inclusive() -> None:
    candidates = tuple(Citation(CitationKind.EVENT, f"event-{index}") for index in range(100))
    result = parse_rca_response(
        _answer(citations=[citation.ref for citation in candidates]), candidate_citations=candidates
    )
    assert result is not None
    assert len(result.citations) == 100
    assert set(result.citations) == set(candidates)


class _Model:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls = 0
        self.error = error

    async def propose_cause(
        self, *, incident_summary: str, candidate_citations: Sequence[Citation]
    ) -> str:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return _answer()


@pytest.mark.parametrize(
    "candidates",
    (
        (),
        (
            Citation(CitationKind.EVENT, "same", ("signal:first",)),
            Citation(CitationKind.EVENT, "same", ("signal:second",)),
        ),
    ),
)
async def test_unusable_evidence_does_not_call_model(candidates: tuple[Citation, ...]) -> None:
    model = _Model()
    assert (
        await LlmRcaReasoner(model=model).reason(
            incident_summary="synthetic incident", candidate_citations=candidates
        )
        is None
    )
    assert model.calls == 0


async def test_transport_failure_does_not_disclose_provider_exception(
    caplog: pytest.LogCaptureFixture,
) -> None:
    model = _Model(RuntimeError("private-provider-detail"))
    assert (
        await LlmRcaReasoner(model=model).reason(
            incident_summary="synthetic incident", candidate_citations=(_RULE,)
        )
        is None
    )
    assert "rca_model_call_failed" in caplog.text
    assert "private-provider-detail" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)
    assert model.calls == 1


async def test_cancellation_is_not_converted_to_model_failure() -> None:
    class CancelledModel:
        async def propose_cause(
            self, *, incident_summary: str, candidate_citations: Sequence[Citation]
        ) -> str:
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await LlmRcaReasoner(model=CancelledModel()).reason(
            incident_summary="synthetic incident", candidate_citations=(_RULE,)
        )
