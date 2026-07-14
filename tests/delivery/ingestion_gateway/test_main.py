"""Dedicated document-ingestion gateway boundary tests."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime
from uuid import UUID

import pytest
from starlette.testclient import TestClient

from fdai.core.document_ingestion import DocumentIngestionService, DocumentIngestionWorker
from fdai.core.rbac.enforcer import RoleEnforcer
from fdai.core.rbac.resolver import GroupMapping, RoleResolver
from fdai.delivery.ingestion_gateway import IngestionGatewayConfig, build_app
from fdai.delivery.read_api.auth import Authenticator
from fdai.shared.contracts import IngestionCapabilities, SourceStorageMode
from fdai.shared.providers.local.document_ingestion import (
    SignatureProtectionInspector,
    StandardLibraryDocumentExtractor,
)
from fdai.shared.providers.testing.document_ingestion import (
    InMemoryDocumentAccessProvider,
    InMemoryDocumentArtifactStore,
    InMemoryDocumentIndex,
    InMemoryDocumentMetadataStore,
    InMemoryDocumentObjectStore,
    RecordingDocumentActivitySink,
    StaticMalwareScanner,
)


def _authenticator() -> Authenticator:
    mapping = GroupMapping(
        reader_group_id="reader-group",
        contributor_group_id="contributor-group",
        approver_group_id="approver-group",
        owner_group_id="owner-group",
        break_glass_group_id="break-glass-group",
    )

    def verify(token: str):
        role = "Reader" if token == "reader" else "Contributor"
        return {"oid": token, "roles": [role]}

    return Authenticator(
        verifier=verify,
        resolver=RoleResolver(group_mapping=mapping),
        enforcer=RoleEnforcer(),
    )


def _stack():
    access = InMemoryDocumentAccessProvider(
        contributors={"collection-a": frozenset({"contributor", "ingestion-dev"})},
        readers={"collection-a": frozenset({"reader"})},
    )
    metadata = InMemoryDocumentMetadataStore()
    objects = InMemoryDocumentObjectStore()
    activity = RecordingDocumentActivitySink()
    service = DocumentIngestionService(
        access=access,
        metadata=metadata,
        objects=objects,
        activity=activity,
        capabilities=IngestionCapabilities(
            supported_formats=("text", "ooxml", "pdf-detect-only"),
            storage_modes=tuple(SourceStorageMode),
            max_file_size=1024,
            max_batch_count=2,
            archives_enabled=False,
            policy_versions=("policy-v1",),
        ),
        clock=lambda: datetime(2026, 7, 14, tzinfo=UTC),
    )
    worker = DocumentIngestionWorker(
        access=access,
        metadata=metadata,
        objects=objects,
        malware=StaticMalwareScanner(),
        protection=SignatureProtectionInspector(),
        extractor=StandardLibraryDocumentExtractor(),
        artifacts=InMemoryDocumentArtifactStore(),
        index=InMemoryDocumentIndex(),
        activity=activity,
    )
    return service, worker


def _body(content: bytes) -> dict[str, object]:
    return {
        "source_name": "guide.txt",
        "collection_id": "collection-a",
        "media_type_hint": "text/plain",
        "expected_size": len(content),
        "expected_sha256": hashlib.sha256(content).hexdigest(),
        "storage_mode": "managed_copy",
        "purposes": ["knowledge_base"],
        "access_descriptor_ref": "acl-1",
        "retention_policy_version": "policy-v1",
    }


def test_production_gateway_requires_auth_and_contributor_role() -> None:
    service, worker = _stack()
    app = build_app(authenticator=_authenticator(), service=service, worker=worker)
    client = TestClient(app)

    assert client.get("/ingestion/capabilities").status_code == 401
    response = client.post(
        "/ingestion/uploads",
        headers={"authorization": "Bearer reader"},
        json=_body(b"text"),
    )
    assert response.status_code == 403


def test_dev_direct_upload_complete_process_versions_and_delete(monkeypatch) -> None:
    monkeypatch.setenv("FDAI_INGESTION_GATEWAY_DEV_MODE", "1")
    service, worker = _stack()
    app = build_app(
        authenticator=_authenticator(),
        service=service,
        worker=worker,
        config=IngestionGatewayConfig(
            dev_mode=True,
            direct_upload=True,
            cors_allow_origins=("http://localhost:5173",),
        ),
    )
    client = TestClient(app)
    content = b"line one\nline two"

    capabilities = client.get("/ingestion/capabilities")
    assert capabilities.status_code == 200
    assert capabilities.json()["direct_upload"] is True
    created = client.post("/ingestion/uploads", json=_body(content))
    assert created.status_code == 201
    payload = created.json()
    upload_id = payload["session"]["upload_id"]
    document_id = payload["session"]["document_id"]
    version_id = payload["session"]["version_id"]
    assert payload["upload"]["target"].endswith(f"/{upload_id}/content")

    resumed = client.post(f"/ingestion/uploads/{upload_id}/resume")
    assert resumed.status_code == 200
    assert client.put(f"/ingestion/uploads/{upload_id}/content", content=content).status_code == 204
    assert client.post(f"/ingestion/uploads/{upload_id}/complete").status_code == 202
    ready = asyncio.run(worker.process(UUID(upload_id)))
    assert ready.state.value == "ready"

    status = client.get(f"/ingestion/uploads/{upload_id}")
    assert status.json()["state"] == "ready"
    versions = client.get(f"/documents/{document_id}/versions")
    assert versions.status_code == 200
    assert versions.json()["items"][0]["available"] is True
    deleted = client.delete(f"/documents/{document_id}/versions/{version_id}")
    assert deleted.status_code == 202
    assert deleted.json()["state"] == "deleted"

    preflight = client.options(
        "/ingestion/uploads",
        headers={
            "origin": "http://localhost:5173",
            "access-control-request-method": "POST",
        },
    )
    assert preflight.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_direct_upload_route_is_hidden_outside_dev() -> None:
    service, worker = _stack()
    app = build_app(authenticator=_authenticator(), service=service, worker=worker)
    response = TestClient(app).put(
        "/ingestion/uploads/00000000-0000-0000-0000-000000000000/content",
        headers={"authorization": "Bearer contributor"},
        content=b"content",
    )
    assert response.status_code == 404


@pytest.mark.parametrize(
    "config",
    [
        IngestionGatewayConfig(dev_mode=True),
        IngestionGatewayConfig(direct_upload=True),
        IngestionGatewayConfig(cors_allow_origins=("*",)),
    ],
)
def test_unsafe_boundary_configuration_is_rejected(monkeypatch, config) -> None:
    monkeypatch.delenv("FDAI_INGESTION_GATEWAY_DEV_MODE", raising=False)
    service, worker = _stack()
    with pytest.raises(ValueError):
        build_app(authenticator=_authenticator(), service=service, worker=worker, config=config)


def test_dev_mode_is_rejected_in_production(monkeypatch) -> None:
    monkeypatch.setenv("FDAI_INGESTION_GATEWAY_DEV_MODE", "1")
    monkeypatch.setenv("RUNTIME_ENV", "prod")
    service, worker = _stack()
    with pytest.raises(ValueError, match="prohibited"):
        build_app(
            authenticator=_authenticator(),
            service=service,
            worker=worker,
            config=IngestionGatewayConfig(dev_mode=True),
        )
