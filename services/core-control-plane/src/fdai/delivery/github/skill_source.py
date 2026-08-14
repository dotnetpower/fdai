"""Bounded GitHub REST adapter for approved runtime skill sources."""

from __future__ import annotations

import base64
import binascii
import mimetypes
import re
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any, Final
from urllib.parse import quote

import httpx

from fdai.shared.providers.skill_source import (
    SkillSourceFile,
    SkillSourceRateLimitError,
    SkillSourceRevision,
)

_API_BASE: Final[str] = "https://api.github.com"
_API_VERSION: Final[str] = "2022-11-28"
_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
_ETAG = re.compile(r'^(?:W/)?"[\x21\x23-\x7e]*"$')
_MAX_PATHS = 64
_MAX_PATH_CHARS = 512
_MAX_FILE_BYTES = 256 * 1024
_MAX_TOTAL_BYTES = 1024 * 1024

TokenProvider = Callable[[], Awaitable[str]]
Clock = Callable[[], datetime]


class GitHubSkillSourceError(RuntimeError):
    """A GitHub response cannot satisfy the approved skill-source contract."""


class GitHubSkillSourceAdapter:
    """Resolve one default-branch commit and fetch exact bounded files at that SHA."""

    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient,
        token_provider: TokenProvider,
        timeout_seconds: float = 20.0,
        clock: Clock = lambda: datetime.now(tz=UTC),
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("GitHub skill source timeout MUST be positive")
        self._http = http_client
        self._token_provider = token_provider
        self._timeout_seconds = timeout_seconds
        self._clock = clock

    async def resolve_revision(
        self,
        *,
        repository: str,
        prior_etag: str | None = None,
    ) -> SkillSourceRevision:
        normalized_repository = _repository(repository)
        headers = await self._headers()
        if prior_etag is not None:
            headers["If-None-Match"] = _etag(prior_etag)
        response = await self._get(
            f"{_API_BASE}/repos/{normalized_repository}/commits/HEAD",
            headers=headers,
        )
        if response.status_code == 304:
            return SkillSourceRevision(
                revision=None,
                etag=_response_etag(response.headers.get("etag")) or prior_etag,
                not_modified=True,
            )
        self._require_success(response)
        payload = _object(response)
        revision = payload.get("sha")
        if not isinstance(revision, str) or _FULL_SHA.fullmatch(revision) is None:
            raise GitHubSkillSourceError("GitHub skill source revision is not a full commit SHA")
        return SkillSourceRevision(
            revision=revision,
            etag=_response_etag(response.headers.get("etag")),
        )

    async def fetch_files(
        self,
        *,
        repository: str,
        revision: str,
        paths: tuple[str, ...],
    ) -> tuple[SkillSourceFile, ...]:
        normalized_repository = _repository(repository)
        if _FULL_SHA.fullmatch(revision) is None:
            raise ValueError("GitHub skill source revision MUST be a full lowercase commit SHA")
        normalized_paths = tuple(_path(path) for path in paths)
        if not normalized_paths or len(normalized_paths) > _MAX_PATHS:
            raise ValueError("GitHub skill source paths MUST contain between 1 and 64 entries")
        if len(set(normalized_paths)) != len(normalized_paths):
            raise ValueError("GitHub skill source paths MUST NOT contain duplicates")

        files: list[SkillSourceFile] = []
        total_bytes = 0
        for path in normalized_paths:
            response = await self._get(
                f"{_API_BASE}/repos/{normalized_repository}/contents/{quote(path, safe='/')}",
                headers=await self._headers(),
                params={"ref": revision},
            )
            self._require_success(response)
            file = _decode_file(response, requested_path=path)
            total_bytes += len(file.content)
            if total_bytes > _MAX_TOTAL_BYTES:
                raise GitHubSkillSourceError(
                    "GitHub skill source files exceed the total size limit"
                )
            files.append(file)
        return tuple(files)

    async def _headers(self) -> dict[str, str]:
        try:
            token = await self._token_provider()
        except Exception:
            raise GitHubSkillSourceError(
                "GitHub skill source authentication is unavailable"
            ) from None
        if not token or len(token) > 4096 or any(ord(char) < 32 for char in token):
            raise GitHubSkillSourceError("GitHub skill source authentication is unavailable")
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": _API_VERSION,
        }

    async def _get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        params: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        try:
            response = await self._http.get(
                url,
                headers=headers,
                params=params,
                timeout=self._timeout_seconds,
                follow_redirects=False,
            )
        except httpx.HTTPError as exc:
            raise GitHubSkillSourceError("GitHub skill source request failed") from exc
        if response.history or response.status_code in {300, 301, 302, 303, 307, 308}:
            raise GitHubSkillSourceError("GitHub skill source redirects are not allowed")
        if response.status_code in {403, 429} and (
            response.status_code == 429
            or response.headers.get("x-ratelimit-remaining") == "0"
            or response.headers.get("retry-after") is not None
        ):
            raise SkillSourceRateLimitError(retry_at=_retry_at(response.headers, now=self._clock()))
        return response

    @staticmethod
    def _require_success(response: httpx.Response) -> None:
        if response.status_code in {401, 403}:
            raise GitHubSkillSourceError("GitHub skill source authentication was rejected")
        if response.status_code != 200:
            raise GitHubSkillSourceError(
                f"GitHub skill source request returned HTTP {response.status_code}"
            )


def _decode_file(response: httpx.Response, *, requested_path: str) -> SkillSourceFile:
    payload = _object(response)
    kind = payload.get("type")
    if kind != "file":
        raise GitHubSkillSourceError("GitHub skill source content is not a regular file")
    if payload.get("path") != requested_path:
        raise GitHubSkillSourceError("GitHub skill source response path does not match the request")
    size = payload.get("size")
    if isinstance(size, bool) or not isinstance(size, int) or not 0 < size <= _MAX_FILE_BYTES:
        raise GitHubSkillSourceError("GitHub skill source file size is outside the allowed bound")
    if payload.get("encoding") != "base64" or not isinstance(payload.get("content"), str):
        raise GitHubSkillSourceError("GitHub skill source content encoding is unsupported")
    try:
        content = base64.b64decode(payload["content"], validate=True)
    except (binascii.Error, ValueError) as exc:
        raise GitHubSkillSourceError("GitHub skill source content is not valid base64") from exc
    if len(content) != size:
        raise GitHubSkillSourceError("GitHub skill source decoded size does not match metadata")
    if requested_path.endswith("/SKILL.md.sig"):
        if len(content) != 64:
            raise GitHubSkillSourceError("GitHub skill source signature MUST contain 64 bytes")
    else:
        try:
            content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise GitHubSkillSourceError("GitHub skill source files MUST be UTF-8") from exc
    media_type = mimetypes.guess_type(requested_path)[0] or "application/octet-stream"
    return SkillSourceFile(path=requested_path, content=content, media_type=media_type)


def _object(response: httpx.Response) -> Mapping[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise GitHubSkillSourceError("GitHub skill source response is not JSON") from exc
    if not isinstance(payload, Mapping):
        raise GitHubSkillSourceError("GitHub skill source response is not an object")
    return payload


def _repository(value: str) -> str:
    if _REPOSITORY.fullmatch(value) is None:
        raise ValueError("GitHub skill source repository MUST be an owner/name identifier")
    return value


def _path(value: str) -> str:
    if (
        not value
        or len(value) > _MAX_PATH_CHARS
        or value.startswith(("/", "\\"))
        or "\\" in value
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or any(ord(char) < 32 for char in value)
    ):
        raise ValueError("GitHub skill source path MUST be a safe relative path")
    return value


def _etag(value: str) -> str:
    if len(value) > 512 or _ETAG.fullmatch(value) is None:
        raise ValueError("GitHub skill source ETag MUST be a bounded quoted entity tag")
    return value


def _response_etag(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return _etag(value)
    except ValueError:
        raise GitHubSkillSourceError("GitHub skill source returned an invalid ETag") from None


def _retry_at(headers: Mapping[str, str], *, now: datetime) -> datetime | None:
    if now.tzinfo is None:
        raise ValueError("GitHub skill source clock MUST include timezone")
    reset = headers.get("x-ratelimit-reset")
    if reset is not None:
        try:
            candidate = datetime.fromtimestamp(int(reset), tz=UTC)
        except (ValueError, OSError, OverflowError):
            candidate = None
        if candidate is not None and candidate > now:
            return candidate
    retry_after = headers.get("retry-after")
    if retry_after is None:
        return None
    try:
        seconds = int(retry_after)
    except ValueError:
        try:
            candidate = parsedate_to_datetime(retry_after)
        except (TypeError, ValueError, OverflowError):
            return None
        return candidate.astimezone(UTC) if candidate > now else None
    return now + timedelta(seconds=seconds) if seconds >= 0 else None


__all__ = [
    "GitHubSkillSourceAdapter",
    "GitHubSkillSourceError",
    "TokenProvider",
]
