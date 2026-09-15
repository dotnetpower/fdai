from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import timedelta, timezone

import pytest
from fdai.core.detection.forecast_observation import (
    ForecastObservationPolicy,
    MetricForecastObservationProvider,
)
from fdai.shared.contracts.models import TelemetryCompleteness
from fdai.shared.providers.metric import (
    MetricPoint,
    MetricProviderError,
    MetricQuery,
    StaticMetricProvider,
)

from .test_forecast_episode import T0, _episode


async def test_observation_uses_first_event_time_breach() -> None:
    episode = _episode()
    provider = MetricForecastObservationProvider(
        StaticMetricProvider(
            tuple(
                MetricPoint(
                    metric_name=episode.metric,
                    at=T0 + timedelta(minutes=minute),
                    value=80.0 if minute < 30 else 95.0,
                    labels={"resource_id": episode.target_ref},
                )
                for minute in range(0, 61, 5)
            )
        )
    )
    observation = await provider.observe(episode)
    assert observation.actual_breach_at == T0 + timedelta(minutes=30)
    assert observation.observed_value == 95.0
    assert observation.telemetry_completeness is TelemetryCompleteness.COMPLETE


async def test_missing_window_is_unavailable_not_false_positive() -> None:
    observation = await MetricForecastObservationProvider(StaticMetricProvider(())).observe(
        _episode()
    )
    assert observation.actual_breach_at is None
    assert observation.observed_value is None
    assert observation.telemetry_completeness is TelemetryCompleteness.UNAVAILABLE


async def test_stale_window_is_partial() -> None:
    episode = _episode()
    observation = await MetricForecastObservationProvider(
        StaticMetricProvider(
            (
                MetricPoint(
                    metric_name=episode.metric,
                    at=T0 + timedelta(minutes=30),
                    value=70.0,
                    labels={"resource_id": episode.target_ref},
                ),
            )
        )
    ).observe(episode)
    assert observation.telemetry_completeness is TelemetryCompleteness.PARTIAL


def _point(minute: int, value: float = 70.0) -> MetricPoint:
    episode = _episode()
    return MetricPoint(
        metric_name=episode.metric,
        at=T0 + timedelta(minutes=minute),
        value=value,
        labels={"resource_id": episode.target_ref},
    )


@pytest.mark.parametrize("minutes", [(60,), (0, 30, 60), (0, 5, 65), (10, 15, 60)])
async def test_incomplete_horizon_never_counts_as_complete(minutes: tuple[int, ...]) -> None:
    observation = await MetricForecastObservationProvider(
        StaticMetricProvider(tuple(_point(minute) for minute in minutes))
    ).observe(_episode())
    assert observation.telemetry_completeness is TelemetryCompleteness.PARTIAL


async def test_identical_duplicates_do_not_supply_minimum_samples() -> None:
    observation = await MetricForecastObservationProvider(
        StaticMetricProvider((_point(60),) * 3)
    ).observe(_episode())
    assert observation.telemetry_completeness is TelemetryCompleteness.PARTIAL


async def test_conflicting_duplicate_is_unavailable() -> None:
    observation = await MetricForecastObservationProvider(
        StaticMetricProvider((_point(60, 70.0), _point(60, 99.0)))
    ).observe(_episode())
    assert observation.telemetry_completeness is TelemetryCompleteness.UNAVAILABLE
    assert any("conflicting-sample" in reference for reference in observation.evidence_refs)


async def test_policy_is_bound_to_observation_evidence() -> None:
    points = tuple(_point(minute) for minute in range(0, 61, 5))
    first = await MetricForecastObservationProvider(StaticMetricProvider(points)).observe(
        _episode()
    )
    second = await MetricForecastObservationProvider(
        StaticMetricProvider(points), policy=ForecastObservationPolicy(max_gap_seconds=600)
    ).observe(_episode())
    assert first.evidence_refs != second.evidence_refs


async def test_point_limit_cannot_silently_truncate_window() -> None:
    observation = await MetricForecastObservationProvider(
        StaticMetricProvider(tuple(_point(minute) for minute in range(61))),
        policy=ForecastObservationPolicy(max_points=10),
    ).observe(_episode())
    assert observation.telemetry_completeness is TelemetryCompleteness.UNAVAILABLE
    assert any("point-limit" in reference for reference in observation.evidence_refs)


@pytest.mark.parametrize(
    "overrides",
    [
        {"min_samples": True},
        {"min_samples": 1},
        {"max_gap_seconds": 0},
        {"max_points": 2},
        {"timeout_seconds": float("nan")},
        {"timeout_seconds": True},
    ],
)
def test_observation_policy_rejects_invalid_bounds(overrides: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        ForecastObservationPolicy(**overrides)  # type: ignore[arg-type]


async def test_clustered_samples_cannot_cover_a_short_horizon() -> None:
    observation = await MetricForecastObservationProvider(
        StaticMetricProvider(tuple(_point(minute) for minute in (0, 1, 2))),
        policy=ForecastObservationPolicy(max_gap_seconds=3600),
    ).observe(_episode())
    assert observation.telemetry_completeness is TelemetryCompleteness.PARTIAL


async def test_evidence_identity_is_bound_to_scope_and_target() -> None:
    points = tuple(_point(minute) for minute in range(0, 61, 5))
    original = await MetricForecastObservationProvider(StaticMetricProvider(points)).observe(
        _episode()
    )
    scoped = await MetricForecastObservationProvider(StaticMetricProvider(points)).observe(
        _episode(access_scope_digest="b" * 64)
    )
    targeted = await MetricForecastObservationProvider(
        StaticMetricProvider(
            tuple(replace(point, labels={"resource_id": "resource-2"}) for point in points)
        )
    ).observe(_episode(target_ref="resource-2"))
    assert len({original.evidence_refs[0], scoped.evidence_refs[0], targeted.evidence_refs[0]}) == 3


async def test_order_and_identical_duplicates_preserve_evidence_identity() -> None:
    points = tuple(_point(minute) for minute in range(0, 61, 5))
    original = await MetricForecastObservationProvider(StaticMetricProvider(points)).observe(
        _episode()
    )
    reordered = await MetricForecastObservationProvider(
        StaticMetricProvider(tuple(reversed(points)) + points)
    ).observe(_episode())
    assert original == reordered


@pytest.mark.parametrize("ratio", [True, 0, -1, 1.01, float("nan"), float("inf")])
def test_coverage_policy_rejects_invalid_ratios(ratio: float) -> None:
    with pytest.raises(ValueError, match="coverage ratio"):
        ForecastObservationPolicy(min_coverage_ratio=ratio)


class _UnfilteredMetrics:
    def __init__(self, points: tuple[MetricPoint, ...]) -> None:
        self.points = points
        self.closed = False

    async def query(self, query: MetricQuery) -> AsyncIterator[MetricPoint]:
        del query
        try:
            for point in self.points:
                yield point
        finally:
            self.closed = True


@pytest.mark.parametrize(
    "point",
    [
        replace(_point(0), metric_name="different_metric"),
        replace(_point(0), labels={"resource_id": "other-resource"}),
        replace(_point(0), labels={}),
        replace(_point(0), at=T0.replace(tzinfo=None)),
        _point(-1),
        _point(66),
        _point(0, float("nan")),
        _point(0, float("inf")),
        _point(0, True),
    ],
)
async def test_invalid_provider_sample_is_held_and_stream_closed(point: MetricPoint) -> None:
    provider = _UnfilteredMetrics((point,))
    observation = await MetricForecastObservationProvider(provider).observe(_episode())
    assert observation.telemetry_completeness is TelemetryCompleteness.UNAVAILABLE
    assert provider.closed


async def test_mixed_series_cannot_supply_window_coverage() -> None:
    provider = _UnfilteredMetrics(
        (_point(0), replace(_point(5), labels={"resource_id": "resource-1", "instance": "two"}))
    )
    observation = await MetricForecastObservationProvider(provider).observe(_episode())
    assert observation.telemetry_completeness is TelemetryCompleteness.UNAVAILABLE
    assert any("mixed-series" in reference for reference in observation.evidence_refs)
    assert provider.closed


async def test_point_limit_closes_provider_stream() -> None:
    provider = _UnfilteredMetrics(tuple(_point(minute) for minute in range(61)))
    observation = await MetricForecastObservationProvider(
        provider, policy=ForecastObservationPolicy(max_points=3)
    ).observe(_episode())
    assert observation.telemetry_completeness is TelemetryCompleteness.UNAVAILABLE
    assert provider.closed


async def test_equivalent_timezones_and_signed_zero_have_canonical_evidence() -> None:
    points = tuple(_point(minute, 0.0) for minute in range(0, 61, 5))
    offset = timezone(timedelta(hours=9))
    shifted = tuple(replace(point, at=point.at.astimezone(offset), value=-0.0) for point in points)
    original = await MetricForecastObservationProvider(StaticMetricProvider(points)).observe(
        _episode()
    )
    translated = await MetricForecastObservationProvider(StaticMetricProvider(shifted)).observe(
        _episode()
    )
    assert original.evidence_refs == translated.evidence_refs


async def test_grace_breach_does_not_replace_horizon_observation() -> None:
    points = tuple(_point(minute) for minute in range(0, 61, 5)) + (_point(61, 99.0),)
    observation = await MetricForecastObservationProvider(StaticMetricProvider(points)).observe(
        _episode()
    )
    assert observation.actual_breach_at == T0 + timedelta(minutes=61)
    assert observation.observed_value == 70.0
    assert observation.telemetry_completeness is TelemetryCompleteness.COMPLETE


async def test_falling_direction_uses_first_threshold_breach() -> None:
    points = tuple(_point(minute, 95.0 if minute < 30 else 70.0) for minute in range(0, 61, 5))
    observation = await MetricForecastObservationProvider(StaticMetricProvider(points)).observe(
        _episode(direction="falling")
    )
    assert observation.actual_breach_at == T0 + timedelta(minutes=30)
    assert observation.telemetry_completeness is TelemetryCompleteness.COMPLETE


async def test_provider_failure_after_partial_results_is_unavailable() -> None:
    class _FailingMetrics:
        async def query(self, query: MetricQuery) -> AsyncIterator[MetricPoint]:
            del query
            yield _point(0)
            raise MetricProviderError("synthetic provider failure")

    observation = await MetricForecastObservationProvider(_FailingMetrics()).observe(_episode())
    assert observation.telemetry_completeness is TelemetryCompleteness.UNAVAILABLE
    assert observation.observed_value is None


class _BlockedMetrics:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.closed = False

    async def query(self, query: MetricQuery) -> AsyncIterator[MetricPoint]:
        del query
        try:
            self.started.set()
            await self.release.wait()
            yield _point(0)
        finally:
            self.closed = True


async def test_provider_timeout_is_bounded_and_unavailable() -> None:
    provider = _BlockedMetrics()
    observation = await MetricForecastObservationProvider(
        provider, policy=ForecastObservationPolicy(timeout_seconds=0.01)
    ).observe(_episode())
    assert observation.telemetry_completeness is TelemetryCompleteness.UNAVAILABLE
    assert provider.closed


async def test_external_cancellation_is_not_an_observation() -> None:
    provider = _BlockedMetrics()
    task = asyncio.create_task(MetricForecastObservationProvider(provider).observe(_episode()))
    await asyncio.wait_for(provider.started.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert provider.closed
