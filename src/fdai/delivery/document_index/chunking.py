"""Structure-aware chunk mapping for document envelopes."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from fdai.shared.contracts import DocumentEnvelope, DocumentSourceSpan
from fdai.shared.providers.knowledge import chunk_text


@dataclass(frozen=True, slots=True)
class DocumentChunkRecord:
    chunk_id: str
    doc_id: str
    text: str
    source_ref: str
    metadata: Mapping[str, str]


_CHUNK_POLICY_VERSION = "structure-aware-v1"


def document_version_ref(document_id: UUID, version_id: UUID) -> str:
    return f"governed:{document_id}:{version_id}"


def chunk_document_envelope(
    envelope: DocumentEnvelope,
    *,
    max_chars: int = 1_200,
    overlap: int = 150,
) -> tuple[DocumentChunkRecord, ...]:
    """Split each structural unit while preserving citation and access metadata."""
    version_ref = document_version_ref(envelope.document_id, envelope.version_id)
    records: list[DocumentChunkRecord] = []
    for unit in envelope.units:
        pieces = chunk_text(unit.text, max_chars=max_chars, overlap=overlap)
        span = DocumentSourceSpan(
            document_id=envelope.document_id,
            version_id=envelope.version_id,
            unit_id=unit.unit_id,
            locator=unit.locator,
        )
        for piece_index, piece in enumerate(pieces):
            digest = hashlib.sha256(piece.encode("utf-8")).hexdigest()
            records.append(
                DocumentChunkRecord(
                    chunk_id=f"{version_ref}:{unit.unit_id}:{piece_index}",
                    doc_id=version_ref,
                    text=piece,
                    source_ref=span.reference,
                    metadata={
                        "governed_document": "true",
                        "document_id": str(envelope.document_id),
                        "version_id": str(envelope.version_id),
                        "collection_id": envelope.collection_id,
                        "access_descriptor_ref": envelope.access_descriptor_ref,
                        "source_sha256": envelope.source_sha256,
                        "unit_id": unit.unit_id,
                        "unit_kind": unit.kind,
                        "locator": unit.locator,
                        "source_span": json.dumps(
                            span.model_dump(mode="json"),
                            ensure_ascii=True,
                            separators=(",", ":"),
                            sort_keys=True,
                        ),
                        "chunk_policy_version": _CHUNK_POLICY_VERSION,
                        "content_digest": digest,
                        "goal_ref": envelope.goal_ref or "",
                        "protection_state": envelope.protection_state.value,
                        "purposes": ",".join(purpose.value for purpose in envelope.purposes),
                    },
                )
            )
    return tuple(records)


__all__ = ["DocumentChunkRecord", "chunk_document_envelope", "document_version_ref"]
