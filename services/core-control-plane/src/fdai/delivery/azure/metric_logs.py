"""Azure Monitor Logs (Log Analytics KQL) implementation of the
:class:`~fdai.shared.providers.metric.MetricProvider` seam.

Design contract: ``docs/roadmap/fork-and-sequencing/scope-expansion.md § 3.2`` (telemetry
ingestion seam). This is the first **real** ``MetricProvider`` adapter;
the upstream default stays :class:`NoopMetricProvider` so the dev-mode
local-fake parity contract in ``docs/roadmap/deployment/dev-and-deploy-parity.md``
holds. ``core/`` never imports this module - it is bound at the
composition root through :func:`~fdai.composition.bind_azure_monitor_logs`.

Design boundaries
-----------------

- Identity flows through the injected
  :class:`~fdai.shared.providers.workload_identity.WorkloadIdentity`
  Protocol - no ``DefaultAzureCredential``, no ``azure-identity`` import.
  A fork MAY plug in IRSA / SPIFFE / GCP-WIF under the same seam.
- HTTP transport is an injected :class:`httpx.AsyncClient`. Tests pass a
  client backed by :class:`httpx.MockTransport`; production wires a
  long-lived shared client at the composition root. This mirrors the
  :mod:`~fdai.delivery.azure.arg_query` adapter exactly.
- The CSP-neutral ``metric_name`` maps to a trusted, config-supplied KQL
  template. Untrusted ``MetricQuery.labels`` are **never** interpolated
  into the KQL - the template returns label columns and the adapter
  filters rows in memory (same semantics as
  :class:`~fdai.shared.providers.metric.StaticMetricProvider`). This
  removes the KQL-injection surface entirely.

Safety / cost invariants
------------------------

- **Bounded time window**: the API-native ``timespan`` parameter bounds
  the query server-side; the KQL template also carries its own time
  filter.
- **Bounded result size**: :attr:`AzureMonitorLogsConfig.max_rows` caps
  the number of parsed rows. Exceeding it raises
  :class:`~fdai.shared.providers.metric.MetricProviderError` (fail-closed)
  rather than silently truncating, so a too-broad query surfaces to the
  operator instead of feeding a partial series into anomaly detection.
- **Fail-closed on partial**: a non-2xx response, a malformed table, or a
  missing configured column raises ``MetricProviderError``. Per
  ``architecture.instructions.md`` the caller abstains and routes to HIL
  rather than auto-acting on a partial observation.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import Any, Final

import httpx

from fdai.shared.providers.metric import (
    MetricPoint,
    MetricProviderError,
    MetricQuery,
)
from fdai.shared.providers.workload_identity import WorkloadIdentity

_DEFAULT_ENDPOINT: Final[str] = "https://api.loganalytics.io"
_DEFAULT_API_PATH: Final[str] = "/v1"
_DEFAULT_AUDIENCE: Final[str] = "https://api.loganalytics.io/.default"
_DEFAULT_TIMEOUT_SECONDS: Final[float] = 30.0
_DEFAULT_MAX_ROWS: Final[int] = 10_000
_DEFAULT_MAX_RESPONSE_BYTES: Final[int] = 50_000_000
_DEFAULT_TIMESTAMP_COLUMN: Final[str] = "TimeGenerated"
_DEFAULT_LOOKBACK_SECONDS: Final[int] = 3_600


@dataclass(frozen=True, slots=True)
class MetricKqlTemplate:
    """A trusted, config-supplied KQL query for one CSP-neutral metric.

    ``kql`` MUST return a table that includes ``timestamp_column``,
    ``value_column``, and every entry in ``label_columns``. The query is
    author-controlled configuration - never built from untrusted input.
    """

    kql: str
    value_column: str
    timestamp_column: str = _DEFAULT_TIMESTAMP_COLUMN
    label_columns: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AzureMonitorLogsConfig:
    """Configuration for the Azure Monitor Logs metric adapter.

    Every value except ``workspace_id`` and ``queries`` has a documented
    default so the composition root only supplies what a fork overrides.
    """

    workspace_id: str
    """Log Analytics workspace GUID (the ``customerId``, not the ARM id)."""

    queries: Mapping[str, MetricKqlTemplate]
    """CSP-neutral ``metric_name`` -> KQL template. A query for a metric
    absent from this map fails closed with ``MetricProviderError``."""

    endpoint: str = _DEFAULT_ENDPOINT
    """Root URL for the Log Analytics query API; sovereign clouds override this."""

    api_path: str = _DEFAULT_API_PATH
    """API version path segment. Pinned by the adapter, not an SDK - a bump
    is an intentional, reviewable contract change."""

    audience: str = _DEFAULT_AUDIENCE
    """OIDC audience for the bearer token requested from ``WorkloadIdentity``."""

    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS
    max_rows: int = _DEFAULT_MAX_ROWS
    max_response_bytes: int = _DEFAULT_MAX_RESPONSE_BYTES
    default_lookback_seconds: int = _DEFAULT_LOOKBACK_SECONDS
    """Window width used to bound a one-sided query. When only ``until`` is
    given, the start is ``until - default_lookback_seconds``; when only
    ``since`` is given, the end is ``now``. This guarantees the server-side
    ``timespan`` is always bounded so a template with no own time filter
    cannot full-scan its table."""

    def __post_init__(self) -> None:
        if not self.workspace_id:
            raise ValueError("AzureMonitorLogsConfig.workspace_id MUST be non-empty")
        # The bearer token is attached to every request; a plaintext endpoint
        # would leak it on the wire. Real Log Analytics endpoints (public +
        # sovereign clouds) are all https, so plaintext is always a misconfig.
        if not self.endpoint.lower().startswith("https://"):
            raise ValueError(
                "AzureMonitorLogsConfig.endpoint MUST use https:// - the bearer "
                f"token is sent on every request (got {self.endpoint!r})"
            )
        if not self.api_path.startswith("/"):
            raise ValueError(
                f"AzureMonitorLogsConfig.api_path MUST start with '/' (got {self.api_path!r})"
            )
        if self.timeout_seconds <= 0:
            raise ValueError("AzureMonitorLogsConfig.timeout_seconds MUST be positive")
        if self.max_rows <= 0:
            raise ValueError("AzureMonitorLogsConfig.max_rows MUST be positive")
        if self.max_response_bytes < 1:
            raise ValueError("AzureMonitorLogsConfig.max_response_bytes MUST be >= 1")
        if self.default_lookback_seconds <= 0:
            raise ValueError("AzureMonitorLogsConfig.default_lookback_seconds MUST be positive")


def _parse_timestamp(raw: Any) -> datetime:
    """Parse a Log Analytics ISO-8601 timestamp into an aware datetime."""
    if isinstance(raw, datetime):
        return raw
    if not isinstance(raw, str) or not raw:
        raise MetricProviderError(f"non-string timestamp in Log Analytics row: {raw!r}")
    text = raw.replace("Z", "+00:00") if raw.endswith("Z") else raw
    try:
        return datetime.fromisoformat(text)
    except ValueError as exc:
        raise MetricProviderError(f"unparseable Log Analytics timestamp: {raw!r}") from exc


def _coerce_value(raw: Any) -> float:
    """Coerce a Log Analytics cell into a float, failing closed on garbage."""
    if isinstance(raw, bool):  # bool is an int subclass - reject to avoid 0/1 surprises
        raise MetricProviderError(f"boolean where numeric metric expected: {raw!r}")
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise MetricProviderError(f"non-numeric metric value: {raw!r}") from exc
    # NaN / +-Inf would silently poison anomaly detection (nan breaks every
    # comparison, inf breaks every sum). Fail closed so the caller abstains.
    if not isfinite(value):
        raise MetricProviderError(f"non-finite metric value: {raw!r}")
    return value


class AzureMonitorLogsMetricProvider:
    """Stream external metric samples from Azure Monitor Logs (KQL)."""

    def __init__(
        self,
        *,
        config: AzureMonitorLogsConfig,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._config: Final[AzureMonitorLogsConfig] = config
        self._identity: Final[WorkloadIdentity] = identity
        self._http: Final[httpx.AsyncClient] = http_client
        # Injected so a one-sided ``since``-only window can be closed at "now"
        # deterministically in tests; defaults to the wall clock.
        self._clock: Final[Callable[[], datetime]] = clock or (lambda: datetime.now(tz=UTC))

    async def query(self, query: MetricQuery) -> AsyncIterator[MetricPoint]:
        template = self._config.queries.get(query.metric_name)
        if template is None:
            raise MetricProviderError(
                f"no KQL template configured for metric {query.metric_name!r}"
            )

        points = await self._run(query=query, template=template)
        for point in points:
            yield point

    async def _run(self, *, query: MetricQuery, template: MetricKqlTemplate) -> list[MetricPoint]:
        url = (
            f"{self._config.endpoint.rstrip('/')}"
            f"{self._config.api_path}"
            f"/workspaces/{self._config.workspace_id}/query"
        )
        body: dict[str, Any] = {"query": template.kql}
        timespan = _build_timespan(
            query.since,
            query.until,
            now=self._clock(),
            lookback=timedelta(seconds=self._config.default_lookback_seconds),
        )
        if timespan is not None:
            body["timespan"] = timespan

        token = await self._identity.get_token(self._config.audience)
        headers = {
            "Authorization": f"Bearer {token.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        try:
            response = await self._http.post(
                url,
                headers=headers,
                content=json.dumps(body),
                timeout=self._config.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise MetricProviderError(
                f"Log Analytics request failed for {query.metric_name!r}: {exc}"
            ) from exc

        if response.status_code >= 400:
            snippet = response.text[:200].replace("\n", " ")
            raise MetricProviderError(
                f"Log Analytics returned HTTP {response.status_code} for "
                f"{query.metric_name!r}: {snippet!r}"
            )

        # Cap the body before parsing. ``max_rows`` only applies AFTER the
        # JSON is parsed into memory, so a hostile / misconfigured workspace
        # returning a multi-gigabyte body would OOM the decoder first. Fail
        # closed on an over-cap body instead.
        if len(response.content) > self._config.max_response_bytes:
            raise MetricProviderError(
                f"Log Analytics response for {query.metric_name!r} is "
                f"{len(response.content)} bytes, over the "
                f"{self._config.max_response_bytes}-byte cap; narrow the query"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise MetricProviderError(
                f"Log Analytics returned non-JSON for {query.metric_name!r}"
            ) from exc

        return self._map_payload(payload=payload, query=query, template=template)

    def _map_payload(
        self,
        *,
        payload: Any,
        query: MetricQuery,
        template: MetricKqlTemplate,
    ) -> list[MetricPoint]:
        tables = payload.get("tables") if isinstance(payload, Mapping) else None
        if not isinstance(tables, list) or not tables:
            raise MetricProviderError(
                f"Log Analytics payload missing 'tables' for {query.metric_name!r}"
            )
        table = tables[0]
        columns = table.get("columns") if isinstance(table, Mapping) else None
        rows = table.get("rows") if isinstance(table, Mapping) else None
        if not isinstance(columns, list) or not isinstance(rows, list):
            raise MetricProviderError(f"Log Analytics table malformed for {query.metric_name!r}")

        index = _column_index(columns)
        ts_i = _require_column(index, template.timestamp_column, query.metric_name)
        val_i = _require_column(index, template.value_column, query.metric_name)
        label_i = {
            name: _require_column(index, name, query.metric_name) for name in template.label_columns
        }
        # Largest cell index any row must supply; a ragged/hostile row shorter
        # than this would otherwise raise IndexError - an unexpected exception
        # that bypasses the fail-closed MetricProviderError contract.
        needed = max(ts_i, val_i, *label_i.values())

        if len(rows) > self._config.max_rows:
            raise MetricProviderError(
                f"Log Analytics returned {len(rows)} rows for {query.metric_name!r}, "
                f"over the max_rows cap of {self._config.max_rows}; narrow the query"
            )

        points: list[MetricPoint] = []
        for row in rows:
            if not isinstance(row, list):
                raise MetricProviderError(
                    f"Log Analytics row is not an array for {query.metric_name!r}"
                )
            if len(row) <= needed:
                raise MetricProviderError(
                    f"Log Analytics row has fewer cells than columns for {query.metric_name!r}"
                )
            labels = {name: str(row[i]) for name, i in label_i.items()}
            if not _labels_match(labels, query.labels):
                continue
            points.append(
                MetricPoint(
                    metric_name=query.metric_name,
                    at=_parse_timestamp(row[ts_i]),
                    value=_coerce_value(row[val_i]),
                    labels=labels,
                )
            )

        points.sort(key=lambda p: p.at)
        return points


def _build_timespan(
    since: datetime | None,
    until: datetime | None,
    *,
    now: datetime,
    lookback: timedelta,
) -> str | None:
    """Return an ISO-8601 interval for the API ``timespan`` param, or None.

    The server-side ``timespan`` is always bounded when any bound is given,
    so a KQL template that carries no own time filter cannot full-scan its
    table:

    - both bounds -> the exact closed interval;
    - ``since`` only -> ``since / now`` (everything since, up to now);
    - ``until`` only -> ``(until - lookback) / until`` (a bounded window
      ending at ``until``);
    - neither -> ``None``, the explicit opt-out where the template's own
      time filter governs.

    A naive datetime is coerced to UTC so the ``timespan`` is never sent
    without a zone (Azure would otherwise interpret it ambiguously).
    """
    if since is None and until is None:
        return None
    lo = _as_utc(since) if since is not None else _as_utc(until) - lookback  # type: ignore[arg-type]
    hi = _as_utc(until) if until is not None else _as_utc(now)
    return f"{lo.isoformat()}/{hi.isoformat()}"


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _column_index(columns: list[Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for i, col in enumerate(columns):
        if isinstance(col, Mapping) and isinstance(col.get("name"), str):
            out[col["name"]] = i
    return out


def _require_column(index: Mapping[str, int], name: str, metric_name: str) -> int:
    if name not in index:
        raise MetricProviderError(
            f"Log Analytics result for {metric_name!r} lacks required column {name!r}"
        )
    return index[name]


def _labels_match(sample: Mapping[str, str], wanted: Mapping[str, str]) -> bool:
    return all(sample.get(k) == v for k, v in wanted.items())


__all__ = [
    "AzureMonitorLogsConfig",
    "AzureMonitorLogsMetricProvider",
    "MetricKqlTemplate",
]
