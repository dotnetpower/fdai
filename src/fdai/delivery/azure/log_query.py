"""Azure Monitor Logs (Log Analytics KQL) implementation of the
:class:`~fdai.shared.providers.observation.LogQueryProvider` seam.

The read-class log-query surface behind the operator console's
``query_log`` tool (RBAC ``READER``, ``side_effect_class="read"``): run a
bounded KQL query against a single Log Analytics workspace and return the
rows. This is the third **real** observation adapter (alongside
``metric_logs.py`` for metrics and ``deployment_history.py`` for change
history); the upstream default stays the in-memory fake so the dev-mode
local-fake parity contract holds. ``core/`` never imports this module - it
is bound at the composition root.

Design boundaries
-----------------

- Identity flows through the injected
  :class:`~fdai.shared.providers.workload_identity.WorkloadIdentity`
  Protocol - no ``DefaultAzureCredential``, no ``azure-identity`` import.
- HTTP transport is an injected :class:`httpx.AsyncClient`. Tests pass a
  client backed by :class:`httpx.MockTransport`; production wires a
  long-lived shared client at the composition root. Mirrors
  :mod:`~fdai.delivery.azure.metric_logs`.

Query trust model
-----------------

Unlike the metric adapter (a trusted, CSP-neutral ``metric_name`` -> KQL
template), the ``LogQueryProvider`` contract takes an **opaque, caller-
supplied KQL query** - the narrator composes it and the tool passes it
through. That input is untrusted, so the adapter bounds it structurally
rather than trusting it:

- **Read-only language**: Log Analytics KQL is a query-only language over
  a single workspace; it cannot mutate or delete data. Combined with the
  executor's least-privilege managed identity (scoped to *this* workspace),
  the blast radius of a hostile query is a bounded read.
- **Server-side time bound**: the ``window`` is sent as the API-native
  ``timespan`` so the query cannot scan an unbounded history.
- **Bounded result size**: the adapter clips the result to ``max_rows``
  (flagging ``truncated=True``) - matching the in-memory fake's semantics -
  and a per-request ``timeout`` caps latency/cost.
- **Fail-closed on partial**: a non-2xx response, a malformed table, or a
  transport error raises
  :class:`~fdai.shared.providers.observation.LogQueryError`; per
  ``architecture.instructions.md`` the caller abstains rather than acting
  on a partial observation.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

import httpx

from fdai.shared.providers.observation import LogQueryError, LogQueryResult
from fdai.shared.providers.workload_identity import WorkloadIdentity

_DEFAULT_ENDPOINT: Final[str] = "https://api.loganalytics.io"
_DEFAULT_API_PATH: Final[str] = "/v1"
_DEFAULT_AUDIENCE: Final[str] = "https://api.loganalytics.io/.default"
_DEFAULT_TIMEOUT_SECONDS: Final[float] = 30.0
_DEFAULT_MAX_ROWS_CAP: Final[int] = 10_000


@dataclass(frozen=True, slots=True)
class AzureLogAnalyticsQueryConfig:
    """Configuration for the Azure Monitor Logs query adapter.

    Every value except ``workspace_id`` has a documented default so the
    composition root only supplies what a fork overrides.
    """

    workspace_id: str
    """Log Analytics workspace GUID (the ``customerId``, not the ARM id)."""

    endpoint: str = _DEFAULT_ENDPOINT
    """Root URL for the Log Analytics query API; sovereign clouds override this."""

    api_path: str = _DEFAULT_API_PATH
    """API version path segment. Pinned by the adapter, not an SDK - a bump
    is an intentional, reviewable contract change."""

    audience: str = _DEFAULT_AUDIENCE
    """OIDC audience for the bearer token requested from ``WorkloadIdentity``."""

    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS
    max_rows_cap: int = _DEFAULT_MAX_ROWS_CAP
    """Hard ceiling on ``max_rows`` regardless of the caller's request, so a
    runaway query cannot buffer an unbounded result set into memory."""

    def __post_init__(self) -> None:
        if not self.workspace_id:
            raise ValueError("AzureLogAnalyticsQueryConfig.workspace_id MUST be non-empty")
        if self.timeout_seconds <= 0:
            raise ValueError("AzureLogAnalyticsQueryConfig.timeout_seconds MUST be > 0")
        if self.max_rows_cap < 1:
            raise ValueError("AzureLogAnalyticsQueryConfig.max_rows_cap MUST be >= 1")


class AzureLogAnalyticsQueryProvider:
    """Run a bounded, read-only KQL query against one Log Analytics workspace."""

    def __init__(
        self,
        *,
        config: AzureLogAnalyticsQueryConfig,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
    ) -> None:
        self._config: Final[AzureLogAnalyticsQueryConfig] = config
        self._identity: Final[WorkloadIdentity] = identity
        self._http: Final[httpx.AsyncClient] = http_client

    async def query_log(
        self,
        *,
        query: str,
        window: str,
        max_rows: int = 100,
    ) -> LogQueryResult:
        """Run ``query`` bounded by ``window`` and return up to ``max_rows`` rows.

        Fails closed by raising :class:`LogQueryError` on an empty query /
        window, a non-2xx response, a transport error, or a malformed
        result table.
        """
        if not query.strip():
            raise LogQueryError("query_log requires a non-empty query")
        if not window.strip():
            raise LogQueryError("query_log requires a non-empty window")
        limit = max(1, min(max_rows, self._config.max_rows_cap))

        payload = await self._run(query=query, window=window)
        rows = self._map_payload(payload)

        truncated = len(rows) > limit
        return LogQueryResult(
            rows=tuple(rows[:limit]),
            truncated=truncated,
            scanned_records=len(rows),
            metadata={"workspace_id": self._config.workspace_id},
        )

    async def _run(self, *, query: str, window: str) -> Any:
        url = (
            f"{self._config.endpoint.rstrip('/')}"
            f"{self._config.api_path}"
            f"/workspaces/{self._config.workspace_id}/query"
        )
        body = {"query": query, "timespan": window}
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
            raise LogQueryError(f"Log Analytics request failed: {exc}") from exc

        if response.status_code >= 400:
            snippet = response.text[:200].replace("\n", " ")
            raise LogQueryError(
                f"Log Analytics returned HTTP {response.status_code}: {snippet!r}"
            )

        try:
            return response.json()
        except ValueError as exc:
            raise LogQueryError("Log Analytics returned non-JSON") from exc

    def _map_payload(self, payload: Any) -> list[Mapping[str, Any]]:
        tables = payload.get("tables") if isinstance(payload, Mapping) else None
        if not isinstance(tables, list) or not tables:
            raise LogQueryError("Log Analytics payload missing 'tables'")
        table = tables[0]
        columns = table.get("columns") if isinstance(table, Mapping) else None
        rows = table.get("rows") if isinstance(table, Mapping) else None
        if not isinstance(columns, list) or not isinstance(rows, list):
            raise LogQueryError("Log Analytics table malformed")

        names = [
            col["name"]
            for col in columns
            if isinstance(col, Mapping) and isinstance(col.get("name"), str)
        ]
        if len(names) != len(columns):
            raise LogQueryError("Log Analytics column metadata malformed")
        if len(set(names)) != len(names):
            # An opaque query (e.g. `project a=x, a=y`) can produce duplicate
            # column names; dict-zipping them would silently drop a column, so
            # fail closed on the ambiguous schema rather than lose data.
            raise LogQueryError("Log Analytics returned duplicate column names")

        mapped: list[Mapping[str, Any]] = []
        for row in rows:
            if not isinstance(row, list):
                raise LogQueryError("Log Analytics row is not an array")
            if len(row) != len(names):
                raise LogQueryError("Log Analytics row/column length mismatch")
            mapped.append(dict(zip(names, row, strict=True)))
        return mapped


__all__ = [
    "AzureLogAnalyticsQueryConfig",
    "AzureLogAnalyticsQueryProvider",
]
