"""Immutable, isolated staging snapshots; never a search or activation authority."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from fdai.core.ontology_platform import QueryManifest
from fdai.core.ontology_platform.models import ObjectSelectorKind, ObjectSetDefinition
from fdai.core.ontology_platform.query_gateway import SecuredObjectSetQueryGateway
from fdai.shared.ontology.acl import ProjectionRequest
from fdai.shared.providers.catalog_search import (
    CatalogGenerationMetadata,
    CatalogSearchDocument,
    catalog_search_document_digest,
)
from fdai.shared.providers.ontology_instance import OntologyObjectRecord
from fdai.shared.providers.state_store import StateStore

from .generation import (
    SemanticGenerationBuild,
    build_ontology_semantic_generation,
    validate_ontology_semantic_generation,
)

_PREFIX = "ontology-semantic-snapshot:v1:"
_MAX_CHUNK_BYTES = 512 * 1024
_MAX_SNAPSHOT_BYTES = 64 * 1024 * 1024
_MAX_DOCUMENTS = 20_000
_MAX_CHUNKS = 512
_DOCUMENTS = TypeAdapter(tuple[CatalogSearchDocument, ...])
_METADATA = TypeAdapter(CatalogGenerationMetadata)


class OntologySnapshotCorruptionError(ValueError):
    """Stored staging data is incomplete, malformed, or inconsistent with its identity."""


@dataclass(frozen=True, slots=True)
class OntologyStagedProjection:
    """Content identities for one complete secured type projection, not activation."""

    snapshot_digest: str
    source_projection_digest: str
    source_generation: str


class _SnapshotHeader(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(pattern=r"^1\.0\.0$")
    principal_scope_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    manifest_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    source_generation: str = Field(min_length=1, max_length=256)
    source_projection_digest: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
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

    async def stage_manifest_from_gateway(
        self,
        *,
        gateway: SecuredObjectSetQueryGateway,
        manifest: QueryManifest,
        as_of: datetime,
        expected_source_generation: str,
        embedding_space_id: str,
        embedding_model_version: str,
        embedding_dimension: int,
    ) -> OntologyStagedProjection:
        """Stage all readable types from one complete source snapshot, never mixed pages.

        The combined declaration/object budget remains 20,000 documents. No write
        occurs until ACL, release, scope, and exact source generation checks pass.
        """
        names = tuple(
            sorted(str(item["name"]) for item in manifest.descriptors if item["kind"] == "object")
        )
        available = _MAX_DOCUMENTS - len(manifest.descriptors) - len(manifest.unavailable)
        if not names or len(manifest.purposes) != 1 or available < 1:
            raise ValueError("ontology staging requires one purpose and a bounded type manifest")
        projected = await gateway.scan_snapshot(
            object_type_names=names,
            purpose=manifest.purposes[0],
            as_of=as_of,
            candidate_limit=available,
            projection_request=ProjectionRequest(
                caller_role=manifest.principal_role,
                declared_purposes=frozenset(manifest.purposes),
                principal_scope_digest=manifest.coverage_receipt.principal_scope_digest,
            ),
        )
        if (
            projected.ontology_release_digest != manifest.release_digest
            or projected.principal_scope_digest != manifest.coverage_receipt.principal_scope_digest
            or projected.graph.source_generation != expected_source_generation
            or projected.caller_role != manifest.principal_role
            or projected.purpose != manifest.purposes[0]
            or projected.object_type_names != names
        ):
            raise ValueError(
                "ontology staging requires current complete authorized source evidence"
            )
        records = tuple(
            OntologyObjectRecord(
                id=record.id,
                object_type=record.object_type,
                properties={
                    key: value
                    for key, value in record.properties.items()
                    if key != "__redactions__"
                    and key not in record.properties.get("__redactions__", {})
                },
            )
            for record in projected.graph.objects
        )
        build = build_ontology_semantic_generation(
            manifest=manifest,
            runtime_objects=records,
            embedding_space_id=embedding_space_id,
            embedding_model_version=embedding_model_version,
            embedding_dimension=embedding_dimension,
        )
        snapshot_digest = await self.stage(
            build=build,
            manifest=manifest,
            source_generation=expected_source_generation,
            source_projection_digest=projected.source_projection_digest,
        )
        return OntologyStagedProjection(
            snapshot_digest,
            projected.source_projection_digest,
            expected_source_generation,
        )

    async def stage_from_gateway(
        self,
        *,
        gateway: SecuredObjectSetQueryGateway,
        definition: ObjectSetDefinition,
        manifest: QueryManifest,
        expected_source_generation: str,
        embedding_space_id: str,
        embedding_model_version: str,
        embedding_dimension: int,
    ) -> OntologyStagedProjection:
        """Read and stage one complete type through the authoritative ACL gateway.

        Only unfiltered single-type projections are supported; the existing 1,000
        object query ceiling is not bypassed. Truncation, missing generations, role,
        scope, purpose, and release drift fail before persistence. Redacted property
        values never enter documents. Multi-type aggregation, paging, embedding, and
        owner-event activation are separate operations, not implied by this receipt.
        """

        if (
            definition.selector.kind is not ObjectSelectorKind.OBJECT_TYPE
            or definition.predicates
            or definition.object_ids is not None
            or definition.traversal is not None
            or definition.include_relationships
            or manifest.purposes != (definition.purpose,)
            or not expected_source_generation.strip()
            or len(expected_source_generation) > 256
            or not any(
                item["kind"] == "object" and item["name"] == definition.selector.name
                for item in manifest.descriptors
            )
        ):
            raise ValueError("ontology staging requires a complete single-purpose type selection")
        result = await gateway.materialize(
            definition,
            projection_request=ProjectionRequest(
                caller_role=manifest.principal_role,
                declared_purposes=frozenset(manifest.purposes),
                principal_scope_digest=manifest.coverage_receipt.principal_scope_digest,
            ),
        )
        receipt = result.receipt
        if (
            not receipt.complete
            or receipt.truncated
            or not receipt.source_complete
            or receipt.redactions.redacted_identity_count
            or receipt.ontology_release.digest != manifest.release_digest
            or receipt.caller_role != manifest.principal_role
            or receipt.purpose != definition.purpose
            or receipt.principal_scope_digest != manifest.coverage_receipt.principal_scope_digest
            or receipt.source_generation != expected_source_generation
        ):
            raise ValueError(
                "ontology staging requires current complete authorized source evidence"
            )
        records = tuple(
            OntologyObjectRecord(
                id=record.id,
                object_type=record.object_type,
                properties={
                    key: value
                    for key, value in record.properties.items()
                    if key != "__redactions__"
                    and key not in record.properties.get("__redactions__", {})
                },
            )
            for record in result.materialization.graph.objects
        )
        build = build_ontology_semantic_generation(
            manifest=manifest,
            runtime_objects=records,
            embedding_space_id=embedding_space_id,
            embedding_model_version=embedding_model_version,
            embedding_dimension=embedding_dimension,
        )
        snapshot_digest = await self.stage(
            build=build,
            manifest=manifest,
            source_generation=expected_source_generation,
            source_projection_digest=receipt.projected_result_digest,
        )
        return OntologyStagedProjection(
            snapshot_digest, receipt.projected_result_digest, expected_source_generation
        )

    async def stage(
        self,
        *,
        build: SemanticGenerationBuild,
        manifest: QueryManifest,
        source_generation: str,
        source_projection_digest: str | None = None,
    ) -> str:
        """Persist an inactive complete snapshot and return its full content digest."""

        _validate_build(build, manifest)
        chunks = _chunk_documents(build.documents)
        header = _SnapshotHeader(
            schema_version="1.0.0",
            principal_scope_digest=manifest.coverage_receipt.principal_scope_digest,
            manifest_digest=manifest.manifest_digest,
            source_generation=source_generation,
            source_projection_digest=source_projection_digest,
            metadata=_METADATA.dump_python(build.metadata, mode="json"),
            chunk_digests=tuple(_digest(chunk) for chunk in chunks),
            document_count=len(build.documents),
        ).model_dump(mode="json")
        snapshot_digest = _digest(header)
        if await self._store.read_state(f"{_PREFIX}{snapshot_digest}:retired") is not None:
            raise ValueError("ontology snapshot was retired and cannot be restaged")
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
        source_projection_digest: str | None = None,
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
                or header.source_projection_digest != source_projection_digest
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
