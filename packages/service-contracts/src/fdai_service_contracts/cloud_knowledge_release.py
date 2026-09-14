"""Closed, data-only knowledge release and document-ingestion binding contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import Field, StrictInt, model_validator

from fdai_service_contracts.cloud_knowledge import (
    CloudSourceEvidence,
    Digest,
    Identifier,
    KnowledgeContract,
    canonical_bytes,
    content_digest,
)


class CloudKnowledgeDocument(KnowledgeContract):
    """One source snapshot with bounded inert original and normalized text."""

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


class KnowledgeReleaseManifest(KnowledgeContract):
    """Complete bounded collection generation; no archive paths or executable members."""

    schema_version: Literal["fdai.cloud-knowledge.v1"] = "fdai.cloud-knowledge.v1"
    release_id: Identifier
    sequence: Annotated[StrictInt, Field(ge=1)]
    collection_id: Identifier
    registry_digest: Digest
    package_created_at: datetime
    expires_at: datetime
    documents: Annotated[tuple[CloudKnowledgeDocument, ...], Field(min_length=1, max_length=256)]
    withdrawn_source_ids: Annotated[tuple[Identifier, ...], Field(max_length=256)] = ()
    withdrawal_evidence_ref: Identifier | None = None
    reader_version: Literal["1.0.0"] = "1.0.0"

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
        if self.intake_origin == "rollback" and (
            self.rollback_of is None or self.rollback_source_digest is None
        ):
            raise ValueError("knowledge rollback MUST pin its previously admitted source")
        return self
