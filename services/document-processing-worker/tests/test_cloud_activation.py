"""Post-decision cloud activation through the real worker and bounded extractor.

The reused memory store enforces lifecycle CAS and records its outbox/effect journal.
The controlled verifier proves orchestration only, not PostgreSQL chunk/digest
verification, durable lease acquisition, agent approval, or production identity.
No agent is imported or called, and no model or live transport is bound.
"""

from __future__ import annotations

import asyncio
import importlib.util
import socket
import sys
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from types import ModuleType
from typing import Any, NoReturn, cast
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fdai_document_worker_service.adapters.cloud_knowledge import CloudReferenceGuard
from fdai_document_worker_service.adapters.processing import (
    BoundedDocumentExtractor,
    ClamAvMalwareScanner,
    ClamAvScannerConfig,
    SignatureProtectionInspector,
    UnavailableImageOcr,
)
from fdai_document_worker_service.cloud_activation import CloudIndexVerifier
from fdai_document_worker_service.effects import (
    WorkerEffect,
    WorkerEffectKind,
    WorkerEffectStatus,
    worker_effect_id,
)
from fdai_document_worker_service.processing import DocumentIngestionWorker
from fdai_service_contracts import (
    DocumentEnvelope,
    DocumentIndexState,
    DocumentLifecycleConflictError,
    DocumentState,
    DocumentVersion,
    DocumentWorkerClaim,
    SourceStorageMode,
    UploadSession,
)
from fdai_service_contracts.cloud_knowledge import (
    CloudKnowledgeSource,
    Freshness,
    SourceRegistryRevision,
    canonical_bytes,
    content_digest,
)
from fdai_service_contracts.cloud_knowledge_package import KnowledgeTrustedKey, KnowledgeTrustPolicy


def _load_helpers(filename: str) -> ModuleType:
    """Load service-owned fixtures without relying on pytest's module aliases."""
    path = Path(__file__).with_name(filename)
    spec = importlib.util.spec_from_file_location(f"_cloud_activation_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_LIFECYCLE = _load_helpers("test_artifact_index_lifecycle.py")
_RELEASE = _load_helpers("test_cloud_knowledge_extraction.py")
NOW = _RELEASE.NOW
OBSERVED_DIGEST = content_digest(b"synthetic orchestration-only index observation")


@pytest.fixture(autouse=True)
def _no_external_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Retain attempts so a fail-closed worker cannot hide unexpected external I/O."""
    attempts: list[str] = []

    def deny(*_args: object, **_kwargs: object) -> NoReturn:
        attempts.append("network")
        raise AssertionError("activation tests must not use external sockets or DNS")

    for name in (
        "getaddrinfo",
        "gethostbyname",
        "gethostbyname_ex",
        "gethostbyaddr",
        "getnameinfo",
        "create_connection",
    ):
        monkeypatch.setattr(socket, name, deny)
    for name in ("connect", "connect_ex", "sendto", "sendmsg"):
        monkeypatch.setattr(socket.socket, name, deny)
    yield
    assert attempts == []


class _RecordingExtractor(BoundedDocumentExtractor):
    """Count source reads while preserving the production extraction and lineage path."""

    def __init__(self) -> None:
        super().__init__(
            image_ocr=UnavailableImageOcr(), max_input_bytes=16 * 1024, max_characters=16 * 1024
        )
        self.states: list[DocumentState] = []

    async def extract(
        self, *, version: DocumentVersion, chunks: AsyncIterator[bytes]
    ) -> DocumentEnvelope:
        self.states.append(version.state)
        return await super().extract(version=version, chunks=chunks)


class _RecordingIndex(_LIFECYCLE.RecordingIndex):
    """Reuse the controlled index fixture; record builds without pretending to be PostgreSQL."""

    def __init__(self, order: list[str]) -> None:
        super().__init__(order)
        self.committed: list[DocumentEnvelope] = []

    async def commit(self, envelope: DocumentEnvelope) -> int:
        self.committed.append(envelope)
        return await super().commit(envelope)

    async def activate(self, _document_id: UUID, _version_id: UUID) -> None:
        raise AssertionError("cloud availability must use the verified metadata CAS")


class _ControlledVerifier:
    """Orchestrator-only readback proof; real PostgreSQL exact-row/digest proof is separate.

    This separate observer can pause or reject, but never writes metadata, builds an
    index, calls a model, or grants approval. Its digest is explicitly synthetic.
    """

    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.allow_return = asyncio.Event()
        self.reject = False
        self.calls: list[tuple[DocumentVersion, DocumentEnvelope]] = []

    async def verify(self, version: DocumentVersion, envelope: DocumentEnvelope) -> str:
        self.calls.append((version, envelope))
        self.entered.set()
        await self.allow_return.wait()
        if self.reject:
            raise ValueError("synthetic independent readback rejected")
        return OBSERVED_DIGEST


@dataclass
class _Runtime:
    metadata: Any  # Existing FailOnceEffectCompletionMetadata retains its real test CAS checks.
    objects: Any  # Existing MemoryObjects, populated only with the sealed synthetic release.
    artifacts: Any  # Existing RecordingArtifacts; never a production storage fallback.
    index: _RecordingIndex
    extractor: _RecordingExtractor
    malware: ClamAvMalwareScanner
    scanner_transport: AsyncMock
    guard: CloudReferenceGuard
    trust_path: Path
    claim: DocumentWorkerClaim

    def worker(self, verifier: CloudIndexVerifier | None) -> DocumentIngestionWorker:
        """Build a fresh mechanical worker over the same controlled persistent state."""
        return DocumentIngestionWorker(
            metadata=self.metadata,
            objects=self.objects,
            malware=self.malware,
            protection=SignatureProtectionInspector(max_input_bytes=16 * 1024),
            extractor=self.extractor,
            artifacts=self.artifacts,
            index=self.index,
            clock=lambda: NOW,
            indexing_stage_timeout_seconds=5,
            cloud_reference_guard=self.guard.check,
            cloud_index_verifier=verifier,
        )


def _scanner_reply(age_days: int = 0) -> str:
    timestamp = (NOW - timedelta(days=age_days)).astimezone().strftime("%a %b %d %H:%M:%S %Y")
    return f"ClamAV 1.4/12345/{timestamp}\0"


@pytest.fixture
def runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _Runtime:
    """Bind the sealed two-unit fixture to temporary policies and a frozen scanner transport."""
    manifest, original = _RELEASE.release_version()
    source = manifest.documents[0].evidence
    registry = SourceRegistryRevision(
        revision=1,
        approved_by="synthetic-source-reviewer",
        valid_until=NOW + timedelta(days=7),
        sources=(
            CloudKnowledgeSource(
                source_id=source.source_id,
                collection_id=manifest.collection_id,
                url=source.source_url,
                title=manifest.documents[0].title,
                applicability=source.applicability,
                policy=source.policy,
                license_ref=source.license_ref,
                storage_allowed=True,
                internal_transfer_allowed=True,
            ),
        ),
    )
    manifest = manifest.model_copy(update={"registry_digest": registry.digest})
    content = canonical_bytes(manifest)
    assert original.cloud_knowledge is not None
    binding = original.cloud_knowledge.model_copy(
        update={"registry_digest": registry.digest, "manifest_digest": manifest.digest}
    )
    version = DocumentVersion.model_validate(
        original.model_dump()
        | {
            "document_id": UUID(int=2),
            "version_id": UUID(int=3),
            "upload_id": UUID(int=1),
            "cloud_knowledge": binding,
            "source_sha256": manifest.digest,
            "size_bytes": len(content),
            "index_state": DocumentIndexState.QUEUED,
            "revision": 7,
        }
    )
    public_key = Ed25519PrivateKey.generate().public_key().public_bytes_raw().hex()
    trust = KnowledgeTrustPolicy(
        approved_by="synthetic-trust-reviewer",
        valid_from=NOW - timedelta(days=1),
        valid_until=NOW + timedelta(days=7),
        keys=(
            KnowledgeTrustedKey(
                key_id=binding.verified_key_id,
                public_key=public_key,
                valid_from=NOW - timedelta(days=1),
                valid_until=NOW + timedelta(days=7),
            ),
        ),
        revocation_checked_at=NOW,
        revocation_max_age_seconds=3600,
    )
    registry_path, trust_path = tmp_path / "registry.json", tmp_path / "trust.json"
    registry_path.write_bytes(canonical_bytes(registry))
    trust_path.write_bytes(canonical_bytes(trust))
    guard = CloudReferenceGuard(
        {
            "FDAI_CLOUD_KNOWLEDGE_REGISTRY_PATH": str(registry_path),
            "FDAI_CLOUD_KNOWLEDGE_TRUST_PATH": str(trust_path),
        }
    )
    session = UploadSession(
        upload_id=version.upload_id,
        document_id=version.document_id,
        version_id=version.version_id,
        actor_id=version.uploader_id,
        source_name=version.source_name,
        collection_id=version.access.collection_id,
        object_key="source/object",
        media_type_hint=version.media_type,
        expected_size=len(content),
        expected_sha256=version.source_sha256,
        state=version.state,
        storage_mode=SourceStorageMode.LINKED_SOURCE,
        purposes=version.purposes,
        access=version.access,
        retention=version.retention,
        created_at=NOW,
        expires_at=NOW + timedelta(hours=1),
        index_state=DocumentIndexState.QUEUED,
        revision=11,
    )
    monkeypatch.setattr(_LIFECYCLE, "NOW", NOW)
    metadata = _LIFECYCLE.FailOnceEffectCompletionMetadata(session, version)
    metadata.fail_completion = False
    order: list[str] = []
    objects = _LIFECYCLE.MemoryObjects(order)
    objects.content[session.object_key] = content
    malware = ClamAvMalwareScanner(config=ClamAvScannerConfig())
    scanner_transport = AsyncMock(return_value=_scanner_reply())
    monkeypatch.setattr(malware, "_command", scanner_transport)
    return _Runtime(
        metadata,
        objects,
        _LIFECYCLE.RecordingArtifacts(order),
        _RecordingIndex(order),
        _RecordingExtractor(),
        malware,
        scanner_transport,
        guard,
        trust_path,
        _LIFECYCLE._claim(session.upload_id),
    )


@asynccontextmanager
async def _pending_index(
    runtime: _Runtime, verifier: _ControlledVerifier
) -> AsyncIterator[asyncio.Task[DocumentVersion]]:
    """Pause at real worker readback, cancelling and draining unfinished attempts on exit."""
    worker = runtime.worker(verifier)
    task = asyncio.create_task(worker.index(runtime.claim.upload_id, lambda: runtime.claim))
    try:
        await asyncio.wait_for(verifier.entered.wait(), timeout=5)
        yield task
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def _effect(runtime: _Runtime) -> WorkerEffect:
    assert len(runtime.metadata.effects) == 1
    effect = cast(WorkerEffect, next(iter(runtime.metadata.effects.values())))
    version = runtime.metadata.version
    assert effect.kind is WorkerEffectKind.KNOWLEDGE_ACTIVATION
    assert effect.effect_id == worker_effect_id(effect.kind, version.version_id)
    assert effect.object_key == version.cloud_knowledge.manifest_digest
    assert (effect.upload_id, effect.document_id, effect.version_id) == (
        version.upload_id,
        version.document_id,
        version.version_id,
    )
    return effect


def _actions(runtime: _Runtime) -> list[str]:
    return [event.payload["action"] for event in runtime.metadata.events]


def _assert_content_free_outbox(runtime: _Runtime) -> None:
    """Mechanical facts carry references, not document bodies, approvals, or action commands."""
    forbidden = {"text", "content", "approval", "approvers", "action_type", "executor_identity"}
    events = runtime.metadata.events
    assert len({event.idempotency_key for event in events}) == len(events)
    for event in events:
        assert event.topic == "object.event"
        assert event.created_at == NOW
        assert event.payload["producer_principal"] == "Huginn"
        assert event.payload["kind"] == "document_ingestion"
        record = event.payload["record"]
        assert record["actor_id"] == "ingestion-worker"
        assert forbidden.isdisjoint(event.payload) and forbidden.isdisjoint(record)
        assert all(
            text not in event.model_dump_json()
            for text in ("Raw original", "Premium only.", "Premium v2 uses other requirements.")
        )


@pytest.mark.parametrize("fault", ["none", "verifier", "scanner_stale", "guard_revoked"])
async def test_pending_generation_requires_current_independent_readback(
    runtime: _Runtime, fault: str
) -> None:
    verifier = _ControlledVerifier()
    initial_upload_revision = runtime.metadata.session.revision
    initial_version_revision = runtime.metadata.version.revision
    async with _pending_index(runtime, verifier) as task:
        pending = runtime.metadata.version
        assert pending.state is DocumentState.READY and pending.active and not pending.available
        assert pending.index_state is DocumentIndexState.ACTIVE
        assert _actions(runtime) == ["document.indexing", "document.activation_pending"]
        assert _effect(runtime).status is WorkerEffectStatus.PENDING
        observed_version, envelope = verifier.calls[0]
        assert observed_version == pending
        assert envelope.extractor_name == "cloud-reference" and len(envelope.units) == 2
        assert envelope.units == runtime.index.committed[0].units
        assert envelope.cloud_knowledge == pending.cloud_knowledge
        assert runtime.artifacts.envelope.artifact_manifest is not None
        assert runtime.extractor.states == [DocumentState.EXTRACTING, DocumentState.READY]
        if fault == "verifier":
            verifier.reject = True
        elif fault == "scanner_stale":
            runtime.scanner_transport.return_value = _scanner_reply(age_days=7)
        elif fault == "guard_revoked":
            trust = KnowledgeTrustPolicy.model_validate_json(runtime.trust_path.read_bytes())
            revoked = trust.model_copy(update={"revoked_key_ids": (trust.keys[0].key_id,)})
            runtime.trust_path.write_bytes(canonical_bytes(revoked))
        verifier.allow_return.set()
        result = await asyncio.wait_for(task, timeout=5)

    success = fault == "none"
    assert result == runtime.metadata.version
    assert result.state is (DocumentState.READY if success else DocumentState.FAILED)
    assert result.active is success and result.available is success
    assert result.index_state is (
        DocumentIndexState.ACTIVE if success else DocumentIndexState.FAILED
    )
    assert result.failure_code == (None if success else "cloud_activation_unverified")
    assert runtime.metadata.session.state is result.state
    assert runtime.metadata.session.index_state is result.index_state
    assert result.cloud_knowledge == pending.cloud_knowledge
    assert result.cloud_knowledge is not None
    assert result.cloud_knowledge.sources[0].freshness(NOW) is Freshness.STALE
    assert _actions(runtime) == [
        "document.indexing",
        "document.activation_pending",
        "document.ready" if success else "document.failed",
    ]
    record = runtime.metadata.events[-1].payload["record"]
    assert record["cloud_verification"] == ("verified" if success else "failed")
    assert record["cloud_index_digest"] == (OBSERVED_DIGEST if success else None)
    assert [
        (event.payload["record"]["upload_revision"], event.payload["record"]["version_revision"])
        for event in runtime.metadata.events
    ] == [(initial_upload_revision + step, initial_version_revision + step) for step in (1, 2, 3)]
    assert _effect(runtime).status is WorkerEffectStatus.COMPLETED
    assert _effect(runtime).completed_at == NOW
    expected_scanner_calls = 3 if fault in {"none", "scanner_stale"} else 2
    assert runtime.scanner_transport.await_count == expected_scanner_calls
    _assert_content_free_outbox(runtime)


async def test_restart_resumes_pending_readback_without_rebuilding_or_model_use(
    runtime: _Runtime,
) -> None:
    first = _ControlledVerifier()
    async with _pending_index(runtime, first):
        pending = runtime.metadata.version
        effect_id = _effect(runtime).effect_id
        stored_artifact = runtime.artifacts.envelope
    # Cancellation models process loss after the pending CAS, not an authority decision.
    assert runtime.metadata.version == pending and not pending.available and pending.active
    assert _effect(runtime).status is WorkerEffectStatus.PENDING
    assert _actions(runtime) == ["document.indexing", "document.activation_pending"]
    runtime.claim = runtime.claim.model_copy(
        update={"owner": "restarted-worker", "attempt_id": UUID(int=5), "revision": 2}
    )
    restarted = _ControlledVerifier()
    restarted.allow_return.set()

    result = await asyncio.wait_for(
        runtime.worker(restarted).index(runtime.claim.upload_id, lambda: runtime.claim), timeout=5
    )

    assert result.state is DocumentState.READY and result.active and result.available
    assert len(restarted.calls) == 1 and restarted.calls[0][0] == pending
    assert runtime.extractor.states == [
        DocumentState.EXTRACTING,
        DocumentState.READY,
        DocumentState.READY,
    ]
    assert len(runtime.index.committed) == 1
    assert runtime.artifacts.envelope is stored_artifact
    assert result.revision == pending.revision + 1
    assert _effect(runtime).effect_id == effect_id
    assert _effect(runtime).status is WorkerEffectStatus.COMPLETED
    assert _actions(runtime) == [
        "document.indexing",
        "document.activation_pending",
        "document.ready",
    ]
    _assert_content_free_outbox(runtime)


async def test_failed_terminal_replay_completes_journal_without_republishing_success(
    runtime: _Runtime,
) -> None:
    verifier = _ControlledVerifier()
    verifier.reject = True
    verifier.allow_return.set()
    runtime.metadata.fail_completion = True
    with pytest.raises(RuntimeError, match="injected effect completion crash"):
        await runtime.worker(verifier).index(runtime.claim.upload_id, lambda: runtime.claim)
    failed = runtime.metadata.version
    assert failed.state is DocumentState.FAILED and not failed.active and not failed.available
    assert _effect(runtime).status is WorkerEffectStatus.PENDING
    events = tuple(runtime.metadata.events)
    extraction_states = tuple(runtime.extractor.states)
    scanner_calls = runtime.scanner_transport.await_count
    restarted = _ControlledVerifier()

    result = await asyncio.wait_for(
        runtime.worker(restarted).index(runtime.claim.upload_id, lambda: runtime.claim), timeout=5
    )

    assert result == failed
    assert _effect(runtime).status is WorkerEffectStatus.COMPLETED
    assert not restarted.calls
    assert tuple(runtime.extractor.states) == extraction_states
    assert runtime.scanner_transport.await_count == scanner_calls
    assert len(runtime.index.committed) == 1
    assert tuple(runtime.metadata.events) == events
    assert "document.ready" not in _actions(runtime)
    _assert_content_free_outbox(runtime)


async def test_missing_verifier_contains_pending_generation_instead_of_claiming_ready(
    runtime: _Runtime,
) -> None:
    result = await runtime.worker(None).index(runtime.claim.upload_id, lambda: runtime.claim)
    assert result.state is DocumentState.FAILED and not result.active and not result.available
    assert result.failure_code == "cloud_activation_unverified"
    assert _effect(runtime).status is WorkerEffectStatus.COMPLETED
    assert _actions(runtime) == [
        "document.indexing",
        "document.activation_pending",
        "document.failed",
    ]
    _assert_content_free_outbox(runtime)


async def test_second_cas_cannot_overwrite_a_newer_pending_revision(runtime: _Runtime) -> None:
    verifier = _ControlledVerifier()
    async with _pending_index(runtime, verifier) as task:
        # A concurrent writer changes both revisions while the observer holds its old snapshot.
        runtime.metadata.session = runtime.metadata.session.model_copy(
            update={"revision": runtime.metadata.session.revision + 1}
        )
        runtime.metadata.version = runtime.metadata.version.model_copy(
            update={"revision": runtime.metadata.version.revision + 1}
        )
        concurrent = runtime.metadata.version
        verifier.allow_return.set()
        with pytest.raises(DocumentLifecycleConflictError, match="test CAS conflict"):
            await asyncio.wait_for(task, timeout=5)
    assert runtime.metadata.version == concurrent and not concurrent.available
    assert _effect(runtime).status is WorkerEffectStatus.PENDING
    assert _actions(runtime) == ["document.indexing", "document.activation_pending"]
    _assert_content_free_outbox(runtime)
