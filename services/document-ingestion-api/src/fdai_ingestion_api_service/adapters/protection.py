"""Purpose-bound Purview/RMS preview and immutable-source authorization."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Protocol
from urllib.parse import urlparse
from uuid import UUID, uuid4

import httpx
from fdai_service_contracts import (
    DocumentAccessDeniedError,
    DocumentVersion,
    ProviderUnavailableError,
)

from fdai_ingestion_api_service.download_authorization import SourceDownloadAuthorization

_MAX_DECISION_BYTES = 16 * 1024


class _AccessToken(Protocol):
    @property
    def token(self) -> str: ...


class ProtectionTokenCredential(Protocol):
    async def get_token(self, *scopes: str) -> _AccessToken: ...


class _PurviewRmsAuthorizer:
    """Use the configured provider identity, never the operator's token."""

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
            or endpoint_url.username is not None
            or endpoint_url.password is not None
            or endpoint_url.query
            or endpoint_url.fragment
            or audience_url.scheme != "https"
            or audience_url.hostname != endpoint_url.hostname
            or audience_url.port != endpoint_url.port
            or audience_url.username is not None
            or audience_url.password is not None
            or audience_url.query
            or audience_url.fragment
            or audience_url.path != "/.default"
        ):
            raise ValueError("protection endpoint and audience MUST share an HTTPS origin")
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("protection timeout MUST be finite and positive")
        self._endpoint = endpoint.rstrip("/")
        self._audience = audience
        self._credential = credential
        self._client = client
        self._timeout_seconds = timeout_seconds

    async def _decision(
        self,
        *,
        actor_id: str,
        actor_groups: frozenset[str],
        version: DocumentVersion,
        purpose: str,
        extra: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        provider_ref = version.protection_provider_ref
        policy_revision = version.protection_policy_revision
        if provider_ref is None or policy_revision is None:
            raise DocumentAccessDeniedError(
                "rights-managed content has no provider authorization binding"
            )
        actor_digest = hashlib.sha256(actor_id.encode()).hexdigest()
        group_digests = sorted(hashlib.sha256(group.encode()).hexdigest() for group in actor_groups)
        expected: dict[str, object] = {
            "document_id": str(version.document_id),
            "version_id": str(version.version_id),
            "source_sha256": version.source_sha256,
            "provider_ref": provider_ref,
            "policy_revision": policy_revision,
            "actor_sha256": actor_digest,
            "group_sha256": group_digests,
            "purpose": purpose,
            **(extra or {}),
        }
        payload = await self._request_decision(expected)
        if (
            not isinstance(payload, dict)
            or any(type(payload.get(key)) is not type(value) for key, value in expected.items())
            or any(payload.get(key) != value for key, value in expected.items())
        ):
            raise ProviderUnavailableError("protection authorization binding failed")
        allowed = payload.get("allowed")
        if not isinstance(allowed, bool):
            raise ProviderUnavailableError("protection decision is invalid")
        if not allowed:
            raise DocumentAccessDeniedError("protection authorization was denied")
        return {**expected, "allowed": True, "expires_at": payload.get("expires_at")}

    async def _request_decision(self, expected: Mapping[str, object]) -> object:
        try:
            async with asyncio.timeout(self._timeout_seconds):
                token = await self._credential.get_token(self._audience)
                if not token.token.strip():
                    raise ProviderUnavailableError("protection credential token is empty")
                async with self._client.stream(
                    "POST",
                    f"{self._endpoint}/authorize",
                    json=expected,
                    headers={
                        "Authorization": f"Bearer {token.token}",
                        "Accept-Encoding": "identity",
                    },
                    timeout=self._timeout_seconds,
                    follow_redirects=False,
                ) as response:
                    response.raise_for_status()
                    if response.headers.get("content-encoding", "identity").lower() != "identity":
                        raise ProviderUnavailableError(
                            "compressed protection decisions are unsupported"
                        )
                    body = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=4096):
                        if len(body) + len(chunk) > _MAX_DECISION_BYTES:
                            raise ProviderUnavailableError(
                                "protection decision exceeds the size limit"
                            )
                        body.extend(chunk)
                    payload: object = json.loads(body)
                    return payload
        except (httpx.HTTPError, ValueError, RecursionError, TimeoutError) as exc:
            raise ProviderUnavailableError("protection authorization failed") from exc


class PurviewRmsPreviewAuthorizer(_PurviewRmsAuthorizer):
    """Preserve the preview-only provider protocol."""

    async def authorize(
        self,
        *,
        actor_id: str,
        actor_groups: frozenset[str],
        version: DocumentVersion,
    ) -> None:
        await self._decision(
            actor_id=actor_id,
            actor_groups=actor_groups,
            version=version,
            purpose="governed_preview",
        )


class PurviewRmsSourceDownloadAuthorizer(_PurviewRmsAuthorizer):
    """Admit only a new, exact export decision with at most sixty seconds of validity."""

    def __init__(
        self,
        *,
        endpoint: str,
        audience: str,
        credential: ProtectionTokenCredential,
        client: httpx.AsyncClient,
        timeout_seconds: float = 15.0,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], UUID] | None = None,
    ) -> None:
        super().__init__(
            endpoint=endpoint,
            audience=audience,
            credential=credential,
            client=client,
            timeout_seconds=timeout_seconds,
        )
        self._clock = clock or (lambda: datetime.now(tz=UTC))
        self._id_factory = id_factory or uuid4

    async def authorize(
        self,
        *,
        actor_id: str,
        actor_groups: frozenset[str],
        version: DocumentVersion,
    ) -> SourceDownloadAuthorization:
        requested_at = self._clock()
        if requested_at.tzinfo is None or requested_at.utcoffset() is None:
            raise ProviderUnavailableError("source download authorization clock is invalid")
        request_id = self._id_factory()
        decision = await self._decision(
            actor_id=actor_id,
            actor_groups=actor_groups,
            version=version,
            purpose="governed_source_download",
            extra={
                "request_id": str(request_id),
                "document_revision": version.revision,
                "access_descriptor_ref": version.access.reference,
            },
        )
        raw_expiry = decision["expires_at"]
        if not isinstance(raw_expiry, str):
            raise ProviderUnavailableError("source download authorization expiry is missing")
        try:
            expires_at = datetime.fromisoformat(raw_expiry)
        except ValueError as exc:
            raise ProviderUnavailableError(
                "source download authorization expiry is invalid"
            ) from exc
        observed_at = self._clock()
        if (
            expires_at.tzinfo is None
            or expires_at.utcoffset() is None
            or observed_at.tzinfo is None
            or observed_at.utcoffset() is None
            or observed_at < requested_at
            or not observed_at < expires_at <= requested_at + timedelta(seconds=60)
        ):
            raise ProviderUnavailableError("source download authorization validity is invalid")
        return SourceDownloadAuthorization(
            request_id=request_id,
            canonical_receipt=json.dumps(decision, sort_keys=True, separators=(",", ":")),
            issued_at=requested_at,
            expires_at=expires_at,
        )
