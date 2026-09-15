"""Closed, data-only knowledge release and document-ingestion binding contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Generic, Literal, Self, TypeVar

from pydantic import Field, StrictInt, TypeAdapter, model_validator

from fdai_service_contracts.cloud_knowledge import (
    CloudSourceEvidence,
    Digest,
    Identifier,
    KnowledgeContract,
    canonical_bytes,
    content_digest,
)
from fdai_service_contracts.cloud_knowledge_structure import CloudStructuredDocument, excerpt_digest


class CloudKnowledgeDocument(KnowledgeContract):
    """Collector-local or legacy v1 snapshot; both original and normalized hashes are checked."""

    evidence: CloudSourceEvidence
    title: Annotated[str, Field(min_length=1, max_length=256)]
    original_text: Annotated[str, Field(min_length=1, max_length=8 * 1024 * 1024)]
    text: Annotated[str, Field(min_length=1, max_length=8 * 1024 * 1024)]
    normalizer_version: Literal["1.0.0"] = "1.0.0"

    @model_validator(mode="after")
    def hashes(self) -> Self:
        if (
            content_digest(self.original_text.encode()) != self.evidence.source_sha256
            or content_digest(self.text.encode()) != self.evidence.normalized_sha256
        ):
            raise ValueError("document text MUST match its source and normalized hashes")
        return self


class CloudKnowledgeTextDocument(KnowledgeContract):
    """V2 transport text; the absent original's digest is signed provenance, not recomputed proof.

    Original-body fields are forbidden. Receiving this record never fetches the
    source or grants admission; only the included normalized text is hash-checked.
    """

    evidence: CloudSourceEvidence
    title: Annotated[str, Field(min_length=1, max_length=256)]
    text: Annotated[str, Field(min_length=1, max_length=8 * 1024 * 1024)]
    normalizer_version: Literal["1.0.0"] = "1.0.0"

    @model_validator(mode="after")
    def normalized_hash(self) -> Self:
        if content_digest(self.text.encode()) != self.evidence.normalized_sha256:
            raise ValueError("normalized document text MUST match its hash")
        return self


def normalized_document(
    document: CloudKnowledgeDocument | CloudKnowledgeTextDocument,
) -> CloudKnowledgeTextDocument:
    """Validate before projecting to v2; preserve text, evidence and dates without mutating
    input.
    """
    if isinstance(document, CloudKnowledgeDocument):
        snapshot = CloudKnowledgeDocument.model_validate(document.model_dump(warnings="error"))
        values = snapshot.model_dump(exclude={"original_text"})
    else:
        values = document.model_dump(warnings="error")
    return CloudKnowledgeTextDocument.model_validate(values)


_Document = TypeVar(
    "_Document", CloudKnowledgeDocument, CloudKnowledgeTextDocument, CloudStructuredDocument
)


class _ReleaseManifest(KnowledgeContract, Generic[_Document]):
    """Shared immutable collection/time invariants, independent of transported representation."""

    release_id: Identifier
    sequence: Annotated[StrictInt, Field(ge=1)]
    collection_id: Identifier
    registry_digest: Digest
    package_created_at: datetime
    expires_at: datetime
    documents: Annotated[tuple[_Document, ...], Field(min_length=1, max_length=256)]
    withdrawn_source_ids: Annotated[tuple[Identifier, ...], Field(max_length=256)] = ()
    withdrawal_evidence_ref: Identifier | None = None

    @model_validator(mode="after")
    def complete_generation(self) -> Self:
        if self.expires_at <= self.package_created_at:
            raise ValueError("release expiry MUST follow creation")
        ids = [doc.evidence.source_id for doc in self.documents]
        if (
            len(set(ids)) != len(ids)
            or len(set(self.withdrawn_source_ids)) != len(self.withdrawn_source_ids)
            or set(ids).intersection(self.withdrawn_source_ids)
        ):
            raise ValueError("release source identities MUST be unique and disjoint")
        if self.withdrawn_source_ids and self.withdrawal_evidence_ref is None:
            raise ValueError("withdrawals require an explicit reviewed evidence reference")
        if any(doc.evidence.check.checked_at > self.package_created_at for doc in self.documents):
            raise ValueError("package creation MUST NOT precede its source evidence")
        return self

    @property
    def digest(self) -> str:
        return content_digest(canonical_bytes(self))


class KnowledgeReleaseManifest(_ReleaseManifest[CloudKnowledgeDocument]):
    """Legacy v1 reader contract; its canonical bytes remain unchanged for signed history."""

    schema_version: Literal["fdai.cloud-knowledge.v1"] = "fdai.cloud-knowledge.v1"
    reader_version: Literal["1.0.0"] = "1.0.0"


class KnowledgeTextReleaseManifest(_ReleaseManifest[CloudKnowledgeTextDocument]):
    """Complete v2 generation containing normalized text and provenance, never original bodies."""

    schema_version: Literal["fdai.cloud-knowledge.v2"] = "fdai.cloud-knowledge.v2"
    reader_version: Literal["2.0.0"] = "2.0.0"


class KnowledgeStructuredReleaseManifest(_ReleaseManifest[CloudStructuredDocument]):
    """V3 complete structured generation with sealed deterministic excerpt digests."""

    schema_version: Literal["fdai.cloud-knowledge.v3"] = "fdai.cloud-knowledge.v3"
    reader_version: Literal["3.0.0"] = "3.0.0"
    excerpt_digests: Annotated[tuple[Digest, ...], Field(min_length=1, max_length=256)]

    @model_validator(mode="after")
    def derived_inventory(self) -> Self:
        if any(doc.derived_at > self.package_created_at for doc in self.documents):
            raise ValueError("package creation cannot precede derivation")
        if self.excerpt_digests != tuple(excerpt_digest(doc) for doc in self.documents):
            raise ValueError("structured release excerpt inventory does not match")
        return self


KnowledgeManifest = Annotated[
    KnowledgeReleaseManifest | KnowledgeTextReleaseManifest | KnowledgeStructuredReleaseManifest,
    Field(discriminator="schema_version"),
]
_MANIFEST_ADAPTER: TypeAdapter[KnowledgeManifest] = TypeAdapter(KnowledgeManifest)


def parse_knowledge_manifest(content: bytes) -> KnowledgeManifest:
    """Read an explicitly versioned v1/v2 manifest; callers still verify canonical
    identity/trust.
    """
    return _MANIFEST_ADAPTER.validate_json(content)


class KnowledgeReleaseBinding(KnowledgeContract):
    """Server-verified provenance attached to an ordinary governed upload/version.

    The binding is not an approval. The existing independent document admission,
    inspection, Var approval, Muninn index command and Saga audit remain required.
    """

    release_id: Identifier
    sequence: Annotated[StrictInt, Field(ge=1)]
    manifest_digest: Digest
    registry_digest: Digest
    package_created_at: datetime
    imported_at: datetime
    admission_expires_at: datetime
    verified_key_id: Identifier
    intake_origin: Literal["package", "collector", "rollback"] = "package"
    sources: Annotated[tuple[CloudSourceEvidence, ...], Field(min_length=1, max_length=256)]
    processing_digests: Annotated[
        tuple[Digest, ...], Field(max_length=256, exclude_if=lambda values: not values)
    ] = ()
    rollback_of: Identifier | None = None
    rollback_source_digest: Digest | None = None
    withdrawn_source_ids: Annotated[tuple[Identifier, ...], Field(max_length=256)] = ()

    @model_validator(mode="after")
    def chronology(self) -> Self:
        if not self.package_created_at <= self.imported_at < self.admission_expires_at:
            raise ValueError("knowledge admission times are invalid")
        ids = [item.source_id for item in self.sources]
        if len(set(ids)) != len(ids):
            raise ValueError("knowledge binding source identities MUST be unique")
        if self.processing_digests and len(self.processing_digests) != len(self.sources):
            raise ValueError("knowledge processing identities must cover every bound source")
        if self.intake_origin == "rollback" and (
            self.rollback_of is None or self.rollback_source_digest is None
        ):
            raise ValueError("knowledge rollback MUST pin its previously admitted source")
        return self
