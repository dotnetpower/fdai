"""Metric-series source - bridge the § 3.2 MetricProvider into detection.

Design contract: ``docs/roadmap/fork-and-sequencing/scope-expansion.md`` section 3.2 (the metric
ingestion seam) and
[observability-and-detection.md](../../../../docs/roadmap/rules-and-detection/observability-and-detection.md)
sections 2-3 (anomaly / forecast detection).

The § 3.2 :class:`~fdai.shared.providers.metric.MetricProvider` seam ships "so
[the control plane] can consume those external metrics for anomaly detection",
but the detectors (:class:`~fdai.core.detection.anomaly.MetricAnomalyDetector`,
forecast, seasonal) take a :class:`MetricSample` history + observed pair a
caller must supply - nothing bridged the two. :class:`MetricSeriesSource` is
that bridge: it queries the metric seam for one series scoped to a resource,
converts each :class:`~fdai.shared.providers.metric.MetricPoint` into a
:class:`MetricSample`, and splits the window into ``history`` (the baseline)
plus ``observed`` (the latest point).

Fail-safe, matching the seam's fail-closed contract: a provider outage or an
empty window yields ``None`` rather than raising, and a thin history makes the
detector cold-start (abstain) instead of firing on a shaky baseline. The
control plane never raises a finding on the *absence* of telemetry.

CSP-neutral: imports only the metric Protocol, the detection sample type, and
the standard library, so it stays under the ``core/`` import rule.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime

from fdai.core.detection.anomaly import AnomalyFinding, MetricAnomalyDetector
from fdai.core.detection.series import MetricSample
from fdai.shared.providers.metric import MetricProvider, MetricProviderError, MetricQuery

_LOGGER = logging.getLogger(__name__)
_RESOURCE_LABEL = "resource_id"


@dataclass(frozen=True, slots=True)
class MetricSeries:
    """A fetched metric series split into baseline history + latest observed."""

    history: tuple[MetricSample, ...]
    observed: MetricSample


class MetricSeriesSource:
    """Fetch a resource-scoped metric series from the metric seam."""

    __slots__ = ("_provider", "_resource_label")

    def __init__(
        self,
        metric_provider: MetricProvider,
        *,
        resource_label: str = _RESOURCE_LABEL,
    ) -> None:
        self._provider = metric_provider
        self._resource_label = resource_label

    async def fetch(
        self,
        *,
        metric_name: str,
        resource_ref: str,
        since: datetime,
        until: datetime,
    ) -> MetricSeries | None:
        """Return the series for ``metric_name`` on ``resource_ref``, or ``None``.

        ``None`` means "no usable series": a provider outage (swallowed
        fail-safe), an empty window, or a single point (no baseline). The
        samples are sorted chronologically; the latest is ``observed`` and the
        rest are ``history``.
        """
        query = MetricQuery(
            metric_name=metric_name,
            labels={self._resource_label: resource_ref},
            since=since,
            until=until,
        )
        samples: list[MetricSample] = []
        dropped = 0
        try:
            async for point in self._provider.query(query):
                # This bridge is the boundary between an untrusted metric
                # provider (a fork adapter need not sanitize) and the pure
                # detectors. A non-finite value (NaN / +-Inf) poisons every
                # downstream baseline / fit and serializes to invalid JSON, so
                # drop it here rather than carry garbage into detection.
                if not math.isfinite(point.value):
                    dropped += 1
                    continue
                if point.at < since or point.at > until:
                    dropped += 1
                    continue
                samples.append(MetricSample(timestamp=point.at, value=point.value))
        except MetricProviderError:
            _LOGGER.warning(
                "detection_metric_series_unavailable",
                extra={"metric": metric_name, "resource_ref": resource_ref},
            )
            return None
        if dropped:
            _LOGGER.warning(
                "detection_metric_series_dropped_non_finite",
                extra={"metric": metric_name, "resource_ref": resource_ref, "dropped": dropped},
            )
        if len(samples) < 2:
            return None
        samples.sort(key=lambda s: s.timestamp)
        return MetricSeries(history=tuple(samples[:-1]), observed=samples[-1])

    async def detect_anomaly(
        self,
        detector: MetricAnomalyDetector,
        *,
        metric_name: str,
        resource_ref: str,
        since: datetime,
        until: datetime,
        window_bucket: str,
    ) -> AnomalyFinding | None:
        """Fetch the series and run ``detector`` over it, or abstain.

        Returns ``None`` when there is no usable series (fail-safe) or the
        detector abstains (cold-start / within-threshold). A returned finding
        is the detector's deterministic verdict - the source adds no judgment.
        """
        series = await self.fetch(
            metric_name=metric_name,
            resource_ref=resource_ref,
            since=since,
            until=until,
        )
        if series is None:
            return None
        return detector.evaluate(
            metric=metric_name,
            resource_ref=resource_ref,
            history=series.history,
            observed=series.observed,
            window_bucket=window_bucket,
        )


__all__ = ["MetricSeries", "MetricSeriesSource"]
