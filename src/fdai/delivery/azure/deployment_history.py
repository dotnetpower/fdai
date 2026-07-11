"""Azure Resource Graph implementation of the
:class:`~fdai.shared.providers.observation.DeploymentHistoryProvider` seam.

Answers "what changed in the estate over the window" - the change /
deployment signal the T1 causal-chain RCA reasons over (the ``is_change``
antecedents) and the operator console surfaces via the ``query_deployments``
tool. This is the first **real** ``DeploymentHistoryProvider`` adapter; the
upstream default stays the in-memory fake so the dev-mode local-fake parity
contract holds. ``core/`` never imports this module - it is bound at the
composition root.

Design boundaries
-----------------

- Identity flows through the injected
  :class:`~fdai.shared.providers.workload_identity.WorkloadIdentity`
  Protocol - no ``DefaultAzureCredential``, no ``azure-identity`` import.
  A fork MAY plug in IRSA / SPIFFE / GCP-WIF under the same seam.
- HTTP transport is an injected :class:`httpx.AsyncClient`. Tests pass a
  client backed by :class:`httpx.MockTransport`; production wires a
  long-lived shared client at the composition root. This mirrors
  :mod:`~fdai.delivery.azure.arg_query` and
  :mod:`~fdai.delivery.azure.metric_logs` exactly.
- The Kusto query is a **trusted, config-supplied template** (e.g. over
  the Azure Resource Graph ``resourcechanges`` table). Untrusted inputs
  are **never** interpolated into it: the ``window`` bounds the query only
  as a validated integer second-count substituted for the ``{window_seconds}``
  token, and the untrusted ``resource_ref`` filter is applied **in memory**
  over returned rows (same semantics as
  :class:`~fdai.shared.providers.testing.observation.InMemoryDeploymentHistoryProvider`).
  This removes the Kusto-injection surface entirely.

Safety / cost invariants
------------------------

- **Bounded time window**: ``window`` is parsed to a positive integer
  second-count (ISO-8601 duration); an unparseable or non-positive window
  fails closed with :class:`~fdai.shared.providers.observation.DeploymentHistoryError`.
- **Bounded pagination**: ``max_pages`` caps ``$skipToken`` follow-ups.
- **Bounded result size**: ``max_records`` caps the number of mapped
  records; exceeding it raises ``DeploymentHistoryError`` (fail-closed)
  rather than silently truncating, so a too-broad query surfaces to the
  operator instead of feeding a partial change set into RCA.
- **Fail-closed on partial**: a non-2xx response, a malformed page, or a
  row missing a configured column raises ``DeploymentHistoryError``. Per
  ``architecture.instructions.md`` the caller abstains rather than acting
  on a partial observation.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

import httpx

from fdai.shared.providers.observation import (
    DeploymentHistoryError,
    DeploymentHistoryResult,
    DeploymentRecord,
)
from fdai.shared.providers.workload_identity import WorkloadIdentity

_DEFAULT_ARG_ENDPOINT: Final[str] = "https://management.azure.com"
_DEFAULT_ARG_API_VERSION: Final[str] = "2022-10-01"
_DEFAULT_AUDIENCE: Final[str] = "https://management.azure.com/.default"
_DEFAULT_PAGE_SIZE: Final[int] = 1000
_DEFAULT_MAX_PAGES: Final[int] = 32
_DEFAULT_MAX_RECORDS: Final[int] = 10_000
_DEFAULT_TIMEOUT_SECONDS: Final[float] = 30.0
_WINDOW_TOKEN: Final[str] = "{window_seconds}"  # noqa: S105 - query placeholder, not a secret

# ISO-8601 duration (PnW nD T nH nM nS). At least one component required.
_ISO8601_DURATION: Final[re.Pattern[str]] = re.compile(
    r"^P(?!$)(?:(\d+)W)?(?:(\d+)D)?(?:T(?!$)(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$"
)


@dataclass(frozen=True, slots=True)
class AzureDeploymentHistoryConfig:
    """Configuration for the Azure Resource Graph deployment-history adapter.

    ``kql_template`` is author-controlled configuration (never built from
    untrusted input) and MUST contain the ``{window_seconds}`` token and
    return a table including ``deployment_ref_column``, ``timestamp_column``,
    ``resource_ref_column``, ``status_column``, and ``author_column``.
    """

    subscription_scopes: tuple[str, ...]
    kql_template: str

    deployment_ref_column: str = "deployment_ref"
    timestamp_column: str = "timestamp"
    resource_ref_column: str = "resource_ref"
    status_column: str = "status"
    author_column: str = "author"

    arg_endpoint: str = _DEFAULT_ARG_ENDPOINT
    arg_api_version: str = _DEFAULT_ARG_API_VERSION
    audience: str = _DEFAULT_AUDIENCE
    page_size: int = _DEFAULT_PAGE_SIZE
    max_pages: int = _DEFAULT_MAX_PAGES
    max_records: int = _DEFAULT_MAX_RECORDS
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if not self.subscription_scopes:
            raise ValueError("AzureDeploymentHistoryConfig.subscription_scopes MUST NOT be empty")
        if _WINDOW_TOKEN not in self.kql_template:
            raise ValueError(
                f"AzureDeploymentHistoryConfig.kql_template MUST contain the "
                f"{_WINDOW_TOKEN!r} token for the bounded time window"
            )
        if self.page_size < 1 or self.page_size > 1000:
            raise ValueError("page_size MUST be in [1, 1000]")
        if self.max_pages < 1:
            raise ValueError("max_pages MUST be >= 1")
        if self.max_records < 1:
            raise ValueError("max_records MUST be >= 1")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds MUST be > 0")
        # A blank column name would make every row fail _require at query
        # time (a silent empty result for the member source, a hard error
        # for the console); catch the misconfig at startup instead.
        for name, column in (
            ("deployment_ref_column", self.deployment_ref_column),
            ("timestamp_column", self.timestamp_column),
            ("resource_ref_column", self.resource_ref_column),
            ("status_column", self.status_column),
            ("author_column", self.author_column),
        ):
            if not column:
                raise ValueError(f"AzureDeploymentHistoryConfig.{name} MUST be non-empty")


class AzureResourceGraphDeploymentHistory:
    """Query estate changes / deployments from Azure Resource Graph (Kusto)."""

    def __init__(
        self,
        *,
        config: AzureDeploymentHistoryConfig,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
    ) -> None:
        self._config: Final[AzureDeploymentHistoryConfig] = config
        self._identity: Final[WorkloadIdentity] = identity
        self._http: Final[httpx.AsyncClient] = http_client

    async def query_deployments(
        self, *, window: str, resource_ref: str | None = None
    ) -> DeploymentHistoryResult:
        """Return every deployment/change in ``window`` (optionally filtered).

        ``window`` is an ISO-8601 duration (``PT1H``, ``P1D``, ``P7D``);
        the untrusted ``resource_ref`` is applied in memory. Fails closed
        by raising :class:`DeploymentHistoryError`.
        """
        window_seconds = _parse_window_seconds(window)
        query = self._config.kql_template.replace(_WINDOW_TOKEN, str(window_seconds))
        rows = await self._fetch_all_pages(query=query)

        records: list[DeploymentRecord] = []
        for row in rows:
            record = self._map_row(row)
            if resource_ref is not None and resource_ref not in record.resource_refs:
                continue
            records.append(record)

        return DeploymentHistoryResult(records=tuple(records), window=window)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _fetch_all_pages(self, *, query: str) -> list[Mapping[str, Any]]:
        url = (
            f"{self._config.arg_endpoint.rstrip('/')}"
            "/providers/Microsoft.ResourceGraph/resources"
            f"?api-version={self._config.arg_api_version}"
        )
        token = await self._identity.get_token(self._config.audience)
        headers = {
            "Authorization": f"Bearer {token.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        collected: list[Mapping[str, Any]] = []
        skip_token: str | None = None

        for page in range(self._config.max_pages):
            body: dict[str, Any] = {
                "subscriptions": list(self._config.subscription_scopes),
                "query": query,
                "options": {"$top": self._config.page_size},
            }
            if skip_token is not None:
                body["options"]["$skipToken"] = skip_token

            try:
                response = await self._http.post(
                    url,
                    headers=headers,
                    content=json.dumps(body),
                    timeout=self._config.timeout_seconds,
                )
            except httpx.HTTPError as exc:
                raise DeploymentHistoryError(
                    f"ARG deployment-history request failed (page {page}): {exc}"
                ) from exc

            if response.status_code >= 400:
                snippet = response.text[:200].replace("\n", " ")
                raise DeploymentHistoryError(
                    f"ARG returned HTTP {response.status_code} for deployment history "
                    f"(page {page}): {snippet!r}"
                )

            try:
                payload = response.json()
            except ValueError as exc:
                raise DeploymentHistoryError(
                    f"ARG returned non-JSON for deployment history (page {page})"
                ) from exc

            data = payload.get("data") if isinstance(payload, Mapping) else None
            if not isinstance(data, list):
                raise DeploymentHistoryError(
                    f"ARG payload missing 'data' array for deployment history (page {page})"
                )

            for row in data:
                if isinstance(row, Mapping):
                    collected.append(row)
            if len(collected) > self._config.max_records:
                raise DeploymentHistoryError(
                    f"ARG returned more than {self._config.max_records} deployment "
                    "records; narrow the query window or resource filter"
                )

            next_token = payload.get("$skipToken")
            if not isinstance(next_token, str) or not next_token:
                break
            skip_token = next_token
        else:
            raise DeploymentHistoryError(
                f"ARG deployment history exceeded the max_pages cap of "
                f"{self._config.max_pages}; narrow the query"
            )

        return collected

    def _map_row(self, row: Mapping[str, Any]) -> DeploymentRecord:
        deployment_ref = self._require(row, self._config.deployment_ref_column)
        timestamp = self._require(row, self._config.timestamp_column)
        resource_ref = self._require(row, self._config.resource_ref_column)
        status = self._optional(row, self._config.status_column)
        author = self._optional(row, self._config.author_column)
        return DeploymentRecord(
            deployment_ref=deployment_ref,
            timestamp=timestamp,
            author=author,
            resource_refs=(resource_ref,),
            status=status,
        )

    @staticmethod
    def _require(row: Mapping[str, Any], column: str) -> str:
        value = row.get(column)
        if value is None or value == "":
            raise DeploymentHistoryError(f"ARG deployment row lacks required column {column!r}")
        return str(value)

    @staticmethod
    def _optional(row: Mapping[str, Any], column: str) -> str:
        value = row.get(column)
        return "" if value is None else str(value)


def _parse_window_seconds(window: str) -> int:
    """Parse an ISO-8601 duration into a positive integer second-count.

    Only the fields an operator uses for a lookback window are honored
    (weeks, days, hours, minutes, seconds). Months/years are rejected as
    ambiguous. Parsing is case-insensitive (``pt1h`` == ``PT1H``). Fails
    closed with :class:`DeploymentHistoryError`.
    """
    match = _ISO8601_DURATION.match(window.strip().upper()) if window else None
    if match is None:
        raise DeploymentHistoryError(
            f"unparseable window {window!r}; expected an ISO-8601 duration (PT1H, P1D, P7D)"
        )
    weeks, days, hours, minutes, seconds = (int(g) if g else 0 for g in match.groups())
    total = ((((weeks * 7 + days) * 24 + hours) * 60 + minutes) * 60) + seconds
    if total <= 0:
        raise DeploymentHistoryError(f"window {window!r} resolves to a non-positive duration")
    return total


__all__ = [
    "AzureDeploymentHistoryConfig",
    "AzureResourceGraphDeploymentHistory",
]
