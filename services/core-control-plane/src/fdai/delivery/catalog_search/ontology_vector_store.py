"""Inactive, source-bound vector persistence outside the Rule search corpora."""

from __future__ import annotations

import asyncio
import math
import re
from collections.abc import Mapping
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from fdai.core.ontology_platform import QueryManifest
from fdai.shared.providers.catalog_search import CatalogGenerationMetadata, Embedder
from fdai.shared.providers.state_store import StateStore

from .ontology_snapshot_store import OntologyGenerationSnapshotStore, _digest, _encode

_PREFIX = "ontology-semantic-vectors:v1:"
_MAX_HEADER_BYTES = 8 * 1024 * 1024
_Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class _VectorRow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    binding_digest: _Digest
    document_id: str = Field(min_length=1, max_length=1024)
    document_digest: _Digest
    vector: tuple[float, ...] = Field(min_length=1, max_length=65536)


class _VectorHeader(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(pattern=r"^1\.0\.0$")
    snapshot_digest: _Digest
    generation_digest: _Digest
    binding_digest: _Digest
    rows: dict[str, _Digest] = Field(min_length=1, max_length=20_000)


class OntologyVectorSnapshotStore:
    """Persist bounded embedding rows and publish their completion header last.

    The configured embedding identity must equal the source generation identity.
    Exact retries reuse immutable completed rows without another provider call.
    Reads verify the full header and only the requested rows, at most 1,000.
    This store neither certifies embedding relevance nor activates any generation.
    """

    def __init__(
        self,
        store: StateStore,
        *,
        embedder: Embedder,
        embedding_space_id: str,
        embedding_model_version: str,
        embedding_dimension: int,
        call_timeout_seconds: float = 10.0,
        build_timeout_seconds: float = 120.0,
    ) -> None:
        if (
            not embedding_space_id.strip()
            or not embedding_model_version.strip()
            or len(embedding_space_id) > 256
            or len(embedding_model_version) > 256
            or not 1 <= embedding_dimension <= 65536
            or not math.isfinite(call_timeout_seconds)
            or not math.isfinite(build_timeout_seconds)
            or not 0 < call_timeout_seconds <= build_timeout_seconds <= 7200
        ):
            raise ValueError("ontology vectors require bounded embedding identity and deadlines")
        self._store = store
        self._embedder = embedder
        self._identity = (embedding_space_id, embedding_model_version, embedding_dimension)
        self._call_timeout = call_timeout_seconds
        self._build_timeout = build_timeout_seconds

    async def stage(
        self,
        *,
        snapshots: OntologyGenerationSnapshotStore,
        snapshot_digest: str,
        manifest: QueryManifest,
        source_generation: str,
        source_projection_digest: str | None = None,
    ) -> str:
        """Embed one complete source snapshot; expired attempts never return success.

        Provider exceptions expose only a stable unavailable reason. Parent
        cancellation propagates, and total and per-call deadlines bound work.
        Persisted partial artifacts remain inert and reusable; a late storage return
        does not prove that its write was rolled back.
        """
        deadline = asyncio.get_running_loop().time() + self._build_timeout
        async with asyncio.timeout(self._build_timeout):
            build = await snapshots.read(
                snapshot_digest,
                manifest=manifest,
                source_generation=source_generation,
                source_projection_digest=source_projection_digest,
            )
            _check_deadline(deadline)
            if build is None:
                raise ValueError("ontology vectors require a complete source snapshot")
            binding = self._binding(snapshot_digest, build.metadata)
            retired = await self._store.read_state(f"{_PREFIX}{binding}:retired")
            _check_deadline(deadline)
            if retired is not None:
                raise ValueError("ontology vectors were retired and cannot be restaged")
            if any(item.embedding or item.generation_id is not None for item in build.documents):
                raise ValueError("ontology vectors require canonical unembedded source documents")
            completion_key = f"{_PREFIX}{binding}:complete"
            completion = await self._store.read_state(completion_key)
            _check_deadline(deadline)
            if completion is not None:
                if set(completion) != {"vector_digest"} or not isinstance(
                    completion["vector_digest"], str
                ):
                    raise ValueError("ontology vector completion identity mismatch")
                completed_digest = completion["vector_digest"]
                for offset in range(0, len(build.documents), 1000):
                    _check_deadline(deadline)
                    await self.read(
                        completed_digest,
                        snapshot_digest=snapshot_digest,
                        generation=build.metadata,
                        document_ids=tuple(
                            item.rule_id for item in build.documents[offset : offset + 1000]
                        ),
                    )
                    _check_deadline(deadline)
                return completed_digest
            rows: dict[str, str] = {}
            for document, document_digest in zip(
                build.documents, build.document_digests, strict=True
            ):
                _check_deadline(deadline)
                key = _row_key(binding, document.rule_id)
                raw = await self._store.read_state(key)
                _check_deadline(deadline)
                if raw is None:
                    vector = await self._embed(document.text, deadline=deadline)
                    row = _VectorRow(
                        binding_digest=binding,
                        document_id=document.rule_id,
                        document_digest=document_digest,
                        vector=vector,
                    )
                    _check_deadline(deadline)
                    await self._store.write_state_if_absent(key, row.model_dump(mode="json"))
                    _check_deadline(deadline)
                    raw = await self._store.read_state(key)
                    _check_deadline(deadline)
                row = _parse_row(raw, binding, document.rule_id, self._identity[2])
                if row.document_digest != document_digest:
                    raise ValueError("ontology vector source document identity mismatch")
                rows[document.rule_id] = _digest(row.model_dump(mode="json"))
            header = _VectorHeader(
                schema_version="1.0.0",
                snapshot_digest=snapshot_digest,
                generation_digest=build.metadata.generation_digest,
                binding_digest=binding,
                rows=rows,
            ).model_dump(mode="json")
            if len(_encode(header)) > _MAX_HEADER_BYTES:
                raise ValueError("ontology vector header exceeds bounded capacity")
            digest = _digest(header)
            key = f"{_PREFIX}{digest}:header"
            _check_deadline(deadline)
            inserted = await self._store.write_state_if_absent(key, header)
            _check_deadline(deadline)
            if not inserted:
                existing = await self._store.read_state(key)
                _check_deadline(deadline)
                if existing is None or _digest(existing) != digest:
                    raise ValueError("ontology vector immutable header conflict")
            completion_value = {"vector_digest": digest}
            _check_deadline(deadline)
            inserted = await self._store.write_state_if_absent(completion_key, completion_value)
            _check_deadline(deadline)
            if not inserted:
                existing = await self._store.read_state(completion_key)
                _check_deadline(deadline)
                if existing != completion_value:
                    raise ValueError("ontology vector immutable completion conflict")
            return digest

    async def read(
        self,
        vector_digest: str,
        *,
        snapshot_digest: str,
        generation: CatalogGenerationMetadata,
        document_ids: tuple[str, ...],
    ) -> dict[str, tuple[float, ...]]:
        """Read exact requested vectors; missing or changed rows never become empty hits."""
        deadline = asyncio.get_running_loop().time() + self._call_timeout
        async with asyncio.timeout(self._call_timeout):
            result = await self._read(
                vector_digest,
                snapshot_digest=snapshot_digest,
                generation=generation,
                document_ids=document_ids,
                deadline=deadline,
            )
            _check_deadline(deadline)
            return result

    async def embed_query(
        self, query: str, *, generation: CatalogGenerationMetadata
    ) -> tuple[float, ...]:
        """Embed a bounded query only in the exact configured generation space."""
        if not query.strip() or len(query.encode("utf-8")) > 16_384:
            raise ValueError("ontology vector query is empty or exceeds its byte bound")
        if self._identity != (
            generation.embedding_space_id,
            generation.embedding_model_version,
            generation.embedding_dimension,
        ):
            raise ValueError("ontology vector configured embedding identity mismatch")
        return await self._embed(query)

    async def _embed(self, text: str, *, deadline: float | None = None) -> tuple[float, ...]:
        call_deadline = asyncio.get_running_loop().time() + self._call_timeout
        if deadline is not None:
            call_deadline = min(deadline, call_deadline)
        try:
            _check_deadline(call_deadline)
            async with asyncio.timeout(call_deadline - asyncio.get_running_loop().time()):
                vector = tuple(await self._embedder.embed(text))
            _validate_vector(vector, self._identity[2])
            _check_deadline(call_deadline)
            return vector
        except Exception:
            raise ValueError("ontology embedding provider unavailable") from None

    async def _read(
        self,
        vector_digest: str,
        *,
        snapshot_digest: str,
        generation: CatalogGenerationMetadata,
        document_ids: tuple[str, ...],
        deadline: float,
    ) -> dict[str, tuple[float, ...]]:
        if (
            re.fullmatch(r"sha256:[0-9a-f]{64}", vector_digest) is None
            or not 1 <= len(document_ids) <= 1000
            or len(document_ids) != len(set(document_ids))
        ):
            raise ValueError("ontology vector reads require bounded unique document identities")
        binding = self._binding(snapshot_digest, generation)
        raw = await self._store.read_state(f"{_PREFIX}{vector_digest}:header")
        _check_deadline(deadline)
        try:
            if (
                raw is None
                or len(_encode(raw)) > _MAX_HEADER_BYTES
                or _digest(raw) != vector_digest
            ):
                raise ValueError("invalid header")
            header = _VectorHeader.model_validate(raw)
            if (
                header.snapshot_digest != snapshot_digest
                or header.generation_digest != generation.generation_digest
                or header.binding_digest != binding
                or len(header.rows) != generation.document_digest_manifest.document_count
            ):
                raise ValueError("invalid identity")
            result: dict[str, tuple[float, ...]] = {}
            for document_id in document_ids:
                _check_deadline(deadline)
                stored = await self._store.read_state(_row_key(binding, document_id))
                _check_deadline(deadline)
                if stored is None or _digest(stored) != header.rows[document_id]:
                    raise ValueError("invalid row")
                row = _parse_row(stored, binding, document_id, self._identity[2])
                result[document_id] = row.vector
            return result
        except (ValueError, TypeError, KeyError):
            raise ValueError("ontology vector snapshot content or identity mismatch") from None

    def _binding(self, snapshot_digest: str, generation: CatalogGenerationMetadata) -> str:
        if re.fullmatch(r"sha256:[0-9a-f]{64}", snapshot_digest) is None:
            raise ValueError("ontology vector source identity requires a full sha256 digest")
        if self._identity != (
            generation.embedding_space_id,
            generation.embedding_model_version,
            generation.embedding_dimension,
        ):
            raise ValueError("ontology vector configured embedding identity mismatch")
        return _digest(
            {"snapshot_digest": snapshot_digest, "generation_digest": generation.generation_digest}
        )


def _check_deadline(deadline: float) -> None:
    if asyncio.get_running_loop().time() >= deadline:
        raise TimeoutError("ontology retrieval deadline exceeded")


def _row_key(binding: str, document_id: str) -> str:
    return f"{_PREFIX}{binding}:row:{_digest(document_id)}"


def _validate_vector(vector: tuple[float, ...], dimension: int) -> None:
    if (
        len(vector) != dimension
        or any(isinstance(value, bool) or not math.isfinite(value) for value in vector)
        or not 0 < math.hypot(*vector) < math.inf
    ):
        raise ValueError("ontology vector requires finite nonzero values and exact dimensions")


def _parse_row(
    raw: Mapping[str, Any] | None, binding: str, document_id: str, dimension: int
) -> _VectorRow:
    try:
        row = _VectorRow.model_validate(raw)
        if row.binding_digest != binding or row.document_id != document_id:
            raise ValueError("invalid row identity")
        _validate_vector(row.vector, dimension)
        return row
    except (ValueError, TypeError):
        raise ValueError("ontology vector row content or identity mismatch") from None
