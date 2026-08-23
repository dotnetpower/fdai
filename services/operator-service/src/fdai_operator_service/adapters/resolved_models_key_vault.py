"""Load one bounded resolved-model artifact from Azure Key Vault."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import quote, urlsplit

import httpx

KEY_VAULT_AUDIENCE = "https://vault.azure.net/.default"
_API_VERSION = "7.4"
_MAX_ARTIFACT_BYTES = 1_048_576
_SECRET_NAME = re.compile(r"^[A-Za-z0-9-]{1,127}$")
_SECRET_VERSION = re.compile(r"^[A-Za-z0-9]{1,64}$")
_VAULT_AUDIENCES = {
    ".vault.azure.net": KEY_VAULT_AUDIENCE,
    ".vault.azure.cn": "https://vault.azure.cn/.default",
    ".vault.usgovcloudapi.net": "https://vault.usgovcloudapi.net/.default",
}

TokenProvider = Callable[[str], Awaitable[str]]
Clock = Callable[[], datetime]


class AsyncHttpClient(Protocol):
    """Perform one bounded Key Vault GET request."""

    async def get(self, url: str, **kwargs: Any) -> httpx.Response: ...


@dataclass(frozen=True, slots=True)
class KeyVaultResolvedModelsConfig:
    """Identify one Key Vault secret without carrying credentials or values."""

    vault_url: str
    secret_name: str
    secret_version: str | None = None
    timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        parsed = urlsplit(self.vault_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
            or parsed.port not in {None, 443}
        ):
            raise ValueError("Key Vault resolved-model URL MUST be an HTTPS origin")
        if not any(parsed.hostname.endswith(suffix) for suffix in _VAULT_AUDIENCES):
            raise ValueError("Key Vault resolved-model URL MUST use an Azure vault DNS suffix")
        if _SECRET_NAME.fullmatch(self.secret_name) is None:
            raise ValueError("Key Vault resolved-model secret name is invalid")
        if (
            self.secret_version is not None
            and _SECRET_VERSION.fullmatch(self.secret_version) is None
        ):
            raise ValueError("Key Vault resolved-model secret version is invalid")
        if self.timeout_seconds <= 0 or self.timeout_seconds > 60:
            raise ValueError("Key Vault resolved-model timeout MUST be in (0, 60]")


@dataclass(frozen=True, slots=True)
class ResolvedModelsArtifact:
    """Carry validated JSON content and its exact source digest."""

    content: str = field(repr=False)
    digest: str
    secret_version: str | None


class KeyVaultResolvedModelsSource:
    """Read and validate one secret without logging its value or provider body."""

    def __init__(
        self,
        *,
        config: KeyVaultResolvedModelsConfig,
        token_provider: TokenProvider,
        http_client: AsyncHttpClient,
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        self._config = config
        self._token_provider = token_provider
        self._http_client = http_client
        self._clock = clock

    async def load(self) -> ResolvedModelsArtifact:
        """Return a current bounded JSON artifact or fail closed."""

        try:
            async with asyncio.timeout(self._config.timeout_seconds):
                return await self._load_within_deadline()
        except TimeoutError as exc:
            raise ValueError("Key Vault resolved-model load timed out") from exc

    async def _load_within_deadline(self) -> ResolvedModelsArtifact:
        token = await self._token_provider(self._audience())
        if not token:
            raise ValueError("Key Vault resolved-model token is unavailable")
        response = await self._http_client.get(
            self._secret_url(),
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=self._config.timeout_seconds,
            follow_redirects=False,
        )
        if response.status_code < 200 or response.status_code >= 300:
            raise ValueError(
                f"Key Vault resolved-model read failed with status {response.status_code}"
            )
        if len(response.content) > _MAX_ARTIFACT_BYTES * 2:
            raise ValueError("Key Vault resolved-model response exceeds the size limit")
        try:
            envelope = response.json()
        except (json.JSONDecodeError, RecursionError) as exc:
            raise ValueError("Key Vault resolved-model response is invalid") from exc
        if not isinstance(envelope, Mapping):
            raise ValueError("Key Vault resolved-model response is invalid")
        self._validate_attributes(envelope.get("attributes"))
        value = envelope.get("value")
        if not isinstance(value, str):
            raise ValueError("Key Vault resolved-model secret value is unavailable")
        encoded = value.encode("utf-8")
        if len(encoded) > _MAX_ARTIFACT_BYTES:
            raise ValueError("Key Vault resolved-model artifact exceeds the size limit")
        try:
            payload = json.loads(value)
        except (json.JSONDecodeError, RecursionError) as exc:
            raise ValueError("Key Vault resolved-model artifact is invalid") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("capabilities"), list):
            raise ValueError("Key Vault resolved-model artifact is invalid")
        secret_version = self._response_version(envelope.get("id"))
        return ResolvedModelsArtifact(
            content=value,
            digest=hashlib.sha256(encoded).hexdigest(),
            secret_version=secret_version,
        )

    def _secret_url(self) -> str:
        version = quote(self._config.secret_version or "", safe="")
        return (
            f"{self._config.vault_url.rstrip('/')}/secrets/"
            f"{quote(self._config.secret_name, safe='')}/{version}?api-version={_API_VERSION}"
        )

    def _audience(self) -> str:
        hostname = urlsplit(self._config.vault_url).hostname
        for suffix, audience in _VAULT_AUDIENCES.items():
            if hostname is not None and hostname.endswith(suffix):
                return audience
        raise AssertionError("validated Key Vault URL has one supported DNS suffix")

    def _validate_attributes(self, raw: object) -> None:
        if raw is None:
            return
        if not isinstance(raw, Mapping):
            raise ValueError("Key Vault resolved-model attributes are invalid")
        enabled = raw.get("enabled")
        if enabled is not None:
            if type(enabled) is not bool:
                raise ValueError("Key Vault resolved-model enabled state is invalid")
            if not enabled:
                raise ValueError("Key Vault resolved-model secret is disabled")
        expires = raw.get("exp")
        if expires is None:
            return
        if isinstance(expires, bool) or not isinstance(expires, int):
            raise ValueError("Key Vault resolved-model expiration is invalid")
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Key Vault resolved-model clock MUST be timezone-aware")
        if expires <= int(now.timestamp()):
            raise ValueError("Key Vault resolved-model secret is expired")

    def _response_version(self, raw: object) -> str | None:
        if raw is None:
            return None
        if not isinstance(raw, str):
            raise ValueError("Key Vault resolved-model secret id is invalid")
        parsed = urlsplit(raw)
        expected = urlsplit(self._config.vault_url)
        path = parsed.path.rstrip("/").split("/")
        if (
            parsed.scheme != "https"
            or parsed.hostname != expected.hostname
            or parsed.port not in {None, 443}
            or parsed.query
            or parsed.fragment
            or len(path) != 4
            or path[1] != "secrets"
            or path[2] != self._config.secret_name
            or _SECRET_VERSION.fullmatch(path[3]) is None
        ):
            raise ValueError("Key Vault resolved-model secret id is invalid")
        version = path[3]
        if self._config.secret_version is not None and version != self._config.secret_version:
            raise ValueError("Key Vault resolved-model secret version does not match request")
        return version


__all__ = [
    "KEY_VAULT_AUDIENCE",
    "KeyVaultResolvedModelsConfig",
    "KeyVaultResolvedModelsSource",
    "ResolvedModelsArtifact",
]
