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
- Fail-closed: a non-2xx response or malformed payload envelope raises
    :class:`ChangeFeedError`; malformed deployment records are skipped with a
    redacted structured warning. RCA then correlates over whatever it already
    has rather than blocking on the feed.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

import httpx

from fdai.shared.providers.change_feed import ChangeFeedError, ChangeRecord

_DEFAULT_API: Final[str] = "https://api.github.com"
_DEFAULT_TIMEOUT_SECONDS: Final[float] = 20.0
_DEFAULT_MAX_RECORDS: Final[int] = 200
_LOGGER = logging.getLogger(__name__)

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
        parts = self.repository.strip().split("/") if isinstance(self.repository, str) else []
        if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
            raise ValueError("GitHubChangeFeedConfig.repository MUST be 'owner/name'")
        if self.environment is not None and not self.environment.strip():
            raise ValueError("GitHubChangeFeedConfig.environment MUST be non-empty when set")
        if not isinstance(self.api_base, str) or not self.api_base.lower().startswith("https://"):
            raise ValueError(
                f"GitHubChangeFeedConfig.api_base MUST use https:// (got {self.api_base!r})"
            )
        if (
            isinstance(self.timeout_seconds, bool)
            or not math.isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
        ):
            raise ValueError("GitHubChangeFeedConfig.timeout_seconds MUST be positive")
        if isinstance(self.max_records, bool) or self.max_records <= 0:
            raise ValueError("GitHubChangeFeedConfig.max_records MUST be positive")


def _parse_ts(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    trimmed = raw.strip()
    text = trimmed[:-1] + "+00:00" if trimmed.endswith(("Z", "z")) else trimmed
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt.astimezone(UTC) if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _as_utc(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)


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
        since = _as_utc(since)
        until = _as_utc(until)
        if since > until:
            raise ChangeFeedError("GitHub change feed since MUST NOT exceed until")
        try:
            token = await self._token_provider()
        except Exception as exc:  # noqa: BLE001 - normalize token failures at provider boundary
            raise ChangeFeedError(
                f"GitHub token acquisition failed for {self._config.repository!r}"
            ) from exc
        if not isinstance(token, str) or not token.strip():
            raise ChangeFeedError(
                f"GitHub token provider returned an empty token for {self._config.repository!r}"
            )
        repo_slug = self._config.repository.strip()
        url = f"{self._config.api_base.rstrip('/')}/repos/{repo_slug}/deployments"
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
            _LOGGER.warning(
                "github_change_feed_record_skipped",
                extra={
                    "provider": "github",
                    "record_type": "deployment",
                    "reason": "invalid_created_at",
                },
            )
            return None
        sha = str(row.get("sha") or "").strip()[:12]
        env = str(row.get("environment") or "").strip()
        creator = row.get("creator")
        author = str(creator.get("login") or "").strip() if isinstance(creator, Mapping) else ""
        cleaned_hint = resource_hint.strip() if isinstance(resource_hint, str) else ""
        hints = (cleaned_hint,) if cleaned_hint else ()
        raw_id = row.get("id")
        deploy_key = str(raw_id).strip() if raw_id is not None else ""
        if not deploy_key:
            deploy_key = sha
        if not deploy_key:
            return None
        desc = row.get("description") or sha or deploy_key
        return ChangeRecord(
            change_id=f"gh-deploy-{deploy_key}",
            at=at,
            source="github",
            ref=sha or deploy_key,
            summary=f"deployment to {env or 'unknown'}: {desc}",
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
