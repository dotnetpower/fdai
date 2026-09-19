"""Immutable, isolated staging snapshots; never a search or activation authority."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from fdai.core.ontology_platform import QueryManifest
from fdai.shared.providers.catalog_search import (
    CatalogGenerationMetadata,
    CatalogSearchDocument,
    catalog_search_document_digest,
)
from fdai.shared.providers.state_store import StateStore

from .generation import SemanticGenerationBuild, validate_ontology_semantic_generation

_PREFIX = "ontology-semantic-snapshot:v1:"
_MAX_CHUNK_BYTES = 512 * 1024
_MAX_SNAPSHOT_BYTES = 64 * 1024 * 1024
_MAX_DOCUMENTS = 20_000
_MAX_CHUNKS = 512
_DOCUMENTS = TypeAdapter(tuple[CatalogSearchDocument, ...])
_METADATA = TypeAdapter(CatalogGenerationMetadata)


class OntologySnapshotCorruptionError(ValueError):
    """Stored staging data is incomplete, malformed, or inconsistent with its identity."""


class _SnapshotHeader(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(pattern=r"^1\.0\.0$")
    principal_scope_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    manifest_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    source_generation: str = Field(min_length=1, max_length=256)
    metadata: dict[str, Any]
    chunk_digests: tuple[str, ...] = Field(min_length=1, max_length=_MAX_CHUNKS)
    document_count: int = Field(ge=1, le=_MAX_DOCUMENTS)


class OntologyGenerationSnapshotStore:
    """Stage bounded documents under content keys, then publish a completion header.

    The injected service-owned StateStore provides durability. A header is written
    only after all immutable chunks exist; retries reuse exact content. Reads require
    the caller's current principal manifest and source generation and revalidate all
    chunks. This does not authorize source objects, activate a generation, or update
    Rule corpus pointers. Source projection and activation remain owner obligations.
    """

    def __init__(self, store: StateStore) -> None:
        self._store = store

    async def stage(
        self,
        *,
        build: SemanticGenerationBuild,
        manifest: QueryManifest,
        source_generation: str,
    ) -> str:
        """Persist an inactive complete snapshot and return its full content digest."""

        _validate_build(build, manifest)
        chunks = _chunk_documents(build.documents)
        header = _SnapshotHeader(
            schema_version="1.0.0",
            principal_scope_digest=manifest.coverage_receipt.principal_scope_digest,
            manifest_digest=manifest.manifest_digest,
            source_generation=source_generation,
            metadata=_METADATA.dump_python(build.metadata, mode="json"),
            chunk_digests=tuple(_digest(chunk) for chunk in chunks),
            document_count=len(build.documents),
        ).model_dump(mode="json")
        snapshot_digest = _digest(header)
        for ordinal, chunk in enumerate(chunks):
            await self._write_immutable(_chunk_key(snapshot_digest, ordinal), chunk)
        await self._write_immutable(f"{_PREFIX}{snapshot_digest}:header", header)
        return snapshot_digest

    async def read(
        self,
        snapshot_digest: str,
        *,
        manifest: QueryManifest,
        source_generation: str,
    ) -> SemanticGenerationBuild | None:
        """Return only an exact complete staging snapshot; absent headers mean pending.

        Identity drift or corruption raises instead of falling back to another
        principal, source generation, or Rule catalog. Missing chunks after a header
        exists are corruption, not an empty successful projection.
        """

        if re.fullmatch(r"sha256:[0-9a-f]{64}", snapshot_digest) is None:
            raise ValueError("ontology snapshot requires a full sha256 digest")
        raw_header = await self._store.read_state(f"{_PREFIX}{snapshot_digest}:header")
        if raw_header is None:
            return None
        try:
            if _digest(raw_header) != snapshot_digest:
                raise ValueError("header digest mismatch")
            header = _SnapshotHeader.model_validate(raw_header)
            if (
                header.principal_scope_digest != manifest.coverage_receipt.principal_scope_digest
                or header.manifest_digest != manifest.manifest_digest
                or header.source_generation != source_generation
            ):
                raise ValueError("current source or principal manifest mismatch")
            metadata = _METADATA.validate_python(header.metadata)
            documents: list[CatalogSearchDocument] = []
            total_bytes = 0
            for ordinal, expected_digest in enumerate(header.chunk_digests):
                chunk = await self._store.read_state(_chunk_key(snapshot_digest, ordinal))
                if chunk is None or set(chunk) != {"documents"}:
                    raise ValueError("chunk missing or malformed")
                encoded = _encode(chunk)
                total_bytes += len(encoded)
                if len(encoded) > _MAX_CHUNK_BYTES or total_bytes > _MAX_SNAPSHOT_BYTES:
                    raise ValueError("snapshot byte limit exceeded")
                if _digest(chunk) != expected_digest:
                    raise ValueError("chunk digest mismatch")
                documents.extend(_DOCUMENTS.validate_python(chunk["documents"]))
                if len(documents) > header.document_count:
                    raise ValueError("snapshot document count exceeded")
            if len(documents) != header.document_count:
                raise ValueError("snapshot document count mismatch")
            build = SemanticGenerationBuild(
                metadata=metadata,
                documents=tuple(documents),
                document_digests=tuple(catalog_search_document_digest(item) for item in documents),
                reused_document_count=0,
            )
            _validate_build(build, manifest)
            return build
        except (TypeError, ValueError, KeyError):
            raise OntologySnapshotCorruptionError(
                "ontology snapshot failed exact staged-content validation"
            ) from None

    async def _write_immutable(self, key: str, value: Mapping[str, Any]) -> None:
        if await self._store.write_state_if_absent(key, value):
            return
        existing = await self._store.read_state(key)
        if existing is None or _encode(existing) != _encode(value):
            raise OntologySnapshotCorruptionError("ontology snapshot immutable write conflict")


def _validate_build(build: SemanticGenerationBuild, manifest: QueryManifest) -> None:
    if build.metadata.state != "staged":
        raise ValueError("ontology snapshot requires an inactive staged generation")
    if not 1 <= len(build.documents) <= _MAX_DOCUMENTS:
        raise ValueError("ontology snapshot document count is out of bounds")
    if len({item.rule_id for item in build.documents}) != len(build.documents):
        raise ValueError("ontology snapshot document identities MUST be unique")
    validate_ontology_semantic_generation(
        build=build, manifest=manifest, validator_id="ontology-snapshot-store-v1"
    )


def _chunk_documents(documents: tuple[CatalogSearchDocument, ...]) -> tuple[dict[str, Any], ...]:
    chunks: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    row_bytes = 0
    total_bytes = 0
    for document in documents:
        row = _DOCUMENTS.dump_python((document,), mode="json")[0]
        size = len(_encode(row))
        if size + 32 > _MAX_CHUNK_BYTES:
            raise ValueError("ontology snapshot document exceeds chunk byte limit")
        if rows and (len(rows) >= 128 or row_bytes + size + len(rows) + 32 > _MAX_CHUNK_BYTES):
            chunks.append({"documents": rows})
            total_bytes += len(_encode(chunks[-1]))
            rows, row_bytes = [], 0
        rows.append(row)
        row_bytes += size
        if total_bytes + row_bytes > _MAX_SNAPSHOT_BYTES or len(chunks) >= _MAX_CHUNKS:
            raise ValueError("ontology snapshot exceeds bounded staging capacity")
    if rows:
        chunks.append({"documents": rows})
    if sum(len(_encode(chunk)) for chunk in chunks) > _MAX_SNAPSHOT_BYTES:
        raise ValueError("ontology snapshot exceeds bounded staging capacity")
    return tuple(chunks)


def _chunk_key(snapshot_digest: str, ordinal: int) -> str:
    return f"{_PREFIX}{snapshot_digest}:chunk:{ordinal}"


def _encode(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(_encode(value)).hexdigest()
