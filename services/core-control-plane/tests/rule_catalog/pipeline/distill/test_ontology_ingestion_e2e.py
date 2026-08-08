"""End-to-end upload through ontology review package creation."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import UUID

import pytest
from fdai.core.document_ingestion import (
    CreateUploadRequest,
    DocumentIngestionService,
    DocumentIngestionWorker,
)
from fdai.rule_catalog.pipeline.distill.ontology_ingestion import (
    EnvelopeOntologyReviewConsumer,
)
from fdai.rule_catalog.pipeline.distill.ontology_models import AuthorityClass
from fdai.rule_catalog.pipeline.distill.ontology_review import OntologyReviewPackage
from fdai.rule_catalog.pipeline.distill.ontology_verify import (
    EntityRecord,
    SourceAuthorityPolicy,
    VerificationContext,
)
from fdai.shared.contracts import (
    DocumentEnvelope,
    DocumentPurpose,
    DocumentState,
    IngestionCapabilities,
    SourceStorageMode,
)
from fdai.shared.providers.distiller import (
    CandidateKind,
    DistillationResult,
    DistilledCandidate,
    ManualDocument,
)
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

_NOW = datetime(2026, 8, 3, tzinfo=UTC)
_CLAIM = "Checkout service is owned by Platform team."


class _Ids:
    def __init__(self) -> None:
        self._next = 0

    def __call__(self) -> UUID:
        self._next += 1
        return UUID(int=self._next)


class _Distiller:
    async def distill(self, document: ManualDocument) -> DistillationResult:
        return DistillationResult(
            candidates=(
                DistilledCandidate(
                    kind=CandidateKind.ONTOLOGY_OBJECT,
                    candidate_id="candidate-ownership",
                    source_ref=document.source_ref,
                    source_section="Ownership",
                    source_lines=(1, 1),
                    content_sha=document.content_sha,
                    body={
                        "operation": "update",
                        "target_type": "BusinessService",
                        "target_identity": "service:checkout",
                        "authority": "declared_intent",
                        "source_assertion": _CLAIM,
                        "properties": {"owner_ref": "team:platform"},
                    },
                ),
            )
        )


class _AwareDistiller:
    def __init__(self) -> None:
        self.contexts: list[VerificationContext] = []

    async def distill_ontology(
        self,
        document: ManualDocument,
        context: VerificationContext,
    ) -> DistillationResult:
        self.contexts.append(context)
        return await _Distiller().distill(document)


class _Sink:
    def __init__(self) -> None:
        self.packages: list[OntologyReviewPackage] = []

    async def put(self, package: OntologyReviewPackage) -> None:
        self.packages.append(package)


@pytest.mark.parametrize("distiller", (_Distiller(), _AwareDistiller()), ids=("legacy", "aware"))
async def test_upload_extraction_builds_replay_stable_ontology_review_package(
    distiller: _Distiller | _AwareDistiller,
) -> None:
    sink = _Sink()
    consumer = EnvelopeOntologyReviewConsumer(
        distiller=distiller,
        context_provider=_context,
        sink=sink,
    )
    service, worker, artifacts = _pipeline(consumer)
    content = (_CLAIM + "\n").encode()
    session, _ = await service.create_upload(
        actor_id="uploader",
        request=CreateUploadRequest(
            source_name="manual.md",
            collection_id="collection-a",
            media_type_hint="text/markdown",
            expected_size=len(content),
            expected_sha256=hashlib.sha256(content).hexdigest(),
            storage_mode=SourceStorageMode.MANAGED_COPY,
            purposes=(DocumentPurpose.MANUAL_DISTILLATION,),
            access_descriptor_ref="access:manuals",
            reader_groups=("manual-readers",),
            retention_policy_version="policy-v1",
        ),
    )
    await service.put_local_content(
        actor_id="uploader",
        upload_id=session.upload_id,
        content=content,
    )
    await service.complete_upload(actor_id="uploader", upload_id=session.upload_id)

    version = await worker.process(session.upload_id)
    envelope = artifacts.envelopes[(session.document_id, session.version_id)]

    assert version.state is DocumentState.READY
    assert len(sink.packages) == 1
    package = sink.packages[0]
    assert package.summary.total_claims == 1
    assert package.summary.mapped_claims == 1
    assert package.claims[0].evidence.structural_locator == ("markdown/paragraph:1/lines:1-1")
    assert package.proposals[0].proposal.evidence == package.claims[0].evidence

    await consumer.consume(session=session, envelope=envelope)
    assert sink.packages[1].package_digest == package.package_digest
    if isinstance(distiller, _AwareDistiller):
        assert distiller.contexts == [_context(envelope), _context(envelope)]


def _pipeline(consumer: EnvelopeOntologyReviewConsumer):
    access = InMemoryDocumentAccessProvider(
        contributors={"collection-a": frozenset({"uploader"})},
        readers={"collection-a": frozenset({"reader"})},
        owners={"collection-a": frozenset({"owner"})},
    )
    metadata = InMemoryDocumentMetadataStore()
    objects = InMemoryDocumentObjectStore(chunk_size=7)
    artifacts = InMemoryDocumentArtifactStore()
    index = InMemoryDocumentIndex()
    activity = RecordingDocumentActivitySink()
    capabilities = IngestionCapabilities(
        supported_formats=("text", "ooxml", "pdf"),
        storage_modes=tuple(SourceStorageMode),
        max_file_size=1024 * 1024,
        max_batch_count=10,
        archives_enabled=False,
        policy_versions=("policy-v1",),
        direct_upload=True,
    )
    service = DocumentIngestionService(
        access=access,
        metadata=metadata,
        objects=objects,
        activity=activity,
        capabilities=capabilities,
        clock=lambda: _NOW,
        id_factory=_Ids(),
    )
    worker = DocumentIngestionWorker(
        access=access,
        metadata=metadata,
        objects=objects,
        malware=StaticMalwareScanner(),
        protection=SignatureProtectionInspector(),
        extractor=StandardLibraryDocumentExtractor(),
        artifacts=artifacts,
        index=index,
        activity=activity,
        consumers=(consumer,),
        clock=lambda: _NOW,
    )
    return service, worker, artifacts


def _context(envelope: DocumentEnvelope) -> VerificationContext:
    source_ref = f"document://{envelope.document_id}/versions/{envelope.version_id}"
    return VerificationContext(
        ontology_release="a" * 64,
        current_graph_revision="graph-1",
        object_types=frozenset({"BusinessService"}),
        links=(),
        entities=(EntityRecord("service:checkout", "BusinessService"),),
        source_policies=(
            SourceAuthorityPolicy(
                source_ref,
                frozenset({AuthorityClass.DECLARED_INTENT}),
                10,
            ),
        ),
        claim_text=(),
    )
