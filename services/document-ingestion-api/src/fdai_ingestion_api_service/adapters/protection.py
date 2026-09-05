"""Delegated Purview/RMS preview authorization."""

from __future__ import annotations

import hashlib
from typing import Protocol
from urllib.parse import urlparse

import httpx
from fdai_service_contracts import (
    DocumentAccessDeniedError,
    DocumentVersion,
    ProviderUnavailableError,
)


class _AccessToken(Protocol):
    token: str


class ProtectionTokenCredential(Protocol):
    async def get_token(self, *scopes: str) -> _AccessToken: ...


class PurviewRmsPreviewAuthorizer:
    """Authorize one effective reader without forwarding the operator token."""

    def __init__(
        self,
        *,
        endpoint: str,
        audience: str,
        credential: ProtectionTokenCredential,
        client: httpx.AsyncClient,
        timeout_seconds: float = 15.0,
    ) -> None:
        endpoint_url = urlparse(endpoint)
        audience_url = urlparse(audience)
        if (
            endpoint_url.scheme != "https"
            or not endpoint_url.hostname
            or endpoint_url.query
            or endpoint_url.fragment
            or audience_url.scheme != "https"
            or audience_url.hostname != endpoint_url.hostname
            or audience_url.port != endpoint_url.port
            or audience_url.path != "/.default"
        ):
            raise ValueError("preview protection endpoint and audience MUST share an HTTPS origin")
        if timeout_seconds <= 0:
            raise ValueError("preview protection timeout MUST be positive")
        self._endpoint = endpoint.rstrip("/")
        self._audience = audience
        self._credential = credential
        self._client = client
        self._timeout_seconds = timeout_seconds

    async def authorize(
        self,
        *,
        actor_id: str,
        actor_groups: frozenset[str],
        version: DocumentVersion,
    ) -> None:
        provider_ref = version.protection_provider_ref
        policy_revision = version.protection_policy_revision
        if provider_ref is None or policy_revision is None:
            raise DocumentAccessDeniedError(
                "rights-managed preview has no provider authorization binding"
            )
        actor_digest = hashlib.sha256(actor_id.encode()).hexdigest()
        group_digests = sorted(hashlib.sha256(group.encode()).hexdigest() for group in actor_groups)
        token = await self._credential.get_token(self._audience)
        try:
            response = await self._client.post(
                f"{self._endpoint}/authorize",
                json={
                    "document_id": str(version.document_id),
                    "version_id": str(version.version_id),
                    "source_sha256": version.source_sha256,
                    "provider_ref": provider_ref,
                    "policy_revision": policy_revision,
                    "actor_sha256": actor_digest,
                    "group_sha256": group_digests,
                    "purpose": "governed_preview",
                },
                headers={"Authorization": f"Bearer {token.token}"},
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderUnavailableError("preview protection authorization failed") from exc
        if (
            not isinstance(payload, dict)
            or payload.get("document_id") != str(version.document_id)
            or payload.get("version_id") != str(version.version_id)
            or payload.get("source_sha256") != version.source_sha256
            or payload.get("provider_ref") != provider_ref
            or payload.get("policy_revision") != policy_revision
            or payload.get("actor_sha256") != actor_digest
            or payload.get("group_sha256") != group_digests
            or payload.get("purpose") != "governed_preview"
        ):
            raise ProviderUnavailableError("preview protection authorization binding failed")
        allowed = payload.get("allowed")
        if not isinstance(allowed, bool):
            raise ProviderUnavailableError("preview protection decision is invalid")
        if not allowed:
            raise DocumentAccessDeniedError("preview protection authorization was denied")
