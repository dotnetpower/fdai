"""Off-path Rule semantic generation construction, validation, and activation."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime

from fdai.delivery.catalog_search.generation import SemanticGenerationBuild
from fdai.shared.providers.catalog_search import (
    CatalogCorpus,
    CatalogGenerationMetadata,
    CatalogSearchDocument,
    CatalogSemanticIndex,
    build_document_digest_manifest,
    catalog_generation_digest,
    catalog_search_document_digest,
)

_DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")
_MAX_DOCUMENTS = 20_000


@dataclass(frozen=True, slots=True)
class RuleSemanticGenerationValidationReceipt:
    """Independent proof of a complete Rule generation and its exact identities."""

    corpus: CatalogCorpus
    generation_digest: str
    catalog_digest: str
    semantic_schema_digest: str
    ontology_release_digest: str
    embedding_space_id: str
    embedding_model_version: str
    embedding_dimension: int
    document_count: int
    document_digest_root: str
    document_digest_chunks: tuple[str, ...]
    validator_artifact_digest: str
    receipt_digest: str


def build_rule_semantic_generation(
    *,
    documents: Sequence[CatalogSearchDocument],
    corpus: CatalogCorpus,
    catalog_digest: str,
    semantic_schema_digest: str,
    ontology_release_digest: str,
    embedding_space_id: str,
    embedding_model_version: str,
    embedding_dimension: int,
    previous_documents: Sequence[CatalogSearchDocument] = (),
) -> SemanticGenerationBuild:
    """Build one deterministic inactive Rule generation without provider I/O."""

    candidates = tuple(sorted(documents, key=lambda item: item.rule_id))
    _validate_rule_documents(
        candidates,
        corpus=corpus,
        embedding_dimension=embedding_dimension,
    )
    previous_by_digest = {catalog_search_document_digest(item): item for item in previous_documents}
    materialized: list[CatalogSearchDocument] = []
    document_digests: list[str] = []
    reused = 0
    for candidate in candidates:
        digest = catalog_search_document_digest(candidate)
        previous = previous_by_digest.get(digest)
        if previous is not None and previous.rule_id == candidate.rule_id:
            materialized.append(previous)
            reused += 1
        else:
            materialized.append(candidate)
        document_digests.append(digest)
    ordered_digests = tuple(document_digests)
    document_manifest = build_document_digest_manifest(ordered_digests)
    generation_digest = catalog_generation_digest(
        corpus=corpus,
        catalog_digest=catalog_digest,
        semantic_schema_digest=semantic_schema_digest,
        ontology_release_digest=ontology_release_digest,
        embedding_space_id=embedding_space_id,
        embedding_model_version=embedding_model_version,
        embedding_dimension=embedding_dimension,
        document_digest_manifest=document_manifest,
    )
    metadata = CatalogGenerationMetadata(
        generation_id=f"rule-search:{corpus}:{generation_digest[7:31]}",
        generation_digest=generation_digest,
        corpus=corpus,
        catalog_digest=catalog_digest,
        semantic_schema_digest=semantic_schema_digest,
        ontology_release_digest=ontology_release_digest,
        embedding_space_id=embedding_space_id,
        embedding_model_version=embedding_model_version,
        embedding_dimension=embedding_dimension,
        document_digest_manifest=document_manifest,
    )
    return SemanticGenerationBuild(
        metadata=metadata,
        documents=tuple(materialized),
        document_digests=ordered_digests,
        reused_document_count=reused,
    )


def validate_rule_semantic_generation(
    *,
    build: SemanticGenerationBuild,
    corpus: CatalogCorpus,
    catalog_digest: str,
    semantic_schema_digest: str,
    ontology_release_digest: str,
    embedding_space_id: str,
    embedding_model_version: str,
    embedding_dimension: int,
    validator_artifact_digest: str,
) -> RuleSemanticGenerationValidationReceipt:
    """Independently recompute Rule coverage, identity, and ordered row digests."""

    if _DIGEST.fullmatch(validator_artifact_digest) is None:
        raise ValueError("Rule generation validator artifact MUST be a sha256 digest")
    _validate_rule_documents(
        build.documents,
        corpus=corpus,
        embedding_dimension=embedding_dimension,
    )
    metadata = build.metadata
    expected_identity = (
        corpus,
        catalog_digest,
        semantic_schema_digest,
        ontology_release_digest,
        embedding_space_id,
        embedding_model_version,
        embedding_dimension,
    )
    actual_identity = (
        metadata.corpus,
        metadata.catalog_digest,
        metadata.semantic_schema_digest,
        metadata.ontology_release_digest,
        metadata.embedding_space_id,
        metadata.embedding_model_version,
        metadata.embedding_dimension,
    )
    if actual_identity != expected_identity:
        raise ValueError("Rule generation validation identity mismatch")
    recomputed_digests = tuple(catalog_search_document_digest(item) for item in build.documents)
    if recomputed_digests != build.document_digests:
        raise ValueError("Rule generation document digest mismatch")
    document_manifest = build_document_digest_manifest(recomputed_digests)
    if document_manifest != metadata.document_digest_manifest:
        raise ValueError("Rule generation document manifest mismatch")
    recomputed_generation_digest = catalog_generation_digest(
        corpus=corpus,
        catalog_digest=catalog_digest,
        semantic_schema_digest=semantic_schema_digest,
        ontology_release_digest=ontology_release_digest,
        embedding_space_id=embedding_space_id,
        embedding_model_version=embedding_model_version,
        embedding_dimension=embedding_dimension,
        document_digest_manifest=document_manifest,
    )
    if recomputed_generation_digest != metadata.generation_digest:
        raise ValueError("Rule generation digest mismatch")
    document_digest_chunks = tuple(chunk.digest for chunk in document_manifest.chunks)
    payload = {
        "schema_version": "1.0.0",
        "corpus": corpus,
        "generation_digest": recomputed_generation_digest,
        "catalog_digest": catalog_digest,
        "semantic_schema_digest": semantic_schema_digest,
        "ontology_release_digest": ontology_release_digest,
        "embedding_space_id": embedding_space_id,
        "embedding_model_version": embedding_model_version,
        "embedding_dimension": embedding_dimension,
        "document_count": document_manifest.document_count,
        "document_digest_root": document_manifest.document_digest_root,
        "document_digest_chunks": document_digest_chunks,
        "validator_artifact_digest": validator_artifact_digest,
        "valid": True,
    }
    return RuleSemanticGenerationValidationReceipt(
        corpus=corpus,
        generation_digest=recomputed_generation_digest,
        catalog_digest=catalog_digest,
        semantic_schema_digest=semantic_schema_digest,
        ontology_release_digest=ontology_release_digest,
        embedding_space_id=embedding_space_id,
        embedding_model_version=embedding_model_version,
        embedding_dimension=embedding_dimension,
        document_count=document_manifest.document_count,
        document_digest_root=document_manifest.document_digest_root,
        document_digest_chunks=document_digest_chunks,
        validator_artifact_digest=validator_artifact_digest,
        receipt_digest=_digest(payload),
    )


def bind_rule_semantic_generation_validation(
    build: SemanticGenerationBuild,
    receipt: RuleSemanticGenerationValidationReceipt,
) -> SemanticGenerationBuild:
    """Attach a receipt only when it covers this exact Rule generation."""

    metadata = build.metadata
    receipt_identity = (
        receipt.corpus,
        receipt.generation_digest,
        receipt.catalog_digest,
        receipt.semantic_schema_digest,
        receipt.ontology_release_digest,
        receipt.embedding_space_id,
        receipt.embedding_model_version,
        receipt.embedding_dimension,
    )
    metadata_identity = (
        metadata.corpus,
        metadata.generation_digest,
        metadata.catalog_digest,
        metadata.semantic_schema_digest,
        metadata.ontology_release_digest,
        metadata.embedding_space_id,
        metadata.embedding_model_version,
        metadata.embedding_dimension,
    )
    if receipt_identity != metadata_identity:
        raise ValueError("Rule generation validation receipt targets another generation")
    document_manifest = build_document_digest_manifest(build.document_digests)
    if (
        receipt.document_count != document_manifest.document_count
        or receipt.document_digest_root != document_manifest.document_digest_root
        or receipt.document_digest_chunks
        != tuple(chunk.digest for chunk in document_manifest.chunks)
    ):
        raise ValueError("Rule generation validation receipt document identity mismatch")
    return replace(
        build,
        metadata=replace(metadata, validation_receipt_digest=receipt.receipt_digest),
    )


async def publish_rule_semantic_generation(
    *,
    index: CatalogSemanticIndex,
    build: SemanticGenerationBuild,
    activated_at: datetime,
) -> CatalogGenerationMetadata:
    """Stage and atomically activate one independently validated Rule generation."""

    if activated_at.tzinfo is None:
        raise ValueError("Rule generation activation time MUST be timezone-aware")
    if build.metadata.validation_receipt_digest is None:
        raise ValueError("Rule generation validation receipt is unavailable")
    await index.stage_generation(build.metadata, build.documents)
    return await index.activate_generation(
        build.metadata.generation_id,
        expected_generation_digest=build.metadata.generation_digest,
        activated_at=activated_at,
    )


def _validate_rule_documents(
    documents: Sequence[CatalogSearchDocument],
    *,
    corpus: CatalogCorpus,
    embedding_dimension: int,
) -> None:
    if not documents or len(documents) > _MAX_DOCUMENTS:
        raise ValueError(f"Rule generation document count MUST be in [1, {_MAX_DOCUMENTS}]")
    identifiers = tuple(item.rule_id for item in documents)
    if identifiers != tuple(sorted(identifiers)):
        raise ValueError("Rule generation documents MUST use canonical Rule id order")
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("Rule generation document ids MUST be unique")
    if any(item.document_kind != "rule" or item.corpus != corpus for item in documents):
        raise ValueError("Rule generation documents MUST match the Rule corpus")
    if any(item.embedding and len(item.embedding) != embedding_dimension for item in documents):
        raise ValueError("Rule generation document embedding dimension mismatch")


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
    "RuleSemanticGenerationValidationReceipt",
    "bind_rule_semantic_generation_validation",
    "build_rule_semantic_generation",
    "publish_rule_semantic_generation",
    "validate_rule_semantic_generation",
]
