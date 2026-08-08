"""Prometheus HTTP-API implementation of the
:class:`~fdai.shared.providers.metric.MetricProvider` seam.

Design contract: ``docs/roadmap/fork-and-sequencing/scope-expansion.md § 3.2``. A second live
``MetricProvider`` alongside the Azure Monitor Logs adapter, this one
CSP-neutral: it speaks the Prometheus query API and therefore works against
vanilla Prometheus, Thanos, Cortex / Mimir, and Azure Monitor managed
Prometheus (AMP) equally. ``core/`` never imports it - a fork binds it at
the composition root in place of :class:`NoopMetricProvider`.

Design boundaries mirror :mod:`~fdai.delivery.azure.metric_logs`:

- HTTP transport is an injected :class:`httpx.AsyncClient` (tests use
  :class:`httpx.MockTransport`).
- An optional injected
  :class:`~fdai.shared.providers.workload_identity.WorkloadIdentity`
  supplies a bearer token when ``audience`` is set (AMP / AAD-guarded
  endpoints); an unauthenticated Prometheus is reached without it.
- The CSP-neutral ``metric_name`` maps to a trusted, config-supplied
  PromQL query. Untrusted ``MetricQuery.labels`` are filtered in memory,
  never interpolated into PromQL.

Safety / cost invariants: a bounded ``timeout``, a ``max_points`` cap that
fails closed rather than truncating, and fail-closed handling of any
non-``success`` status or malformed payload.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite
from typing import Any, Final

import httpx

from fdai.shared.providers.metric import (
    MetricPoint,
    MetricProviderError,
    MetricQuery,
)
from fdai.shared.providers.workload_identity import WorkloadIdentity

_DEFAULT_STEP_SECONDS: Final[float] = 60.0
_DEFAULT_TIMEOUT_SECONDS: Final[float] = 30.0
_DEFAULT_MAX_POINTS: Final[int] = 50_000


@dataclass(frozen=True, slots=True)
class PrometheusMetricConfig:
    """Configuration for the Prometheus metric adapter.

    ``queries`` binds each CSP-neutral ``metric_name`` to a trusted PromQL
    string. A metric absent from the map fails closed.
    """

    base_url: str
    queries: Mapping[str, str]
    audience: str | None = None
    step_seconds: float = _DEFAULT_STEP_SECONDS
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS
    max_points: int = _DEFAULT_MAX_POINTS

    def __post_init__(self) -> None:
        if not self.base_url:
            raise ValueError("PrometheusMetricConfig.base_url MUST be non-empty")
        if self.step_seconds <= 0:
            raise ValueError("PrometheusMetricConfig.step_seconds MUST be positive")
        if self.max_points <= 0:
            raise ValueError("PrometheusMetricConfig.max_points MUST be positive")


class PrometheusMetricProvider:
    """Stream external metric samples from a Prometheus-compatible API."""

    def __init__(
        self,
        *,
        config: PrometheusMetricConfig,
        http_client: httpx.AsyncClient,
        identity: WorkloadIdentity | None = None,
    ) -> None:
        if config.audience and identity is None:
            raise ValueError(
                "PrometheusMetricConfig.audience is set but no WorkloadIdentity "
                "was injected to mint the bearer token"
            )
        self._config: Final[PrometheusMetricConfig] = config
        self._http: Final[httpx.AsyncClient] = http_client
        self._identity: Final[WorkloadIdentity | None] = identity

    async def query(self, query: MetricQuery) -> AsyncIterator[MetricPoint]:
        promql = self._config.queries.get(query.metric_name)
        if promql is None:
            raise MetricProviderError(
                f"no PromQL query configured for metric {query.metric_name!r}"
            )
        points = await self._run(query=query, promql=promql)
        for point in points:
            yield point

    async def _run(self, *, query: MetricQuery, promql: str) -> list[MetricPoint]:
        ranged = query.since is not None and query.until is not None
        if ranged:
            url = f"{self._config.base_url.rstrip('/')}/api/v1/query_range"
            params: dict[str, str] = {
                "query": promql,
                "start": str(query.since.timestamp()),  # type: ignore[union-attr]
                "end": str(query.until.timestamp()),  # type: ignore[union-attr]
                "step": str(self._config.step_seconds),
            }
        else:
            url = f"{self._config.base_url.rstrip('/')}/api/v1/query"
            params = {"query": promql}
            if query.until is not None:
                params["time"] = str(query.until.timestamp())

        headers = {"Accept": "application/json"}
        if self._config.audience and self._identity is not None:
            token = await self._identity.get_token(self._config.audience)
            headers["Authorization"] = f"Bearer {token.token}"

        try:
            response = await self._http.post(
                url, data=params, headers=headers, timeout=self._config.timeout_seconds
            )
        except httpx.HTTPError as exc:
            raise MetricProviderError(
                f"Prometheus request failed for {query.metric_name!r}: {exc}"
            ) from exc

        if response.status_code >= 400:
            snippet = response.text[:200].replace("\n", " ")
            raise MetricProviderError(
                f"Prometheus returned HTTP {response.status_code} for "
                f"{query.metric_name!r}: {snippet!r}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise MetricProviderError(
                f"Prometheus returned non-JSON for {query.metric_name!r}"
            ) from exc

        return self._map_payload(payload=payload, query=query)

    def _map_payload(self, *, payload: Any, query: MetricQuery) -> list[MetricPoint]:
        if not isinstance(payload, Mapping) or payload.get("status") != "success":
            status = payload.get("status") if isinstance(payload, Mapping) else "unknown"
            raise MetricProviderError(f"Prometheus status {status!r} for {query.metric_name!r}")
        data = payload.get("data")
        result = data.get("result") if isinstance(data, Mapping) else None
        result_type = data.get("resultType") if isinstance(data, Mapping) else None
        if not isinstance(result, list):
            raise MetricProviderError(
                f"Prometheus payload missing 'data.result' for {query.metric_name!r}"
            )

        points: list[MetricPoint] = []
        for series in result:
            if not isinstance(series, Mapping):
                continue
            labels = {
                str(k): str(v) for k, v in (series.get("metric") or {}).items() if k != "__name__"
            }
            if not _labels_match(labels, query.labels):
                continue
            for at, value in _samples(series, result_type):
                points.append(
                    MetricPoint(
                        metric_name=query.metric_name,
                        at=at,
                        value=value,
                        labels=labels,
                    )
                )
                if len(points) > self._config.max_points:
                    raise MetricProviderError(
                        f"Prometheus returned over the max_points cap of "
                        f"{self._config.max_points} for {query.metric_name!r}; "
                        f"narrow the query or widen the step"
                    )

        points.sort(key=lambda p: p.at)
        return points


def _samples(series: Mapping[str, Any], result_type: Any) -> list[tuple[datetime, float]]:
    """Extract (timestamp, value) pairs from a matrix or vector series."""
    if result_type == "matrix":
        raw = series.get("values") or []
    else:  # vector / scalar - single "value"
        single = series.get("value")
        raw = [single] if single is not None else []
    out: list[tuple[datetime, float]] = []
    for pair in raw:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise MetricProviderError(f"malformed Prometheus sample: {pair!r}")
        ts_raw, val_raw = pair
        try:
            at = datetime.fromtimestamp(float(ts_raw), tz=UTC)
            value = float(val_raw)
        except (TypeError, ValueError) as exc:
            raise MetricProviderError(f"non-numeric Prometheus sample: {pair!r}") from exc
        # Prometheus returns NaN / +-Inf for stale or gapped series. Those are
        # "no data", not real observations - skip them rather than let a NaN
        # poison anomaly detection (nan breaks every comparison).
        if not isfinite(value):
            continue
        out.append((at, value))
    return out


def _labels_match(sample: Mapping[str, str], wanted: Mapping[str, str]) -> bool:
    return all(sample.get(k) == v for k, v in wanted.items())


__all__ = [
    "PrometheusMetricConfig",
    "PrometheusMetricProvider",
]
