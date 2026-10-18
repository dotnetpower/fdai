"""Purpose, identity, replay and expiry checks for protected original-byte export."""

from __future__ import annotations

import asyncio
import gzip
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
import pytest
from fdai_ingestion_api_service import production
from fdai_ingestion_api_service.adapters.protection import PurviewRmsSourceDownloadAuthorizer
from fdai_ingestion_api_service.download import GovernedDocumentDownload
from fdai_ingestion_api_service.http import _document_summary
from fdai_service_contracts import (
    AccessDescriptor,
    DocumentAccessDeniedError,
    DocumentPurpose,
    DocumentState,
    DocumentVersion,
    ProtectionState,
    ProviderUnavailableError,
    RetentionPolicy,
)
from starlette.applications import Starlette

_NOW = datetime(2026, 10, 18, 11, 0, tzinfo=UTC)


@dataclass(frozen=True)
class Token:
    token: str = "test-provider-token"


class Credential:
    async def get_token(self, *scopes: str) -> Token:
        assert scopes == ("https://protection.example/.default",)
        return Token()


def _version() -> DocumentVersion:
    return DocumentVersion(
        document_id=UUID(int=1),
        version_id=UUID(int=2),
        upload_id=UUID(int=3),
        source_name="guide.pdf",
        source_sha256="a" * 64,
        size_bytes=100,
        media_type="application/pdf",
        state=DocumentState.READY,
        revision=1,
        protection_state=ProtectionState.RIGHTS_MANAGED_ACCESSIBLE,
        protection_provider_ref="provider:document:1",
        protection_policy_revision=7,
        access=AccessDescriptor(reference="collection:knowledge", collection_id="knowledge"),
        retention=RetentionPolicy(policy_version="v1"),
        purposes=(DocumentPurpose.KNOWLEDGE_BASE,),
        uploader_id="operator",
        created_at=_NOW,
        updated_at=_NOW,
        active=True,
        available=True,
    )


def _authorizer(
    client: httpx.AsyncClient,
) -> PurviewRmsSourceDownloadAuthorizer:
    return PurviewRmsSourceDownloadAuthorizer(
        endpoint="https://protection.example/v1",
        audience="https://protection.example/.default",
        credential=Credential(),
        client=client,
        clock=lambda: _NOW,
        id_factory=lambda: UUID(int=4),
    )


async def test_source_export_requires_a_fresh_purpose_bound_receipt() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["purpose"] == "governed_source_download"
        assert body["document_revision"] == 1
        assert body["access_descriptor_ref"] == "collection:knowledge"
        assert body["request_id"] == str(UUID(int=4))
        assert "reader" not in request.content.decode()
        assert "private-group" not in request.content.decode()
        return httpx.Response(
            200,
            json={
                **body,
                "allowed": True,
                "expires_at": (_NOW + timedelta(seconds=60)).isoformat(),
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        receipt = await _authorizer(client).authorize(
            actor_id="reader",
            actor_groups=frozenset({"private-group"}),
            version=_version(),
        )
    assert receipt.request_id == UUID(int=4)
    assert receipt.expires_at == _NOW + timedelta(seconds=60)
    assert len(receipt.receipt_sha256) == 64
    assert json.loads(receipt.canonical_receipt)["purpose"] == "governed_source_download"
    assert "test-provider-token" not in receipt.canonical_receipt
    assert "reader" not in receipt.canonical_receipt


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("purpose", "governed_preview"),
        ("request_id", str(UUID(int=5))),
        ("document_id", str(UUID(int=6))),
        ("version_id", str(UUID(int=7))),
        ("source_sha256", "b" * 64),
        ("provider_ref", "provider:other"),
        ("policy_revision", 8),
        ("document_revision", True),
        ("access_descriptor_ref", "collection:other"),
        ("actor_sha256", "b" * 64),
        ("group_sha256", []),
    ],
)
async def test_source_export_rejects_mismatched_receipt_bindings(field: str, value: object) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                **body,
                "allowed": True,
                "expires_at": (_NOW + timedelta(seconds=30)).isoformat(),
                field: value,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ProviderUnavailableError, match="binding failed"):
            await _authorizer(client).authorize(
                actor_id="reader", actor_groups=frozenset({"group"}), version=_version()
            )


@pytest.mark.parametrize(
    "expiry",
    [
        None,
        60,
        "invalid",
        _NOW.replace(tzinfo=None).isoformat(),
        _NOW.isoformat(),
        (_NOW - timedelta(seconds=1)).isoformat(),
        (_NOW + timedelta(seconds=61)).isoformat(),
    ],
)
async def test_source_export_rejects_unbounded_or_expired_receipts(expiry: object) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={**json.loads(request.content), "allowed": True, "expires_at": expiry}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ProviderUnavailableError, match="expiry|validity"):
            await _authorizer(client).authorize(
                actor_id="reader", actor_groups=frozenset(), version=_version()
            )


@pytest.mark.parametrize("allowed", [False, None, "true", 1])
async def test_source_export_never_treats_invalid_or_denied_decisions_as_permission(
    allowed: object,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                **json.loads(request.content),
                "allowed": allowed,
                "expires_at": (_NOW + timedelta(seconds=30)).isoformat(),
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        error = DocumentAccessDeniedError if allowed is False else ProviderUnavailableError
        with pytest.raises(error, match="denied|invalid"):
            await _authorizer(client).authorize(
                actor_id="reader", actor_groups=frozenset(), version=_version()
            )


async def test_source_export_does_not_follow_provider_redirects() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(307, headers={"location": "https://elsewhere.example/authorize"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=True
    ) as client:
        with pytest.raises(ProviderUnavailableError, match="authorization failed"):
            await _authorizer(client).authorize(
                actor_id="reader", actor_groups=frozenset(), version=_version()
            )
    assert len(requests) == 1
    assert requests[0].url.host == "protection.example"


async def test_an_earlier_source_export_receipt_cannot_authorize_a_new_request() -> None:
    prior: dict[str, object] = {}
    nonce = iter([UUID(int=4), UUID(int=5)])

    def handler(request: httpx.Request) -> httpx.Response:
        if not prior:
            prior.update(
                {
                    **json.loads(request.content),
                    "allowed": True,
                    "expires_at": (_NOW + timedelta(seconds=30)).isoformat(),
                }
            )
        return httpx.Response(200, json=prior)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        authorizer = PurviewRmsSourceDownloadAuthorizer(
            endpoint="https://protection.example/v1",
            audience="https://protection.example/.default",
            credential=Credential(),
            client=client,
            clock=lambda: _NOW,
            id_factory=lambda: next(nonce),
        )
        await authorizer.authorize(actor_id="reader", actor_groups=frozenset(), version=_version())
        with pytest.raises(ProviderUnavailableError, match="binding failed"):
            await authorizer.authorize(
                actor_id="reader", actor_groups=frozenset(), version=_version()
            )


@pytest.mark.parametrize("timeout", [0.0, -1.0, float("nan"), float("inf")])
async def test_protection_timeout_must_be_finite_and_positive(timeout: float) -> None:
    async with httpx.AsyncClient() as client:
        with pytest.raises(ValueError, match="finite and positive"):
            PurviewRmsSourceDownloadAuthorizer(
                endpoint="https://protection.example/v1",
                audience="https://protection.example/.default",
                credential=Credential(),
                client=client,
                timeout_seconds=timeout,
            )


@pytest.mark.parametrize(
    ("defect", "message"),
    [
        ("oversize", "size limit"),
        ("compressed", "compressed protection"),
        ("invalid-json", "authorization failed"),
        ("not-object", "binding failed"),
    ],
)
async def test_source_export_rejects_untrusted_response_shapes_and_bounds(
    defect: str, message: str
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = {
            **json.loads(request.content),
            "allowed": True,
            "expires_at": (_NOW + timedelta(seconds=30)).isoformat(),
        }
        if defect == "oversize":
            return httpx.Response(200, json={**body, "extra": "x" * 16_384})
        if defect == "compressed":
            return httpx.Response(
                200,
                headers={"content-encoding": "gzip"},
                content=gzip.compress(json.dumps(body).encode()),
            )
        if defect == "invalid-json":
            return httpx.Response(200, content=b"invalid")
        return httpx.Response(200, json=[body])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ProviderUnavailableError, match=message):
            await _authorizer(client).authorize(
                actor_id="reader", actor_groups=frozenset(), version=_version()
            )


@pytest.mark.parametrize(
    ("endpoint", "audience"),
    [
        ("http://protection.example/v1", "http://protection.example/.default"),
        ("https://user@protection.example/v1", "https://protection.example/.default"),
        ("https://protection.example/v1?token=invalid", "https://protection.example/.default"),
        ("https://protection.example/v1", "https://other.example/.default"),
        ("https://protection.example/v1", "https://user@protection.example/.default"),
        ("https://protection.example/v1", "https://protection.example/.default#fragment"),
        ("https://protection.example/v1", "https://protection.example/.default?query=value"),
    ],
)
async def test_source_export_cannot_bind_credentials_to_an_unsafe_origin(
    endpoint: str, audience: str
) -> None:
    async with httpx.AsyncClient() as client:
        with pytest.raises(ValueError, match="HTTPS origin"):
            PurviewRmsSourceDownloadAuthorizer(
                endpoint=endpoint, audience=audience, credential=Credential(), client=client
            )


@pytest.mark.parametrize("provider", ["signature", "purview_rms"])
async def test_production_composes_the_distinct_download_purpose_only_for_bound_protection(
    monkeypatch: pytest.MonkeyPatch, tmp_path, provider: str
) -> None:
    captured: dict[str, object] = {}

    def capture(**kwargs: object) -> Starlette:
        captured.update(kwargs)
        return Starlette()

    monkeypatch.setattr(production, "build_app", capture)
    monkeypatch.setattr(production, "_azure_credential", lambda _credential: Credential())
    environment = {
        key: f"example-{index}" for index, key in enumerate(production._COMMON_REQUIRED_ENV)
    }
    environment.update(
        {
            "FDAI_EXECUTION_VENUE": "local",
            "FDAI_DATABASE_URL": "postgresql://example.invalid/fdai",
            "FDAI_DATABASE_ROLE": "fdai_ingestion_api",
            "FDAI_INGESTION_DEPLOYMENT_ROLE": "api",
            "FDAI_KAFKA_BOOTSTRAP_SERVERS": "127.0.0.1:19092",
            "FDAI_DOCUMENT_EVENT_TOPIC": "fdai.pipeline.stages",
            "FDAI_INGESTION_CORS_ALLOW_ORIGINS": "http://127.0.0.1:5273",
            "FDAI_LOCAL_DOCUMENT_STORE_DIR": str(tmp_path),
            "FDAI_DOCUMENT_PROTECTION_PROVIDER": provider,
            "FDAI_PROTECTION_ENDPOINT": "https://protection.example/v1",
            "FDAI_PROTECTION_AUDIENCE": "https://protection.example/.default",
        }
    )
    production.build_application(environment)
    download = captured["download"]
    assert isinstance(download, GovernedDocumentDownload)
    if provider == "purview_rms":
        assert isinstance(download._protection, PurviewRmsSourceDownloadAuthorizer)
        assert download.supports_protected_source_download
        await download._protection._client.aclose()
    else:
        assert download._protection is None
        assert not download.supports_protected_source_download


async def test_receipt_expiring_during_provider_io_cannot_authorize_download() -> None:
    now = _NOW

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal now
        now += timedelta(seconds=2)
        return httpx.Response(
            200,
            json={
                **json.loads(request.content),
                "allowed": True,
                "expires_at": (_NOW + timedelta(seconds=1)).isoformat(),
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        authorizer = PurviewRmsSourceDownloadAuthorizer(
            endpoint="https://protection.example/v1",
            audience="https://protection.example/.default",
            credential=Credential(),
            client=client,
            clock=lambda: now,
        )
        with pytest.raises(ProviderUnavailableError, match="validity"):
            await authorizer.authorize(
                actor_id="reader", actor_groups=frozenset(), version=_version()
            )


async def test_missing_source_policy_never_reaches_the_provider() -> None:
    def forbidden(_request: httpx.Request) -> httpx.Response:
        pytest.fail("unbound source policy reached the provider")

    async with httpx.AsyncClient(transport=httpx.MockTransport(forbidden)) as client:
        with pytest.raises(DocumentAccessDeniedError, match="no provider authorization binding"):
            await _authorizer(client).authorize(
                actor_id="reader",
                actor_groups=frozenset(),
                version=_version().model_copy(update={"protection_policy_revision": None}),
            )


@pytest.mark.parametrize("stage", ["credential", "response"])
async def test_total_deadline_includes_credentials_and_provider_response(stage: str) -> None:
    blocker = asyncio.Event()
    interrupted = False

    class BlockingCredential(Credential):
        async def get_token(self, *scopes: str) -> Token:
            nonlocal interrupted
            if stage == "credential":
                try:
                    await blocker.wait()
                finally:
                    interrupted = True
            return await super().get_token(*scopes)

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal interrupted
        try:
            await blocker.wait()
        finally:
            interrupted = True
        pytest.fail("unbounded response completed")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        authorizer = PurviewRmsSourceDownloadAuthorizer(
            endpoint="https://protection.example/v1",
            audience="https://protection.example/.default",
            credential=BlockingCredential(),
            client=client,
            clock=lambda: _NOW,
            timeout_seconds=0.01,
        )
        with pytest.raises(ProviderUnavailableError, match="authorization failed"):
            await authorizer.authorize(
                actor_id="reader", actor_groups=frozenset(), version=_version()
            )
    assert interrupted


async def test_empty_provider_identity_never_sends_an_authorization_request() -> None:
    class EmptyCredential(Credential):
        async def get_token(self, *scopes: str) -> Token:
            return Token("")

    def forbidden(_request: httpx.Request) -> httpx.Response:
        pytest.fail("empty provider identity reached the network")

    async with httpx.AsyncClient(transport=httpx.MockTransport(forbidden)) as client:
        authorizer = PurviewRmsSourceDownloadAuthorizer(
            endpoint="https://protection.example/v1",
            audience="https://protection.example/.default",
            credential=EmptyCredential(),
            client=client,
        )
        with pytest.raises(ProviderUnavailableError, match="credential token is empty"):
            await authorizer.authorize(
                actor_id="reader", actor_groups=frozenset(), version=_version()
            )


@pytest.mark.parametrize("change", ["naive", "backward"])
async def test_changed_clock_cannot_extend_provider_authority(change: str) -> None:
    now = _NOW

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal now
        now = _NOW.replace(tzinfo=None) if change == "naive" else _NOW - timedelta(seconds=1)
        return httpx.Response(
            200,
            json={
                **json.loads(request.content),
                "allowed": True,
                "expires_at": (_NOW + timedelta(seconds=30)).isoformat(),
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        authorizer = PurviewRmsSourceDownloadAuthorizer(
            endpoint="https://protection.example/v1",
            audience="https://protection.example/.default",
            credential=Credential(),
            client=client,
            clock=lambda: now,
        )
        with pytest.raises(ProviderUnavailableError, match="validity"):
            await authorizer.authorize(
                actor_id="reader", actor_groups=frozenset(), version=_version()
            )


async def test_caller_cancellation_is_not_converted_to_permission_or_provider_success() -> None:
    started = asyncio.Event()
    blocker = asyncio.Event()
    interrupted = False

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal interrupted
        started.set()
        try:
            await blocker.wait()
        finally:
            interrupted = True
        pytest.fail("cancelled provider request returned")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        task = asyncio.create_task(
            _authorizer(client).authorize(
                actor_id="reader", actor_groups=frozenset(), version=_version()
            )
        )
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert interrupted


@pytest.mark.parametrize("bound", [False, True])
@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({}, True),
        ({"active": False}, True),
        ({"available": False}, False),
        ({"state": DocumentState.HELD}, False),
        ({"protection_state": ProtectionState.UNKNOWN}, False),
        ({"protection_policy_revision": None}, False),
        ({"protection_provider_ref": None}, False),
    ],
)
def test_library_download_availability_reflects_source_and_provider_binding(
    bound: bool, change: dict[str, object], expected: bool
) -> None:
    summary = _document_summary(
        _version().model_copy(update=change),
        actor_id="reader",
        actor_groups=frozenset(),
        protected_source_download_available=bound,
    )
    assert summary["download_available"] is (bound and expected)
