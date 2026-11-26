"""Evidence-bounded RCA for distributed trace continuity findings."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.detection.trace_continuity import (
    TraceContinuityDetector,
    TraceSpanObservation,
    TraceTopologyObservation,
)
from fdai.core.rca import (
    CauseDomain,
    CitationKind,
    RcaOutcome,
    RcaTier,
    TraceCauseEvidence,
    TraceRcaCause,
    analyze_trace_continuity_cause,
)

_NOW = datetime(2026, 9, 9, 0, 0, tzinfo=UTC)
_HOPS = ("app-gateway", "application", "agent", "api-gateway", "model-endpoint")


def _span(trace_id: str, hop: str, sequence: int) -> TraceSpanObservation:
    return TraceSpanObservation(
        trace_id=trace_id,
        span_id=f"span-{sequence}",
        hop=hop,
        sequence=sequence,
        observed_at=_NOW + timedelta(seconds=sequence),
        evidence_ref=f"telemetry:span-{sequence}",
    )


def _result(*, missing_hop: str | None = None, regenerate_at: int | None = None):
    spans = tuple(
        _span(
            "trace-front" if regenerate_at is None or sequence < regenerate_at else "trace-back",
            hop,
            sequence,
        )
        for sequence, hop in enumerate(_HOPS)
        if hop != missing_hop
    )
    return TraceContinuityDetector(clock=lambda: _NOW).evaluate(
        TraceTopologyObservation(
            topology_ref="synthetic-agent-request",
            scenario_id="scenario-trace-1",
            resource_ref="trace-topology/synthetic-agent-request",
            window_bucket="2026-09-09T00:00Z",
            expected_hops=_HOPS,
            spans=spans,
            completed=True,
        )
    )


def _order_invalid_result():
    spans = tuple(
        _span("trace-front", hop, sequence)
        for sequence, hop in (
            (0, "app-gateway"),
            (1, "application"),
            (3, "agent"),
            (2, "api-gateway"),
            (4, "model-endpoint"),
        )
    )
    return TraceContinuityDetector(clock=lambda: _NOW).evaluate(
        TraceTopologyObservation(
            topology_ref="synthetic-agent-request",
            scenario_id="scenario-trace-1",
            resource_ref="trace-topology/synthetic-agent-request",
            window_bucket="2026-09-09T00:00Z",
            expected_hops=_HOPS,
            spans=spans,
            completed=True,
        )
    )


def _evidence(
    cause: TraceRcaCause,
    *affected_items: str,
) -> TraceCauseEvidence:
    return TraceCauseEvidence(
        cause=cause,
        topology_ref="synthetic-agent-request",
        scenario_id="scenario-trace-1",
        window_bucket="2026-09-09T00:00Z",
        observed_at=_NOW + timedelta(seconds=4),
        confidence=0.8,
        affected_items=affected_items,
        evidence_refs=(f"telemetry:cause:{cause.value}",),
    )


def test_header_propagation_cause_requires_the_observed_boundary() -> None:
    result = analyze_trace_continuity_cause(
        _result(regenerate_at=2),
        cause_evidence=(
            _evidence(
                TraceRcaCause.HEADER_PROPAGATION,
                "application->agent",
            ),
        ),
    )

    assert result.outcome is RcaOutcome.GROUNDED
    assert result.hypothesis is not None
    assert result.hypothesis.tier is RcaTier.T1
    assert result.hypothesis.cause_domain is CauseDomain.UNKNOWN
    assert "application->agent" in result.hypothesis.cause
    assert result.hypothesis.remediation_ref is None
    assert all(citation.kind is CitationKind.TELEMETRY for citation in result.hypothesis.citations)


@pytest.mark.parametrize(
    ("cause", "domain", "cause_text"),
    [
        (TraceRcaCause.INSTRUMENTATION, CauseDomain.APPLICATION, "instrumentation"),
        (TraceRcaCause.COLLECTOR, CauseDomain.SHARED_DEPENDENCY, "collector"),
    ],
)
def test_missing_hop_distinguishes_independently_cited_causes(
    cause: TraceRcaCause,
    domain: CauseDomain,
    cause_text: str,
) -> None:
    result = analyze_trace_continuity_cause(
        _result(missing_hop="agent"),
        cause_evidence=(_evidence(cause, "agent"),),
    )

    assert result.outcome is RcaOutcome.GROUNDED
    assert result.hypothesis is not None
    assert result.hypothesis.cause_domain is domain
    assert cause_text in result.hypothesis.cause
    assert result.hypothesis.remediation_ref is None


def test_dropped_context_can_cite_an_adjacent_header_boundary() -> None:
    result = analyze_trace_continuity_cause(
        _result(missing_hop="agent"),
        cause_evidence=(
            _evidence(
                TraceRcaCause.HEADER_PROPAGATION,
                "application->agent",
            ),
        ),
    )

    assert result.outcome is RcaOutcome.GROUNDED
    assert result.hypothesis is not None
    assert "header" not in result.hypothesis.cause
    assert "context propagation" in result.hypothesis.cause


def test_missing_cause_evidence_holds_for_review() -> None:
    result = analyze_trace_continuity_cause(
        _result(missing_hop="agent"),
        cause_evidence=(),
    )

    assert result.outcome is RcaOutcome.ABSTAINED
    assert result.reason == "trace_cause_evidence_missing"


def test_conflicting_cause_evidence_holds_for_review() -> None:
    result = analyze_trace_continuity_cause(
        _result(missing_hop="agent"),
        cause_evidence=(
            _evidence(TraceRcaCause.INSTRUMENTATION, "agent"),
            _evidence(TraceRcaCause.COLLECTOR, "agent"),
        ),
    )

    assert result.outcome is RcaOutcome.ABSTAINED
    assert result.reason == "trace_cause_evidence_conflicting"


def test_mismatched_cause_scope_holds_for_review() -> None:
    result = analyze_trace_continuity_cause(
        _result(regenerate_at=2),
        cause_evidence=(
            _evidence(
                TraceRcaCause.HEADER_PROPAGATION,
                "agent->api-gateway",
            ),
        ),
    )

    assert result.outcome is RcaOutcome.ABSTAINED
    assert result.reason == "trace_cause_evidence_scope_mismatch"


def test_hop_order_does_not_guess_an_offending_instrumentation_hop() -> None:
    result = analyze_trace_continuity_cause(
        _order_invalid_result(),
        cause_evidence=(_evidence(TraceRcaCause.INSTRUMENTATION, "agent"),),
    )

    assert result.outcome is RcaOutcome.ABSTAINED
    assert result.reason == "trace_cause_evidence_scope_mismatch"


def test_continuous_trace_never_produces_a_cause() -> None:
    result = analyze_trace_continuity_cause(
        _result(),
        cause_evidence=(_evidence(TraceRcaCause.INSTRUMENTATION, "agent"),),
    )

    assert result.outcome is RcaOutcome.ABSTAINED
    assert result.reason == "trace_not_discontinuous"


def test_invalid_confidence_configuration_is_never_hidden_by_an_early_hold() -> None:
    with pytest.raises(ValueError, match="min_confidence MUST be in"):
        analyze_trace_continuity_cause(
            _result(),
            cause_evidence=(),
            min_confidence=1.1,
        )


def test_combined_trace_citations_hold_instead_of_truncating() -> None:
    continuity = replace(
        _result(missing_hop="agent"),
        evidence_refs=tuple(f"telemetry:continuity:{index}" for index in range(100)),
    )
    cause = replace(
        _evidence(TraceRcaCause.INSTRUMENTATION, "agent"),
        evidence_refs=tuple(f"telemetry:cause:{index}" for index in range(100)),
    )

    result = analyze_trace_continuity_cause(
        continuity,
        cause_evidence=(cause,),
    )

    assert result.outcome is RcaOutcome.ABSTAINED
    assert result.reason == "trace_citation_limit_exceeded"


def test_trace_cause_evidence_is_bounded_and_unique() -> None:
    with pytest.raises(ValueError, match="affected_items MUST be unique"):
        _evidence(TraceRcaCause.INSTRUMENTATION, "agent", "agent")

    with pytest.raises(ValueError, match="evidence_refs MUST contain 1"):
        TraceCauseEvidence(
            cause=TraceRcaCause.COLLECTOR,
            topology_ref="synthetic-agent-request",
            scenario_id="scenario-trace-1",
            window_bucket="2026-09-09T00:00Z",
            observed_at=_NOW,
            confidence=0.8,
            affected_items=("agent",),
            evidence_refs=(),
        )


def test_trace_cause_evidence_rejects_whitespace_and_canonicalizes_order() -> None:
    with pytest.raises(ValueError, match="bounded non-empty text"):
        _evidence(TraceRcaCause.INSTRUMENTATION, " agent")

    evidence = TraceCauseEvidence(
        cause=TraceRcaCause.HEADER_PROPAGATION,
        topology_ref="synthetic-agent-request",
        scenario_id="scenario-trace-1",
        window_bucket="2026-09-09T00:00Z",
        observed_at=_NOW,
        confidence=0.8,
        affected_items=("agent->api-gateway", "application->agent"),
        evidence_refs=("telemetry:z", "telemetry:a"),
    )

    assert evidence.affected_items == ("agent->api-gateway", "application->agent")
    assert evidence.evidence_refs == ("telemetry:a", "telemetry:z")


@pytest.mark.parametrize(
    "change",
    [
        {"topology_ref": "other-topology"},
        {"scenario_id": "other-scenario"},
        {"window_bucket": "other-window"},
        {"observed_at": _NOW + timedelta(seconds=5)},
    ],
)
def test_trace_cause_evidence_cannot_replay_across_scope_or_time(
    change: dict[str, object],
) -> None:
    cause = replace(
        _evidence(TraceRcaCause.INSTRUMENTATION, "agent"),
        **change,
    )

    result = analyze_trace_continuity_cause(
        _result(missing_hop="agent"),
        cause_evidence=(cause,),
    )

    assert result.outcome is RcaOutcome.ABSTAINED
    assert result.reason == "trace_cause_evidence_scope_mismatch"


def test_stale_trace_cause_evidence_holds_with_a_bounded_age() -> None:
    cause = replace(
        _evidence(TraceRcaCause.INSTRUMENTATION, "agent"),
        observed_at=_NOW - timedelta(seconds=301),
    )

    result = analyze_trace_continuity_cause(
        _result(missing_hop="agent"),
        cause_evidence=(cause,),
    )

    assert result.outcome is RcaOutcome.ABSTAINED
    assert result.reason == "trace_cause_evidence_scope_mismatch"

    with pytest.raises(ValueError, match="max_evidence_age MUST be positive"):
        analyze_trace_continuity_cause(
            _result(missing_hop="agent"),
            cause_evidence=(cause,),
            max_evidence_age=timedelta(0),
        )
    with pytest.raises(ValueError, match="min_confidence"):
        analyze_trace_continuity_cause(
            _result(missing_hop="agent"),
            cause_evidence=(cause,),
            min_confidence=True,
        )
    with pytest.raises(ValueError, match="confidence MUST be finite"):
        TraceCauseEvidence(
            cause=TraceRcaCause.COLLECTOR,
            topology_ref="synthetic-agent-request",
            scenario_id="scenario-trace-1",
            window_bucket="2026-09-09T00:00Z",
            observed_at=_NOW,
            confidence=True,
            affected_items=("agent",),
            evidence_refs=("telemetry:cause:collector",),
        )

    with pytest.raises(ValueError, match="at most 24 hours"):
        analyze_trace_continuity_cause(
            _result(missing_hop="agent"),
            cause_evidence=(cause,),
            max_evidence_age=timedelta(hours=24, microseconds=1),
        )


def test_trace_cause_confidence_is_bounded_by_evidence_and_t1_ceiling() -> None:
    cause = replace(
        _evidence(TraceRcaCause.INSTRUMENTATION, "agent"),
        confidence=0.95,
    )

    grounded = analyze_trace_continuity_cause(
        _result(missing_hop="agent"),
        cause_evidence=(cause,),
    )
    held = analyze_trace_continuity_cause(
        _result(missing_hop="agent"),
        cause_evidence=(cause,),
        min_confidence=0.9,
    )

    assert grounded.hypothesis is not None
    assert grounded.hypothesis.confidence == 0.85
    assert held.outcome is RcaOutcome.ABSTAINED
    assert held.reason == "confidence_0.85_below_min_0.90"

    with pytest.raises(ValueError, match="confidence MUST be finite"):
        replace(cause, confidence=float("nan"))


def test_default_trace_confidence_floor_holds_zero_confidence_evidence() -> None:
    cause = replace(
        _evidence(TraceRcaCause.INSTRUMENTATION, "agent"),
        confidence=0.0,
    )

    result = analyze_trace_continuity_cause(
        _result(missing_hop="agent"),
        cause_evidence=(cause,),
    )

    assert result.outcome is RcaOutcome.ABSTAINED
    assert result.reason == "confidence_0.00_below_min_0.50"
