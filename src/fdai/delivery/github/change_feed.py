"""GitHub implementation of the
:class:`~fdai.shared.providers.change_feed.ChangeFeed` seam.

Reads recent deployments (and their linked commits) from the GitHub REST
API and normalizes them into CSP/VCS-neutral
:class:`~fdai.shared.providers.change_feed.ChangeRecord` values that RCA
correlates against an incident. ``core/`` never imports this module - it is
bound at the composition root.

Design boundaries mirror the other ``delivery`` adapters:

- HTTP transport is an injected :class:`httpx.AsyncClient` (tests use
  :class:`httpx.MockTransport`).
- The token is supplied by an injected zero-argument async ``token_provider``
  callable so a fork can source it from Key Vault, a GitHub App installation
  token, or a workload identity federation exchange without this module
  importing any secret SDK.
- Fail-closed: a non-2xx response or malformed payload raises
  :class:`ChangeFeedError`; RCA then correlates over whatever it already
  has rather than blocking on the feed.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

import httpx

from fdai.shared.providers.change_feed import ChangeFeedError, ChangeRecord

_DEFAULT_API: Final[str] = "https://api.github.com"
_DEFAULT_TIMEOUT_SECONDS: Final[float] = 20.0
_DEFAULT_MAX_RECORDS: Final[int] = 200

TokenProvider = Callable[[], Awaitable[str]]


@dataclass(frozen=True, slots=True)
class GitHubChangeFeedConfig:
    """Configuration for the GitHub change feed.

    ``repository`` is ``owner/name``. ``environment`` optionally narrows to
    one deployment environment (e.g. ``production``).
    """

    repository: str
    environment: str | None = None
    api_base: str = _DEFAULT_API
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS
    max_records: int = _DEFAULT_MAX_RECORDS

    def __post_init__(self) -> None:
        if "/" not in self.repository:
            raise ValueError("GitHubChangeFeedConfig.repository MUST be 'owner/name'")
        if self.max_records <= 0:
            raise ValueError("GitHubChangeFeedConfig.max_records MUST be positive")


def _parse_ts(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    text = raw.replace("Z", "+00:00") if raw.endswith("Z") else raw
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


class GitHubChangeFeed:
    """Fetch and normalize recent GitHub deployments into change records."""

    def __init__(
        self,
        *,
        config: GitHubChangeFeedConfig,
        http_client: httpx.AsyncClient,
        token_provider: TokenProvider,
    ) -> None:
        self._config: Final[GitHubChangeFeedConfig] = config
        self._http: Final[httpx.AsyncClient] = http_client
        self._token_provider: Final[TokenProvider] = token_provider

    async def recent(
        self,
        *,
        since: datetime,
        until: datetime,
        resource_hint: str | None = None,
    ) -> list[ChangeRecord]:
        token = await self._token_provider()
        url = f"{self._config.api_base.rstrip('/')}/repos/{self._config.repository}/deployments"
        params: dict[str, str] = {"per_page": str(min(self._config.max_records, 100))}
        if self._config.environment:
            params["environment"] = self._config.environment

        try:
            response = await self._http.get(
                url,
                params=params,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                timeout=self._config.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise ChangeFeedError(
                f"GitHub deployments request failed for {self._config.repository!r}: {exc}"
            ) from exc

        if response.status_code >= 400:
            snippet = response.text[:200].replace("\n", " ")
            raise ChangeFeedError(
                f"GitHub returned HTTP {response.status_code} for "
                f"{self._config.repository!r}: {snippet!r}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise ChangeFeedError(
                f"GitHub returned non-JSON for {self._config.repository!r}"
            ) from exc

        if not isinstance(payload, list):
            raise ChangeFeedError(
                f"GitHub deployments payload is not a list for {self._config.repository!r}"
            )

        records: list[ChangeRecord] = []
        for row in payload:
            record = self._map_deployment(row, resource_hint=resource_hint)
            if record is None:
                continue
            if since <= record.at <= until:
                records.append(record)
            if len(records) >= self._config.max_records:
                break
        return records

    def _map_deployment(self, row: Any, *, resource_hint: str | None) -> ChangeRecord | None:
        if not isinstance(row, Mapping):
            return None
        at = _parse_ts(row.get("created_at"))
        if at is None:
            return None
        sha = str(row.get("sha", ""))[:12]
        env = str(row.get("environment", ""))
        creator = row.get("creator")
        author = str(creator.get("login", "")) if isinstance(creator, Mapping) else ""
        hints = (resource_hint,) if resource_hint else ()
        return ChangeRecord(
            change_id=f"gh-deploy-{row.get('id', sha)}",
            at=at,
            source="github",
            ref=sha or str(row.get("id", "")),
            summary=f"deployment to {env or 'unknown'}: {row.get('description') or sha}",
            author=author,
            resource_hints=hints,
            metadata={"environment": env} if env else {},
        )


__all__ = [
    "ChangeFeedError",
    "GitHubChangeFeed",
    "GitHubChangeFeedConfig",
    "TokenProvider",
]
