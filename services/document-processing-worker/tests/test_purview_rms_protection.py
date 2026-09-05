"""Focused Purview/RMS provider and revocation reconciliation tests."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest
from fdai_document_worker_service.adapters.protection import (
    ProtectionReconciliationCandidate,
    PurviewRmsConfig,
    PurviewRmsProtectionInspector,
    PurviewRmsRevocationReconciler,
)
from fdai_service_contracts import ProtectionState, ProviderUnavailableError


class Credential:
    async def get_token(self, *_scopes: str) -> object:
        return SimpleNamespace(token="provider-token")


async def _chunks(content: bytes) -> AsyncIterator[bytes]:
    yield content[:3]
    yield content[3:]


def _config(**updates: object) -> PurviewRmsConfig:
    values: dict[str, object] = {
        "endpoint": "https://protection.example/v1",
        "audience": "https://protection.example/.default",
        "max_input_bytes": 1024,
    }
    values.update(updates)
    return PurviewRmsConfig(**values)  # type: ignore[arg-type]


async def test_inspection_binds_digest_and_preserves_accessible_label() -> None:
    content = b"protected-office-content"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer provider-token"
        assert (
            request.headers["x-fdai-source-name-sha256"]
            == hashlib.sha256(b"restricted.docx").hexdigest()
        )
        digest = hashlib.sha256(request.content).hexdigest()
        return httpx.Response(
            200,
            json={
                "source_sha256": digest,
                "state": "rights_managed_accessible",
                "observed_format": "docx",
                "media_type": (
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                ),
                "sensitivity_label": "confidential",
                "reason_code": None,
                "revoked": False,
                "provider_ref": "provider:document:1",
                "policy_revision": 7,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        inspector = PurviewRmsProtectionInspector(
            config=_config(),
            credential=Credential(),  # type: ignore[arg-type]
            client=client,
        )
        result = await inspector.inspect(
            source_name="restricted.docx",
            media_type_hint=(
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ),
            chunks=_chunks(content),
        )

    assert result.state is ProtectionState.RIGHTS_MANAGED_ACCESSIBLE
    assert result.sensitivity_label == "confidential"
    assert result.provider_ref == "provider:document:1"
    assert result.policy_revision == 7


async def test_inspection_fails_closed_on_provider_digest_mismatch() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "source_sha256": "0" * 64,
                "state": "none",
                "observed_format": "pdf",
                "media_type": "application/pdf",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        inspector = PurviewRmsProtectionInspector(
            config=_config(),
            credential=Credential(),  # type: ignore[arg-type]
            client=client,
        )
        with pytest.raises(ProviderUnavailableError, match="digest binding"):
            await inspector.inspect(
                source_name="source.pdf",
                media_type_hint="application/pdf",
                chunks=_chunks(b"%PDF-1.7"),
            )


async def test_revocation_reconciliation_is_batch_bounded_and_digest_fenced() -> None:
    candidate = ProtectionReconciliationCandidate(
        document_id=UUID(int=1),
        version_id=UUID(int=2),
        source_sha256="a" * 64,
        provider_ref="provider:document:1",
        policy_revision=7,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        item = request.extensions["decoded_body"]["items"][0]
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        **item,
                        "policy_revision": 8,
                        "revoked": True,
                        "state": "rights_managed_accessible",
                    }
                ]
            },
        )

    class DecodeBodyTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            import json

            request.extensions["decoded_body"] = json.loads(request.content)
            return handler(request)

    async with httpx.AsyncClient(transport=DecodeBodyTransport()) as client:
        reconciler = PurviewRmsRevocationReconciler(
            config=_config(max_reconciliation_batch=1),
            credential=Credential(),  # type: ignore[arg-type]
            client=client,
        )
        decisions = await reconciler.reconcile((candidate,))
        with pytest.raises(ValueError, match="exceeds"):
            await reconciler.reconcile((candidate, candidate))

    assert decisions[0].revoked is True
    assert decisions[0].state is ProtectionState.RIGHTS_MANAGED_ACCESS_DENIED
    assert decisions[0].reason_code == "rights_management_revoked"


async def test_revocation_reconciliation_rejects_cross_provider_response() -> None:
    candidate = ProtectionReconciliationCandidate(
        document_id=UUID(int=1),
        version_id=UUID(int=2),
        source_sha256="a" * 64,
        provider_ref="provider:document:1",
        policy_revision=7,
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "document_id": str(candidate.document_id),
                        "version_id": str(candidate.version_id),
                        "source_sha256": candidate.source_sha256,
                        "provider_ref": "provider:document:other",
                        "policy_revision": 8,
                        "revoked": False,
                        "state": "rights_managed_accessible",
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        reconciler = PurviewRmsRevocationReconciler(
            config=_config(),
            credential=Credential(),  # type: ignore[arg-type]
            client=client,
        )
        with pytest.raises(ProviderUnavailableError, match="binding failed"):
            await reconciler.reconcile((candidate,))


def test_protection_config_rejects_unsafe_endpoint_and_scope() -> None:
    with pytest.raises(ValueError, match="HTTPS URL"):
        _config(endpoint="http://protection.example/v1")
    with pytest.raises(ValueError, match=".default"):
        _config(audience="https://protection.example")
