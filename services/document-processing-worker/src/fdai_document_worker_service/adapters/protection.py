"""Purview/RMS-compatible protection inspection and revocation reconciliation."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse
from uuid import UUID

import httpx
from fdai_service_contracts import (
    AdapterReadiness,
    ProtectionInspection,
    ProtectionState,
    ProviderUnavailableError,
    configured_readiness,
    live_readiness,
    live_unavailable_readiness,
)


class _AccessToken(Protocol):
    token: str


class ProtectionTokenCredential(Protocol):
    async def get_token(self, *scopes: str) -> _AccessToken: ...


@dataclass(frozen=True, slots=True)
class PurviewRmsConfig:
    endpoint: str
    audience: str
    max_input_bytes: int
    timeout_seconds: float = 30.0
    max_reconciliation_batch: int = 100

    def __post_init__(self) -> None:
        parsed = urlparse(self.endpoint)
        if parsed.scheme != "https" or not parsed.hostname or parsed.query or parsed.fragment:
            raise ValueError("protection endpoint MUST be an HTTPS URL without query or fragment")
        audience = urlparse(self.audience)
        if (
            audience.scheme != "https"
            or audience.hostname != parsed.hostname
            or audience.port != parsed.port
            or audience.path != "/.default"
            or audience.query
            or audience.fragment
        ):
            raise ValueError(
                "protection audience MUST match the provider HTTPS origin and use .default"
            )
        if self.max_input_bytes < 1:
            raise ValueError("protection input budget MUST be positive")
        if self.timeout_seconds <= 0:
            raise ValueError("protection timeout MUST be positive")
        if not 1 <= self.max_reconciliation_batch <= 1000:
            raise ValueError("protection reconciliation batch MUST be in [1, 1000]")


@dataclass(frozen=True, slots=True)
class ProtectionReconciliationCandidate:
    document_id: UUID
    version_id: UUID
    source_sha256: str
    provider_ref: str
    policy_revision: int

    def __post_init__(self) -> None:
        if len(self.source_sha256) != 64:
            raise ValueError("source_sha256 MUST contain a SHA-256 digest")
        if not self.provider_ref:
            raise ValueError("provider_ref MUST NOT be empty")
        if self.policy_revision < 0:
            raise ValueError("policy_revision MUST NOT be negative")


@dataclass(frozen=True, slots=True)
class ProtectionReconciliationDecision:
    document_id: UUID
    version_id: UUID
    source_sha256: str
    policy_revision: int
    revoked: bool
    state: ProtectionState
    reason_code: str | None


class PurviewRmsProtectionInspector:
    """Inspect protected bytes through a deployment-owned MIP/RMS provider."""

    def __init__(
        self,
        *,
        config: PurviewRmsConfig,
        credential: ProtectionTokenCredential,
        client: httpx.AsyncClient,
    ) -> None:
        self._config = config
        self._credential = credential
        self._client = client

    def readiness(self) -> AdapterReadiness:
        return configured_readiness("purview-rms-protection")

    async def probe_readiness(self) -> AdapterReadiness:
        try:
            token = await self._credential.get_token(self._config.audience)
            response = await self._client.get(
                f"{self._config.endpoint.rstrip('/')}/health",
                headers={"Authorization": f"Bearer {token.token}"},
                timeout=min(self._config.timeout_seconds, 5.0),
            )
            response.raise_for_status()
        except (httpx.HTTPError, TimeoutError):
            return live_unavailable_readiness("purview-rms-protection", "probe_failed")
        return live_readiness("purview-rms-protection")

    async def inspect(
        self,
        *,
        source_name: str,
        media_type_hint: str,
        chunks: AsyncIterator[bytes],
    ) -> ProtectionInspection:
        content = await _read_bounded(chunks, self._config.max_input_bytes)
        source_sha256 = hashlib.sha256(content).hexdigest()
        token = await self._credential.get_token(self._config.audience)
        try:
            response = await self._client.post(
                f"{self._config.endpoint.rstrip('/')}/inspect",
                content=content,
                headers={
                    "Authorization": f"Bearer {token.token}",
                    "Content-Type": media_type_hint or "application/octet-stream",
                    "X-FDAI-Source-Name-SHA256": hashlib.sha256(source_name.encode()).hexdigest(),
                    "X-FDAI-Source-SHA256": source_sha256,
                },
                timeout=self._config.timeout_seconds,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError("protection provider inspection failed") from exc
        payload = _object_payload(response)
        if payload.get("source_sha256") != source_sha256:
            raise ProviderUnavailableError("protection provider digest binding failed")
        state = _protection_state(payload.get("state"))
        revoked = payload.get("revoked", False)
        if not isinstance(revoked, bool):
            raise ProviderUnavailableError(
                "protection provider returned an invalid revocation flag"
            )
        reason_code = _optional_string(payload, "reason_code")
        if revoked:
            state = ProtectionState.RIGHTS_MANAGED_ACCESS_DENIED
            reason_code = "rights_management_revoked"
        return ProtectionInspection(
            state=state,
            observed_format=_required_string(payload, "observed_format"),
            media_type=_required_string(payload, "media_type"),
            sensitivity_label=_optional_string(payload, "sensitivity_label"),
            reason_code=reason_code,
        )


class PurviewRmsRevocationReconciler:
    """Recheck persisted provider references without resending source content."""

    def __init__(
        self,
        *,
        config: PurviewRmsConfig,
        credential: ProtectionTokenCredential,
        client: httpx.AsyncClient,
    ) -> None:
        self._config = config
        self._credential = credential
        self._client = client

    async def reconcile(
        self, candidates: Sequence[ProtectionReconciliationCandidate]
    ) -> tuple[ProtectionReconciliationDecision, ...]:
        if not candidates:
            return ()
        if len(candidates) > self._config.max_reconciliation_batch:
            raise ValueError("protection reconciliation batch exceeds the configured bound")
        token = await self._credential.get_token(self._config.audience)
        try:
            response = await self._client.post(
                f"{self._config.endpoint.rstrip('/')}/reconcile",
                json={
                    "items": [
                        {
                            "document_id": str(item.document_id),
                            "version_id": str(item.version_id),
                            "source_sha256": item.source_sha256,
                            "provider_ref": item.provider_ref,
                            "policy_revision": item.policy_revision,
                        }
                        for item in candidates
                    ]
                },
                headers={"Authorization": f"Bearer {token.token}"},
                timeout=self._config.timeout_seconds,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError("protection revocation reconciliation failed") from exc
        payload = _object_payload(response)
        values = payload.get("items")
        if not isinstance(values, list) or len(values) != len(candidates):
            raise ProviderUnavailableError("protection reconciliation response is incomplete")
        expected = {(item.document_id, item.version_id): item for item in candidates}
        decisions: list[ProtectionReconciliationDecision] = []
        for raw in values:
            if not isinstance(raw, dict):
                raise ProviderUnavailableError("protection reconciliation item is invalid")
            try:
                key = (
                    UUID(_required_string(raw, "document_id")),
                    UUID(_required_string(raw, "version_id")),
                )
            except ValueError as exc:
                raise ProviderUnavailableError(
                    "protection reconciliation identity is invalid"
                ) from exc
            candidate = expected.pop(key, None)
            if (
                candidate is None
                or raw.get("source_sha256") != candidate.source_sha256
                or raw.get("provider_ref") != candidate.provider_ref
            ):
                raise ProviderUnavailableError("protection reconciliation binding failed")
            policy_revision = raw.get("policy_revision")
            revoked = raw.get("revoked")
            if not isinstance(policy_revision, int) or policy_revision < candidate.policy_revision:
                raise ProviderUnavailableError(
                    "protection reconciliation policy revision regressed"
                )
            if not isinstance(revoked, bool):
                raise ProviderUnavailableError(
                    "protection reconciliation revocation flag is invalid"
                )
            state = _protection_state(raw.get("state"))
            reason_code = _optional_string(raw, "reason_code")
            if revoked:
                state = ProtectionState.RIGHTS_MANAGED_ACCESS_DENIED
                reason_code = "rights_management_revoked"
            decisions.append(
                ProtectionReconciliationDecision(
                    document_id=candidate.document_id,
                    version_id=candidate.version_id,
                    source_sha256=candidate.source_sha256,
                    policy_revision=policy_revision,
                    revoked=revoked,
                    state=state,
                    reason_code=reason_code,
                )
            )
        if expected:
            raise ProviderUnavailableError("protection reconciliation omitted a candidate")
        return tuple(decisions)


async def _read_bounded(chunks: AsyncIterator[bytes], limit: int) -> bytes:
    content = bytearray()
    async for chunk in chunks:
        content.extend(chunk)
        if len(content) > limit:
            raise ValueError("protection input exceeds the configured bound")
    return bytes(content)


def _object_payload(response: httpx.Response) -> dict[str, object]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise ProviderUnavailableError("protection provider response is not JSON") from exc
    if not isinstance(payload, dict):
        raise ProviderUnavailableError("protection provider response is not an object")
    return payload


def _protection_state(value: object) -> ProtectionState:
    if not isinstance(value, str):
        raise ProviderUnavailableError("protection provider state is missing")
    try:
        return ProtectionState(value)
    except ValueError as exc:
        raise ProviderUnavailableError("protection provider state is unsupported") from exc


def _required_string(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ProviderUnavailableError(f"protection provider {key} is missing")
    return value


def _optional_string(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ProviderUnavailableError(f"protection provider {key} is invalid")
    return value
