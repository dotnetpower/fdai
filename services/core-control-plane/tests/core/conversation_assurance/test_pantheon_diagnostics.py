from __future__ import annotations

from dataclasses import replace

import pytest
from fdai.agents import PANTHEON_SPECS
from fdai.core.conversation_assurance import (
    ConversationTurnTraceReceipt,
    PantheonDiagnosticCase,
    PantheonDiagnosticVerdict,
    PantheonRubric,
    PantheonSemanticReview,
    PantheonTurnDiagnostic,
    ParticipantPromptReceipt,
    T2Expectation,
    aggregate_pantheon_diagnostics,
    build_pantheon_census,
    evaluate_pantheon_turn,
    required_observed_rubrics,
    semantic_rubrics,
)

_DIGEST = "a" * 64


def _trace(**overrides: object) -> ConversationTurnTraceReceipt:
    values: dict[str, object] = {
        "campaign_id": "campaign-1",
        "case_id": "case-1",
        "source_revision": "b" * 40,
        "source_content_digest": "8" * 64,
        "turn_digest": _DIGEST,
        "session_digest": "b" * 64,
        "correlation_digest": "c" * 64,
        "locale": "en",
        "expected_primary_agent": "Njord",
        "actual_primary_agent": "Njord",
        "routing_method": "semantic_judgment",
        "semantic_score": 0.95,
        "semantic_margin": 0.25,
        "contributors": ("Freyr",),
        "handoff_owner": None,
        "participants": (
            ParticipantPromptReceipt(
                agent="Njord",
                prompt_version="v3",
                prompt_sha256="d" * 64,
                situation="operator:direct:T1:en",
            ),
        ),
        "tool_ids": ("read_cost_samples",),
        "evidence_ref_digests": ("e" * 64,),
        "evidence_manifest_digest": "f" * 64,
        "answer_digest": "1" * 64,
        "verification_status": "verified",
        "verification_authority": "cost-evidence",
        "t1_reason": "no_structured_conflict",
        "t1_signal_count": 2,
        "t1_conflict_count": 0,
        "t1_conclusion_preserved": True,
        "t2_required": False,
        "t2_attempted": False,
        "t2_status": "not_required",
        "t2_model_family": None,
        "budget_reserved": False,
        "metering_receipt_digest": None,
        "latency_ms": 200,
        "latency_budget_ms": 1_000,
        "terminal_status": "completed",
    }
    values.update(overrides)
    return ConversationTurnTraceReceipt(**values)  # type: ignore[arg-type]


def _case(**overrides: object) -> PantheonDiagnosticCase:
    values: dict[str, object] = {
        "case_id": "case-1",
        "expected_primary_agent": "Njord",
        "expected_routing_method": "semantic_judgment",
        "allowed_contributors": ("Freyr",),
        "expected_handoff": False,
        "expected_handoff_owner": None,
        "t2_expectation": T2Expectation.FORBIDDEN,
        "minimum_semantic_score": 0.8,
        "minimum_semantic_margin": 0.1,
    }
    values.update(overrides)
    return PantheonDiagnosticCase(**values)  # type: ignore[arg-type]


def _semantic_review(identity: str, family: str, value: bool = True) -> PantheonSemanticReview:
    return PantheonSemanticReview(
        reviewer_identity=identity,
        model_family=family,
        confidence=0.9,
        results=tuple((rubric, value) for rubric in semantic_rubrics()),
    )


def _observed(value: bool = True) -> tuple[tuple[PantheonRubric, bool], ...]:
    return tuple((rubric, value) for rubric in required_observed_rubrics())


def test_census_has_exact_bilingual_230_case_contract() -> None:
    census = build_pantheon_census(PANTHEON_SPECS)

    assert census.version == "pantheon-census-v1"
    assert len(census.cases) == 230
    assert len({item.case_id for item in census.cases}) == 230
    assert sum(item.suite == "agent" for item in census.cases) == 180
    assert sum(item.suite == "routing" for item in census.cases) == 30
    assert sum(item.suite == "t2" for item in census.cases) == 20
    assert sum(item.locale == "en" for item in census.cases) == 115
    assert sum(item.locale == "ko" for item in census.cases) == 115
    assert len(census.content_digest) == 64


def test_passing_diagnostic_recomputes_all_thirty_atomic_items() -> None:
    result = evaluate_pantheon_turn(
        case=_case(),
        trace=_trace(),
        observed_results=_observed(),
        semantic_reviews=(
            _semantic_review("judge-a", "family-a"),
            _semantic_review("judge-b", "family-b"),
        ),
    )

    assert result.score == 30
    assert result.verdict is PantheonDiagnosticVerdict.PASS
    assert len(result.results) == 30
    assert result.to_dict()["qualification_authority"] is False


def test_low_confidence_or_same_family_semantic_review_fails_closed() -> None:
    low_confidence = replace(_semantic_review("judge-a", "family-a"), confidence=0.8)

    result = evaluate_pantheon_turn(
        case=_case(),
        trace=_trace(),
        observed_results=_observed(),
        semantic_reviews=(
            low_confidence,
            _semantic_review("judge-b", "family-a"),
        ),
    )

    assert result.score == 25
    assert result.verdict is PantheonDiagnosticVerdict.REVIEW
    assert all(not item.passed for item in result.results[10:15])


def test_same_reviewer_identity_cannot_supply_two_families() -> None:
    result = evaluate_pantheon_turn(
        case=_case(),
        trace=_trace(),
        observed_results=_observed(),
        semantic_reviews=(
            _semantic_review("judge-a", "family-a"),
            _semantic_review("judge-a", "family-b"),
        ),
    )

    assert all(not item.passed for item in result.results[10:15])


def test_hard_zero_dominates_a_perfect_score() -> None:
    result = evaluate_pantheon_turn(
        case=_case(),
        trace=_trace(hard_zero_violations=("direct_executor_call",)),
        observed_results=_observed(),
        semantic_reviews=(
            _semantic_review("judge-a", "family-a"),
            _semantic_review("judge-b", "family-b"),
        ),
    )

    assert result.score == 30
    assert result.verdict is PantheonDiagnosticVerdict.HARD_ZERO_FAIL


def test_diagnostic_rejects_verdict_that_conflicts_with_atomic_score() -> None:
    with pytest.raises(ValueError, match="verdict MUST match"):
        PantheonTurnDiagnostic(
            case_id="case-1",
            agent="Njord",
            locale="en",
            score=30,
            verdict=PantheonDiagnosticVerdict.FAIL,
            results=(),
            hard_zero_violations=(),
            trace_receipt_digest=_DIGEST,
        )


def test_diagnostic_rejects_non_hex_trace_digest() -> None:
    with pytest.raises(ValueError, match="trace digest MUST be SHA-256"):
        PantheonTurnDiagnostic(
            case_id="case-1",
            agent="Njord",
            locale="en",
            score=30,
            verdict=PantheonDiagnosticVerdict.PASS,
            results=(),
            hard_zero_violations=(),
            trace_receipt_digest="z" * 64,
        )


def test_required_t2_needs_budget_metering_and_preserves_t1_on_failure() -> None:
    result = evaluate_pantheon_turn(
        case=_case(t2_expectation=T2Expectation.REQUIRED),
        trace=_trace(
            t2_required=True,
            t2_attempted=True,
            t2_status="error",
            budget_reserved=True,
            t2_model_family="family-c",
            metering_receipt_digest="9" * 64,
            t1_conclusion_preserved=True,
        ),
        observed_results=_observed(),
        semantic_reviews=(
            _semantic_review("judge-a", "family-a"),
            _semantic_review("judge-b", "family-b"),
        ),
    )

    assert result.score == 30
    assert result.verdict is PantheonDiagnosticVerdict.PASS


def test_trace_rejects_attempted_t2_without_budget_reservation() -> None:
    with pytest.raises(ValueError, match="budget reservation"):
        _trace(t2_attempted=True, t2_status="completed")


def test_trace_represents_budget_denial_without_an_attempt() -> None:
    trace = _trace(
        t2_required=True,
        t2_attempted=False,
        t2_status="budget_denied",
        budget_reserved=False,
    )

    assert trace.t2_status == "budget_denied"


def test_aggregation_counts_only_supplied_evaluated_rows() -> None:
    first = evaluate_pantheon_turn(
        case=_case(),
        trace=_trace(),
        observed_results=_observed(),
        semantic_reviews=(
            _semantic_review("judge-a", "family-a"),
            _semantic_review("judge-b", "family-b"),
        ),
    )
    failed_results = tuple(
        replace(item, passed=index <= 20) for index, item in enumerate(first.results, start=1)
    )
    second = replace(
        first,
        case_id="case-2",
        score=20,
        verdict=PantheonDiagnosticVerdict.FAIL,
        results=failed_results,
    )

    summary = aggregate_pantheon_diagnostics(
        (first, second),
        explicit_route_results=(True, False),
        owner_route_pairs=(("Njord", "Njord"), ("Freyr", "Njord")),
        required_t2_results=(True, False),
        forbidden_t2_results=(True, True),
    )

    assert summary.turns == 2
    assert summary.pass_count == 1
    assert summary.fail_count == 1
    assert summary.explicit_target_accuracy == 0.5
    assert summary.owner_routing_f1 is not None
    assert summary.missed_t2_rate == 0.5
    assert summary.unnecessary_t2_rate == 0.0
