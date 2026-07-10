"""Datadog HTTP-API implementation of the
:class:`~fdai.shared.providers.metric.MetricProvider` seam.

Design contract mirrors :mod:`fdai.delivery.prometheus.metric`: another
live ``MetricProvider`` alongside Prometheus and Azure Monitor Logs, so a
fork operating on Datadog can plug the same seam without editing
``core/``. The CSP-neutral ``metric_name`` maps to a trusted,
config-supplied Datadog query string (``avg:system.cpu.user{host:*}``);
untrusted :attr:`MetricQuery.labels` are filtered in memory, never
interpolated into the query string.

Auth: Datadog requires both an ``DD-API-KEY`` and a ``DD-APPLICATION-KEY``
for the metrics query API. Both are resolved through an injected
:class:`~fdai.shared.providers.secret_provider.SecretProvider` at query
time (never cached across the process, never logged, never surfaced in
error messages).

Safety / cost invariants match the Prometheus adapter: bounded
``timeout_seconds``, a ``max_points`` cap that fails closed rather than
truncating, and fail-closed handling of any non-``ok`` status or
malformed payload. Non-finite (NaN / +/-Inf) samples are dropped as
"no data" rather than propagated - Datadog uses NaN to signal a gapped
series and letting a NaN reach the anomaly detector would poison every
comparison downstream.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from math import isfinite
from typing import Any, Final

import httpx

from fdai.shared.providers.metric import (
    MetricPoint,
    MetricProviderError,
    MetricQuery,
)
from fdai.shared.providers.secret_provider import SecretProvider

_DEFAULT_TIMEOUT_SECONDS: Final[float] = 30.0
_DEFAULT_MAX_POINTS: Final[int] = 50_000
_DEFAULT_BASE_URL: Final[str] = "https://api.datadoghq.com"


@dataclass(frozen=True, slots=True)
class DatadogMetricConfig:
    """Configuration for the Datadog metric adapter.

    ``queries`` binds each CSP-neutral ``metric_name`` to a trusted
    Datadog query string (for example
    ``{"host.cpu.utilization": "avg:system.cpu.user{*}"}``). A metric
    absent from the map fails closed.

    ``api_key_secret`` / ``app_key_secret`` are the *names* looked up on
    the injected :class:`SecretProvider`; the raw secret values NEVER
    live in the config object.
    """

    queries: Mapping[str, str]
    api_key_secret: str
    app_key_secret: str
    base_url: str = _DEFAULT_BASE_URL
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS
    max_points: int = _DEFAULT_MAX_POINTS
    extra_tags: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.base_url:
            raise ValueError("DatadogMetricConfig.base_url MUST be non-empty")
        # Fail-fast on a plaintext base_url. The Datadog metrics API
        # requires DD-API-KEY + DD-APPLICATION-KEY on every request; a
        # misconfigured ``http://`` endpoint would leak both secrets on
        # the wire. Real Datadog endpoints (US1/EU/US3/US5/GovCloud) are
        # all https, so there is no legitimate operational use case for
        # plaintext here.
        if not self.base_url.lower().startswith("https://"):
            raise ValueError(
                "DatadogMetricConfig.base_url MUST use https:// - the API "
                "sends DD-API-KEY and DD-APPLICATION-KEY on every request "
                f"(got {self.base_url!r})"
            )
        if not self.api_key_secret or not self.app_key_secret:
            raise ValueError(
                "DatadogMetricConfig.api_key_secret and app_key_secret MUST be non-empty"
            )
        if self.timeout_seconds <= 0:
            raise ValueError("DatadogMetricConfig.timeout_seconds MUST be positive")
        if self.max_points <= 0:
            raise ValueError("DatadogMetricConfig.max_points MUST be positive")


class DatadogMetricProvider:
    """Stream external metric samples from the Datadog metrics API."""

    def __init__(
        self,
        *,
        config: DatadogMetricConfig,
        http_client: httpx.AsyncClient,
        secrets: SecretProvider,
    ) -> None:
        self._config: Final[DatadogMetricConfig] = config
        self._http: Final[httpx.AsyncClient] = http_client
        self._secrets: Final[SecretProvider] = secrets

    async def query(self, query: MetricQuery) -> AsyncIterator[MetricPoint]:
        dd_query = self._config.queries.get(query.metric_name)
        if dd_query is None:
            raise MetricProviderError(
                f"no Datadog query configured for metric {query.metric_name!r}"
            )
        points = await self._run(query=query, dd_query=dd_query)
        for point in points:
            yield point

    async def _run(self, *, query: MetricQuery, dd_query: str) -> list[MetricPoint]:
        # Datadog requires an explicit [from, to] window in unix seconds.
        # An instant query is expressed as a 1-second window ending "now".
        now = datetime.now(tz=UTC)
        until = query.until or now
        since = query.since or until
        if since > until:
            raise MetricProviderError(
                f"DatadogMetricProvider: since > until for {query.metric_name!r}"
            )
        params: dict[str, str] = {
            "from": str(int(since.timestamp())),
            "to": str(int(until.timestamp())),
            "query": dd_query,
        }

        api_key = await self._secrets.get(self._config.api_key_secret)
        app_key = await self._secrets.get(self._config.app_key_secret)
        headers = {
            "Accept": "application/json",
            "DD-API-KEY": api_key,
            "DD-APPLICATION-KEY": app_key,
        }

        url = f"{self._config.base_url.rstrip('/')}/api/v1/query"
        try:
            response = await self._http.get(
                url,
                params=params,
                headers=headers,
                timeout=self._config.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            # Never surface the URL or headers in the error - the URL is
            # safe but the headers carry secrets. Keep the message minimal.
            raise MetricProviderError(
                f"Datadog request failed for {query.metric_name!r}: {type(exc).__name__}"
            ) from exc

        if response.status_code >= 400:
            snippet = response.text[:200].replace("\n", " ")
            raise MetricProviderError(
                f"Datadog returned HTTP {response.status_code} for "
                f"{query.metric_name!r}: {snippet!r}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise MetricProviderError(
                f"Datadog returned non-JSON for {query.metric_name!r}"
            ) from exc

        return self._map_payload(payload=payload, query=query)

    def _map_payload(self, *, payload: Any, query: MetricQuery) -> list[MetricPoint]:
        if not isinstance(payload, Mapping):
            raise MetricProviderError(f"Datadog payload not an object for {query.metric_name!r}")
        status = payload.get("status")
        # The v1/query endpoint sometimes omits `status` on a successful
        # response and returns `series`. Treat "ok" or missing-with-series
        # as success; anything else is a failure (fail closed).
        series = payload.get("series")
        if status not in (None, "ok"):
            error = payload.get("error") or "unknown"
            raise MetricProviderError(
                f"Datadog status {status!r} ({error!r}) for {query.metric_name!r}"
            )
        if not isinstance(series, list):
            raise MetricProviderError(f"Datadog payload missing 'series' for {query.metric_name!r}")

        points: list[MetricPoint] = []
        for entry in series:
            if not isinstance(entry, Mapping):
                continue
            labels = _labels_from_tag_set(entry.get("tag_set"))
            # Merge in the operator-supplied static tags (e.g. env). These
            # are trusted config, unlike the query labels which are just
            # filters. Static tags never overwrite a tag from Datadog.
            for k, v in self._config.extra_tags.items():
                labels.setdefault(str(k), str(v))
            if not _labels_match(labels, query.labels):
                continue
            for at, value in _pointlist_samples(entry.get("pointlist")):
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
                        f"Datadog returned over the max_points cap of "
                        f"{self._config.max_points} for {query.metric_name!r}; "
                        f"narrow the window or the query"
                    )

        points.sort(key=lambda p: p.at)
        return points


def _labels_from_tag_set(tag_set: Any) -> dict[str, str]:
    """Convert a Datadog tag_set (list of ``key:value`` strings) into a dict.

    A bare tag (no ``:``) is preserved with an empty value so the caller
    can still filter on it - dropping it silently would let a filter like
    ``{"prod": ""}`` match series it should not.
    """
    result: dict[str, str] = {}
    if not isinstance(tag_set, list):
        return result
    for raw in tag_set:
        if not isinstance(raw, str):
            continue
        key, sep, value = raw.partition(":")
        if not key:
            continue
        result[key] = value if sep else ""
    return result


def _pointlist_samples(pointlist: Any) -> list[tuple[datetime, float]]:
    """Extract (timestamp, value) pairs from a Datadog series ``pointlist``.

    Datadog returns ``[ts_ms, value]`` pairs; ``value`` MAY be ``null``
    or NaN for a gap in the series. Skip those - they are "no data",
    not real observations, and a NaN reaching anomaly detection would
    break every downstream comparison.
    """
    if not isinstance(pointlist, list):
        return []
    out: list[tuple[datetime, float]] = []
    for pair in pointlist:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise MetricProviderError(f"malformed Datadog sample: {pair!r}")
        ts_raw, val_raw = pair
        if val_raw is None:
            continue
        try:
            at = datetime.fromtimestamp(float(ts_raw) / 1000.0, tz=UTC)
            value = float(val_raw)
        except (TypeError, ValueError) as exc:
            raise MetricProviderError(f"non-numeric Datadog sample: {pair!r}") from exc
        if not isfinite(value):
            continue
        out.append((at, value))
    return out


def _labels_match(sample: Mapping[str, str], wanted: Mapping[str, str]) -> bool:
    return all(sample.get(k) == v for k, v in wanted.items())


__all__ = [
    "DatadogMetricConfig",
    "DatadogMetricProvider",
]
