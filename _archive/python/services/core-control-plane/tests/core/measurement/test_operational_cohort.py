"""Prospective operational cohort aggregation tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fdai.core.measurement.cohort_claim_policy import (
    COHORT_CLAIM_POLICY_PATH,
    load_cohort_claim_policy,
)
from fdai.core.measurement.operational_cohort import (
    OperationalCohortArmBatch,
    OperationalGuardObservation,
    OperationalMetricObservation,
    _zero_threshold_basis_points,
    aggregate_operational_cohort_arm,
)
from fdai_service_contracts.baseline_cohort import CohortArm

REPO_ROOT = Path(__file__).resolve().parents[5]
POLICY = load_cohort_claim_policy(REPO_ROOT / COHORT_CLAIM_POLICY_PATH)
REVISION = "0123456789abcdef0123456789abcdef01234567"
START = datetime(2026, 6, 1, tzinfo=UTC)
END = START + timedelta(days=30)


def _digest(index: int) -> str:
    return f"sha256:{index:064x}"


def _metric(
    metric_id: str,
    index: int,
    *,
    value: float,
    cluster: int | None = None,
    observed_at: datetime = START + timedelta(days=1),
) -> OperationalMetricObservation:
    return OperationalMetricObservation(
        metric_id=metric_id,
        observation_digest=_digest(index + 10_000),
        source_cluster_digest=_digest(index if cluster is None else cluster),
        value=value,
        observed_at=observed_at,
    )


def _guard(
    guard_id: str,
    index: int,
    *,
    breached: bool = False,
    cluster: int | None = None,
) -> OperationalGuardObservation:
    return OperationalGuardObservation(
        guard_id=guard_id,
        observation_digest=_digest(index + 20_000),
        source_cluster_digest=_digest(index if cluster is None else cluster),
        breached=breached,
        observed_at=START + timedelta(days=1),
    )


def _batch(
    *,
    metric_count: int = 30,
    guard_count: int = 30,
    synthetic: bool = False,
) -> OperationalCohortArmBatch:
    metrics: list[OperationalMetricObservation] = []
    for metric_offset, metric_id in enumerate(POLICY.required_metric_ids, start=1):
        for index in range(metric_count):
            value = float((index + metric_offset) % 7 + 1)
            if metric_id == "auto_resolution_rate":
                value = float(index % 2)
            metrics.append(
                _metric(
                    metric_id,
                    metric_offset * 1_000 + index,
                    value=value,
                )
            )
    guards = tuple(
        _guard(guard_id, guard_offset * 1_000 + index)
        for guard_offset, guard_id in enumerate(POLICY.required_guard_ids, start=20)
        for index in range(guard_count)
    )
    return OperationalCohortArmBatch(
        arm=CohortArm.BASELINE,
        fdai_revision=REVISION,
        window_start=START,
        window_end=END,
        synthetic=synthetic,
        metrics=tuple(metrics),
        guards=guards,
    )


def test_complete_real_observations_produce_denominator_aware_arm_facts() -> None:
    batch = _batch(metric_count=35, guard_count=40)

    first = aggregate_operational_cohort_arm(batch, POLICY)
    second = aggregate_operational_cohort_arm(batch, POLICY)

    assert first == second
    assert first.sample_count == 35
    assert first.synthetic is False
    assert first.metrics_complete is True
    assert {metric.sample_size for metric in first.metrics} == {35}
    assert {guard.sample_size for guard in first.guards} == {40}
    assert all(metric.confidence_level_basis_points == 9_500 for metric in first.metrics)
    assert all(not guard.breached for guard in first.guards)
    auto_resolution = next(
        metric for metric in first.metrics if metric.metric_id == "auto_resolution_rate"
    )
    assert 0 <= auto_resolution.lower_bound < auto_resolution.absolute_value
    assert auto_resolution.absolute_value < auto_resolution.upper_bound <= 1


def test_each_required_measure_controls_the_effective_sample_floor() -> None:
    batch = _batch()
    missing_metric = POLICY.required_metric_ids[-1]
    reduced = OperationalCohortArmBatch(
        arm=batch.arm,
        fdai_revision=batch.fdai_revision,
        window_start=batch.window_start,
        window_end=batch.window_end,
        synthetic=batch.synthetic,
        metrics=tuple(
            row
            for row in batch.metrics
            if row.metric_id != missing_metric
            or int(row.source_cluster_digest.removeprefix("sha256:"), 16) % 1_000 < 29
        ),
        guards=batch.guards,
    )

    result = aggregate_operational_cohort_arm(reduced, POLICY)

    assert result.sample_count == 29
    assert (
        next(metric.sample_size for metric in result.metrics if metric.metric_id == missing_metric)
        == 29
    )


def test_an_absent_required_measure_keeps_the_arm_incomplete() -> None:
    batch = _batch()
    missing_metric = POLICY.required_metric_ids[-1]
    reduced = OperationalCohortArmBatch(
        arm=batch.arm,
        fdai_revision=batch.fdai_revision,
        window_start=batch.window_start,
        window_end=batch.window_end,
        synthetic=batch.synthetic,
        metrics=tuple(row for row in batch.metrics if row.metric_id != missing_metric),
        guards=batch.guards,
    )

    result = aggregate_operational_cohort_arm(reduced, POLICY)

    assert result.sample_count == 0
    assert result.metrics_complete is False
    assert missing_metric not in {metric.metric_id for metric in result.metrics}


def test_an_identical_retry_does_not_add_statistical_weight() -> None:
    batch = _batch()
    retried = OperationalCohortArmBatch(
        arm=batch.arm,
        fdai_revision=batch.fdai_revision,
        window_start=batch.window_start,
        window_end=batch.window_end,
        synthetic=batch.synthetic,
        metrics=(*batch.metrics, batch.metrics[0]),
        guards=(*batch.guards, batch.guards[0]),
    )

    result = aggregate_operational_cohort_arm(retried, POLICY)

    assert result.sample_count == 30


def test_conflicting_rows_with_one_independence_key_fail_closed() -> None:
    batch = _batch()
    original = batch.metrics[0]
    conflict = _metric(
        original.metric_id,
        99_999,
        value=1.0 - original.value,
        cluster=int(original.source_cluster_digest.removeprefix("sha256:"), 16),
    )
    conflicted = OperationalCohortArmBatch(
        arm=batch.arm,
        fdai_revision=batch.fdai_revision,
        window_start=batch.window_start,
        window_end=batch.window_end,
        synthetic=batch.synthetic,
        metrics=(*batch.metrics, conflict),
        guards=batch.guards,
    )

    with pytest.raises(ValueError, match="conflicting metric observations"):
        aggregate_operational_cohort_arm(conflicted, POLICY)


def test_out_of_window_or_overlong_observation_windows_fail_closed() -> None:
    batch = _batch()
    outside = _metric(
        POLICY.required_metric_ids[0],
        99_998,
        value=0.0,
        observed_at=END + timedelta(seconds=1),
    )
    with pytest.raises(ValueError, match="outside"):
        aggregate_operational_cohort_arm(
            OperationalCohortArmBatch(
                arm=batch.arm,
                fdai_revision=batch.fdai_revision,
                window_start=batch.window_start,
                window_end=batch.window_end,
                synthetic=batch.synthetic,
                metrics=(*batch.metrics, outside),
                guards=batch.guards,
            ),
            POLICY,
        )

    with pytest.raises(ValueError, match="exceeds"):
        aggregate_operational_cohort_arm(
            OperationalCohortArmBatch(
                arm=batch.arm,
                fdai_revision=batch.fdai_revision,
                window_start=batch.window_start,
                window_end=START + timedelta(days=91),
                synthetic=batch.synthetic,
                metrics=batch.metrics,
                guards=batch.guards,
            ),
            POLICY,
        )


def test_synthetic_status_is_preserved_instead_of_relabelled() -> None:
    result = aggregate_operational_cohort_arm(_batch(synthetic=True), POLICY)

    assert result.synthetic is True


def test_one_zero_threshold_breach_cannot_round_down_to_zero() -> None:
    assert _zero_threshold_basis_points(0, 1_000_000) == 0
    assert _zero_threshold_basis_points(1, 1_000_000) == 1
