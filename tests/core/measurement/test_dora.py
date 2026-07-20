"""Deterministic DORA deployment metric aggregation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fdai.core.measurement import DeploymentObservation, compute_dora

_END = datetime(2026, 7, 20, tzinfo=UTC)
_START = _END - timedelta(days=10)


def _deployment(
    deployment_id: str,
    *,
    deployed_days_ago: int,
    lead_hours: int = 2,
    failed: bool = False,
    recovery_hours: int | None = None,
) -> DeploymentObservation:
    deployed_at = _END - timedelta(days=deployed_days_ago)
    return DeploymentObservation(
        deployment_id=deployment_id,
        committed_at=deployed_at - timedelta(hours=lead_hours),
        deployed_at=deployed_at,
        failed=failed,
        recovered_at=(
            deployed_at + timedelta(hours=recovery_hours) if recovery_hours is not None else None
        ),
    )


def test_computes_all_four_dora_metrics_and_deduplicates() -> None:
    deployments = (
        _deployment("d1", deployed_days_ago=1, lead_hours=1),
        _deployment("d2", deployed_days_ago=2, lead_hours=2, failed=True, recovery_hours=1),
        _deployment("d3", deployed_days_ago=3, lead_hours=3, failed=True),
        _deployment("d1", deployed_days_ago=1, lead_hours=1),
        _deployment("outside", deployed_days_ago=20),
    )

    summary = compute_dora(deployments, window_start=_START, window_end=_END)

    assert summary.deployment_count == 3
    assert summary.deployment_frequency_per_day == pytest.approx(0.3)
    assert summary.change_failure_rate == pytest.approx(2 / 3)
    assert summary.lead_time_mean_seconds == 7_200
    assert summary.lead_time_median_seconds == 7_200
    assert summary.lead_time_p90_seconds == 10_800
    assert summary.failed_change_recovery_mean_seconds == 3_600
    assert summary.unrecovered_failure_count == 1


def test_empty_window_reports_unmeasured_rates_honestly() -> None:
    summary = compute_dora((), window_start=_START, window_end=_END)
    assert summary.deployment_count == 0
    assert summary.deployment_frequency_per_day == 0
    assert summary.change_failure_rate is None
    assert summary.lead_time_mean_seconds is None
    assert summary.failed_change_recovery_mean_seconds is None


def test_invalid_temporal_records_are_counted_not_folded() -> None:
    invalid = DeploymentObservation(
        deployment_id="bad",
        committed_at=_END,
        deployed_at=_END - timedelta(hours=1),
        failed=False,
    )
    summary = compute_dora((invalid,), window_start=_START, window_end=_END)
    assert summary.invalid_count == 1
    assert summary.deployment_count == 0


def test_rejects_invalid_window_and_recovery_shape() -> None:
    with pytest.raises(ValueError, match="window MUST be positive"):
        compute_dora((), window_start=_END, window_end=_START)
    with pytest.raises(ValueError, match="only failed deployments"):
        DeploymentObservation(
            deployment_id="bad",
            committed_at=_START,
            deployed_at=_END,
            failed=False,
            recovered_at=_END,
        )
