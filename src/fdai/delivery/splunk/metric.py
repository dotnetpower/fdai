"""Splunk implementation of the
:class:`~fdai.shared.providers.metric.MetricProvider` seam.

Design contract mirrors :mod:`fdai.delivery.datadog.metric` and
:mod:`fdai.delivery.prometheus.metric`: another live ``MetricProvider``
alongside Prometheus, Datadog, and Azure Monitor Logs, so a fork running
on Splunk can plug the same seam without editing ``core/``. The
CSP-neutral ``metric_name`` maps to a trusted, config-supplied Splunk
search (SPL, typically ``| mstats ...``); untrusted
:attr:`MetricQuery.labels` are filtered in memory, never interpolated
into the SPL string.

Transport: Splunk's search **export** endpoint
(``POST /services/search/jobs/export`` with ``output_mode=json``) streams
newline-delimited JSON (one ``{"result": {...}}`` object per line). Each
result carries a time field (default ``_time``) and a value field (default
``value``); any other field on the result is treated as a label so a
caller can filter (e.g. ``{"host": "web-a"}``).

Auth: a single Splunk authentication token resolved through an injected
:class:`~fdai.shared.providers.secret_provider.SecretProvider` at query
time (never cached across the process, never logged, never surfaced in
error messages), sent as ``Authorization: Bearer <token>``.

Safety / cost invariants match the sibling adapters: bounded
``timeout_seconds``, a ``max_points`` cap that fails closed rather than
truncating, and fail-closed handling of any non-2xx status or malformed
payload. Non-finite (NaN / +/-Inf) samples are dropped as "no data"
rather than propagated so an anomaly detector downstream cannot be
poisoned by a gap value.
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
_DEFAULT_VALUE_FIELD: Final[str] = "value"
_DEFAULT_TIME_FIELD: Final[str] = "_time"
_EXPORT_PATH: Final[str] = "/services/search/jobs/export"


@dataclass(frozen=True, slots=True)
class SplunkMetricConfig:
    """Configuration for the Splunk metric adapter.

    ``searches`` binds each CSP-neutral ``metric_name`` to a trusted SPL
    search string (for example
    ``{"host.cpu.utilization": "| mstats avg(cpu.user) as value by host"}``).
    A metric absent from the map fails closed.

    ``token_secret`` is the *name* looked up on the injected
    :class:`SecretProvider`; the raw token value NEVER lives in the config
    object. ``value_field`` / ``time_field`` name the result fields the
    adapter reads; every other field on the result becomes a label.
    """

    base_url: str
    searches: Mapping[str, str]
    token_secret: str
    value_field: str = _DEFAULT_VALUE_FIELD
    time_field: str = _DEFAULT_TIME_FIELD
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS
    max_points: int = _DEFAULT_MAX_POINTS
    extra_labels: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.base_url:
            raise ValueError("SplunkMetricConfig.base_url MUST be non-empty")
        # Fail-fast on a plaintext base_url. The export endpoint sends the
        # Splunk auth token as a bearer header on every request; a
        # misconfigured ``http://`` endpoint would leak it on the wire.
        if not self.base_url.lower().startswith("https://"):
            raise ValueError(
                "SplunkMetricConfig.base_url MUST use https:// - the search "
                "export API sends the Splunk auth token on every request "
                f"(got {self.base_url!r})"
            )
        if not self.token_secret:
            raise ValueError("SplunkMetricConfig.token_secret MUST be non-empty")
        if not self.value_field:
            raise ValueError("SplunkMetricConfig.value_field MUST be non-empty")
        if not self.time_field:
            raise ValueError("SplunkMetricConfig.time_field MUST be non-empty")
        if self.timeout_seconds <= 0:
            raise ValueError("SplunkMetricConfig.timeout_seconds MUST be positive")
        if self.max_points <= 0:
            raise ValueError("SplunkMetricConfig.max_points MUST be positive")


class SplunkMetricProvider:
    """Stream external metric samples from the Splunk search export API."""

    def __init__(
        self,
        *,
        config: SplunkMetricConfig,
        http_client: httpx.AsyncClient,
        secrets: SecretProvider,
    ) -> None:
        self._config: Final[SplunkMetricConfig] = config
        self._http: Final[httpx.AsyncClient] = http_client
        self._secrets: Final[SecretProvider] = secrets

    async def query(self, query: MetricQuery) -> AsyncIterator[MetricPoint]:
        search = self._config.searches.get(query.metric_name)
        if search is None:
            raise MetricProviderError(
                f"no Splunk search configured for metric {query.metric_name!r}"
            )
        points = await self._run(query=query, search=search)
        for point in points:
            yield point

    async def _run(self, *, query: MetricQuery, search: str) -> list[MetricPoint]:
        now = datetime.now(tz=UTC)
        until = query.until or now
        since = query.since or until
        if since > until:
            raise MetricProviderError(
                f"SplunkMetricProvider: since > until for {query.metric_name!r}"
            )

        # Splunk export uses epoch-second earliest/latest bounds.
        data = {
            "search": search if search.lstrip().startswith("|") else f"search {search}",
            "output_mode": "json",
            "earliest_time": str(int(since.timestamp())),
            "latest_time": str(int(until.timestamp())),
        }

        token = await self._secrets.get(self._config.token_secret)
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
        }

        url = f"{self._config.base_url.rstrip('/')}{_EXPORT_PATH}"
        try:
            response = await self._http.post(
                url,
                data=data,
                headers=headers,
                timeout=self._config.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            # Never surface the URL or headers - the header carries the
            # token. Keep the message minimal.
            raise MetricProviderError(
                f"Splunk request failed for {query.metric_name!r}: {type(exc).__name__}"
            ) from exc

        if response.status_code >= 400:
            snippet = response.text[:200].replace("\n", " ")
            raise MetricProviderError(
                f"Splunk returned HTTP {response.status_code} for "
                f"{query.metric_name!r}: {snippet!r}"
            )

        return self._map_export(text=response.text, query=query)

    def _map_export(self, *, text: str, query: MetricQuery) -> list[MetricPoint]:
        points: list[MetricPoint] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                envelope = _parse_json_object(line)
            except ValueError as exc:
                raise MetricProviderError(
                    f"Splunk returned a malformed JSON line for {query.metric_name!r}"
                ) from exc
            # A Splunk export stream can interleave non-result control
            # objects (e.g. ``{"messages": [...]}``); skip anything without
            # a ``result`` block rather than fail the whole batch.
            result = envelope.get("result")
            if not isinstance(result, Mapping):
                continue
            point = self._map_result(result=result, query=query)
            if point is None:
                continue
            points.append(point)
            if len(points) > self._config.max_points:
                raise MetricProviderError(
                    f"Splunk returned over the max_points cap of "
                    f"{self._config.max_points} for {query.metric_name!r}; "
                    f"narrow the window or the search"
                )

        points.sort(key=lambda p: p.at)
        return points

    def _map_result(self, *, result: Mapping[str, Any], query: MetricQuery) -> MetricPoint | None:
        raw_value = result.get(self._config.value_field)
        if raw_value is None:
            # No value on this row is "no data", not a hard error.
            return None
        try:
            value = float(raw_value)
        except (TypeError, ValueError) as exc:
            raise MetricProviderError(
                f"non-numeric Splunk sample for {query.metric_name!r}: {raw_value!r}"
            ) from exc
        if not isfinite(value):
            return None

        at = _parse_time(result.get(self._config.time_field))
        if at is None:
            raise MetricProviderError(
                f"Splunk result missing/invalid {self._config.time_field!r} "
                f"for {query.metric_name!r}"
            )

        labels = self._labels_from_result(result)
        if not _labels_match(labels, query.labels):
            return None
        return MetricPoint(
            metric_name=query.metric_name,
            at=at,
            value=value,
            labels=labels,
        )

    def _labels_from_result(self, result: Mapping[str, Any]) -> dict[str, str]:
        """Every field on the result that is not the time or value field
        becomes a label. Splunk internal fields (``_raw``, ``_time``, ...)
        other than the configured time field are dropped."""
        labels: dict[str, str] = {}
        for key, raw in result.items():
            if key in (self._config.value_field, self._config.time_field):
                continue
            if key.startswith("_"):
                continue
            labels[str(key)] = str(raw)
        # Operator-supplied static labels (trusted config) never overwrite
        # a label already present on the result.
        for k, v in self._config.extra_labels.items():
            labels.setdefault(str(k), str(v))
        return labels


def _parse_json_object(line: str) -> Mapping[str, Any]:
    import json

    parsed = json.loads(line)
    if not isinstance(parsed, Mapping):
        raise ValueError("Splunk export line is not a JSON object")
    return parsed


def _parse_time(raw: Any) -> datetime | None:
    """Parse a Splunk ``_time`` value.

    Splunk emits ``_time`` either as an epoch second string/number or as
    an ISO-8601 timestamp depending on the search. Handle both; return
    ``None`` on anything unparseable so the caller fails closed.
    """
    if raw is None:
        return None
    # Numeric epoch (int/float or a numeric string). A non-finite or
    # out-of-range value (NaN / +/-inf, or a millisecond epoch mistaken for
    # seconds) raises OverflowError / OSError - not just ValueError - so
    # catch all of them and fall through to the string path rather than
    # letting a poisoned _time crash the whole batch (fail-closed to None).
    try:
        return datetime.fromtimestamp(float(raw), tz=UTC)
    except (TypeError, ValueError, OverflowError, OSError):
        pass
    if isinstance(raw, str):
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


def _labels_match(sample: Mapping[str, str], wanted: Mapping[str, str]) -> bool:
    return all(sample.get(k) == v for k, v in wanted.items())


__all__ = [
    "SplunkMetricConfig",
    "SplunkMetricProvider",
]
