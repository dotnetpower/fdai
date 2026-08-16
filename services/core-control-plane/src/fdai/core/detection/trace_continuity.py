"""Deterministic continuity checks for one declared distributed trace topology.

The detector compares normalized span metadata with an ordered expected-hop
contract. It never queries a telemetry backend and never proposes or executes a
change. Discontinuities become shadow Events that re-enter event-ingest; empty
or incomplete telemetry remains unknown instead of being treated as failure.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import NAMESPACE_URL, uuid4, uuid5

from fdai.shared.contracts.models import Event, IncidentCorrelation, Mode, Severity

_DEFAULT_SOURCE = "fdai.core.detection.trace_continuity"
_EVENT_TYPE = "trace-continuity.discontinuity"
_MAX_EXPECTED_HOPS = 32
_MAX_SPANS = 512
_MAX_EVIDENCE_REFS = 100


class TraceContinuityState(StrEnum):
    """Terminal detector state without implying a root cause."""

    CONTINUOUS = "continuous"
    DISCONTINUOUS = "discontinuous"
    UNKNOWN = "unknown"


class TraceContinuityReason(StrEnum):
    """Evidence-bounded reason for the detector state."""

    COMPLETE = "trace_complete"
    CONTEXT_REGENERATED = "trace_context_regenerated"
    CONTEXT_DROPPED = "trace_context_dropped"
    HOP_ORDER_INVALID = "trace_hop_order_invalid"
    RUN_INCOMPLETE = "trace_run_incomplete"
    NO_SPANS = "trace_spans_unavailable"


@dataclass(frozen=True, slots=True)
class TraceSpanObservation:
    """One normalized span identity used by the continuity detector."""

    trace_id: str
    span_id: str
    hop: str
    sequence: int
    observed_at: datetime
    evidence_ref: str

    def __post_init__(self) -> None:
        for name, value in (
            ("trace_id", self.trace_id),
            ("span_id", self.span_id),
            ("hop", self.hop),
            ("evidence_ref", self.evidence_ref),
        ):
            if not value or len(value) > 512:
                raise ValueError(f"TraceSpanObservation.{name} MUST be bounded non-empty text")
        if self.sequence < 0:
            raise ValueError("TraceSpanObservation.sequence MUST be non-negative")
        if self.observed_at.tzinfo is None:
            raise ValueError("TraceSpanObservation.observed_at MUST be timezone-aware")


@dataclass(frozen=True, slots=True)
class TraceTopologyObservation:
    """One completed or pending scenario run against an expected topology."""

    topology_ref: str
    scenario_id: str
    resource_ref: str
    window_bucket: str
    expected_hops: tuple[str, ...]
    spans: tuple[TraceSpanObservation, ...]
    completed: bool

    def __post_init__(self) -> None:
        for name, value in (
            ("topology_ref", self.topology_ref),
            ("scenario_id", self.scenario_id),
            ("resource_ref", self.resource_ref),
            ("window_bucket", self.window_bucket),
        ):
            if not value or len(value) > 512:
                raise ValueError(f"TraceTopologyObservation.{name} MUST be bounded non-empty text")
        if not 2 <= len(self.expected_hops) <= _MAX_EXPECTED_HOPS:
            raise ValueError(
                "TraceTopologyObservation.expected_hops MUST contain 2 to "
                f"{_MAX_EXPECTED_HOPS} hops"
            )
        if len(set(self.expected_hops)) != len(self.expected_hops):
            raise ValueError("TraceTopologyObservation.expected_hops MUST be unique")
        if any(not hop or len(hop) > 128 for hop in self.expected_hops):
            raise ValueError("TraceTopologyObservation.expected_hops MUST be bounded text")
        if len(self.spans) > _MAX_SPANS:
            raise ValueError(
                f"TraceTopologyObservation.spans MUST contain at most {_MAX_SPANS} items"
            )


@dataclass(frozen=True, slots=True)
class TraceContinuityResult:
    """Replayable continuity decision with bounded evidence references."""

    state: TraceContinuityState
    reason: TraceContinuityReason
    topology_ref: str
    scenario_id: str
    resource_ref: str
    window_bucket: str
    expected_hops: tuple[str, ...]
    observed_hops: tuple[str, ...]
    missing_hops: tuple[str, ...]
    trace_ids: tuple[str, ...]
    disconnected_boundaries: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    observed_at: datetime | None


class TraceContinuityDetector:
    """Evaluate trace topology metadata without backend or action authority."""

    def __init__(
        self,
        *,
        detector_id: str = "distributed-trace-continuity-v1",
        source: str = _DEFAULT_SOURCE,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not detector_id or len(detector_id) > 128:
            raise ValueError("trace continuity detector_id MUST be bounded non-empty text")
        if not source:
            raise ValueError("trace continuity source MUST be non-empty")
        self._detector_id = detector_id
        self._source = source
        self._clock = clock or (lambda: datetime.now(tz=UTC))

    def evaluate(self, observation: TraceTopologyObservation) -> TraceContinuityResult:
        """Return a deterministic state; incomplete telemetry remains unknown."""
        if not observation.completed:
            return self._result(
                observation,
                state=TraceContinuityState.UNKNOWN,
                reason=TraceContinuityReason.RUN_INCOMPLETE,
            )
        if not observation.spans:
            return self._result(
                observation,
                state=TraceContinuityState.UNKNOWN,
                reason=TraceContinuityReason.NO_SPANS,
            )

        expected = observation.expected_hops
        by_trace: dict[str, list[TraceSpanObservation]] = {}
        for span in observation.spans:
            by_trace.setdefault(span.trace_id, []).append(span)
        ordered_by_trace = {
            trace_id: tuple(sorted(spans, key=_span_order)) for trace_id, spans in by_trace.items()
        }
        if any(_contains_in_order(spans, expected) for spans in ordered_by_trace.values()):
            return self._result(
                observation,
                state=TraceContinuityState.CONTINUOUS,
                reason=TraceContinuityReason.COMPLETE,
            )

        observed_hops = {span.hop for span in observation.spans}
        missing_hops = tuple(hop for hop in expected if hop not in observed_hops)
        if missing_hops:
            reason = TraceContinuityReason.CONTEXT_DROPPED
        elif len(ordered_by_trace) > 1:
            reason = TraceContinuityReason.CONTEXT_REGENERATED
        else:
            reason = TraceContinuityReason.HOP_ORDER_INVALID
        return self._result(
            observation,
            state=TraceContinuityState.DISCONTINUOUS,
            reason=reason,
        )

    def to_event(
        self,
        result: TraceContinuityResult,
        *,
        mode: Mode = Mode.SHADOW,
    ) -> Event | None:
        """Normalize only a discontinuity into a governed shadow Event."""
        if result.state is not TraceContinuityState.DISCONTINUOUS:
            return None
        now = self._clock()
        return Event(
            schema_version="1.0.0",
            event_id=uuid4(),
            idempotency_key=str(
                uuid5(
                    NAMESPACE_URL,
                    ":".join(
                        (
                            "fdai-trace-continuity",
                            self._detector_id,
                            result.topology_ref,
                            result.scenario_id,
                            result.window_bucket,
                        )
                    ),
                )
            ),
            correlation_id=result.scenario_id,
            source=self._source,
            event_type=_EVENT_TYPE,
            resource_ref=result.resource_ref,
            payload={
                "kind": "trace_continuity",
                "detector_id": self._detector_id,
                "severity": Severity.HIGH.value,
                "reason_code": result.reason.value,
                "topology_ref": result.topology_ref,
                "expected_hops": list(result.expected_hops),
                "observed_hops": list(result.observed_hops),
                "missing_hops": list(result.missing_hops),
                "trace_ids": list(result.trace_ids),
                "disconnected_boundaries": list(result.disconnected_boundaries),
                "evidence_refs": list(result.evidence_refs),
                "window_bucket": result.window_bucket,
            },
            detected_at=result.observed_at or now,
            ingested_at=now,
            incident_correlation=IncidentCorrelation.CORRELATE,
            mode=mode,
        )

    def _result(
        self,
        observation: TraceTopologyObservation,
        *,
        state: TraceContinuityState,
        reason: TraceContinuityReason,
    ) -> TraceContinuityResult:
        ordered_spans = tuple(sorted(observation.spans, key=_span_order))
        observed_hops = tuple(
            hop
            for hop in observation.expected_hops
            if any(span.hop == hop for span in ordered_spans)
        )
        missing_hops = tuple(
            hop for hop in observation.expected_hops if hop not in set(observed_hops)
        )
        trace_ids = tuple(sorted({span.trace_id for span in ordered_spans}))
        evidence_refs = tuple(
            sorted({span.evidence_ref for span in ordered_spans})[:_MAX_EVIDENCE_REFS]
        )
        return TraceContinuityResult(
            state=state,
            reason=reason,
            topology_ref=observation.topology_ref,
            scenario_id=observation.scenario_id,
            resource_ref=observation.resource_ref,
            window_bucket=observation.window_bucket,
            expected_hops=observation.expected_hops,
            observed_hops=observed_hops,
            missing_hops=missing_hops,
            trace_ids=trace_ids,
            disconnected_boundaries=_disconnected_boundaries(
                ordered_spans,
                observation.expected_hops,
            ),
            evidence_refs=evidence_refs,
            observed_at=max((span.observed_at for span in ordered_spans), default=None),
        )


def _span_order(span: TraceSpanObservation) -> tuple[int, datetime, str, str]:
    return span.sequence, span.observed_at, span.trace_id, span.span_id


def _contains_in_order(
    spans: tuple[TraceSpanObservation, ...],
    expected_hops: tuple[str, ...],
) -> bool:
    expected_index = 0
    for span in spans:
        if span.hop == expected_hops[expected_index]:
            expected_index += 1
            if expected_index == len(expected_hops):
                return True
    return False


def _disconnected_boundaries(
    spans: tuple[TraceSpanObservation, ...],
    expected_hops: tuple[str, ...],
) -> tuple[str, ...]:
    first_by_hop: dict[str, TraceSpanObservation] = {}
    for span in spans:
        first_by_hop.setdefault(span.hop, span)
    boundaries: list[str] = []
    for upstream, downstream in zip(expected_hops, expected_hops[1:], strict=False):
        left = first_by_hop.get(upstream)
        right = first_by_hop.get(downstream)
        if left is not None and right is not None and left.trace_id != right.trace_id:
            boundaries.append(f"{upstream}->{downstream}")
    return tuple(boundaries)


__all__ = [
    "TraceContinuityDetector",
    "TraceContinuityReason",
    "TraceContinuityResult",
    "TraceContinuityState",
    "TraceSpanObservation",
    "TraceTopologyObservation",
]
