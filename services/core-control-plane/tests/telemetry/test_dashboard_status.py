from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fdai.shared.telemetry.dashboard_status import (
    MetricObservation,
    PanelStatus,
    resolve_dashboard_readings,
)

DESCRIPTOR_PATH = Path(__file__).resolve().parents[4] / "docs" / "dashboards" / "phase-0-kpi.json"
PRODUCER = "fdai.shared.telemetry.metrics_derivation.derive_dashboard_metrics"
NOW = datetime(2026, 8, 31, tzinfo=UTC)


def _descriptor() -> dict[str, object]:
    return json.loads(DESCRIPTOR_PATH.read_text(encoding="utf-8"))


def _observation(
    *,
    observed_at: datetime = NOW,
    producer: str = PRODUCER,
    synthetic: bool = False,
) -> MetricObservation:
    return MetricObservation(
        metric_key="auto_resolution_rate",
        value=0.75,
        observed_at=observed_at,
        producer=producer,
        synthetic=synthetic,
    )


def _reading(observations: list[MetricObservation]):
    readings = resolve_dashboard_readings(
        _descriptor(),
        observations,
        as_of=NOW,
        live=True,
    )
    return next(item for item in readings if item.panel_id == "success.2.auto_resolution_rate")


def test_current_authoritative_observation_is_available() -> None:
    reading = _reading([_observation()])
    assert reading.status is PanelStatus.AVAILABLE
    assert reading.value == 0.75
    assert reading.reason is None


def test_missing_observation_is_unavailable_not_zero() -> None:
    reading = _reading([])
    assert reading.status is PanelStatus.UNAVAILABLE
    assert reading.value is None
    assert reading.reason == "missing_observation"


def test_stale_observation_is_unavailable() -> None:
    reading = _reading([_observation(observed_at=NOW - timedelta(hours=2))])
    assert reading.status is PanelStatus.UNAVAILABLE
    assert reading.reason == "stale_observation"


def test_conflicting_observations_are_unavailable() -> None:
    reading = _reading([_observation(), _observation()])
    assert reading.status is PanelStatus.UNAVAILABLE
    assert reading.reason == "conflicting_observations"


def test_synthetic_observation_cannot_satisfy_live_dashboard() -> None:
    reading = _reading([_observation(synthetic=True)])
    assert reading.status is PanelStatus.UNAVAILABLE
    assert reading.reason == "synthetic_observation"


def test_declared_later_phase_panel_remains_unavailable() -> None:
    readings = resolve_dashboard_readings(_descriptor(), [], as_of=NOW, live=True)
    reading = next(item for item in readings if item.panel_id == "guard.rollback_rate")
    assert reading.status is PanelStatus.UNAVAILABLE
    assert reading.value is None
    assert reading.reason == "authoritative_rollback_outcomes_not_bound"
