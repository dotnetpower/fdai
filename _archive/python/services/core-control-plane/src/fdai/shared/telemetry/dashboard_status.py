"""Resolve dashboard panel availability without inventing missing metric values."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any


class PanelStatus(StrEnum):
    """Availability states exposed by the dashboard projection."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class MetricObservation:
    """One normalized metric value from an authoritative producer."""

    metric_key: str
    value: float
    observed_at: datetime
    producer: str
    synthetic: bool = False

    def __post_init__(self) -> None:
        if not self.metric_key.strip() or not self.producer.strip():
            raise ValueError("metric_key and producer MUST be non-empty")
        if self.observed_at.tzinfo is None:
            raise ValueError("metric observation timestamp MUST include timezone")
        if not math.isfinite(self.value):
            raise ValueError("metric observation value MUST be finite")


@dataclass(frozen=True, slots=True)
class PanelReading:
    """One panel value or an explicit reason that no value is eligible."""

    panel_id: str
    status: PanelStatus
    value: float | None
    reason: str | None


def resolve_dashboard_readings(
    descriptor: Mapping[str, Any],
    observations: Sequence[MetricObservation],
    *,
    as_of: datetime,
    live: bool,
) -> tuple[PanelReading, ...]:
    """Resolve panels and fail closed when a metric observation is not trustworthy."""

    if as_of.tzinfo is None:
        raise ValueError("dashboard as_of timestamp MUST include timezone")

    by_key: dict[str, MetricObservation | None] = {}
    for observation in observations:
        if observation.metric_key in by_key:
            by_key[observation.metric_key] = None
        else:
            by_key[observation.metric_key] = observation

    readings: list[PanelReading] = []
    for panel in descriptor["panels"]:
        panel_id = str(panel["id"])
        source = panel["source"]
        if source["kind"] == "unavailable":
            readings.append(
                PanelReading(
                    panel_id=panel_id,
                    status=PanelStatus.UNAVAILABLE,
                    value=None,
                    reason=str(source["reason"]),
                )
            )
            continue

        metric_key = str(source["field"])
        candidate = by_key.get(metric_key)
        if metric_key in by_key and candidate is None:
            reason = "conflicting_observations"
        elif candidate is None:
            reason = "missing_observation"
        elif candidate.producer != source["producer"]:
            reason = "producer_mismatch"
        elif candidate.observed_at > as_of:
            reason = "observation_from_future"
        elif as_of - candidate.observed_at > timedelta(seconds=int(source["max_age_seconds"])):
            reason = "stale_observation"
        elif live and candidate.synthetic:
            reason = "synthetic_observation"
        else:
            readings.append(
                PanelReading(
                    panel_id=panel_id,
                    status=PanelStatus.AVAILABLE,
                    value=candidate.value,
                    reason=None,
                )
            )
            continue

        readings.append(
            PanelReading(
                panel_id=panel_id,
                status=PanelStatus.UNAVAILABLE,
                value=None,
                reason=reason,
            )
        )

    return tuple(readings)


__all__ = [
    "MetricObservation",
    "PanelReading",
    "PanelStatus",
    "resolve_dashboard_readings",
]
