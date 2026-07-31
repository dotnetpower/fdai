"""Continuous impact-envelope guard and typed stop event."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from fdai.core.impact_analysis import ImpactEnvelopeRecord


class ChaosStopReason(StrEnum):
    AFFECTED_SET_EXCEEDED = "affected_set_exceeded"
    DURATION_EXCEEDED = "duration_exceeded"
    OBJECTIVE_BOUND_EXCEEDED = "objective_bound_exceeded"
    FORBIDDEN_SIGNAL = "forbidden_signal"
    TELEMETRY_INCOMPLETE = "telemetry_incomplete"
    BACKEND_UNREACHABLE = "backend_unreachable"


@dataclass(frozen=True, slots=True)
class ImpactObservation:
    observed_resources: frozenset[str]
    signals: frozenset[str]
    objective_values: Mapping[str, float]
    source_observed_at: Mapping[str, datetime]
    elapsed_seconds: float
    injector_reachable: bool = True
    recovery_reachable: bool = True


@dataclass(frozen=True, slots=True)
class ChaosStopEvent:
    run_id: str
    impact_envelope_id: str
    reason: ChaosStopReason
    observed_resources: tuple[str, ...]
    observed_signals: tuple[str, ...]
    occurred_at: datetime
    detail: str

    def to_payload(self) -> dict[str, object]:
        return {
            "event_type": "chaos.stop-triggered",
            "run_id": self.run_id,
            "impact_envelope_id": self.impact_envelope_id,
            "reason": self.reason.value,
            "observed_resources": list(self.observed_resources),
            "observed_signals": list(self.observed_signals),
            "occurred_at": self.occurred_at.isoformat(),
            "detail": self.detail,
        }


ImpactGuard = Callable[[float], Awaitable[ChaosStopEvent | None]]


def evaluate_impact_guard(
    *,
    run_id: str,
    envelope: ImpactEnvelopeRecord,
    observation: ImpactObservation,
    now: datetime,
) -> ChaosStopEvent | None:
    if not run_id.strip() or now.tzinfo is None:
        raise ValueError("guard run id and aware timestamp are required")
    stop = _stop_reason(envelope, observation, now=now)
    if stop is None:
        return None
    reason, detail = stop
    return ChaosStopEvent(
        run_id=run_id,
        impact_envelope_id=envelope.envelope_id,
        reason=reason,
        observed_resources=tuple(sorted(observation.observed_resources)),
        observed_signals=tuple(sorted(observation.signals)),
        occurred_at=now,
        detail=detail,
    )


def _stop_reason(
    envelope: ImpactEnvelopeRecord,
    observation: ImpactObservation,
    *,
    now: datetime,
) -> tuple[ChaosStopReason, str] | None:
    if not observation.observed_resources <= set(envelope.affected_resource_ids):
        return ChaosStopReason.AFFECTED_SET_EXCEEDED, "observed resource outside envelope"
    if observation.elapsed_seconds > envelope.max_duration_seconds:
        return ChaosStopReason.DURATION_EXCEEDED, "experiment duration exceeded"
    if not observation.injector_reachable or not observation.recovery_reachable:
        return ChaosStopReason.BACKEND_UNREACHABLE, "injector or recovery backend unavailable"
    forbidden = observation.signals & set(envelope.forbidden_signals)
    if forbidden:
        return ChaosStopReason.FORBIDDEN_SIGNAL, f"forbidden signal: {sorted(forbidden)[0]}"
    requirements = envelope.telemetry_requirements
    for source in requirements.required_sources:
        observed_at = observation.source_observed_at.get(source)
        if (
            observed_at is None
            or observed_at.tzinfo is None
            or (now - observed_at).total_seconds() > requirements.freshness_seconds
        ):
            return ChaosStopReason.TELEMETRY_INCOMPLETE, f"telemetry unavailable: {source}"
    for bound in envelope.objective_bounds:
        observed = observation.objective_values.get(bound.metric)
        if observed is None:
            return ChaosStopReason.TELEMETRY_INCOMPLETE, f"objective unavailable: {bound.metric}"
        if bound.lower is not None and observed < bound.lower:
            return ChaosStopReason.OBJECTIVE_BOUND_EXCEEDED, f"{bound.metric} below lower bound"
        if bound.upper is not None and observed > bound.upper:
            return ChaosStopReason.OBJECTIVE_BOUND_EXCEEDED, f"{bound.metric} above upper bound"
    return None


__all__ = [
    "ChaosStopEvent",
    "ChaosStopReason",
    "evaluate_impact_guard",
    "ImpactGuard",
    "ImpactObservation",
]
