"""Exact-text offline replay from pinned private diagnostics, never a live fallback."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictFloat

from .ontology_evaluation_evidence import (
    _MAX_RECORD_BYTES,
    _RECORD,
    _read_private_evidence_bytes,
)
from .ontology_vector_store import _validate_vector

_Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class _EmbeddingResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    call_index: int = Field(strict=True, ge=1, le=128)
    text_digest: _Digest
    embedding_space_id: str = Field(min_length=1, max_length=256)
    embedding_model_version: str = Field(min_length=1, max_length=256)
    embedding_dimension: int = Field(strict=True, ge=1, le=65536)
    vector: tuple[StrictFloat, ...] = Field(min_length=1, max_length=65536)


def embedding_result_payload(
    text: str,
    vector: Sequence[float],
    *,
    call_index: int,
    identity: tuple[str, str, int],
) -> dict[str, object]:
    """Validate before persisting exact provider output; never include the input text."""
    frozen = tuple(vector)
    _validate_vector(frozen, identity[2])
    return _EmbeddingResult(
        call_index=call_index,
        text_digest=_text_digest(text),
        embedding_space_id=identity[0],
        embedding_model_version=identity[1],
        embedding_dimension=identity[2],
        vector=frozen,
    ).model_dump(mode="json")


def _text_digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


class OntologyEvaluationReplayEmbedder:
    """Immutable offline lookups; a miss, changed model or incomplete evidence fails closed.

    The caller pins the whole evidence file and recorded source/model identity. These
    checks establish byte consistency, not provider attestation or production authority.
    A replay does not refresh vector provenance and must not be reported as live calls.
    """

    def __init__(
        self,
        *,
        vectors: Mapping[str, tuple[float, ...]],
        identity: tuple[str, str, int],
        evidence_digest: str,
    ) -> None:
        self.embedding_space_id, self.embedding_model_version, self.dim = identity
        self.evidence_digest = evidence_digest
        self._vectors = MappingProxyType(dict(vectors))

    async def embed(self, text: str) -> tuple[float, ...]:
        vector = self._vectors.get(_text_digest(text))
        if vector is None:
            raise ValueError("ontology offline replay has no vector for the exact input")
        return vector

    @classmethod
    def from_evidence(
        cls,
        path: Path,
        *,
        expected_file_digest: str,
        expected_source_commit: str,
        expected_identity: tuple[str, str, int],
    ) -> OntologyEvaluationReplayEmbedder:
        """Load only complete, pinned, private regular files with matched call/result pairs."""
        if (
            re.fullmatch(r"sha256:[0-9a-f]{64}", expected_file_digest) is None
            or re.fullmatch(r"[0-9a-f]{40}", expected_source_commit) is None
        ):
            raise ValueError("ontology replay requires full file and source digests")
        raw = _read_private_evidence_bytes(path, expected_file_digest)
        try:
            lines = raw.splitlines()
            if (
                not raw.endswith(b"\n")
                or not 4 <= len(lines) <= 262
                or any(len(line) + 1 > _MAX_RECORD_BYTES for line in lines)
            ):
                raise ValueError("incomplete evidence")
            records = [_RECORD.validate_json(line) for line in lines]
            if records[0].event != "started" or records[-1].event != "completed":
                raise ValueError("incomplete evidence")
            vectors: dict[str, tuple[float, ...]] = {}
            intents = completed = 0
            for index, record in enumerate(records):
                if record.sequence != index or record.source_commit != expected_source_commit:
                    raise ValueError("changed record identity")
                if 0 < index < len(records) - 1 and record.event in (
                    "started",
                    "completed",
                    "aborted",
                    "cancelled",
                ):
                    raise ValueError("invalid terminal ordering")
                if record.event == "embedding_call_intent":
                    call_index = record.payload.get("call_index")
                    if (
                        type(call_index) is not int
                        or call_index != intents + 1
                        or intents != completed
                    ):
                        raise ValueError("unpaired embedding intent")
                    intents += 1
                elif record.event == "embedding_result":
                    result = _EmbeddingResult.model_validate(record.payload)
                    if result.call_index != completed + 1 or result.call_index != intents:
                        raise ValueError("unpaired embedding result")
                    if (
                        result.embedding_space_id,
                        result.embedding_model_version,
                        result.embedding_dimension,
                    ) != expected_identity:
                        raise ValueError("changed model identity")
                    _validate_vector(result.vector, result.embedding_dimension)
                    existing = vectors.get(result.text_digest)
                    if existing is not None and existing != result.vector:
                        raise ValueError("conflicting vectors for identical text")
                    vectors[result.text_digest] = result.vector
                    completed += 1
                elif record.event == "stage" and completed != intents:
                    raise ValueError("stage has an incomplete embedding")
            report = records[-1].payload.get("report")
            calls = report.get("embedding_calls") if isinstance(report, dict) else None
            if (
                not vectors
                or intents != completed
                or type(calls) is not int
                or calls != completed
                or not isinstance(report, dict)
                or report.get("embedding_source") != "caller_supplied"
            ):
                raise ValueError("incomplete vector retention")
        except ValueError:
            raise ValueError(
                "ontology replay evidence is incomplete, invalid or inconsistent"
            ) from None
        return cls(
            vectors=vectors, identity=expected_identity, evidence_digest=expected_file_digest
        )
