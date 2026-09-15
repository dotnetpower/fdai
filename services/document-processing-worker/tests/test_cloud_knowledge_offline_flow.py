"""Synthetic in-process control-flow drill, not production trust or air-gap evidence.

Real package verification, pantheon decisions, worker extraction, and Core rendering
use test stores and a fake clean scanner transport. Fixture handoffs and synthetic
stage claims do not prove PostgreSQL, durable leases, service roles, broker delivery,
or OS isolation. The controlled readback digest is not a persisted-index receipt;
search/access fixtures do not prove ranking, authentication, or citation HTTP delivery.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from collections.abc import AsyncIterator, Iterator
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.forseti import Forseti
from fdai.agents.heimdall import Heimdall
from fdai.agents.muninn import Muninn
from fdai.agents.saga import Saga
from fdai.agents.thor import Thor
from fdai.agents.var import Var
from fdai.core.knowledge.governed_document_reader import (
    AuthorizedGovernedDocumentReader,
    RoleScopedDocumentScopeResolver,
)
from fdai.shared.contracts import DocumentVersion as CoreDocumentVersion
from fdai.shared.contracts.models import CeilingRole
from fdai.shared.providers.knowledge import KnowledgeChunk
from fdai_core_service.semantic_turn_processor import _render_governed_document_answer
from fdai_document_worker_service.adapters.cloud_knowledge import CloudReferenceGuard
from fdai_document_worker_service.adapters.processing import (
    ClamAvMalwareScanner,
    ClamAvScannerConfig,
)
from fdai_document_worker_service.effects import WorkerEffectStatus
from fdai_service_contracts import (
    DocumentEnvelope,
    DocumentIndexState,
    DocumentState,
    DocumentVersion,
    DocumentWorkerIndexCommand,
    DocumentWorkerStage,
    MalwareVerdict,
    ProtectionState,
    UploadSession,
)
from fdai_service_contracts import cloud_knowledge as cloud
from fdai_service_contracts.cloud_knowledge_release import KnowledgeReleaseBinding


def _load(path: Path) -> ModuleType:
    """Reuse checkout-owned fixtures, never execute their test functions."""
    spec = importlib.util.spec_from_file_location(f"_offline_flow_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_SERVICES = Path(__file__).resolve().parents[3] / "services"
_INTAKE = _load(_SERVICES / "document-ingestion-api/tests/test_cloud_knowledge_intake.py")
_ACTIVATION = _load(Path(__file__).with_name("test_cloud_activation.py"))
_READER = _load(
    _SERVICES / "core-control-plane/tests/core/knowledge/test_governed_document_reader.py"
)
_DATES = _load(_SERVICES / "core-control-plane/tests/core/knowledge/test_cloud_reference.py")
package_case = _INTAKE.package_case
intake = _INTAKE.intake
NOW = _INTAKE.NOW
REVIEWER = "reviewer@example.com"


@pytest.fixture(autouse=True)
def _denied_network(intake: Any, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Reuse the counting DNS/socket deny after intake; its teardown requires zero attempts."""
    assert intake.clock.return_value == NOW
    yield from _ACTIVATION._no_external_network.__wrapped__(monkeypatch)


def _pantheon() -> tuple[InMemoryBus, Var, Thor]:
    bus = InMemoryBus(registry=load_pantheon(), handler_timeout=5)
    heimdall = Heimdall(bus=bus, clock=lambda: NOW.timestamp())
    forseti, saga, muninn = Forseti(bus=bus), Saga(), Muninn()
    saga.bind_bus(bus)
    muninn.bind_bus(bus)
    # Synthetic reviewer membership, not production identity or an approval replacement.
    var = Var(
        bus=bus,
        approver_authorizer=lambda actor, action: (
            actor == REVIEWER and action == "document.promote-authoritative"
        ),
    )
    thor = Thor(bus=bus)
    for topic, agents in {
        "object.event": (heimdall, forseti),
        "object.anomaly": (forseti,),
        "object.verdict": (saga, thor),
        "object.audit-entry": (var, muninn),
        "object.approval": (saga, thor),
    }.items():
        for agent in agents:
            bus.subscribe(topic, agent.spec.name, agent.on_typed_message)
    return bus, var, thor


def _runtime(
    intake: Any,
    session: UploadSession,
    version: DocumentVersion,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Any:
    """Hand off actual RECEIVED records; only subsequent worker CAS may advance them."""
    lifecycle = _ACTIVATION._LIFECYCLE
    monkeypatch.setattr(lifecycle, "NOW", NOW)
    monkeypatch.setattr(_ACTIVATION, "NOW", NOW)
    # One-time test-store handoff, not a claim about cross-service persistence/replication.
    metadata = lifecycle.MemoryMetadata(session, version)
    registry_path, trust_path = tmp_path / "registry.json", tmp_path / "trust.json"
    registry_path.write_bytes(cloud.canonical_bytes(intake.service.registry))
    trust_path.write_bytes(cloud.canonical_bytes(intake.service.trust))
    guard = CloudReferenceGuard(
        {
            "FDAI_CLOUD_KNOWLEDGE_REGISTRY_PATH": str(registry_path),
            "FDAI_CLOUD_KNOWLEDGE_TRUST_PATH": str(trust_path),
        }
    )
    malware = ClamAvMalwareScanner(config=ClamAvScannerConfig())

    async def clean_scan(chunks: AsyncIterator[bytes]) -> MalwareVerdict:
        assert (
            b"".join([chunk async for chunk in chunks])
            == intake.objects.content[session.object_key]
        )
        return MalwareVerdict.CLEAN

    # Only scanner transport is faked; freshness parsing, protection, and extraction stay real.
    monkeypatch.setattr(malware, "_scan", AsyncMock(side_effect=clean_scan))
    scanner_transport = AsyncMock(return_value=_ACTIVATION._scanner_reply())
    monkeypatch.setattr(malware, "_command", scanner_transport)
    order: list[str] = []
    return _ACTIVATION._Runtime(
        metadata=metadata,
        objects=intake.objects,
        artifacts=lifecycle.RecordingArtifacts(order),
        index=_ACTIVATION._RecordingIndex(order),
        extractor=_ACTIVATION._RecordingExtractor(),
        malware=malware,
        scanner_transport=scanner_transport,
        guard=guard,
        trust_path=trust_path,
        claim=lifecycle._claim(session.upload_id),
    )


class _BoundSources:
    """Read this fixture's sealed sources under the real guard; never invent a newer check."""

    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime

    async def resolve(
        self, binding: KnowledgeReleaseBinding, source_id: str, now: datetime
    ) -> tuple[cloud.CloudSourceEvidence, bool]:
        version = self.runtime.metadata.version
        assert binding == version.cloud_knowledge
        self.runtime.guard.check(version, now)
        return next(source for source in binding.sources if source.source_id == source_id), False


def _reader(runtime: Any) -> AuthorizedGovernedDocumentReader:
    """Project actual worker state and units into a synthetic retained-hit search snapshot."""
    version = runtime.metadata.version
    envelope: DocumentEnvelope = runtime.index.committed[0]
    assert envelope.cloud_knowledge == version.cloud_knowledge
    # Core has a narrower read contract; preserve supported fields, including actual readiness.
    projected = CoreDocumentVersion.model_validate(
        {
            name: value
            for name, value in version.model_dump(mode="json").items()
            if name in CoreDocumentVersion.model_fields
        }
    )
    hits: list[KnowledgeChunk] = []
    for unit in envelope.units:
        source = next(
            source
            for source in version.cloud_knowledge.sources
            if unit.locator.startswith(
                f"cloud:{cloud.content_digest(source.source_id.encode())[:16]}:"
            )
        )
        hit = _READER._hit(
            document_id=version.document_id,
            version_id=version.version_id,
            chunk_id=unit.unit_id,
            locator=unit.locator,
        )
        hits.append(
            replace(
                hit,
                text=unit.text,
                metadata={
                    **hit.metadata,
                    "collection_id": version.access.collection_id,
                    "access_descriptor_ref": version.access.reference,
                    "cloud_source": source.model_dump_json(),
                },
            )
        )
    return AuthorizedGovernedDocumentReader(
        search=_READER._Search(hits),
        metadata=_READER._Metadata((projected,)),
        access=_READER._Access(),
        scopes=RoleScopedDocumentScopeResolver(
            collection_id=version.access.collection_id,
            allowed_access_refs=frozenset({version.access.reference}),
        ),
        clock=lambda: NOW,
        retrieval_mode="lexical",
        cloud_reference=_BoundSources(runtime),
    )


async def _search(runtime: Any) -> Any:
    return await _reader(runtime).search(
        query="reference",
        principal_ref="reader@example.com",
        principal_role=CeilingRole.READER,
        principal_groups=frozenset({"role:Reader"}),
        purpose="operations-review",
        limit=2,
    )


@pytest.mark.parametrize("representation", ["text", "structured"])
async def test_signed_offline_package_requires_review_and_readback_before_dated_answer(
    intake: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, representation: str
) -> None:
    # Age the synthetic source BEFORE signing, never the received/READY metadata afterwards.
    intake.manifest = intake.manifest.model_copy(
        update={
            "documents": tuple(
                _INTAKE._PACKAGE_HELPERS._document(source, at=NOW - timedelta(days=44 + index))
                for index, source in enumerate(intake.service.registry.sources)
            )
        }
    )
    if representation == "structured":
        from fdai_service_contracts.cloud_knowledge_release import (
            KnowledgeStructuredReleaseManifest,
        )
        from fdai_service_contracts.cloud_knowledge_structure import (
            CloudArticleBlock,
            CloudStructuredDocument,
            excerpt_digest,
        )

        documents = tuple(
            CloudStructuredDocument(
                evidence=doc.evidence,
                title=doc.title,
                text=doc.text,
                derived_at=intake.manifest.package_created_at,
                blocks=(
                    CloudArticleBlock(
                        block_id="body",
                        kind="paragraph",
                        start=0,
                        end=len(doc.text),
                        heading_path=(doc.title,),
                    ),
                ),
            )
            for doc in intake.manifest.documents
        )
        intake.manifest = KnowledgeStructuredReleaseManifest.model_validate(
            intake.manifest.model_dump(exclude={"schema_version", "reader_version", "documents"})
            | {
                "documents": documents,
                "excerpt_digests": tuple(excerpt_digest(doc) for doc in documents),
            }
        )
    # This helper calls CloudKnowledgeService.import_package and checks the actual session.
    version = await intake.ingest()
    session = intake.metadata.uploads[version.upload_id]
    assert version.state is session.state is DocumentState.RECEIVED
    assert not version.active and not version.available
    assert version.index_state is DocumentIndexState.NOT_REQUESTED
    content = intake.objects.content[session.object_key]
    assert content == cloud.canonical_bytes(intake.manifest)
    binding = version.cloud_knowledge
    assert binding is not None and binding.verified_key_id == _INTAKE.KEY_ID
    assert binding.manifest_digest == cloud.content_digest(content) == version.source_sha256
    assert binding.sources == tuple(doc.evidence for doc in intake.manifest.documents)
    assert binding.imported_at == NOW and binding.intake_origin == "package"

    runtime = _runtime(intake, session, version, tmp_path, monkeypatch)
    verifier = _ACTIVATION._ControlledVerifier()
    worker = runtime.worker(verifier)
    bus, var, thor = _pantheon()
    received = intake.metadata.events[-1]
    assert received.payload["event_type"] == "document.received"
    await bus.publish("Huginn", received.topic, received.payload)
    admission = bus.messages_on("object.audit-entry")[-1].payload
    assert admission["stage"] == "received" and admission["decision"] == "admit"
    assert not bus.messages_on("object.context-index")
    inspection_claim = runtime.claim.model_copy(update={"stage": DocumentWorkerStage.INSPECTION})
    inspected = await worker.inspect(session.upload_id, lambda: inspection_claim)
    assert inspected.state is DocumentState.PROTECTION_CHECK
    assert inspected.protection_state is ProtectionState.NONE and inspected.failure_code is None
    assert not inspected.active and not inspected.available and not runtime.index.committed
    inspection = runtime.metadata.events[-1]
    assert inspection.payload["event_type"] == "document.inspected"
    assert inspection.payload["record"]["malware_verdict"] == "clean"
    await bus.publish("Huginn", inspection.topic, inspection.payload)
    assert bus.messages_on("object.verdict")[-1].payload["decision"] == "hil"
    (ticket,) = var.pending_tickets()
    assert ticket.initiator_principal == version.uploader_id
    assert not bus.messages_on("object.context-index") and not runtime.extractor.states
    with pytest.raises(ValueError, match="no self-approval"):
        await var.decide(ticket.correlation_id, approver=version.uploader_id, decision="approve")
    assert not bus.messages_on("object.approval") and not bus.messages_on("object.context-index")
    approval = await var.decide(ticket.correlation_id, approver=REVIEWER, decision="approve")
    assert approval is not None and approval["approvers"] == [REVIEWER]
    assert not var.pending_tickets()
    assert [m.payload["decision"] for m in bus.messages_on("object.audit-entry")] == [
        "admit",
        "hil",
        "approved",
    ]
    (command_message,) = bus.messages_on("object.context-index")
    # Strip only bus-envelope metadata, then validate the actual Muninn command.
    command = DocumentWorkerIndexCommand.model_validate(
        {
            key: value
            for key, value in command_message.payload.items()
            if key != "envelope_schema_version"
        }
    )
    assert command.upload_id == session.upload_id
    assert command.document_id == str(version.document_id)
    assert command.producer_principal == "Muninn" and runtime.metadata.version == inspected

    # A synthetic post-command claim exercises orchestration, not PostgreSQL claim acquisition.
    task = asyncio.create_task(worker.index(command.upload_id, lambda: runtime.claim))
    try:
        await asyncio.wait_for(verifier.entered.wait(), timeout=5)
        pending = runtime.metadata.version
        assert pending.state is DocumentState.READY and pending.active and not pending.available
        assert pending.index_state is DocumentIndexState.ACTIVE and not task.done()
        assert _ACTIVATION._effect(runtime).status is WorkerEffectStatus.PENDING
        observed, reread = verifier.calls[0]
        envelope = runtime.index.committed[0]
        assert observed == pending and reread.units == envelope.units
        assert len(envelope.units) == 2 and envelope.extractor_name == "cloud-reference"
        assert envelope.cloud_knowledge == binding and envelope.artifact_manifest is not None
        assert runtime.extractor.states == [DocumentState.EXTRACTING, DocumentState.READY]
        with pytest.raises(RuntimeError, match="revision is not readable"):
            await _search(runtime)
        verifier.allow_return.set()
        ready = await asyncio.wait_for(task, timeout=5)
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    assert ready == runtime.metadata.version and ready.state is DocumentState.READY
    assert ready.active and ready.available and ready.cloud_knowledge == binding
    assert ready.index_state is runtime.metadata.session.index_state is DocumentIndexState.ACTIVE
    assert _ACTIVATION._effect(runtime).status is WorkerEffectStatus.COMPLETED
    terminal = runtime.metadata.events[-1]
    assert terminal.payload["action"] == "document.ready"
    assert terminal.payload["record"]["cloud_index_digest"] == _ACTIVATION.OBSERVED_DIGEST
    assert len(runtime.index.committed) == len(verifier.calls) == 1
    assert intake.objects.content[session.object_key] == content
    collection = await _search(runtime)
    assert collection.observed_at == NOW and collection.retrieval_mode == "lexical"
    assert len(collection.excerpts) == len(envelope.units)
    source_prefix = f"document://{ready.document_id}/versions/{ready.version_id}#"
    for excerpt in collection.excerpts:
        source = excerpt.cloud_source
        assert source in binding.sources and source is not None
        assert source.collected_at < source.check.checked_at < binding.imported_at
        assert excerpt.cloud_status == "stale" and not source.allows_current_guidance(NOW)
        assert excerpt.instruction_authority is False
        assert excerpt.text == next(
            unit.text for unit in envelope.units if unit.locator == excerpt.locator
        )
        assert excerpt.source_ref.startswith(source_prefix)
    # This helper calls the real _answer_row_values; URL-bearing text stays subject to redaction.
    output = _DATES._output(collection)
    answer = _render_governed_document_answer(
        [output], korean=False, output_shape="governed_document_excerpts"
    )
    assert answer is not None
    for source in binding.sources:
        assert f"Collected: {source.collected_at.isoformat()}" in answer
        assert f"source checked: {source.check.checked_at.isoformat()}" in answer
    assert all(row["values"]["redaction_applied"] for row in output["rows"][1:])
    assert "historical reference only" in answer and "Dated reference only" in answer
    assert "Not a live resource observation." in answer
    assert binding.imported_at.isoformat() not in answer
    assert "instruction_authority=false" in answer and "execution_authority=false" in answer
    assert "https://" not in answer
    korean = _render_governed_document_answer(
        [output], korean=True, output_shape="governed_document_excerpts"
    )
    assert korean is not None and "과거 참조용" in korean
    for source in binding.sources:
        assert source.collected_at.isoformat() in korean
        assert source.check.checked_at.isoformat() in korean
    assert binding.imported_at.isoformat() not in korean
    facts = (*intake.metadata.events, *runtime.metadata.events)
    assert all(event.created_at == NOW for event in facts)
    serialized = json.dumps([message.payload for message in bus.published], ensure_ascii=False)
    serialized += "".join(event.model_dump_json() for event in facts)
    assert all(doc.text not in serialized for doc in intake.manifest.documents)
    for source in intake.service.registry.sources:
        original = _INTAKE._PACKAGE_HELPERS._collected_document(source).original_text
        assert original not in serialized and original.encode() not in content
    assert b'"original_text"' not in content
    assert not bus.messages_on("object.action-run") and thor.action_runs == {}
    assert all(message.principal != "Thor" for message in bus.published)
    assert bus.handler_errors == 0 and not bus.dead_letters
