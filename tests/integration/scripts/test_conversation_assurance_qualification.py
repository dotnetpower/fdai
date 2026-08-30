from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest
from fdai.agents import PANTHEON_SPECS
from fdai.core.conversation_assurance import (
    ConversationTurnTraceReceipt,
    PantheonDiagnosticVerdict,
    PantheonRubric,
    PantheonRubricResult,
    PantheonTurnDiagnostic,
    ParticipantPromptReceipt,
    T2Expectation,
    build_pantheon_census,
)
from scripts.automation.conversation_assurance_qualification import (
    PantheonCaseMeasurement,
    qualify_pantheon_series,
)

_REVISION = "b" * 40
_CLEAN_DIGEST = hashlib.sha256(f"{_REVISION}\n".encode()).hexdigest()


def _measurement(index: int) -> PantheonCaseMeasurement:
    census = build_pantheon_census(PANTHEON_SPECS)
    case = census.cases[index]
    required_t2 = case.t2_expectation is T2Expectation.REQUIRED
    trace = ConversationTurnTraceReceipt(
        campaign_id=f"campaign-{index // 20}",
        case_id=case.case_id,
        source_revision=_REVISION,
        source_content_digest=_CLEAN_DIGEST,
        turn_digest=hashlib.sha256(f"turn-{index}".encode()).hexdigest(),
        session_digest=hashlib.sha256(f"session-{index}".encode()).hexdigest(),
        correlation_digest=hashlib.sha256(f"correlation-{index}".encode()).hexdigest(),
        locale=case.locale,
        expected_primary_agent=case.expected_primary_agent,
        actual_primary_agent=case.expected_primary_agent,
        routing_method=case.expected_routing_method,
        semantic_score=None if case.expected_routing_method == "explicit" else 1.0,
        semantic_margin=None if case.expected_routing_method == "explicit" else 1.0,
        contributors=case.allowed_contributors,
        handoff_owner=case.expected_handoff_owner,
        participants=(
            ParticipantPromptReceipt(
                agent=case.expected_primary_agent,
                prompt_version="v1",
                prompt_sha256=hashlib.sha256(f"prompt-{index}".encode()).hexdigest(),
                situation=f"operator:direct:T1:{case.locale}",
            ),
        ),
        tool_ids=(),
        evidence_ref_digests=(),
        evidence_manifest_digest=hashlib.sha256(f"evidence-{index}".encode()).hexdigest(),
        answer_digest=hashlib.sha256(f"answer-{index}".encode()).hexdigest(),
        verification_status="verified",
        verification_authority="test",
        t1_reason="structured_conflict" if required_t2 else "no_structured_conflict",
        t1_signal_count=2 if required_t2 else 0,
        t1_conflict_count=1 if required_t2 else 0,
        t1_conclusion_preserved=True,
        t2_required=required_t2,
        t2_attempted=required_t2,
        t2_status="completed" if required_t2 else "not_required",
        t2_model_family="family-c" if required_t2 else None,
        budget_reserved=required_t2,
        metering_receipt_digest=(
            hashlib.sha256(f"metering-{index}".encode()).hexdigest() if required_t2 else None
        ),
        latency_ms=10,
        latency_budget_ms=1_000,
        terminal_status="completed",
    )
    results = tuple(
        PantheonRubricResult(
            item_id=item_id,
            rubric=rubric,
            passed=True,
            reason="verified",
        )
        for item_id, rubric in enumerate(PantheonRubric, start=1)
    )
    diagnostic = PantheonTurnDiagnostic(
        case_id=case.case_id,
        agent=case.expected_primary_agent,
        locale=case.locale,
        score=30,
        verdict=PantheonDiagnosticVerdict.PASS,
        results=results,
        hard_zero_violations=(),
        trace_receipt_digest=trace.receipt_digest,
        t2_expectation=case.t2_expectation,
    )
    return PantheonCaseMeasurement(diagnostic=diagnostic, trace=trace)


def _complete_series() -> tuple[PantheonCaseMeasurement, ...]:
    return tuple(_measurement(index) for index in range(230))


def _replace_trace(
    measurement: PantheonCaseMeasurement,
    trace: ConversationTurnTraceReceipt,
) -> PantheonCaseMeasurement:
    return PantheonCaseMeasurement(
        diagnostic=replace(measurement.diagnostic, trace_receipt_digest=trace.receipt_digest),
        trace=trace,
    )


def test_complete_clean_census_produces_qualified_replayable_evidence() -> None:
    evidence = qualify_pantheon_series(
        build_pantheon_census(PANTHEON_SPECS),
        _complete_series(),
    )

    assert evidence.qualified is True
    assert evidence.turns == 230
    assert evidence.explicit_target_accuracy == 1.0
    assert evidence.owner_routing_f1 == 1.0
    assert evidence.missed_t2_rate == 0.0
    assert evidence.unnecessary_t2_rate == 0.0
    assert evidence.minimum_score == 30
    assert evidence.hard_zero_count == 0
    assert len(evidence.agent_locale_floors) == 30
    assert len(evidence.measurement_set_digest) == 64
    assert evidence.to_dict()["evidence_digest"] == evidence.evidence_digest


def test_unrouted_owner_is_a_false_negative_without_expected_owner_fallback() -> None:
    census = build_pantheon_census(PANTHEON_SPECS)
    measurements = list(_complete_series())
    index = next(
        index
        for index, case in enumerate(census.cases)
        if case.expected_routing_method == "semantic_judgment"
    )
    measurement = measurements[index]
    unrouted_trace = replace(measurement.trace, actual_primary_agent=None)
    unrouted_results = (
        replace(measurement.diagnostic.results[0], passed=False),
        *measurement.diagnostic.results[1:],
    )
    measurements[index] = PantheonCaseMeasurement(
        diagnostic=replace(
            measurement.diagnostic,
            score=29,
            results=unrouted_results,
            trace_receipt_digest=unrouted_trace.receipt_digest,
        ),
        trace=unrouted_trace,
    )

    evidence = qualify_pantheon_series(census, tuple(measurements))

    assert evidence.owner_routing_f1 < 0.98
    assert evidence.qualified is False
    assert "owner_routing_f1_below_threshold" in evidence.failure_reasons


def test_incomplete_or_non_terminal_series_cannot_qualify() -> None:
    census = build_pantheon_census(PANTHEON_SPECS)
    measurements = _complete_series()

    with pytest.raises(ValueError, match="exact unique census coverage"):
        qualify_pantheon_series(census, measurements[:-1])

    first = measurements[0]
    non_terminal = (
        _replace_trace(first, replace(first.trace, terminal_status="failed")),
        *measurements[1:],
    )
    with pytest.raises(ValueError, match="installed census"):
        qualify_pantheon_series(census, non_terminal)


def test_dirty_source_digest_cannot_qualify() -> None:
    census = build_pantheon_census(PANTHEON_SPECS)
    measurements = tuple(
        _replace_trace(
            item,
            replace(item.trace, source_content_digest="f" * 64),
        )
        for item in _complete_series()
    )

    evidence = qualify_pantheon_series(census, measurements)

    assert evidence.source_tree_clean is False
    assert evidence.qualified is False
    assert "source_tree_not_clean" in evidence.failure_reasons


def test_trace_safety_mismatch_and_measurement_substitution_are_detected() -> None:
    census = build_pantheon_census(PANTHEON_SPECS)
    measurements = _complete_series()
    first = measurements[0]
    unsafe_trace = replace(first.trace, hard_zero_violations=("sensitive_output",))
    unsafe_measurements = (
        _replace_trace(first, unsafe_trace),
        *measurements[1:],
    )

    with pytest.raises(ValueError, match="installed census"):
        qualify_pantheon_series(census, unsafe_measurements)

    baseline = qualify_pantheon_series(census, measurements)
    replacement_trace = replace(first.trace, latency_ms=11)
    substituted = qualify_pantheon_series(
        census,
        (_replace_trace(first, replacement_trace), *measurements[1:]),
    )

    assert substituted.qualified is True
    assert substituted.measurement_set_digest != baseline.measurement_set_digest
    assert substituted.evidence_digest != baseline.evidence_digest
