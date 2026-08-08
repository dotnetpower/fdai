"""Azure DevOps implementation of the
:class:`~fdai.shared.providers.change_feed.ChangeFeed` seam.

Reads recent completed **builds** (and their source commit) from the Azure
DevOps REST API and normalizes them into CSP/VCS-neutral
:class:`~fdai.shared.providers.change_feed.ChangeRecord` values that RCA
correlates against an incident. Mirrors
:mod:`fdai.delivery.github.change_feed`; ``core/`` never imports this module.

Design boundaries
-----------------

- HTTP transport is an injected :class:`httpx.AsyncClient` (tests use
  :class:`httpx.MockTransport`).
- The credential is supplied by an injected zero-argument async
  ``token_provider`` callable so a fork can source a PAT from Key Vault or
  mint an Entra token via workload-identity federation without this module
  importing any secret SDK. ``auth_scheme`` selects how the token is sent:
  ``basic`` (default; a PAT sent as HTTP Basic with an empty username, the
  standard ADO PAT scheme) or ``bearer`` (an Entra access token).
- **Multi-page fetch**: Azure DevOps paginates with the
  ``x-ms-continuationtoken`` response header, echoed back as the
  ``continuationToken`` query parameter. A single page can miss in-window
  changes for a historical ``until``, so the adapter follows the token up
  to ``max_pages`` and **fails closed** (raises :class:`ChangeFeedError`)
  if more pages remain past the cap rather than silently truncating.
- Fail-closed: a non-2xx response or malformed payload raises
  :class:`ChangeFeedError`; RCA then correlates over whatever it already
  has rather than blocking on the feed.
"""

from __future__ import annotations

import base64
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

import httpx

from fdai.shared.providers.change_feed import ChangeFeedError, ChangeRecord

_DEFAULT_API: Final[str] = "https://dev.azure.com"
_DEFAULT_API_VERSION: Final[str] = "7.1"
_DEFAULT_TIMEOUT_SECONDS: Final[float] = 20.0
_DEFAULT_MAX_RECORDS: Final[int] = 200
_DEFAULT_MAX_PAGES: Final[int] = 10
_DEFAULT_PAGE_SIZE: Final[int] = 100
_DEFAULT_MAX_RESPONSE_BYTES: Final[int] = 10_000_000

TokenProvider = Callable[[], Awaitable[str]]


@dataclass(frozen=True, slots=True)
class AzureDevOpsChangeFeedConfig:
    """Configuration for the Azure DevOps change feed.

    ``organization`` / ``project`` scope the build query. ``definition_ids``
    optionally narrows to specific build/pipeline definitions.
    """

    organization: str
    project: str
    definition_ids: tuple[int, ...] = ()
    auth_scheme: str = "basic"
    api_base: str = _DEFAULT_API
    api_version: str = _DEFAULT_API_VERSION
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS
    max_records: int = _DEFAULT_MAX_RECORDS
    max_pages: int = _DEFAULT_MAX_PAGES
    page_size: int = _DEFAULT_PAGE_SIZE
    max_response_bytes: int = _DEFAULT_MAX_RESPONSE_BYTES

    def __post_init__(self) -> None:
        if not self.organization:
            raise ValueError("AzureDevOpsChangeFeedConfig.organization MUST be non-empty")
        if not self.project:
            raise ValueError("AzureDevOpsChangeFeedConfig.project MUST be non-empty")
        if self.auth_scheme not in ("basic", "bearer"):
            raise ValueError("auth_scheme MUST be 'basic' or 'bearer'")
        if not self.api_base.lower().startswith("https://"):
            raise ValueError(
                f"AzureDevOpsChangeFeedConfig.api_base MUST use https:// (got {self.api_base!r})"
            )
        if self.max_records <= 0:
            raise ValueError("max_records MUST be positive")
        if self.max_pages <= 0:
            raise ValueError("max_pages MUST be positive")
        if not 1 <= self.page_size <= 5000:
            raise ValueError("page_size MUST be in [1, 5000]")
        if self.max_response_bytes < 1:
            raise ValueError("max_response_bytes MUST be >= 1")


def _as_utc(dt: datetime) -> datetime:
    """Return ``dt`` as UTC-aware; a naive value is assumed to be UTC."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _parse_ts(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    text = raw.replace("Z", "+00:00") if raw.endswith("Z") else raw
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


class AzureDevOpsChangeFeed:
    """Fetch and normalize recent Azure DevOps builds into change records."""

    def __init__(
        self,
        *,
        config: AzureDevOpsChangeFeedConfig,
        http_client: httpx.AsyncClient,
        token_provider: TokenProvider,
    ) -> None:
        self._config: Final[AzureDevOpsChangeFeedConfig] = config
        self._http: Final[httpx.AsyncClient] = http_client
        self._token_provider: Final[TokenProvider] = token_provider

    async def recent(
        self,
        *,
        since: datetime,
        until: datetime,
        resource_hint: str | None = None,
    ) -> list[ChangeRecord]:
        # Normalize the window bounds to UTC-aware up front: a naive bound
        # from a caller would raise TypeError when compared against the
        # UTC-aware record timestamps below, escaping the ChangeFeedError
        # fail-closed contract.
        since = _as_utc(since)
        until = _as_utc(until)
        headers = await self._auth_headers()
        url = (
            f"{self._config.api_base.rstrip('/')}/{self._config.organization}"
            f"/{self._config.project}/_apis/build/builds"
        )
        base_params: dict[str, str] = {
            "api-version": self._config.api_version,
            "$top": str(self._config.page_size),
            "statusFilter": "completed",
            "queryOrder": "finishTimeDescending",
            "minTime": since.astimezone(UTC).isoformat(),
            "maxTime": until.astimezone(UTC).isoformat(),
        }
        if self._config.definition_ids:
            base_params["definitions"] = ",".join(str(d) for d in self._config.definition_ids)

        records: list[ChangeRecord] = []
        continuation: str | None = None
        for _page in range(self._config.max_pages):
            params = dict(base_params)
            if continuation is not None:
                params["continuationToken"] = continuation
            payload, continuation = await self._fetch_page(url, params=params, headers=headers)

            for row in payload:
                record = self._map_build(row, resource_hint=resource_hint)
                if record is None:
                    continue
                if since <= record.at <= until:
                    records.append(record)
                if len(records) >= self._config.max_records:
                    return records

            if not continuation:
                return records
        # Loop ran to max_pages with a continuation token still pending:
        # fail closed rather than return a window that may be missing
        # in-range builds (matches the ARG pagination-cap discipline).
        raise ChangeFeedError(
            f"Azure DevOps pagination cap ({self._config.max_pages}) exceeded for "
            f"{self._config.organization}/{self._config.project}; narrow the time window"
        )

    async def _fetch_page(
        self, url: str, *, params: Mapping[str, str], headers: Mapping[str, str]
    ) -> tuple[list[Any], str | None]:
        try:
            response = await self._http.get(
                url, params=params, headers=headers, timeout=self._config.timeout_seconds
            )
        except httpx.HTTPError as exc:
            raise ChangeFeedError(
                f"Azure DevOps builds request failed for "
                f"{self._config.organization}/{self._config.project}: {type(exc).__name__}"
            ) from exc

        if response.status_code >= 400:
            snippet = response.text[:200].replace("\n", " ")
            raise ChangeFeedError(
                f"Azure DevOps returned HTTP {response.status_code} for "
                f"{self._config.organization}/{self._config.project}: {snippet!r}"
            )

        if len(response.content) > self._config.max_response_bytes:
            raise ChangeFeedError(
                f"Azure DevOps response for "
                f"{self._config.organization}/{self._config.project} is "
                f"{len(response.content)} bytes, over the "
                f"{self._config.max_response_bytes}-byte cap; narrow the window"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise ChangeFeedError(
                f"Azure DevOps returned non-JSON for "
                f"{self._config.organization}/{self._config.project}"
            ) from exc

        if not isinstance(payload, Mapping):
            raise ChangeFeedError(
                f"Azure DevOps builds payload is not an object for "
                f"{self._config.organization}/{self._config.project}"
            )
        value = payload.get("value")
        if not isinstance(value, list):
            raise ChangeFeedError(
                f"Azure DevOps builds payload missing 'value' array for "
                f"{self._config.organization}/{self._config.project}"
            )
        token = response.headers.get("x-ms-continuationtoken")
        return value, (token or None)

    async def _auth_headers(self) -> dict[str, str]:
        token = await self._token_provider()
        headers = {"Accept": "application/json"}
        if self._config.auth_scheme == "bearer":
            headers["Authorization"] = f"Bearer {token}"
        else:
            # ADO PAT: HTTP Basic with an empty username.
            basic = base64.b64encode(f":{token}".encode()).decode("ascii")
            headers["Authorization"] = f"Basic {basic}"
        return headers

    def _map_build(self, row: Any, *, resource_hint: str | None) -> ChangeRecord | None:
        if not isinstance(row, Mapping):
            return None
        at = _parse_ts(row.get("finishTime"))
        if at is None:
            return None
        sha = str(row.get("sourceVersion", ""))[:12]
        build_number = str(row.get("buildNumber", ""))
        branch = str(row.get("sourceBranch", ""))
        requested = row.get("requestedFor")
        author = str(requested.get("displayName", "")) if isinstance(requested, Mapping) else ""
        hints = (resource_hint,) if resource_hint else ()
        metadata: dict[str, str] = {}
        if branch:
            metadata["branch"] = branch
        if build_number:
            metadata["build_number"] = build_number
        # Coalesce a stable id; a JSON ``"id": null`` returns None from .get,
        # so guard explicitly rather than rendering "ado-build-None".
        raw_id = row.get("id")
        build_key = str(raw_id) if raw_id is not None else (sha or build_number)
        if not build_key:
            return None
        return ChangeRecord(
            change_id=f"ado-build-{build_key}",
            at=at,
            source="azure-devops",
            ref=sha or build_number or build_key,
            summary=f"build {build_number or sha} on {branch or 'unknown'}",
            author=author,
            resource_hints=hints,
            metadata=metadata,
        )


__all__ = [
    "AzureDevOpsChangeFeed",
    "AzureDevOpsChangeFeedConfig",
    "ChangeFeedError",
    "TokenProvider",
]
