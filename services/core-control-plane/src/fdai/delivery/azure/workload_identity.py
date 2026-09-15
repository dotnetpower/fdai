"""ManagedIdentityWorkloadIdentity - production `WorkloadIdentity` adapter.

Reaches the attached Managed Identity endpoint via ``httpx`` or uses the Azure
Identity SDK for an explicitly configured AKS projected service-account token.
The attached identity wire contract is documented and stable
(https://learn.microsoft.com/en-us/entra/identity/managed-identities-azure-resources/how-to-use-vm-token).

Container Apps injects two environment variables when a user-assigned MI
is attached to the app:

- ``IDENTITY_ENDPOINT`` - the local token endpoint URL.
- ``IDENTITY_HEADER`` - the value MSAL must send in the ``X-IDENTITY-HEADER``
  request header (proof the caller is inside the pod's namespace).

The adapter reads both at construction, caches tokens per audience until
close to expiry, and returns
:class:`~fdai.shared.providers.workload_identity.IdentityToken`
records the rest of the app already understands.
"""

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

from fdai.shared.providers.workload_identity import IdentityToken

_API_VERSION: Final[str] = "2019-08-01"
_MIN_TTL_SECONDS: Final[int] = 60


class ManagedIdentityConfigurationError(RuntimeError):
    """Raised when the required MI env vars are missing at construction."""


@dataclass(frozen=True, slots=True)
class ManagedIdentityWorkloadIdentityConfig:
    """Injectable overrides for the MI token endpoint (mostly for tests)."""

    endpoint: str
    header: str
    """Value of the ``X-IDENTITY-HEADER`` request header."""

    client_id: str | None = None
    """User-assigned MI client id. None → system-assigned (Container Apps
    with a single user-assigned MI still exposes it as system-assigned to
    the identity endpoint)."""

    timeout_seconds: float = 10.0
    federated_tenant_id: str | None = None
    federated_token_file: str | None = None


class ManagedIdentityWorkloadIdentity:
    """Async :class:`WorkloadIdentity` backed by Azure Managed Identity.

    Fail-fast: :class:`ManagedIdentityConfigurationError` on missing env.
    Every ``get_token`` call round-trips over ``httpx`` unless a cached
    token has more than :data:`_MIN_TTL_SECONDS` of life left - this
    matches the Azure guidance to refresh well before expiry.
    """

    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient,
        config: ManagedIdentityWorkloadIdentityConfig | None = None,
    ) -> None:
        cfg = config or _config_from_env()
        if cfg.federated_token_file is not None:
            _validate_federation(cfg)
        elif not cfg.endpoint.startswith(("https://", "http://")):
            raise ManagedIdentityConfigurationError("IDENTITY_ENDPOINT MUST be an absolute URL")
        if cfg.federated_token_file is None and not cfg.header:
            raise ManagedIdentityConfigurationError("IDENTITY_HEADER MUST NOT be empty")
        if cfg.timeout_seconds <= 0:
            raise ManagedIdentityConfigurationError("timeout_seconds MUST be > 0")
        self._config = cfg
        self._http = http_client
        self._cache: dict[str, IdentityToken] = {}
        # One asyncio Lock per audience. Without this, N concurrent
        # callers requesting the same audience would each fire a
        # separate IMDS round-trip on a cold cache - IMDS rate-limits
        # per-instance, so a burst on startup can flap. Serializing
        # per-audience folds the second-onwards caller onto the cached
        # result the first caller stores.
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
        """Build an adapter selecting one attached UAMI by env key."""
        return cls(
            http_client=http_client,
            config=_config_from_env(env=env, client_id_env=client_id_env),
        )

    async def _audience_lock(self, audience: str) -> asyncio.Lock:
        async with self._registry_lock:
            lock = self._audience_locks.get(audience)
            if lock is None:
                lock = asyncio.Lock()
                self._audience_locks[audience] = lock
            return lock

    async def get_token(self, audience: str) -> IdentityToken:
        cached = self._cache.get(audience)
        now = datetime.now(tz=UTC)
        if cached is not None and cached.expires_at > now + timedelta(seconds=_MIN_TTL_SECONDS):
            return cached

        lock = await self._audience_lock(audience)
        async with lock:
            # Re-check under the lock: another coroutine may have
            # populated the cache while we were awaiting the lock.
            cached = self._cache.get(audience)
            now = datetime.now(tz=UTC)
            if cached is not None and cached.expires_at > now + timedelta(seconds=_MIN_TTL_SECONDS):
                return cached
            return await self._fetch_and_cache(audience)

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
                        token = await credential.get_token(scope)
                except (AzureError, OSError, ValueError):
                    raise RuntimeError("AKS workload identity token acquisition failed") from None
            identity = IdentityToken(
                token=token.token,
                expires_at=datetime.fromtimestamp(token.expires_on, tz=UTC),
                audience=audience,
            )
            self._cache[audience] = identity
            return identity
        params: dict[str, str] = {
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
        try:
            token_str = str(body["access_token"])
            expires_on = int(body["expires_on"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("Managed Identity endpoint returned an unrecognized body") from exc

        identity = IdentityToken(
            token=token_str,
            expires_at=datetime.fromtimestamp(expires_on, tz=UTC),
            audience=audience,
        )
        self._cache[audience] = identity
        return identity


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
    """Convert an OIDC ``.default`` scope into the older resource id.

    Managed Identity's token endpoint uses the older ``resource=<uri>``
    query parameter, not the OAuth2 ``scope=`` form. Strip the trailing
    ``/.default`` when present so callers can use the modern scope
    string uniformly across dev/prod.
    """
    if audience.endswith("/.default"):
        return audience[: -len("/.default")]
    return audience


def _config_from_env(
    env: Mapping[str, str] | None = None,
    *,
    client_id_env: str = "FDAI_MI_CLIENT_ID",
) -> ManagedIdentityWorkloadIdentityConfig:
    """Read the standard Container Apps / IMDS env vars."""
    src: Mapping[str, str] = env if env is not None else os.environ
    if "AZURE_FEDERATED_TOKEN_FILE" in src:
        client_id = src.get("AZURE_CLIENT_ID")
        selected = src.get(client_id_env)
        if selected and (client_id is None or selected.casefold() != client_id.casefold()):
            raise ManagedIdentityConfigurationError(
                "AKS workload identity differs from the selected service identity"
            )
        return ManagedIdentityWorkloadIdentityConfig(
            endpoint="",
            header="",
            client_id=client_id,
            federated_tenant_id=src.get("AZURE_TENANT_ID"),
            federated_token_file=src["AZURE_FEDERATED_TOKEN_FILE"],
        )
    endpoint = (
        src.get("IDENTITY_ENDPOINT")
        or src.get("MSI_ENDPOINT")
        or os.environ.get("IDENTITY_ENDPOINT")
        or os.environ.get("MSI_ENDPOINT")
    )
    header = (
        src.get("IDENTITY_HEADER")
        or src.get("MSI_SECRET")
        or os.environ.get("IDENTITY_HEADER")
        or os.environ.get("MSI_SECRET")
        or ""
    )
    if not endpoint:
        raise ManagedIdentityConfigurationError(
            "IDENTITY_ENDPOINT (or MSI_ENDPOINT) MUST be set - this adapter "
            "only runs where an Azure Managed Identity is attached"
        )
    return ManagedIdentityWorkloadIdentityConfig(
        endpoint=endpoint,
        header=header,
        client_id=src.get(client_id_env),
    )


__all__ = [
    "ManagedIdentityConfigurationError",
    "ManagedIdentityWorkloadIdentity",
    "ManagedIdentityWorkloadIdentityConfig",
]
