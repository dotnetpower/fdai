"""MetricSeriesSource - bridge the section 3.2 metric seam into detection.

Covers fetch (empty / single-point / multi-point split / outage fail-safe) and
the detect_anomaly convenience (fires on a spike, abstains on no-series and
cold-start). Uses the in-memory Static/Noop metric providers; async tests run
under asyncio_mode="auto".
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fdai.core.detection import MetricAnomalyDetector, MetricSeriesSource
from fdai.shared.providers.metric import (
    MetricPoint,
    MetricProviderError,
    MetricQuery,
    NoopMetricProvider,
    StaticMetricProvider,
)

_NOW = datetime(2026, 7, 9, 12, 0, 0, tzinfo=UTC)
_SINCE = _NOW - timedelta(hours=1)
_RES = "vm-01"
_METRIC = "cpu.percent"


def _point(minutes_ago: int, value: float) -> MetricPoint:
    return MetricPoint(
        metric_name=_METRIC,
        at=_NOW - timedelta(minutes=minutes_ago),
        value=value,
        labels={"resource_id": _RES},
    )


async def _fetch(provider):  # noqa: ANN001
    return await MetricSeriesSource(provider).fetch(
        metric_name=_METRIC, resource_ref=_RES, since=_SINCE, until=_NOW
    )


# ---------------------------------------------------------------------------
# fetch
# ---------------------------------------------------------------------------


async def test_empty_window_yields_none() -> None:
    assert await _fetch(NoopMetricProvider()) is None


async def test_single_point_yields_none_no_baseline() -> None:
    assert await _fetch(StaticMetricProvider([_point(1, 10.0)])) is None


async def test_multi_point_splits_history_and_observed_sorted() -> None:
    # Supplied out of order; the source sorts chronologically.
    provider = StaticMetricProvider([_point(1, 30.0), _point(5, 10.0), _point(3, 20.0)])
    series = await _fetch(provider)
    assert series is not None
    assert [s.value for s in series.history] == [10.0, 20.0]
    assert series.observed.value == 30.0


async def test_provider_points_outside_requested_window_are_dropped() -> None:
    provider = StaticMetricProvider(
        [
            MetricPoint(
                metric_name=_METRIC,
                at=_SINCE - timedelta(seconds=1),
                value=99.0,
                labels={"resource_id": _RES},
            ),
            _point(5, 10.0),
            _point(1, 30.0),
            MetricPoint(
                metric_name=_METRIC,
                at=_NOW + timedelta(seconds=1),
                value=100.0,
                labels={"resource_id": _RES},
            ),
        ]
    )
    series = await _fetch(provider)
    assert series is not None
    assert [sample.value for sample in series.history] == [10.0]
    assert series.observed.value == 30.0


async def test_non_finite_points_are_dropped_at_the_boundary() -> None:
    # A NaN / +-Inf sample from an unsanitized provider must be dropped here so
    # it never poisons a downstream detector; the finite remainder survives.
    provider = StaticMetricProvider(
        [
            _point(5, 10.0),
            _point(4, float("nan")),
            _point(3, 20.0),
            _point(2, float("inf")),
            _point(1, 30.0),
        ]
    )
    series = await _fetch(provider)
    assert series is not None
    assert [s.value for s in series.history] == [10.0, 20.0]
    assert series.observed.value == 30.0


async def test_all_non_finite_yields_none() -> None:
    # Dropping every non-finite sample leaves < 2 points -> no usable baseline.
    provider = StaticMetricProvider([_point(2, float("nan")), _point(1, float("-inf"))])
    assert await _fetch(provider) is None


class _RaisingProvider:
    async def query(self, query: MetricQuery):
        raise MetricProviderError("metric backend down")
        yield  # pragma: no cover - unreachable, makes this an async generator


async def test_provider_outage_is_fail_safe() -> None:
    assert await _fetch(_RaisingProvider()) is None


async def test_labels_scope_to_resource() -> None:
    # A point for a different resource is filtered out by the provider, leaving
    # a single in-scope point -> no baseline -> None.
    provider = StaticMetricProvider(
        [
            _point(1, 10.0),
            MetricPoint(
                metric_name=_METRIC,
                at=_NOW - timedelta(minutes=2),
                value=99.0,
                labels={"resource_id": "other"},
            ),
        ]
    )
    assert await _fetch(provider) is None


# ---------------------------------------------------------------------------
# detect_anomaly
# ---------------------------------------------------------------------------


def _detector() -> MetricAnomalyDetector:
    return MetricAnomalyDetector(detector_id="d1", min_samples=3, z_threshold=3.0)


async def test_detect_anomaly_fires_on_spike() -> None:
    # Flat baseline (10) + a spike (100) -> deviation against a constant series.
    provider = StaticMetricProvider(
        [_point(5, 10.0), _point(4, 10.0), _point(3, 10.0), _point(2, 10.0), _point(1, 100.0)]
    )
    finding = await MetricSeriesSource(provider).detect_anomaly(
        _detector(),
        metric_name=_METRIC,
        resource_ref=_RES,
        since=_SINCE,
        until=_NOW,
        window_bucket="2026-07-09T12:00",
    )
    assert finding is not None
    assert finding.direction == "over"
    assert finding.metric == _METRIC


async def test_detect_anomaly_no_series_abstains() -> None:
    finding = await MetricSeriesSource(NoopMetricProvider()).detect_anomaly(
        _detector(),
        metric_name=_METRIC,
        resource_ref=_RES,
        since=_SINCE,
        until=_NOW,
        window_bucket="b",
    )
    assert finding is None


async def test_detect_anomaly_cold_start_abstains() -> None:
    # 3 points -> history of 2 < min_samples(3) -> detector cold-starts.
    provider = StaticMetricProvider([_point(3, 10.0), _point(2, 10.0), _point(1, 100.0)])
    finding = await MetricSeriesSource(provider).detect_anomaly(
        _detector(),
        metric_name=_METRIC,
        resource_ref=_RES,
        since=_SINCE,
        until=_NOW,
        window_bucket="b",
    )
    assert finding is None
