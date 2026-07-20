"""Bounded GitHub repository adapter for approved runtime skill sources."""

from __future__ import annotations

import base64
import binascii
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from urllib.parse import quote

import httpx

from fdai.shared.providers.skill_source import (
    SkillSourceFile,
    SkillSourceRateLimitError,
    SkillSourceRevision,
)

_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
_COMMIT = re.compile(r"^[a-f0-9]{40}$")
_MAX_FILES = 64
_MAX_FILE_BYTES = 256 * 1024
_MAX_TOTAL_BYTES = 1024 * 1024

GitHubTokenProvider = Callable[[], Awaitable[str]]


class GitHubSkillSourceError(RuntimeError):
    """An approved source could not be fetched completely and safely."""


@dataclass(frozen=True, slots=True)
class GitHubSkillSourceConfig:
    api_base: str = "https://api.github.com"
    timeout_seconds: float = 20.0

    def __post_init__(self) -> None:
        parsed = httpx.URL(self.api_base)
        if parsed.scheme != "https" or not parsed.host:
            raise ValueError("GitHub skill source API base MUST be HTTPS")
        if self.timeout_seconds <= 0:
            raise ValueError("GitHub skill source timeout MUST be positive")


class GitHubSkillSourceAdapter:
    """Resolve one immutable commit and fetch only explicitly requested files."""

    def __init__(
        self,
        *,
        config: GitHubSkillSourceConfig,
        http_client: httpx.AsyncClient,
        token_provider: GitHubTokenProvider,
    ) -> None:
        self._config: Final = config
        self._http: Final = http_client
        self._token_provider: Final = token_provider

    async def resolve_revision(
        self,
        *,
        repository: str,
        prior_etag: str | None = None,
    ) -> SkillSourceRevision:
        _repository(repository)
        headers = await self._headers()
        if prior_etag is not None:
            headers["If-None-Match"] = prior_etag
        response = await self._get(
            f"/repos/{repository}/commits/HEAD",
            headers=headers,
        )
        if response.status_code == 304:
            return SkillSourceRevision(revision=None, etag=prior_etag, not_modified=True)
        payload = _json_object(response, "commit")
        revision = payload.get("sha")
        if not isinstance(revision, str) or _COMMIT.fullmatch(revision) is None:
            raise GitHubSkillSourceError("GitHub skill source commit SHA is invalid")
        return SkillSourceRevision(
            revision=revision,
            etag=response.headers.get("etag"),
        )

    async def fetch_files(
        self,
        *,
        repository: str,
        revision: str,
        paths: tuple[str, ...],
    ) -> tuple[SkillSourceFile, ...]:
        _repository(repository)
        if _COMMIT.fullmatch(revision) is None:
            raise ValueError("GitHub skill source revision MUST be a full commit SHA")
        if not paths or len(paths) > _MAX_FILES or len(set(paths)) != len(paths):
            raise ValueError("GitHub skill source paths MUST contain 1..64 unique files")
        for path in paths:
            _safe_path(path)
        headers = await self._headers()
        fetched: list[SkillSourceFile] = []
        total_bytes = 0
        for path in paths:
            encoded_path = quote(path, safe="/")
            response = await self._get(
                f"/repos/{repository}/contents/{encoded_path}",
                headers=headers,
                params={"ref": revision},
            )
            payload = _json_object(response, "content")
            if payload.get("type") != "file" or payload.get("path") != path:
                raise GitHubSkillSourceError(
                    "GitHub skill source returned a non-file or path mismatch"
                )
            if payload.get("encoding") != "base64" or not isinstance(payload.get("content"), str):
                raise GitHubSkillSourceError("GitHub skill source content encoding is invalid")
            try:
                content = base64.b64decode(payload["content"], validate=True)
            except (ValueError, binascii.Error) as exc:
                raise GitHubSkillSourceError(
                    "GitHub skill source base64 content is invalid"
                ) from exc
            if not content or len(content) > _MAX_FILE_BYTES:
                raise GitHubSkillSourceError("GitHub skill source file exceeds byte budget")
            total_bytes += len(content)
            if total_bytes > _MAX_TOTAL_BYTES:
                raise GitHubSkillSourceError("GitHub skill source artifact exceeds byte budget")
            fetched.append(
                SkillSourceFile(
                    path=path,
                    content=content,
                    media_type="application/octet-stream",
                )
            )
        return tuple(fetched)

    async def _headers(self) -> dict[str, str]:
        token = await self._token_provider()
        if not token:
            raise GitHubSkillSourceError("GitHub skill source authentication is unavailable")
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def _get(
        self,
        path: str,
        *,
        headers: Mapping[str, str],
        params: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        url = f"{self._config.api_base.rstrip('/')}{path}"
        try:
            response = await self._http.get(
                url,
                headers=headers,
                params=params,
                timeout=self._config.timeout_seconds,
                follow_redirects=False,
            )
        except httpx.HTTPError as exc:
            raise GitHubSkillSourceError("GitHub skill source request failed") from exc
        if 300 <= response.status_code < 400 and response.status_code != 304:
            raise GitHubSkillSourceError("GitHub skill source redirects are not accepted")
        if response.status_code == 429 or (
            response.status_code == 403 and response.headers.get("x-ratelimit-remaining") == "0"
        ):
            raise SkillSourceRateLimitError(retry_at=_retry_at(response))
        if response.status_code == 403:
            raise GitHubSkillSourceError("GitHub skill source authorization failed")
        if response.status_code >= 400:
            raise GitHubSkillSourceError(
                f"GitHub skill source returned HTTP {response.status_code}"
            )
        return response


def _json_object(response: httpx.Response, label: str) -> Mapping[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise GitHubSkillSourceError(f"GitHub skill source {label} response is not JSON") from exc
    if not isinstance(payload, Mapping):
        raise GitHubSkillSourceError(f"GitHub skill source {label} response is not an object")
    return payload


def _retry_at(response: httpx.Response) -> datetime | None:
    reset = response.headers.get("x-ratelimit-reset")
    if reset is not None:
        try:
            return datetime.fromtimestamp(int(reset), tz=UTC)
        except (OverflowError, ValueError):
            return None
    retry_after = response.headers.get("retry-after")
    if retry_after is not None:
        try:
            return datetime.now(tz=UTC) + timedelta(seconds=max(0, int(retry_after)))
        except ValueError:
            return None
    return None


def _repository(value: str) -> None:
    if _REPOSITORY.fullmatch(value) is None:
        raise ValueError("GitHub skill source repository MUST be owner/repository")


def _safe_path(value: str) -> None:
    if (
        not value
        or len(value) > 512
        or value.startswith(("/", "\\"))
        or "\\" in value
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise ValueError("GitHub skill source path MUST be a safe relative path")


__all__ = [
    "GitHubSkillSourceAdapter",
    "GitHubSkillSourceConfig",
    "GitHubSkillSourceError",
    "GitHubTokenProvider",
]
