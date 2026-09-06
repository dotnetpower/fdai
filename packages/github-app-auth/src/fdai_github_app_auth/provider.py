"""Mint and refresh repository-scoped GitHub App installation tokens."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Final, TypeAlias
from urllib.parse import urlparse

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key

TokenProvider: TypeAlias = Callable[[], Awaitable[str]]
Clock: TypeAlias = Callable[[], datetime]

_DEFAULT_API_BASE: Final[str] = "https://api.github.com"
_DEFAULT_API_VERSION: Final[str] = "2022-11-28"
_DEFAULT_PERMISSIONS: Final[tuple[tuple[str, str], ...]] = (
    ("contents", "write"),
    ("issues", "write"),
    ("metadata", "read"),
    ("pull_requests", "write"),
)


class GitHubAppTokenError(RuntimeError):
    """Raised when an installation token cannot be minted or safely reused."""


@dataclass(frozen=True, slots=True)
class GitHubAppTokenConfig:
    """Validated GitHub App installation and token-scope configuration."""

    client_id: str
    installation_id: int
    private_key_pem: str = field(repr=False)
    repository: str
    permissions: tuple[tuple[str, str], ...] = _DEFAULT_PERMISSIONS
    api_base: str = _DEFAULT_API_BASE
    api_version: str = _DEFAULT_API_VERSION
    timeout_seconds: float = 15.0
    refresh_skew_seconds: int = 300

    def __post_init__(self) -> None:
        parsed = urlparse(self.api_base)
        if not self.client_id.strip():
            raise ValueError("GitHub App client_id MUST NOT be empty")
        if self.installation_id < 1:
            raise ValueError("GitHub App installation_id MUST be positive")
        if not self.private_key_pem.strip():
            raise ValueError("GitHub App private_key_pem MUST NOT be empty")
        if (
            not self.repository
            or "/" in self.repository
            or self.repository.strip() != self.repository
        ):
            raise ValueError("GitHub App repository MUST be one repository name")
        if parsed.scheme != "https" or not parsed.hostname or parsed.query or parsed.fragment:
            raise ValueError("GitHub App api_base MUST be an HTTPS origin")
        if self.timeout_seconds <= 0:
            raise ValueError("GitHub App timeout_seconds MUST be positive")
        if not 60 <= self.refresh_skew_seconds <= 900:
            raise ValueError("GitHub App refresh_skew_seconds MUST be in [60, 900]")
        permission_names = tuple(name for name, _ in self.permissions)
        if (
            not self.permissions
            or permission_names != tuple(sorted(permission_names))
            or len(permission_names) != len(set(permission_names))
            or any(level not in {"read", "write"} for _, level in self.permissions)
        ):
            raise ValueError("GitHub App permissions MUST be unique, ordered read/write entries")


def static_token_provider(token: str) -> TokenProvider:
    """Return an async compatibility provider for one externally rotated token."""

    normalized = token.strip()
    if not normalized:
        raise ValueError("GitHub token MUST NOT be empty")

    async def provide() -> str:
        return normalized

    return provide


class GitHubAppTokenProvider:
    """Cache one installation token and serialize refresh before expiry."""

    def __init__(
        self,
        *,
        config: GitHubAppTokenConfig,
        http_client: httpx.AsyncClient,
        clock: Clock | None = None,
    ) -> None:
        private_key = load_pem_private_key(config.private_key_pem.encode(), password=None)
        if not isinstance(private_key, RSAPrivateKey):
            raise ValueError("GitHub App private key MUST be RSA")
        self._config = config
        self._http = http_client
        self._clock = clock or (lambda: datetime.now(UTC))
        self._private_key = private_key
        self._lock = asyncio.Lock()
        self._token: str | None = None
        self._expires_at: datetime | None = None

    async def __call__(self) -> str:
        now = self._now()
        if self._is_reusable(now):
            assert self._token is not None
            return self._token
        async with self._lock:
            now = self._now()
            if self._is_reusable(now):
                assert self._token is not None
                return self._token
            token, expires_at = await self._mint(now)
            self._token = token
            self._expires_at = expires_at
            return token

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            raise GitHubAppTokenError("GitHub App token clock MUST be timezone-aware")
        return value.astimezone(UTC)

    def _is_reusable(self, now: datetime) -> bool:
        return (
            self._token is not None
            and self._expires_at is not None
            and self._expires_at - now > timedelta(seconds=self._config.refresh_skew_seconds)
        )

    async def _mint(self, now: datetime) -> tuple[str, datetime]:
        app_jwt = jwt.encode(
            {
                "iat": int((now - timedelta(seconds=60)).timestamp()),
                "exp": int((now + timedelta(minutes=9)).timestamp()),
                "iss": self._config.client_id,
            },
            self._private_key,
            algorithm="RS256",
        )
        url = (
            f"{self._config.api_base.rstrip('/')}/app/installations/"
            f"{self._config.installation_id}/access_tokens"
        )
        try:
            response = await self._http.post(
                url,
                headers={
                    "Authorization": f"Bearer {app_jwt}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": self._config.api_version,
                },
                json={
                    "repositories": [self._config.repository],
                    "permissions": dict(self._config.permissions),
                },
                timeout=self._config.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise GitHubAppTokenError("GitHub App installation-token request failed") from exc
        if response.status_code >= 400:
            raise GitHubAppTokenError(
                f"GitHub App installation-token request returned HTTP {response.status_code}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise GitHubAppTokenError(
                "GitHub App installation-token response was not JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise GitHubAppTokenError("GitHub App installation-token response was not an object")
        token = payload.get("token")
        expires_at = _parse_expiry(payload.get("expires_at"))
        if not isinstance(token, str) or not token.strip():
            raise GitHubAppTokenError("GitHub App installation-token response omitted the token")
        if expires_at - now <= timedelta(seconds=self._config.refresh_skew_seconds):
            raise GitHubAppTokenError("GitHub App installation token expires inside refresh skew")
        return token.strip(), expires_at


def _parse_expiry(raw: object) -> datetime:
    if not isinstance(raw, str) or not raw:
        raise GitHubAppTokenError("GitHub App installation-token response omitted expiry")
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GitHubAppTokenError("GitHub App installation-token expiry was invalid") from exc
    if value.tzinfo is None:
        raise GitHubAppTokenError("GitHub App installation-token expiry lacked timezone")
    return value.astimezone(UTC)
