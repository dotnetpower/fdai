"""Azure Monitor Metrics (native REST API) implementation of the
:class:`~fdai.shared.providers.metric.MetricProvider` seam.

Design contract: cuts the 2-5 min Log Analytics ingestion floor down to
~1-3 min for the analyzer metrics whose values live directly on the
Azure resource (``cpu_percent``, ``healthy_host_count``, backend
latencies, connection counts). It bypasses Log Analytics entirely by
querying the ``Microsoft.Insights/metrics`` REST API directly against
each resource ARM id, which reads from Azure Monitor's own metrics
store and is dramatically fresher than the KQL-over-``AzureMetrics``
table path :mod:`~fdai.delivery.azure.metric_logs` uses.

Boundary with the Log Analytics adapter
---------------------------------------

The two adapters cover **disjoint** metric sets by design:

- **This adapter (Metrics API)** serves metrics whose value maps
  directly onto an Azure platform metric name (``cpu_percent``,
  ``BackendLastByteResponseTime``, ``HealthyHostCount``, ...). One
  HTTP call, no downstream compute, ~1-3 min freshness.
- **Log Analytics KQL** serves metrics that need computation
  (``http_429_rate = throttled / total``, ``request_surge_ratio``,
  ``http_5xx_rate``, ``k8s.pod.restarts`` as a max-min delta).
  Client-side arithmetic against columns is trivial in KQL, expensive
  or impossible in a single Metrics API call - so those stay on the
  KQL floor.

The composition root chains both providers behind the routed / composite
metric provider (Prom > Metrics > Logs) so a single analyzer call lands
on the fastest backend that can serve it - Prom for AKS-observed
metrics (sub-minute), Metrics API for direct Azure PaaS metrics
(~1-3 min), Logs KQL for computed / cross-signal metrics (2-5 min).

Design boundaries mirror :mod:`~fdai.delivery.azure.metric_logs`:

- Identity flows through the injected
  :class:`~fdai.shared.providers.workload_identity.WorkloadIdentity`
  Protocol - no ``DefaultAzureCredential``.
- HTTP transport is an injected :class:`httpx.AsyncClient`.
- The CSP-neutral ``metric_name`` maps to a trusted, config-supplied
  Metrics API template (azure_metric_name + aggregation + interval).
  ``MetricQuery.labels['resource_id']`` selects the target ARM id;
  labels are NEVER interpolated into the URL beyond that (URL-encoded
  path segment only).

Safety / cost invariants
------------------------

- **Bounded time window**: the API-native ``timespan`` parameter is
  always sent; ``interval`` caps the number of points server-side.
- **Bounded result size**: :attr:`AzureMonitorMetricsConfig.max_points`
  caps the number of parsed timeseries points. Exceeding it raises
  :class:`~fdai.shared.providers.metric.MetricProviderError` (fail-closed)
  rather than silently truncating.
- **Fail-closed on partial**: a non-2xx response, a malformed timeseries
  envelope, or a missing metric raises ``MetricProviderError``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import Any, Final
from urllib.parse import quote

import httpx

from fdai.shared.providers.metric import (
    MetricPoint,
    MetricProviderError,
    MetricQuery,
)
from fdai.shared.providers.workload_identity import WorkloadIdentity

_DEFAULT_ENDPOINT: Final[str] = "https://management.azure.com"
_DEFAULT_API_VERSION: Final[str] = "2024-02-01"
_DEFAULT_AUDIENCE: Final[str] = "https://management.azure.com/.default"
_DEFAULT_TIMEOUT_SECONDS: Final[float] = 30.0
_DEFAULT_LOOKBACK_SECONDS: Final[int] = 3_600
_DEFAULT_MAX_POINTS: Final[int] = 5_000
_DEFAULT_MAX_RESPONSE_BYTES: Final[int] = 10_000_000
_DEFAULT_INTERVAL: Final[str] = "PT1M"

_VALID_AGGREGATIONS: Final[frozenset[str]] = frozenset(
    {"Average", "Maximum", "Minimum", "Total", "Count"}
)


@dataclass(frozen=True, slots=True)
class MetricsApiTemplate:
    """One CSP-neutral metric name -> Azure Monitor Metrics query.

    ``azure_metric_name`` is the platform-metric identifier documented
    on each resource type's metric list; ``aggregation`` is the reducer
    Azure computes server-side per ``interval`` bucket. The template is
    author-controlled configuration - never derived from untrusted input.
    """

    azure_metric_name: str
    aggregation: str
    interval: str = _DEFAULT_INTERVAL

    def __post_init__(self) -> None:
        if not self.azure_metric_name:
            raise ValueError("MetricsApiTemplate.azure_metric_name MUST be non-empty")
        if self.aggregation not in _VALID_AGGREGATIONS:
            raise ValueError(
                f"MetricsApiTemplate.aggregation MUST be one of "
                f"{sorted(_VALID_AGGREGATIONS)}, got {self.aggregation!r}"
            )
        if not self.interval.startswith("PT"):
            raise ValueError(
                f"MetricsApiTemplate.interval MUST be an ISO 8601 duration "
                f"(e.g. 'PT1M'); got {self.interval!r}"
            )


@dataclass(frozen=True, slots=True)
class AzureMonitorMetricsConfig:
    """Configuration for the Azure Monitor Metrics adapter.

    Every value except ``templates`` has a documented default so the
    composition root only supplies what a fork overrides.
    """

    templates: Mapping[str, MetricsApiTemplate]
    endpoint: str = _DEFAULT_ENDPOINT
    api_version: str = _DEFAULT_API_VERSION
    audience: str = _DEFAULT_AUDIENCE
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS
    default_lookback_seconds: int = _DEFAULT_LOOKBACK_SECONDS
    max_points: int = _DEFAULT_MAX_POINTS
    max_response_bytes: int = _DEFAULT_MAX_RESPONSE_BYTES

    def __post_init__(self) -> None:
        if not self.templates:
            raise ValueError("AzureMonitorMetricsConfig.templates MUST be non-empty")
        if not self.endpoint.lower().startswith("https://"):
            raise ValueError(
                "AzureMonitorMetricsConfig.endpoint MUST use https:// - the "
                f"bearer token is sent on every request (got {self.endpoint!r})"
            )
        if self.timeout_seconds <= 0:
            raise ValueError("AzureMonitorMetricsConfig.timeout_seconds MUST be positive")
        if self.default_lookback_seconds <= 0:
            raise ValueError("AzureMonitorMetricsConfig.default_lookback_seconds MUST be positive")
        if self.max_points <= 0:
            raise ValueError("AzureMonitorMetricsConfig.max_points MUST be positive")
        if self.max_response_bytes < 1:
            raise ValueError("AzureMonitorMetricsConfig.max_response_bytes MUST be >= 1")


_Clock = Callable[[], datetime]


class AzureMonitorMetricsProvider:
    """Stream external metric samples from the Azure Monitor Metrics REST API."""

    def __init__(
        self,
        *,
        config: AzureMonitorMetricsConfig,
        http_client: httpx.AsyncClient,
        identity: WorkloadIdentity,
        clock: _Clock | None = None,
    ) -> None:
        self._config: Final[AzureMonitorMetricsConfig] = config
        self._http: Final[httpx.AsyncClient] = http_client
        self._identity: Final[WorkloadIdentity] = identity
        self._clock: Final[_Clock] = clock or (lambda: datetime.now(tz=UTC))

    async def query(self, query: MetricQuery) -> AsyncIterator[MetricPoint]:
        template = self._config.templates.get(query.metric_name)
        if template is None:
            raise MetricProviderError(
                f"no Metrics API template configured for metric {query.metric_name!r}"
            )
        resource_id = query.labels.get("resource_id")
        if not resource_id:
            raise MetricProviderError(
                f"MetricQuery for {query.metric_name!r} MUST supply a "
                "``resource_id`` label - the Metrics API is scoped per ARM id"
            )
        points = await self._run(query=query, template=template, resource_id=resource_id)
        for point in points:
            yield point

    async def _run(
        self, *, query: MetricQuery, template: MetricsApiTemplate, resource_id: str
    ) -> list[MetricPoint]:
        # ARM ids start with ``/subscriptions/...``; use ``quote`` with
        # ``safe='/'`` so the leading slash stays but any weird chars in
        # a resource name get escaped, avoiding URL smuggling from a
        # label value that we do NOT fully trust.
        encoded = quote(resource_id, safe="/")
        url = f"{self._config.endpoint.rstrip('/')}{encoded}/providers/Microsoft.Insights/metrics"
        params: dict[str, str] = {
            "api-version": self._config.api_version,
            "metricnames": template.azure_metric_name,
            "aggregation": template.aggregation,
            "interval": template.interval,
            "timespan": _build_timespan(
                query.since,
                query.until,
                now=self._clock(),
                lookback=timedelta(seconds=self._config.default_lookback_seconds),
            ),
        }

        token = await self._identity.get_token(self._config.audience)
        headers = {
            "Authorization": f"Bearer {token.token}",
            "Accept": "application/json",
        }
        try:
            response = await self._http.get(
                url,
                headers=headers,
                params=params,
                timeout=self._config.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise MetricProviderError(
                f"Azure Monitor Metrics request failed for {query.metric_name!r}: {exc}"
            ) from exc

        if response.status_code >= 400:
            snippet = response.text[:200].replace("\n", " ")
            raise MetricProviderError(
                f"Azure Monitor Metrics returned HTTP {response.status_code} for "
                f"{query.metric_name!r}: {snippet!r}"
            )

        if len(response.content) > self._config.max_response_bytes:
            raise MetricProviderError(
                f"Azure Monitor Metrics response for {query.metric_name!r} is "
                f"{len(response.content)} bytes, over the "
                f"{self._config.max_response_bytes}-byte cap; narrow the query"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise MetricProviderError(
                f"Azure Monitor Metrics returned non-JSON for {query.metric_name!r}"
            ) from exc

        return self._map_payload(
            payload=payload,
            query=query,
            template=template,
            resource_id=resource_id,
        )

    def _map_payload(
        self,
        *,
        payload: Any,
        query: MetricQuery,
        template: MetricsApiTemplate,
        resource_id: str,
    ) -> list[MetricPoint]:
        if not isinstance(payload, Mapping):
            raise MetricProviderError(
                f"Azure Monitor Metrics payload not a JSON object for {query.metric_name!r}"
            )
        value = payload.get("value")
        if not isinstance(value, list) or not value:
            raise MetricProviderError(
                f"Azure Monitor Metrics payload missing 'value' for {query.metric_name!r}"
            )
        # The API echoes back a single metric entry when we ask for one
        # metric name; use the first entry defensively.
        metric_entry = value[0]
        if not isinstance(metric_entry, Mapping):
            raise MetricProviderError(
                f"Azure Monitor Metrics 'value[0]' not an object for {query.metric_name!r}"
            )
        timeseries = metric_entry.get("timeseries")
        if not isinstance(timeseries, list):
            raise MetricProviderError(
                f"Azure Monitor Metrics missing 'timeseries' for {query.metric_name!r}"
            )

        # ``aggregation`` name -> JSON key on each ``data`` object.
        agg_key = template.aggregation.lower()
        base_labels: dict[str, str] = {"resource_id": resource_id.lower()}

        points: list[MetricPoint] = []
        for series in timeseries:
            if not isinstance(series, Mapping):
                continue
            series_labels = dict(base_labels)
            for md in series.get("metadatavalues", []) or []:
                if not isinstance(md, Mapping):
                    continue
                name_field = md.get("name")
                name = None
                if isinstance(name_field, Mapping):
                    name = name_field.get("value")
                elif isinstance(name_field, str):
                    name = name_field
                v = md.get("value")
                if isinstance(name, str) and isinstance(v, str):
                    series_labels[name] = v
            data = series.get("data")
            if not isinstance(data, list):
                continue
            for datum in data:
                if not isinstance(datum, Mapping):
                    continue
                raw_value = datum.get(agg_key)
                if raw_value is None:
                    # Metrics API returns bins with no aggregate when
                    # there was no data in that bin; skip rather than
                    # emitting a phantom zero.
                    continue
                try:
                    numeric = float(raw_value)
                except (TypeError, ValueError):
                    raise MetricProviderError(
                        f"Azure Monitor Metrics non-numeric {agg_key} for "
                        f"{query.metric_name!r}: {raw_value!r}"
                    ) from None
                if not isfinite(numeric):
                    raise MetricProviderError(
                        f"Azure Monitor Metrics non-finite {agg_key} for {query.metric_name!r}"
                    )
                ts_raw = datum.get("timeStamp")
                if not isinstance(ts_raw, str):
                    raise MetricProviderError(
                        f"Azure Monitor Metrics point missing 'timeStamp' for {query.metric_name!r}"
                    )
                text = ts_raw.replace("Z", "+00:00") if ts_raw.endswith("Z") else ts_raw
                try:
                    at = datetime.fromisoformat(text)
                except ValueError as exc:
                    raise MetricProviderError(
                        f"Azure Monitor Metrics unparseable timestamp "
                        f"{ts_raw!r} for {query.metric_name!r}"
                    ) from exc
                if not _labels_match_excluding_resource_id(series_labels, query.labels):
                    continue
                points.append(
                    MetricPoint(
                        metric_name=query.metric_name,
                        at=at,
                        value=numeric,
                        labels=series_labels,
                    )
                )
                if len(points) > self._config.max_points:
                    raise MetricProviderError(
                        f"Azure Monitor Metrics returned more than "
                        f"{self._config.max_points} points for "
                        f"{query.metric_name!r}; narrow the query"
                    )

        points.sort(key=lambda p: p.at)
        return points


def _build_timespan(
    since: datetime | None,
    until: datetime | None,
    *,
    now: datetime,
    lookback: timedelta,
) -> str:
    """Return an ISO 8601 interval for the API ``timespan`` param.

    Always bounded server-side: any absent side is derived from ``now``
    and the ``default_lookback_seconds`` window so the Metrics API never
    receives an unbounded request.
    """
    lo = _as_utc(since) if since is not None else _as_utc(now) - lookback
    hi = _as_utc(until) if until is not None else _as_utc(now)
    if lo > hi:
        lo, hi = hi, lo
    return f"{lo.isoformat()}/{hi.isoformat()}"


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _labels_match(sample: Mapping[str, str], wanted: Mapping[str, str]) -> bool:
    return all(sample.get(k) == v for k, v in wanted.items())


def _labels_match_excluding_resource_id(
    sample: Mapping[str, str], wanted: Mapping[str, str]
) -> bool:
    """Post-fetch label filter that ignores ``resource_id``.

    The Metrics API is scoped **per resource ARM id** via the URL path
    (``/subscriptions/.../providers/.../metrics``) - the ``resource_id``
    label is already implicit in the request scope, so the in-memory
    filter would be an unhelpful case-sensitive re-check that turns a
    mixed-case caller value ('Microsoft.DBforMySQL/...') against the
    lowercased echo we emit ('microsoft.dbformysql/...') into an empty
    result. Skip ``resource_id`` here; every other label (e.g.
    ``shard``, ``pod``) still filters normally.
    """
    return all(sample.get(k) == v for k, v in wanted.items() if k != "resource_id")


__all__ = [
    "AzureMonitorMetricsConfig",
    "AzureMonitorMetricsProvider",
    "MetricsApiTemplate",
]
