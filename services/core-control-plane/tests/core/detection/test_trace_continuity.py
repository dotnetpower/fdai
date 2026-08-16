"""Deterministic distributed-trace continuity scenarios."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fdai.core.detection.trace_continuity import (
    TraceContinuityDetector,
    TraceContinuityReason,
    TraceContinuityState,
    TraceSpanObservation,
    TraceTopologyObservation,
)
from fdai.shared.contracts.models import IncidentCorrelation, Mode

_NOW = datetime(2026, 8, 17, 1, 0, tzinfo=UTC)
_HOPS = ("app-gateway", "application", "agent", "api-gateway", "model-endpoint")


def _span(trace_id: str, hop: str, sequence: int) -> TraceSpanObservation:
    return TraceSpanObservation(
        trace_id=trace_id,
        span_id=f"span-{sequence}",
        hop=hop,
        sequence=sequence,
        observed_at=_NOW + timedelta(seconds=sequence),
        evidence_ref=f"telemetry:row-{sequence}",
    )


def _observation(
    spans: tuple[TraceSpanObservation, ...],
    *,
    completed: bool = True,
) -> TraceTopologyObservation:
    return TraceTopologyObservation(
        topology_ref="synthetic-agent-request",
        scenario_id="scenario-001",
        resource_ref="trace-topology/synthetic-agent-request",
        window_bucket="2026-08-17T01:00Z",
        expected_hops=_HOPS,
        spans=spans,
        completed=completed,
    )


def test_preserved_context_is_continuous_and_emits_no_finding() -> None:
    detector = TraceContinuityDetector(clock=lambda: _NOW)
    observation = _observation(
        tuple(_span("trace-a", hop, sequence) for sequence, hop in enumerate(_HOPS))
    )

    result = detector.evaluate(observation)

    assert result.state is TraceContinuityState.CONTINUOUS
    assert result.reason is TraceContinuityReason.COMPLETE
    assert result.missing_hops == ()
    assert detector.to_event(result) is None


def test_regenerated_context_identifies_the_disconnected_boundary() -> None:
    detector = TraceContinuityDetector(clock=lambda: _NOW)
    observation = _observation(
        tuple(
            _span("trace-front" if sequence < 2 else "trace-back", hop, sequence)
            for sequence, hop in enumerate(_HOPS)
        )
    )

    result = detector.evaluate(observation)
    event = detector.to_event(result)

    assert result.state is TraceContinuityState.DISCONTINUOUS
    assert result.reason is TraceContinuityReason.CONTEXT_REGENERATED
    assert result.disconnected_boundaries == ("application->agent",)
    assert event is not None
    assert event.mode is Mode.SHADOW
    assert event.incident_correlation is IncidentCorrelation.CORRELATE
    assert event.correlation_id == observation.scenario_id
    assert event.payload["reason_code"] == "trace_context_regenerated"


def test_dropped_context_names_missing_hops_without_guessing_a_component() -> None:
    detector = TraceContinuityDetector(clock=lambda: _NOW)
    observation = _observation(
        (
            _span("trace-front", "app-gateway", 0),
            _span("trace-front", "application", 1),
            _span("trace-back", "api-gateway", 3),
            _span("trace-back", "model-endpoint", 4),
        )
    )

    result = detector.evaluate(observation)
    event = detector.to_event(result)

    assert result.state is TraceContinuityState.DISCONTINUOUS
    assert result.reason is TraceContinuityReason.CONTEXT_DROPPED
    assert result.missing_hops == ("agent",)
    assert event is not None
    assert event.payload["missing_hops"] == ["agent"]


def test_incomplete_or_empty_runs_remain_unknown() -> None:
    detector = TraceContinuityDetector(clock=lambda: _NOW)

    incomplete = detector.evaluate(
        _observation((_span("trace-a", "application", 1),), completed=False)
    )
    empty = detector.evaluate(_observation(()))

    assert incomplete.state is TraceContinuityState.UNKNOWN
    assert incomplete.reason is TraceContinuityReason.RUN_INCOMPLETE
    assert empty.state is TraceContinuityState.UNKNOWN
    assert empty.reason is TraceContinuityReason.NO_SPANS
    assert detector.to_event(incomplete) is None
    assert detector.to_event(empty) is None
