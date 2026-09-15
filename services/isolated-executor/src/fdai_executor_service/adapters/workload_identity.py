"""Azure Managed Identity adapter owned by the isolated Executor service."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final
from uuid import UUID

import httpx
from azure.core.exceptions import AzureError
from azure.identity.aio import WorkloadIdentityCredential
from fdai_service_contracts.executor import IdentityToken

_API_VERSION: Final[str] = "2019-08-01"
_MIN_TTL_SECONDS: Final[int] = 60


class ManagedIdentityConfigurationError(RuntimeError):
    """Raised when the managed identity endpoint configuration is invalid."""


@dataclass(frozen=True, slots=True)
class ManagedIdentityWorkloadIdentityConfig:
    """Bounded configuration for one Azure Managed Identity endpoint."""

    endpoint: str
    header: str
    client_id: str | None = None
    timeout_seconds: float = 10.0
    federated_tenant_id: str | None = None
    federated_token_file: str | None = None


class ManagedIdentityWorkloadIdentity:
    """Issue short-lived audience-scoped tokens without persisting secrets."""

    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient,
        config: ManagedIdentityWorkloadIdentityConfig | None = None,
    ) -> None:
        resolved = config or _config_from_env()
        if resolved.federated_token_file is not None:
            _validate_federation(resolved)
        elif not resolved.endpoint.startswith(("https://", "http://")):
            raise ManagedIdentityConfigurationError("IDENTITY_ENDPOINT MUST be an absolute URL")
        if resolved.federated_token_file is None and not resolved.header:
            raise ManagedIdentityConfigurationError("IDENTITY_HEADER MUST NOT be empty")
        if resolved.timeout_seconds <= 0:
            raise ManagedIdentityConfigurationError("timeout_seconds MUST be > 0")
        self._config = resolved
        self._http = http_client
        self._cache: dict[str, IdentityToken] = {}
        self._audience_locks: dict[str, asyncio.Lock] = {}
        self._registry_lock = asyncio.Lock()

    @classmethod
    def from_env(
        cls,
        *,
        http_client: httpx.AsyncClient,
        env: Mapping[str, str] | None = None,
        client_id_env: str = "FDAI_MI_CLIENT_ID",
    ) -> ManagedIdentityWorkloadIdentity:
        """Build an adapter selecting one attached identity by environment key."""

        return cls(
            http_client=http_client,
            config=_config_from_env(env=env, client_id_env=client_id_env),
        )

    async def get_token(self, audience: str) -> IdentityToken:
        """Return a cached or freshly issued token for exactly one audience."""

        cached = self._cache.get(audience)
        now = datetime.now(tz=UTC)
        if cached is not None and cached.expires_at > now + timedelta(seconds=_MIN_TTL_SECONDS):
            return cached

        lock = await self._audience_lock(audience)
        async with lock:
            cached = self._cache.get(audience)
            now = datetime.now(tz=UTC)
            if cached is not None and cached.expires_at > now + timedelta(seconds=_MIN_TTL_SECONDS):
                return cached
            return await self._fetch_and_cache(audience)

    async def _audience_lock(self, audience: str) -> asyncio.Lock:
        async with self._registry_lock:
            return self._audience_locks.setdefault(audience, asyncio.Lock())

    async def _fetch_and_cache(self, audience: str) -> IdentityToken:
        if self._config.federated_token_file is not None:
            async with asyncio.timeout(self._config.timeout_seconds):
                try:
                    async with WorkloadIdentityCredential(
                        tenant_id=self._config.federated_tenant_id,
                        client_id=self._config.client_id,
                        token_file_path=self._config.federated_token_file,
                        retry_total=0,
                    ) as credential:
                        scope = (
                            audience
                            if audience.endswith("/.default")
                            else audience.rstrip("/") + "/.default"
                        )
                        received = await credential.get_token(scope)
                except (AzureError, OSError, ValueError):
                    raise RuntimeError("AKS workload identity token acquisition failed") from None
            token = IdentityToken(
                token=received.token,
                expires_at=datetime.fromtimestamp(received.expires_on, tz=UTC),
                audience=audience,
            )
            self._cache[audience] = token
            return token
        params = {
            "api-version": _API_VERSION,
            "resource": _audience_to_resource(audience),
        }
        if self._config.client_id:
            params["client_id"] = self._config.client_id
        response = await self._http.get(
            self._config.endpoint,
            params=params,
            headers={"X-IDENTITY-HEADER": self._config.header},
            timeout=self._config.timeout_seconds,
        )
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, Mapping):
            raise RuntimeError("Managed Identity endpoint returned an unrecognized body")
        try:
            token_value = str(body["access_token"])
            expires_on = int(body["expires_on"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("Managed Identity endpoint returned an unrecognized body") from exc
        token = IdentityToken(
            token=token_value,
            expires_at=datetime.fromtimestamp(expires_on, tz=UTC),
            audience=audience,
        )
        self._cache[audience] = token
        return token


def _validate_federation(config: ManagedIdentityWorkloadIdentityConfig) -> None:
    try:
        UUID(config.federated_tenant_id or "")
        UUID(config.client_id or "")
    except ValueError:
        raise ManagedIdentityConfigurationError(
            "AKS workload identity requires valid tenant and client identifiers"
        ) from None
    token_file = config.federated_token_file or ""
    if (
        config.endpoint
        or config.header
        or not token_file
        or token_file != token_file.strip()
        or not Path(token_file).is_absolute()
    ):
        raise ManagedIdentityConfigurationError(
            "AKS workload identity requires one absolute projected token path "
            "without endpoint credentials"
        )


def _audience_to_resource(audience: str) -> str:
    if audience.endswith("/.default"):
        return audience[: -len("/.default")]
    return audience


def _config_from_env(
    env: Mapping[str, str] | None = None,
    *,
    client_id_env: str = "FDAI_MI_CLIENT_ID",
) -> ManagedIdentityWorkloadIdentityConfig:
    source = env if env is not None else os.environ
    if "AZURE_FEDERATED_TOKEN_FILE" in source:
        client_id = source.get("AZURE_CLIENT_ID")
        selected = source.get(client_id_env)
        if selected and (client_id is None or selected.casefold() != client_id.casefold()):
            raise ManagedIdentityConfigurationError(
                "AKS workload identity differs from the selected service identity"
            )
        return ManagedIdentityWorkloadIdentityConfig(
            endpoint="",
            header="",
            client_id=client_id,
            federated_tenant_id=source.get("AZURE_TENANT_ID"),
            federated_token_file=source["AZURE_FEDERATED_TOKEN_FILE"],
        )
    endpoint = source.get("IDENTITY_ENDPOINT") or source.get("MSI_ENDPOINT")
    header = source.get("IDENTITY_HEADER") or source.get("MSI_SECRET") or ""
    if not endpoint:
        raise ManagedIdentityConfigurationError(
            "IDENTITY_ENDPOINT (or MSI_ENDPOINT) MUST be set for Azure Managed Identity"
        )
    return ManagedIdentityWorkloadIdentityConfig(
        endpoint=endpoint,
        header=header,
        client_id=source.get(client_id_env),
    )


__all__ = [
    "ManagedIdentityConfigurationError",
    "ManagedIdentityWorkloadIdentity",
    "ManagedIdentityWorkloadIdentityConfig",
]
