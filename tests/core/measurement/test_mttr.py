"""Tests for the pure MTTR aggregator (KPI 3a)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from fdai.core.measurement.mttr import (
    MttrSummary,
    compute_mttr,
)
from fdai.shared.contracts.models import Incident, IncidentSeverity, IncidentState

_BASE = datetime(2026, 7, 13, 0, 0, 0, tzinfo=UTC)
_EVENT_ID = UUID("00000000-0000-0000-0000-000000000abc")


def _incident(
    *,
    key: str,
    opened_offset_s: float = 0.0,
    resolved_offset_s: float | None = None,
) -> Incident:
    """Build a minimal valid incident with a given open/resolve timing."""
    opened_at = _BASE + timedelta(seconds=opened_offset_s)
    resolved_at = (
        None if resolved_offset_s is None else _BASE + timedelta(seconds=resolved_offset_s)
    )
    return Incident(
        schema_version="1.0.0",
        incident_id=UUID(int=abs(hash(key)) % (2**128)),
        state=IncidentState.RESOLVED if resolved_at else IncidentState.OPEN,
        severity=IncidentSeverity.SEV2,
        opened_at=opened_at,
        resolved_at=resolved_at,
        correlation_keys=(key,),
        member_event_ids=(_EVENT_ID,),
    )


def test_empty_input_is_unmeasured() -> None:
    summary = compute_mttr([])
    assert summary == MttrSummary(resolved_count=0, unresolved_count=0, invalid_count=0)
    assert summary.measured is False
    assert summary.mean_seconds is None
    assert summary.median_seconds is None
    assert summary.p90_seconds is None


def test_unresolved_incidents_are_counted_not_measured() -> None:
    summary = compute_mttr(
        [
            _incident(key="a", resolved_offset_s=None),
            _incident(key="b", resolved_offset_s=None),
        ]
    )
    assert summary.resolved_count == 0
    assert summary.unresolved_count == 2
    assert summary.measured is False
    assert summary.mean_seconds is None


def test_single_resolved_incident() -> None:
    summary = compute_mttr([_incident(key="a", opened_offset_s=0, resolved_offset_s=300)])
    assert summary.resolved_count == 1
    assert summary.mean_seconds == 300.0
    assert summary.median_seconds == 300.0
    # Nearest-rank p90 of a single value is that value.
    assert summary.p90_seconds == 300.0
    assert summary.durations_seconds == (300.0,)


def test_mean_median_p90_over_ten_incidents() -> None:
    # Durations 60, 120, ..., 600 seconds.
    incidents = [
        _incident(key=f"i{i}", opened_offset_s=0, resolved_offset_s=60 * i) for i in range(1, 11)
    ]
    summary = compute_mttr(incidents)
    assert summary.resolved_count == 10
    assert summary.mean_seconds == pytest.approx(330.0)  # mean of 60..600
    assert summary.median_seconds == pytest.approx(330.0)  # (300+360)/2
    # Nearest-rank p90 of n=10: rank = ceil(0.9*10)=9 -> 9th value = 540.
    assert summary.p90_seconds == 540.0


def test_resolved_before_opened_is_invalid_not_negative() -> None:
    summary = compute_mttr(
        [
            _incident(key="ok", opened_offset_s=0, resolved_offset_s=120),
            _incident(key="bad", opened_offset_s=500, resolved_offset_s=100),
        ]
    )
    assert summary.resolved_count == 1
    assert summary.invalid_count == 1
    assert summary.mean_seconds == 120.0


def test_zero_duration_is_valid() -> None:
    summary = compute_mttr([_incident(key="a", opened_offset_s=10, resolved_offset_s=10)])
    assert summary.resolved_count == 1
    assert summary.mean_seconds == 0.0
    assert summary.measured is True


def test_mixed_resolved_unresolved_invalid_counts() -> None:
    summary = compute_mttr(
        [
            _incident(key="r1", opened_offset_s=0, resolved_offset_s=100),
            _incident(key="r2", opened_offset_s=0, resolved_offset_s=200),
            _incident(key="u1", resolved_offset_s=None),
            _incident(key="bad", opened_offset_s=50, resolved_offset_s=10),
        ]
    )
    assert summary.resolved_count == 2
    assert summary.unresolved_count == 1
    assert summary.invalid_count == 1
    assert summary.durations_seconds == (100.0, 200.0)
