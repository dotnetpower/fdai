"""Bounded GitHub REST source for immutable pull-request snapshots."""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Final

import httpx

from .models import PullRequestFile, PullRequestSnapshot

_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
_SHA = re.compile(r"^[a-f0-9]{40}$")

TokenProvider = Callable[[], Awaitable[str | None]]


class GitHubReviewSourceError(RuntimeError):
    """GitHub review evidence could not be fetched completely and safely."""


class GitHubReviewLimitError(GitHubReviewSourceError):
    """The pull request exceeded a configured review evidence budget."""


class GitHubReviewSnapshotChangedError(GitHubReviewSourceError):
    """The pull request changed while its evidence was being collected."""


@dataclass(frozen=True, slots=True)
class GitHubReviewSourceConfig:
    api_base: str = "https://api.github.com"
    timeout_seconds: float = 20.0
    max_files: int = 200
    max_response_bytes: int = 2 * 1024 * 1024
    max_total_patch_chars: int = 1 * 1024 * 1024

    def __post_init__(self) -> None:
        parsed = httpx.URL(self.api_base)
        if (
            parsed.scheme != "https"
            or not parsed.host
            or bool(parsed.username)
            or bool(parsed.password)
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("GitHub review API base MUST be a credential-free HTTPS URL")
        if self.timeout_seconds <= 0:
            raise ValueError("GitHub review timeout MUST be positive")
        if not 1 <= self.max_files <= 1000:
            raise ValueError("GitHub review max_files MUST be in [1, 1000]")
        if self.max_response_bytes < 1024 or self.max_total_patch_chars < 1024:
            raise ValueError("GitHub review byte and patch budgets MUST be at least 1024")


class GitHubPullRequestSource:
    """Fetch one PR twice around its bounded file list to prove SHA stability."""

    def __init__(
        self,
        *,
        config: GitHubReviewSourceConfig,
        http_client: httpx.AsyncClient,
        token_provider: TokenProvider,
    ) -> None:
        self._config: Final = config
        self._http: Final = http_client
        self._token_provider: Final = token_provider

    async def fetch(self, *, repository: str, pull_number: int) -> PullRequestSnapshot:
        _validate_request(repository, pull_number)
        metadata_path = f"/repos/{repository}/pulls/{pull_number}"
        initial = await self._get_object(metadata_path)
        base_sha, head_sha, changed_files = _metadata(initial)
        if changed_files > self._config.max_files:
            raise GitHubReviewLimitError(
                f"pull request changed_files exceeds configured cap {self._config.max_files}"
            )

        files = await self._fetch_files(
            repository=repository,
            pull_number=pull_number,
            expected_count=changed_files,
        )
        final = await self._get_object(metadata_path)
        final_base, final_head, final_count = _metadata(final)
        if (final_base, final_head, final_count) != (base_sha, head_sha, changed_files):
            raise GitHubReviewSnapshotChangedError(
                "pull request changed while review evidence was collected"
            )
        return PullRequestSnapshot(
            repository=repository,
            pull_number=pull_number,
            base_sha=base_sha,
            head_sha=head_sha,
            changed_files=changed_files,
            files=files,
        )

    async def _fetch_files(
        self,
        *,
        repository: str,
        pull_number: int,
        expected_count: int,
    ) -> tuple[PullRequestFile, ...]:
        files: list[PullRequestFile] = []
        patch_chars = 0
        page = 1
        while len(files) < expected_count:
            payload = await self._get_json(
                f"/repos/{repository}/pulls/{pull_number}/files",
                params={"per_page": "100", "page": str(page)},
            )
            if not isinstance(payload, list):
                raise GitHubReviewSourceError("GitHub pull request files response MUST be an array")
            if not payload:
                break
            for raw_file in payload:
                file = _file(raw_file)
                patch_chars += len(file.patch or "")
                if patch_chars > self._config.max_total_patch_chars:
                    raise GitHubReviewLimitError(
                        "pull request patches exceed configured character cap"
                    )
                files.append(file)
                if len(files) > self._config.max_files:
                    raise GitHubReviewLimitError("pull request files exceed configured file cap")
            page += 1
        if len(files) != expected_count:
            raise GitHubReviewSourceError(
                "GitHub pull request file count does not match immutable metadata"
            )
        return tuple(files)

    async def _get_object(self, path: str) -> Mapping[str, Any]:
        payload = await self._get_json(path)
        if not isinstance(payload, Mapping):
            raise GitHubReviewSourceError("GitHub pull request response MUST be an object")
        return payload

    async def _get_json(
        self,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
    ) -> Any:
        try:
            token = await self._token_provider()
        except Exception as exc:  # noqa: BLE001 - credential provider boundary
            raise GitHubReviewSourceError("GitHub review authentication is unavailable") from exc
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            async with self._http.stream(
                "GET",
                f"{self._config.api_base.rstrip('/')}{path}",
                headers=headers,
                params=params,
                timeout=self._config.timeout_seconds,
                follow_redirects=False,
            ) as response:
                if 300 <= response.status_code < 400:
                    raise GitHubReviewSourceError("GitHub review redirects are not accepted")
                if response.status_code >= 400:
                    raise GitHubReviewSourceError(
                        f"GitHub review request returned HTTP {response.status_code}"
                    )
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > self._config.max_response_bytes:
                        raise GitHubReviewLimitError(
                            "GitHub review response exceeds configured byte cap"
                        )
                    body.extend(chunk)
        except GitHubReviewSourceError:
            raise
        except httpx.HTTPError as exc:
            raise GitHubReviewSourceError("GitHub review request failed") from exc
        try:
            return json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GitHubReviewSourceError("GitHub review response is not JSON") from exc


def _validate_request(repository: str, pull_number: int) -> None:
    if _REPOSITORY.fullmatch(repository) is None:
        raise ValueError("repository MUST use owner/name syntax")
    if pull_number < 1:
        raise ValueError("pull_number MUST be positive")


def _metadata(payload: Mapping[str, Any]) -> tuple[str, str, int]:
    base = payload.get("base")
    head = payload.get("head")
    base_sha = base.get("sha") if isinstance(base, Mapping) else None
    head_sha = head.get("sha") if isinstance(head, Mapping) else None
    changed_files = payload.get("changed_files")
    if (
        not isinstance(base_sha, str)
        or _SHA.fullmatch(base_sha) is None
        or not isinstance(head_sha, str)
        or _SHA.fullmatch(head_sha) is None
        or not isinstance(changed_files, int)
        or isinstance(changed_files, bool)
        or changed_files < 0
    ):
        raise GitHubReviewSourceError("GitHub pull request metadata is invalid")
    return base_sha, head_sha, changed_files


def _file(value: Any) -> PullRequestFile:
    if not isinstance(value, Mapping):
        raise GitHubReviewSourceError("GitHub pull request file entry MUST be an object")
    path = value.get("filename")
    status = value.get("status")
    additions = _change_count(value.get("additions"), "additions")
    deletions = _change_count(value.get("deletions"), "deletions")
    patch = value.get("patch")
    if not isinstance(path, str) or not _safe_path(path):
        raise GitHubReviewSourceError("GitHub pull request filename is invalid")
    if not isinstance(status, str) or not status:
        raise GitHubReviewSourceError("GitHub pull request file status is invalid")
    if patch is not None and not isinstance(patch, str):
        raise GitHubReviewSourceError("GitHub pull request patch is invalid")
    return PullRequestFile(
        path=path,
        status=status,
        additions=additions,
        deletions=deletions,
        patch=patch,
    )


def _change_count(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise GitHubReviewSourceError(f"GitHub pull request {label} count is invalid")
    return value


def _safe_path(value: str) -> bool:
    raw_parts = value.split("/")
    path = PurePosixPath(value)
    return (
        bool(value)
        and len(value) <= 512
        and not path.is_absolute()
        and "\\" not in value
        and all(part not in {"", ".", ".."} for part in raw_parts)
    )


__all__ = [
    "GitHubPullRequestSource",
    "GitHubReviewLimitError",
    "GitHubReviewSnapshotChangedError",
    "GitHubReviewSourceConfig",
    "GitHubReviewSourceError",
    "TokenProvider",
]
