"""Synthetic facade tests, not PostgreSQL concurrency or worker-activation evidence."""

from __future__ import annotations

import importlib.util
import json
import socket
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any, NoReturn, cast
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fdai_ingestion_api_service.access import ClaimsDocumentAccessProvider
from fdai_ingestion_api_service.auth import Authenticator, GroupMapping, Role
from fdai_ingestion_api_service.cloud_knowledge.collector import (
    CloudDocumentCollector,
    SourceResponse,
    SourceState,
)
from fdai_ingestion_api_service.cloud_knowledge.scheduler import CloudKnowledgeScheduler
from fdai_ingestion_api_service.cloud_knowledge.service import CloudKnowledgeService
from fdai_ingestion_api_service.cloud_knowledge.store import (
    PostgresCloudKnowledgeStore,
    SourceCheckpoint,
)
from fdai_ingestion_api_service.http import build_app
from fdai_ingestion_api_service.ingestion import DocumentIngestionService
from fdai_service_contracts import (
    DocumentAccessDeniedError,
    DocumentIndexState,
    DocumentPurpose,
    DocumentState,
    DocumentVersion,
    UploadSession,
)
from fdai_service_contracts import cloud_knowledge as cloud
from fdai_service_contracts import cloud_knowledge_package as package
from fdai_service_contracts import cloud_knowledge_release as release
from starlette.testclient import TestClient

NOW = datetime(2026, 9, 14, 12, tzinfo=UTC)
WRITERS = frozenset({"role:Contributor"})
KEY_ID = "synthetic-release-key"
COLLECTION = "reference"
BASE = "/ingestion/cloud-knowledge"


def _deny_io(*_args: object, **_kwargs: object) -> NoReturn:
    raise AssertionError("external I/O is forbidden in these synthetic tests")


class _OfflineTransport:
    async def fetch(
        self, source: cloud.CloudKnowledgeSource, *, etag: str | None
    ) -> SourceResponse:
        _deny_io()


class _MemoryReleases:
    """Test-only immutable reservations; deliberately no database or activation implementation."""

    def __init__(self) -> None:
        self.checkpoints: dict[tuple[str, str], SourceCheckpoint] = {}
        self.releases: dict[tuple[str, int], tuple[str, UUID, dict[str, object]]] = {}
        self.reservations = 0

    async def get(self, registry_digest: str, source_id: str) -> SourceCheckpoint:
        key = registry_digest, source_id
        return self.checkpoints.get(key, SourceCheckpoint(0, SourceState()))

    async def claim(self, registry_digest: str, source_id: str, revision: int) -> UUID | None:
        _deny_io()

    async def finish(self, *_args: object, **_kwargs: object) -> None:
        _deny_io()

    async def next_sequence(self, collection_id: str) -> int:
        return max((seq for owner, seq in self.releases if owner == collection_id), default=0) + 1

    async def reserve_release(
        self, *, collection_id: str, sequence: int, digest: str, upload_id: UUID, payload: str
    ) -> dict[str, object]:
        self.reservations += 1
        key = (collection_id, sequence)
        if key in self.releases:
            previous_digest, previous_upload, record = self.releases[key]
            if previous_digest != digest:
                raise ValueError("knowledge sequence already names different content")
            assert previous_upload == upload_id
            return dict(record)
        if sequence < await self.next_sequence(collection_id):
            raise ValueError("knowledge release replay is not permitted")
        record = cast(dict[str, object], json.loads(payload))
        self.releases[key] = (digest, upload_id, record)
        return dict(record)


def _load_helpers(path: Path) -> ModuleType:
    """Load only checkout-owned test helpers, without depending on pytest's import aliases."""
    spec = importlib.util.spec_from_file_location(f"_intake_fixture_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_PACKAGE_HELPERS = _load_helpers(
    Path(__file__).parents[3] / "packages/service-contracts/tests/test_cloud_knowledge_package.py"
)
package_case = _PACKAGE_HELPERS.case  # Reuse the actual pinned, synthetic signing fixture.
_BEHAVIOR_HELPERS = _load_helpers(Path(__file__).with_name("test_ingestion_service_behavior.py"))


@dataclass
class _Case:
    service: CloudKnowledgeService
    ingestion: DocumentIngestionService
    store: _MemoryReleases
    metadata: Any  # Existing MemoryMetadata, loaded from its test file.
    objects: Any  # Existing MemoryObjects; no production object-store fallback.
    manifest: release.KnowledgeTextReleaseManifest
    key: Ed25519PrivateKey = field(repr=False)
    clock: Mock

    def sealed(self, *, sequence: int = 1, suffix: str = "") -> bytes:
        manifest = self.manifest.model_copy(
            update={"sequence": sequence, "release_id": f"release-{sequence}{suffix}"}
        )
        return package.sign_release(manifest, key_id=KEY_ID, private_key=self.key)

    async def ingest(self, *, sequence: int = 1, actor_id: str = "actor-a") -> DocumentVersion:
        result = await self.service.import_package(
            self.sealed(sequence=sequence), actor_id=actor_id, actor_groups=WRITERS
        )
        assert result["status"] == "ingestion_requested" and result["approval_required"] is True
        session = UploadSession.model_validate(result["session"])
        return DocumentVersion.model_validate(
            self.metadata.versions[(session.document_id, session.version_id)]
        )


@pytest.fixture
def intake(package_case: Any, monkeypatch: pytest.MonkeyPatch) -> _Case:
    for target, name in (
        (socket, "getaddrinfo"),
        (socket.socket, "connect"),
        (socket.socket, "connect_ex"),
        (socket, "create_connection"),
    ):
        monkeypatch.setattr(target, name, _deny_io)
    helpers = _BEHAVIOR_HELPERS
    metadata, objects = helpers.MemoryMetadata(), helpers.MemoryObjects()
    store, clock = _MemoryReleases(), Mock(return_value=NOW)
    objects.put_stream = AsyncMock(wraps=objects.put_stream)
    registry = package_case.registry.model_copy(
        update={"sources": package_case.registry.sources[:2]}
    )
    manifest = package_case.manifest.model_copy(update={"registry_digest": registry.digest})
    capabilities = helpers._lifecycle_service(metadata, objects, now=NOW).capabilities
    ingestion = DocumentIngestionService(
        access=ClaimsDocumentAccessProvider(),
        metadata=metadata,
        objects=objects,
        clock=clock,
        id_factory=Mock(return_value=UUID(int=1)),
        capabilities=capabilities.model_copy(update={"max_file_size": 1024 * 1024}),
    )
    scheduler = CloudKnowledgeScheduler(
        registry=registry,
        store=store,
        clock=clock,
        collector=CloudDocumentCollector(_OfflineTransport(), collector_id="synthetic-collector"),
    )
    service = CloudKnowledgeService(
        registry=registry,
        trust=package_case.trust,
        store=cast(PostgresCloudKnowledgeStore, store),
        scheduler=scheduler,
        ingestion=ingestion,
        clock=clock,
        reader_groups=("role:Reader",),
        retention_policy="test",
    )
    key = package_case.private_key
    return _Case(service, ingestion, store, metadata, objects, manifest, key, clock)


async def _seed_retained_fixture(
    intake: _Case, *, version: DocumentVersion | None = None
) -> DocumentVersion:
    """Install a READY read fixture only; this does not simulate or prove worker activation."""
    if version is None:
        version = await intake.ingest()
    retained = DocumentVersion.model_validate(
        version.model_dump()
        | {"state": "ready", "active": True, "available": True, "index_state": "active"}
    )
    intake.metadata.versions[(version.document_id, version.version_id)] = retained
    session = intake.metadata.uploads[version.upload_id]
    intake.metadata.uploads[version.upload_id] = session.model_copy(
        update={"state": DocumentState.READY, "index_state": DocumentIndexState.ACTIVE}
    )
    intake.clock.return_value += timedelta(minutes=1)
    return retained


def _client(intake: _Case, role: Role) -> TestClient:
    def claims(_token: str) -> dict[str, object]:
        return {"oid": "actor-a", "roles": [role.value]}

    app = build_app(
        authenticator=Authenticator(claims, GroupMapping("r", "c", "a", "o", "b")),
        service=intake.ingestion,
        cloud_knowledge=intake.service,
        deletion=_BEHAVIOR_HELPERS.NoDeletion(),
    )
    return TestClient(app, headers={"Authorization": "Bearer synthetic"})


def _seed_sources(intake: _Case, count: int = 2) -> None:
    for source in intake.service.registry.sources[:count]:
        document = _PACKAGE_HELPERS._collected_document(source)
        intake.store.checkpoints[(intake.manifest.registry_digest, document.evidence.source_id)] = (
            SourceCheckpoint(
                1, SourceState(document=document, last_attempt=document.evidence.check)
            )
        )


async def test_expired_policy_keeps_history_but_never_labels_body_available(intake: _Case) -> None:
    version = await _seed_retained_fixture(intake)
    intake.clock.return_value = intake.service.registry.valid_until
    response = _client(intake, Role.OWNER).get(BASE)
    assert response.status_code == 200
    data = response.json()
    assert data["available"] is True
    assert data["policy_current"] is False
    assert data["can_import"] is data["can_refresh"] is False
    stored = data["collections"][0]["versions"][0]
    assert stored["version_id"] == str(version.version_id)
    assert stored["available"] is False
    assert all(item["freshness"] == "unknown" for item in data["sources"])


async def test_signed_offline_import_is_received_and_replay_idempotent(intake: _Case) -> None:
    assert await intake.service.refresh() == {"checked": 0, "failed": 0, "status": "complete"}
    version = await intake.ingest()
    assert version.state is DocumentState.RECEIVED
    assert not version.active and not version.available
    assert version.index_state is DocumentIndexState.NOT_REQUESTED
    assert version.purposes == (DocumentPurpose.KNOWLEDGE_BASE, DocumentPurpose.CLOUD_REFERENCE)
    assert version.cloud_knowledge is not None
    assert version.cloud_knowledge.verified_key_id == KEY_ID
    assert version.cloud_knowledge.intake_origin == "package"
    assert version.cloud_knowledge.sources == tuple(
        doc.evidence for doc in intake.manifest.documents
    )
    session = intake.metadata.uploads[version.upload_id]
    assert session.state is DocumentState.RECEIVED
    assert intake.objects.content[session.object_key] == cloud.canonical_bytes(intake.manifest)
    actions = [event.payload["action"] for event in intake.metadata.events]
    assert actions == ["upload.created", "document.received"]
    assert all(event.created_at == NOW for event in intake.metadata.events)
    events = tuple(intake.metadata.events)
    intake.clock.return_value += timedelta(minutes=1)
    assert await intake.ingest() == version
    assert len(intake.metadata.uploads) == len(intake.store.releases) == 1
    assert tuple(intake.metadata.events) == events
    intake.objects.put_stream.assert_awaited_once()


@pytest.mark.parametrize("defect", ["binding", "cloud_reference", "knowledge_base", "digest"])
async def test_cloud_reference_requires_bound_knowledge_base_purpose(
    intake: _Case, defect: str
) -> None:
    version = await intake.ingest()
    values = version.model_dump()
    if defect == "binding":
        values["cloud_knowledge"] = None
    elif defect == "digest":
        values["source_sha256"] = cloud.content_digest(b"different synthetic manifest")
    else:
        values["purposes"] = tuple(
            purpose for purpose in version.purposes if purpose.value != defect
        )
    with pytest.raises(ValueError, match="cloud reference"):
        DocumentVersion.model_validate(values)


@pytest.mark.parametrize("fault", ["sequence_digest", "different_actor", "unauthorized_role"])
async def test_rejected_intakes_never_upload_or_change_reserved_content(
    intake: _Case, fault: str
) -> None:
    await intake.ingest()
    before = dict(intake.store.releases)
    conflict = fault == "sequence_digest"
    unauthorized = fault == "unauthorized_role"
    error = ValueError if conflict else DocumentAccessDeniedError
    with pytest.raises(error, match="different content|different requester|contributor"):
        await intake.service.import_package(
            intake.sealed(suffix="-collision" if conflict else ""),
            actor_id="actor-b" if fault == "different_actor" else "actor-a",
            actor_groups=frozenset({"role:Reader"}) if unauthorized else WRITERS,
        )
    assert intake.store.releases == before
    assert len(intake.metadata.uploads) == len(intake.store.releases) == 1
    assert intake.store.reservations == (1 if unauthorized else 2)
    intake.objects.put_stream.assert_awaited_once()


async def test_unauthorized_replacement_cannot_reserve(intake: _Case) -> None:
    await _seed_retained_fixture(intake)
    with pytest.raises(DocumentAccessDeniedError, match="delete access"):
        await intake.ingest(sequence=2, actor_id="actor-b")
    # Regression: authorize the existing-document replacement before reserving its sequence.
    assert intake.store.reservations == 1 and len(intake.store.releases) == 1
    intake.objects.put_stream.assert_awaited_once()


@pytest.mark.parametrize("count", [1, 2])
@pytest.mark.parametrize("structured", [False, True])
async def test_stage_collected_requires_full_scope_without_fake_signature(
    intake: _Case, count: int, structured: bool
) -> None:
    _seed_sources(intake, count)
    if structured:
        from fdai_service_contracts.cloud_knowledge_structure import (
            CloudArticleBlock,
            CloudStructuredDocument,
        )

        intake.service._structured = True
        for key, checkpoint in tuple(intake.store.checkpoints.items()):
            document = checkpoint.state.document
            assert document is not None
            derived = CloudStructuredDocument(
                evidence=document.evidence,
                title=document.title,
                text=document.text,
                derived_at=NOW,
                blocks=(
                    CloudArticleBlock(
                        block_id="body", kind="paragraph", start=0, end=len(document.text)
                    ),
                ),
            )
            intake.store.checkpoints[key] = SourceCheckpoint(
                checkpoint.revision,
                checkpoint.state.model_copy(update={"structured_document": derived}),
            )
    if count == 1:
        with pytest.raises(ValueError, match="complete successful source coverage"):
            await intake.service.stage_collected(
                collection_id=COLLECTION, actor_id="actor-a", actor_groups=WRITERS
            )
        assert intake.store.reservations == 0 and not intake.metadata.uploads
        return
    result = await intake.service.stage_collected(
        collection_id=COLLECTION, actor_id="actor-a", actor_groups=WRITERS
    )
    binding = release.KnowledgeReleaseBinding.model_validate(result["release"])
    assert binding.intake_origin == "collector" and binding.verified_key_id == "connected-collector"
    assert len(binding.sources) == 2 and result["approval_required"] is True
    session = UploadSession.model_validate(result["session"])
    assert session.state is DocumentState.RECEIVED
    content = intake.objects.content[session.object_key]
    assert b'"original_text"' not in content and b"Original reference:" not in content
    assert json.loads(content)["schema_version"] == (
        "fdai.cloud-knowledge.v3" if structured else "fdai.cloud-knowledge.v2"
    )
    assert all(not version.active for version in intake.metadata.versions.values())
    if structured:
        assert len(binding.processing_digests) == 2
        received = intake.metadata.versions[(session.document_id, session.version_id)]
        retained = await _seed_retained_fixture(intake, version=received)
        rollback = await intake.service.rollback(
            collection_id=COLLECTION,
            version_id=retained.version_id,
            actor_id="actor-a",
            actor_groups=frozenset({"role:Owner"}),
        )
        rolled = release.KnowledgeReleaseBinding.model_validate(rollback["release"])
        assert rolled.sequence > binding.sequence
        assert rolled.sources == binding.sources
        assert rolled.processing_digests == binding.processing_digests
        assert rolled.admission_expires_at == binding.admission_expires_at
        assert UploadSession.model_validate(rollback["session"]).state is DocumentState.RECEIVED
    assert all(
        checkpoint.state.document.original_text for checkpoint in intake.store.checkpoints.values()
    )


async def test_status_keeps_active_dates_when_newer_version_is_pending(intake: _Case) -> None:
    active = await _seed_retained_fixture(intake)
    pending = await intake.ingest(sequence=2)
    latest = await intake.ingestion.list_documents(
        actor_id="actor-a", actor_groups=WRITERS, collection_id=COLLECTION, limit=1
    )
    assert latest == (pending,)
    status = await intake.service.status(actor_id="actor-a", actor_groups=WRITERS)
    collections = cast(list[dict[str, Any]], status["collections"])
    assert {row["version_id"] for row in collections[0]["versions"]} == {
        str(active.version_id),
        str(pending.version_id),
    }
    rows = cast(list[dict[str, object]], status["sources"])
    assert rows[0]["collected_at"] == intake.manifest.documents[0].evidence.collected_at.isoformat()
    assert (
        rows[0]["checked_at"] == intake.manifest.documents[0].evidence.check.checked_at.isoformat()
    )
    assert status["automatic_activation"] is False and status["approval_required"] is True


async def test_rollback_uses_higher_sequence_without_renewing_source_dates(intake: _Case) -> None:
    retained = await _seed_retained_fixture(intake)
    await intake.ingest(sequence=2)
    result = await intake.service.rollback(
        collection_id=COLLECTION,
        version_id=retained.version_id,
        actor_id="actor-a",
        actor_groups=frozenset({"role:Owner"}),
    )
    binding = release.KnowledgeReleaseBinding.model_validate(result["release"])
    assert retained.cloud_knowledge is not None
    assert binding.sequence == 3 and binding.intake_origin == "rollback"
    assert binding.rollback_of == retained.cloud_knowledge.release_id
    assert binding.rollback_source_digest == retained.cloud_knowledge.manifest_digest
    assert binding.sources == retained.cloud_knowledge.sources
    assert binding.package_created_at == binding.imported_at == intake.clock.return_value
    assert binding.admission_expires_at == retained.cloud_knowledge.admission_expires_at
    assert UploadSession.model_validate(result["session"]).state is DocumentState.RECEIVED
    assert intake.metadata.versions[(retained.document_id, retained.version_id)] == retained


async def test_legacy_intake_keeps_exact_bytes_but_rollback_emits_only_text(
    intake: _Case, package_case: Any
) -> None:
    case = _PACKAGE_HELPERS._with_registry(package_case, intake.service.registry)
    legacy = _PACKAGE_HELPERS._legacy_manifest(case)
    result = await intake.service.import_package(
        _PACKAGE_HELPERS._legacy_package(case), actor_id="actor-a", actor_groups=WRITERS
    )
    original_session = UploadSession.model_validate(result["session"])
    original_content = intake.objects.content[original_session.object_key]
    assert original_content == cloud.canonical_bytes(legacy)
    version = DocumentVersion.model_validate(
        intake.metadata.versions[(original_session.document_id, original_session.version_id)]
    )
    retained = await _seed_retained_fixture(intake, version=version)
    rollback = await intake.service.rollback(
        collection_id=COLLECTION,
        version_id=retained.version_id,
        actor_id="actor-a",
        actor_groups=frozenset({"role:Owner"}),
    )
    binding = release.KnowledgeReleaseBinding.model_validate(rollback["release"])
    session = UploadSession.model_validate(rollback["session"])
    content = intake.objects.content[session.object_key]
    compact = release.KnowledgeTextReleaseManifest.model_validate_json(content)
    assert b'"original_text"' not in content and b"Original reference:" not in content
    assert binding.rollback_source_digest == legacy.digest != compact.digest
    assert binding.sequence == 2 and binding.intake_origin == "rollback"
    assert binding.sources == retained.cloud_knowledge.sources
    assert binding.admission_expires_at == retained.cloud_knowledge.admission_expires_at
    assert all(
        new.text == old.text for new, old in zip(compact.documents, legacy.documents, strict=True)
    )
    assert intake.objects.content[original_session.object_key] == original_content
    assert not intake.metadata.versions[(session.document_id, session.version_id)].available


@pytest.mark.parametrize("role", [Role.READER, Role.CONTRIBUTOR, Role.APPROVER, Role.OWNER])
def test_http_permission_flags_and_offline_inspection(
    intake: _Case, role: Role, monkeypatch: pytest.MonkeyPatch
) -> None:
    importer = AsyncMock(side_effect=AssertionError("inspection must not import"))
    monkeypatch.setattr(intake.service, "import_package", importer)
    with _client(intake, role) as client:
        status = client.get(BASE)
        assert status.status_code == 200
        assert status.json()["can_refresh"] is (role is Role.OWNER)
        assert status.json()["can_import"] is (role is not Role.READER)
        inspected = client.post(f"{BASE}/packages/inspect", content=intake.sealed())
        assert inspected.status_code == (403 if role is Role.READER else 200)
        if role is not Role.READER:
            assert inspected.json()["status"] == "verified_candidate"
            assert inspected.json()["approval_required"] is True
    importer.assert_not_called()
    assert (
        intake.store.reservations == 0 and not intake.metadata.events and not intake.objects.content
    )


def test_export_is_inert_and_has_safe_content_headers(intake: _Case) -> None:
    _seed_sources(intake)
    with _client(intake, Role.OWNER) as client:
        response = client.post(f"{BASE}/{COLLECTION}/export")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-disposition"].startswith("attachment;")
    assert set(response.headers) == {
        "cache-control",
        "content-disposition",
        "content-length",
        "content-type",
        "x-content-type-options",
    }
    manifest = release.KnowledgeTextReleaseManifest.model_validate_json(response.content)
    assert manifest.documents == intake.manifest.documents
    assert b'"original_text"' not in response.content
    assert b"Original reference:" not in response.content
    assert not {"private_key", "public_key", "signature", "trust"}.intersection(response.json())
    assert intake.store.reservations == 0 and not intake.metadata.uploads
