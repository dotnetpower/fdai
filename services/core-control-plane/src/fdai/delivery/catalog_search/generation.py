"""Off-path full ontology semantic generation construction and activation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime

from fdai.core.ontology_platform import QueryManifest
from fdai.shared.providers.catalog_search import (
    CatalogGenerationMetadata,
    CatalogSearchDocument,
    CatalogSemanticIndex,
    build_document_digest_manifest,
    catalog_generation_digest,
    catalog_search_document_digest,
)
from fdai.shared.providers.ontology_instance import OntologyObjectRecord, normalize_json_value

_SCHEMA_DIGEST = "sha256:" + hashlib.sha256(b"fdai-ontology-semantic-document-v1").hexdigest()
_MAX_DOCUMENTS = 20_000
_MAX_DOCUMENT_BYTES = 65_536


@dataclass(frozen=True, slots=True)
class SemanticGenerationBuild:
    """Complete deterministic documents and generation metadata before staging."""

    metadata: CatalogGenerationMetadata
    documents: tuple[CatalogSearchDocument, ...]
    document_digests: tuple[str, ...]
    reused_document_count: int

    def __post_init__(self) -> None:
        if len(self.documents) != len(self.document_digests):
            raise ValueError("semantic generation document digest count mismatch")
        if not 0 <= self.reused_document_count <= len(self.documents):
            raise ValueError("semantic generation reused count is invalid")


@dataclass(frozen=True, slots=True)
class SemanticGenerationValidationReceipt:
    """Independent deterministic proof that one complete generation is coherent."""

    generation_digest: str
    ontology_release_digest: str
    document_count: int
    document_digest_root: str
    document_digest_chunks: tuple[str, ...]
    validator_id: str
    receipt_digest: str


def build_ontology_semantic_generation(
    *,
    manifest: QueryManifest,
    embedding_space_id: str,
    embedding_model_version: str,
    embedding_dimension: int,
    runtime_objects: Sequence[OntologyObjectRecord] = (),
    previous_documents: Sequence[CatalogSearchDocument] = (),
) -> SemanticGenerationBuild:
    """Build one full inactive generation and reuse exact unchanged documents.

    Runtime object rows are deployment-local projections. This function performs
    no provider reads and never writes or activates an index.
    """

    candidates = [*_declaration_documents(manifest), *_runtime_object_documents(runtime_objects)]
    candidates.sort(key=lambda item: item.rule_id)
    if not candidates or len(candidates) > _MAX_DOCUMENTS:
        raise ValueError(f"semantic generation document count MUST be in [1, {_MAX_DOCUMENTS}]")
    identifiers = [item.rule_id for item in candidates]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("semantic generation document ids MUST be unique")

    previous_by_digest = {catalog_search_document_digest(item): item for item in previous_documents}
    documents: list[CatalogSearchDocument] = []
    digests: list[str] = []
    reused = 0
    for candidate in candidates:
        digest = catalog_search_document_digest(candidate)
        prior = previous_by_digest.get(digest)
        if prior is not None and prior.rule_id == candidate.rule_id:
            documents.append(prior)
            reused += 1
        else:
            documents.append(candidate)
        digests.append(digest)
    ordered_digests = tuple(digests)
    document_manifest = build_document_digest_manifest(ordered_digests)
    catalog_digest = _digest(
        {
            "manifest_digest": manifest.manifest_digest,
            "runtime_object_digests": [
                digest
                for document, digest in zip(documents, ordered_digests, strict=True)
                if document.document_kind == "ontology_object"
            ],
        }
    )
    generation_digest = catalog_generation_digest(
        corpus="active",
        catalog_digest=catalog_digest,
        ontology_release_digest=manifest.release_digest,
        semantic_schema_digest=_SCHEMA_DIGEST,
        embedding_space_id=embedding_space_id,
        embedding_model_version=embedding_model_version,
        embedding_dimension=embedding_dimension,
        document_digest_manifest=document_manifest,
    )
    metadata = CatalogGenerationMetadata(
        generation_id=f"ontology-search:active:{generation_digest[7:31]}",
        generation_digest=generation_digest,
        corpus="active",
        catalog_digest=catalog_digest,
        semantic_schema_digest=_SCHEMA_DIGEST,
        ontology_release_digest=manifest.release_digest,
        embedding_space_id=embedding_space_id,
        embedding_model_version=embedding_model_version,
        embedding_dimension=embedding_dimension,
        document_digest_manifest=document_manifest,
    )
    return SemanticGenerationBuild(
        metadata=metadata,
        documents=tuple(documents),
        document_digests=ordered_digests,
        reused_document_count=reused,
    )


def validate_ontology_semantic_generation(
    *,
    build: SemanticGenerationBuild,
    manifest: QueryManifest,
    validator_id: str,
) -> SemanticGenerationValidationReceipt:
    """Recompute complete declaration coverage and every document digest."""

    if not validator_id or len(validator_id) > 128:
        raise ValueError("semantic generation validator_id MUST be bounded")
    if build.metadata.ontology_release_digest != manifest.release_digest:
        raise ValueError("semantic generation validation release mismatch")
    recomputed = tuple(catalog_search_document_digest(item) for item in build.documents)
    if recomputed != build.document_digests:
        raise ValueError("semantic generation document digest mismatch")
    expected_declarations = {
        f"declaration:{item['kind']}:{item['name']}" for item in manifest.descriptors
    } | {f"unavailable:{item['declaration_id']}" for item in manifest.unavailable}
    actual_declarations = {
        item.rule_id for item in build.documents if item.document_kind == "ontology_declaration"
    }
    if actual_declarations != expected_declarations:
        raise ValueError("semantic generation declaration coverage mismatch")
    document_manifest = build_document_digest_manifest(recomputed)
    document_digest_chunks = tuple(chunk.digest for chunk in document_manifest.chunks)
    payload = {
        "schema_version": "1.0.0",
        "generation_digest": build.metadata.generation_digest,
        "ontology_release_digest": manifest.release_digest,
        "document_count": document_manifest.document_count,
        "document_digest_root": document_manifest.document_digest_root,
        "document_digest_chunks": document_digest_chunks,
        "validator_id": validator_id,
        "valid": True,
    }
    return SemanticGenerationValidationReceipt(
        generation_digest=build.metadata.generation_digest,
        ontology_release_digest=manifest.release_digest,
        document_count=document_manifest.document_count,
        document_digest_root=document_manifest.document_digest_root,
        document_digest_chunks=document_digest_chunks,
        validator_id=validator_id,
        receipt_digest=_digest(payload),
    )


def bind_semantic_generation_validation(
    build: SemanticGenerationBuild,
    receipt: SemanticGenerationValidationReceipt,
) -> SemanticGenerationBuild:
    """Attach only an exact independently recomputed validation receipt."""

    if receipt.generation_digest != build.metadata.generation_digest:
        raise ValueError("semantic generation validation receipt targets another generation")
    if receipt.ontology_release_digest != build.metadata.ontology_release_digest:
        raise ValueError("semantic generation validation receipt targets another release")
    if receipt.document_count != len(build.documents):
        raise ValueError("semantic generation validation receipt count mismatch")
    document_manifest = build_document_digest_manifest(build.document_digests)
    if receipt.document_digest_root != document_manifest.document_digest_root:
        raise ValueError("semantic generation validation receipt root mismatch")
    if receipt.document_digest_chunks != tuple(chunk.digest for chunk in document_manifest.chunks):
        raise ValueError("semantic generation validation receipt chunk mismatch")
    return replace(
        build,
        metadata=replace(build.metadata, validation_receipt_digest=receipt.receipt_digest),
    )


async def publish_ontology_semantic_generation(
    *,
    index: CatalogSemanticIndex,
    build: SemanticGenerationBuild,
    activated_at: datetime,
) -> CatalogGenerationMetadata:
    """Stage and activate only if the prior corpus pointer remains unchanged."""

    if activated_at.tzinfo is None:
        raise ValueError("semantic generation activation time MUST be timezone-aware")
    if build.metadata.validation_receipt_digest is None:
        raise ValueError("semantic generation validation receipt is unavailable")
    prior = await index.active_generation(build.metadata.corpus)
    await index.stage_generation(build.metadata, build.documents)
    return await index.activate_generation(
        build.metadata.generation_id,
        expected_generation_digest=build.metadata.generation_digest,
        expected_active_generation_id=(prior.generation_id if prior is not None else None),
        expected_active_generation_digest=(prior.generation_digest if prior is not None else None),
        activated_at=activated_at,
    )


def _declaration_documents(manifest: QueryManifest) -> list[CatalogSearchDocument]:
    documents: list[CatalogSearchDocument] = []
    for descriptor in manifest.descriptors:
        kind = str(descriptor["kind"])
        name = str(descriptor["name"])
        identifier = f"declaration:{kind}:{name}"
        neighbors: set[str] = set()
        if kind == "link":
            neighbors.update(
                {
                    f"declaration:object:{descriptor['from_type']}",
                    f"declaration:object:{descriptor['to_type']}",
                }
            )
        elif kind == "interface":
            neighbors.update(
                f"declaration:interface:{item}" for item in descriptor.get("extends", [])
            )
        text = _bounded_text(descriptor)
        documents.append(
            CatalogSearchDocument(
                rule_id=identifier,
                text=text,
                neighbor_ids=tuple(sorted(neighbors)),
                document_kind="ontology_declaration",
                manifest_digest=str(descriptor["declaration_digest"]),
            )
        )
    for unavailable in manifest.unavailable:
        documents.append(
            CatalogSearchDocument(
                rule_id=f"unavailable:{unavailable['declaration_id']}",
                text=_bounded_text(unavailable),
                neighbor_ids=(),
                document_kind="ontology_declaration",
            )
        )
    return documents


def _runtime_object_documents(
    records: Sequence[OntologyObjectRecord],
) -> list[CatalogSearchDocument]:
    documents: list[CatalogSearchDocument] = []
    for record in records:
        values = normalize_json_value(
            {
                "id": record.id,
                "object_type": record.object_type,
                "properties": record.properties,
            },
            path=f"ontology_semantic_object.{record.id}",
        )
        documents.append(
            CatalogSearchDocument(
                rule_id=f"object:{record.object_type}:{record.id}",
                text=_bounded_text(values),
                neighbor_ids=(f"declaration:object:{record.object_type}",),
                document_kind="ontology_object",
            )
        )
    return documents


def _bounded_text(value: object) -> str:
    text = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    if len(text.encode("utf-8")) > _MAX_DOCUMENT_BYTES:
        raise ValueError(f"semantic document exceeds {_MAX_DOCUMENT_BYTES} bytes")
    return text


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


__all__ = [
    "SemanticGenerationBuild",
    "SemanticGenerationValidationReceipt",
    "bind_semantic_generation_validation",
    "build_ontology_semantic_generation",
    "publish_ontology_semantic_generation",
    "validate_ontology_semantic_generation",
]
