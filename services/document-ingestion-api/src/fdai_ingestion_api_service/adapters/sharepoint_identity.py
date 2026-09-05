"""Secretless cross-tenant Microsoft Graph credential for SharePoint."""

from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass
from uuid import UUID

import httpx
from azure.core.credentials import AccessToken
from azure.identity.aio import ManagedIdentityCredential
from fdai_service_contracts import ProviderUnavailableError

_TOKEN_EXCHANGE_SCOPE = "api://AzureADTokenExchange/.default"  # noqa: S105
_ASSERTION_TYPE = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"


@dataclass(frozen=True, slots=True)
class SharePointFederatedCredentialConfig:
    target_tenant_id: str
    client_id: str

    def __post_init__(self) -> None:
        for field, value in (
            ("target_tenant_id", self.target_tenant_id),
            ("client_id", self.client_id),
        ):
            try:
                UUID(value)
            except ValueError as exc:
                raise ValueError(f"SharePoint {field} MUST be a UUID") from exc

    @property
    def binding_digest(self) -> str:
        return hashlib.sha256(f"{self.target_tenant_id}:{self.client_id}".encode()).hexdigest()


class FederatedManagedIdentityGraphCredential:
    """Exchange an Azure UAMI assertion for a Graph token in the M365 tenant."""

    def __init__(
        self,
        *,
        config: SharePointFederatedCredentialConfig,
        managed_identity: ManagedIdentityCredential,
        client: httpx.AsyncClient,
    ) -> None:
        self._config = config
        self._managed_identity = managed_identity
        self._client = client
        self._cached: AccessToken | None = None
        self._lock = asyncio.Lock()

    async def get_token(self, *scopes: str) -> AccessToken:
        if len(scopes) != 1 or not scopes[0]:
            raise ValueError("SharePoint Graph credential requires one scope")
        cached = self._cached
        if cached is not None and cached.expires_on > int(time.time()) + 60:
            return cached
        async with self._lock:
            cached = self._cached
            if cached is not None and cached.expires_on > int(time.time()) + 60:
                return cached
            assertion = await self._managed_identity.get_token(_TOKEN_EXCHANGE_SCOPE)
            try:
                response = await self._client.post(
                    "https://login.microsoftonline.com/"
                    f"{self._config.target_tenant_id}/oauth2/v2.0/token",
                    data={
                        "client_id": self._config.client_id,
                        "scope": scopes[0],
                        "grant_type": "client_credentials",
                        "client_assertion_type": _ASSERTION_TYPE,
                        "client_assertion": assertion.token,
                    },
                )
                response.raise_for_status()
                payload = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                raise ProviderUnavailableError(
                    "SharePoint federated token exchange failed"
                ) from exc
            access_token = payload.get("access_token") if isinstance(payload, dict) else None
            expires_in = payload.get("expires_in") if isinstance(payload, dict) else None
            if (
                not isinstance(access_token, str)
                or not access_token
                or isinstance(expires_in, bool)
                or not isinstance(expires_in, int)
                or expires_in <= 60
            ):
                raise ProviderUnavailableError("SharePoint federated token response is invalid")
            token = AccessToken(access_token, int(time.time()) + expires_in)
            self._cached = token
            return token
