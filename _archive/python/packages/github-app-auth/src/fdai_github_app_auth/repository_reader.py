"""Bounded read-only GitHub knowledge validation over the existing token provider."""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import quote, urlparse

import httpx

from fdai_github_app_auth.environment import build_github_token_provider
from fdai_github_app_auth.provider import GitHubAppTokenError, GitHubAppTokenProvider

MAX_RESPONSE_BYTES = 256 * 1024
MAX_README_BYTES = 128 * 1024


class GitHubRepositoryReadError(ValueError):
    """Sanitized failure that never includes provider payloads or credentials."""


@dataclass(frozen=True)
class GitHubRepositoryObservation:
    repository_id: int
    private: bool
    default_branch: str
    commit: str
    readme_digest: str


class GitHubRepositoryReader(Protocol):
    async def verify(self, location: str, credential_reference: str) -> GitHubRepositoryObservation:
        """Observe repository identity, exact default-branch commit, and README bytes."""
        ...


class GitHubApiRepositoryReader:
    def __init__(self, environment: Mapping[str, str], http_client: httpx.AsyncClient):
        self._environment = environment
        self._http = http_client

    async def verify(self, location: str, credential_reference: str) -> GitHubRepositoryObservation:
        try:
            async with asyncio.timeout(30):
                return await self._verify(location, credential_reference)
        except (
            httpx.HTTPError,
            TimeoutError,
            GitHubAppTokenError,
            ValueError,
            RecursionError,
        ) as exc:
            raise GitHubRepositoryReadError("GitHub source validation unavailable") from exc

    async def _verify(
        self, location: str, credential_reference: str
    ) -> GitHubRepositoryObservation:
        if re.fullmatch(
            r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}", location
        ) is None or location.split("/")[1] in {".", ".."}:
            raise GitHubRepositoryReadError("GitHub repository location invalid")
        base = self._environment.get("FDAI_GITOPS_API_BASE", "https://api.github.com").rstrip("/")
        origin = urlparse(base)
        if (
            origin.scheme != "https"
            or not origin.hostname
            or origin.username
            or origin.password
            or origin.query
            or origin.fragment
        ):
            raise GitHubRepositoryReadError("GitHub API origin invalid")
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if credential_reference == "deployment-github-app":
            if self._environment.get("FDAI_GITOPS_TOKEN", "").strip():
                raise GitHubRepositoryReadError("GitHub knowledge requires read-only App access")
            provider = build_github_token_provider(
                self._environment,
                http_client=self._http,
                repository=location.split("/")[1],
                permissions=(("contents", "read"), ("metadata", "read")),
            )
            if not isinstance(provider, GitHubAppTokenProvider):
                raise GitHubRepositoryReadError("GitHub App credentials unavailable")
            headers["Authorization"] = f"Bearer {await provider()}"
        elif credential_reference != "public":
            raise GitHubRepositoryReadError("GitHub credential reference invalid")
        repository_url = f"{base}/repos/{location}"
        metadata = await self._json(repository_url, headers)
        repository_id, private, branch = (
            metadata.get("id"),
            metadata.get("private"),
            metadata.get("default_branch"),
        )
        name = metadata.get("full_name")
        if (
            not isinstance(name, str)
            or name.lower() != location.lower()
            or type(repository_id) is not int
            or repository_id <= 0
            or type(private) is not bool
            or not isinstance(branch, str)
            or not 1 <= len(branch) <= 200
            or (credential_reference == "public" and private)
        ):
            raise GitHubRepositoryReadError("GitHub repository identity invalid")
        commit = await self._json(f"{repository_url}/commits/{quote(branch, safe='')}", headers)
        sha = commit.get("sha")
        if (
            not isinstance(sha, str)
            or len(sha) != 40
            or any(c not in "0123456789abcdef" for c in sha)
        ):
            raise GitHubRepositoryReadError("GitHub commit identity invalid")
        readme = await self._json(f"{repository_url}/readme?ref={sha}", headers)
        size, content = readme.get("size"), readme.get("content")
        if (
            readme.get("type") != "file"
            or readme.get("encoding") != "base64"
            or type(size) is not int
            or not 1 <= size <= MAX_README_BYTES
            or not isinstance(content, str)
        ):
            raise GitHubRepositoryReadError("GitHub README response invalid")
        try:
            raw = base64.b64decode("".join(content.splitlines()), validate=True)
        except (ValueError, binascii.Error) as exc:
            raise GitHubRepositoryReadError("GitHub README encoding invalid") from exc
        if len(raw) != size:
            raise GitHubRepositoryReadError("GitHub README size invalid")
        return GitHubRepositoryObservation(
            repository_id, private, branch, sha, hashlib.sha256(raw).hexdigest()
        )

    async def _json(self, url: str, headers: dict[str, str]) -> dict[str, object]:
        async with self._http.stream(
            "GET", url, headers=headers, timeout=10, follow_redirects=False
        ) as response:
            if response.status_code != 200:
                raise GitHubRepositoryReadError("GitHub read request unsuccessful")
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise GitHubRepositoryReadError("GitHub response exceeds byte limit")
            try:
                payload = json.loads(body)
            except ValueError as exc:
                raise GitHubRepositoryReadError("GitHub response invalid") from exc
            if not isinstance(payload, dict):
                raise GitHubRepositoryReadError("GitHub response invalid")
            return payload
