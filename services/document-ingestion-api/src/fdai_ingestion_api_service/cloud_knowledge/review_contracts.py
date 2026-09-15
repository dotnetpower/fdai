"""Closed local preparation records; a processing result never grants operational admission."""

from __future__ import annotations

from datetime import datetime
from pathlib import PurePosixPath
from typing import Annotated, Literal, Self

from fdai_service_contracts.cloud_knowledge import (
    CloudSourceEvidence,
    Digest,
    Identifier,
    KnowledgeContract,
)
from fdai_service_contracts.cloud_knowledge_structure import (
    CloudStructuredDocument,
    StructuredNormalizerVersion,
)
from pydantic import Field, StrictInt, field_validator, model_validator

MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_SOURCE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_SOURCE_BYTES = 64 * 1024 * 1024
MAX_CANDIDATE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_OUTPUT_BYTES = 64 * 1024 * 1024
MAX_WORKER_BYTES = 32 * 1024 * 1024


class ReviewError(ValueError):
    """A content-free local input/output or resource-boundary failure."""


def relative_path(value: str) -> str:
    """Require one canonical bounded relative POSIX path without links or traversal semantics."""
    path = PurePosixPath(value)
    if (
        not value
        or not path.parts
        or len(value) > 1024
        or not value.isascii()
        or path.is_absolute()
        or value != path.as_posix()
        or len(path.parts) > 32
        or any(part in {".", ".."} for part in path.parts)
        or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value)
        or any(char in value for char in ("\\", ":", "%"))
    ):
        raise ValueError("review input paths must be canonical relative POSIX paths")
    return value


class ReviewSource(KnowledgeContract):
    """A retained collector snapshot addressed by two local hash-verified files."""

    evidence: CloudSourceEvidence
    title: Annotated[str, Field(min_length=1, max_length=256)]
    original_path: str
    normalized_path: str

    _paths = field_validator("original_path", "normalized_path")(relative_path)


class ReviewPlan(KnowledgeContract):
    """A frozen source denominator, not a registry or a smaller post-failure release scope."""

    schema_version: Literal["fdai.cloud-knowledge-review.v1"] = "fdai.cloud-knowledge-review.v1"
    sources: Annotated[tuple[ReviewSource, ...], Field(min_length=1, max_length=256)]

    @model_validator(mode="after")
    def unique_sources(self) -> Self:
        identities = [source.evidence.source_id for source in self.sources]
        if len(set(identities)) != len(identities):
            raise ValueError("review source identities must be unique")
        return self


class ExcerptMetrics(KnowledgeContract):
    """Measurements from complete derivation inside the resource-limited worker."""

    excerpts: Annotated[StrictInt, Field(ge=1, le=8192)]
    maximum_excerpt_bytes: Annotated[StrictInt, Field(ge=1, le=8192)]
    derived_bytes: Annotated[StrictInt, Field(ge=1, le=16 * 1024 * 1024)]

    @model_validator(mode="after")
    def totals(self) -> Self:
        if (
            not self.maximum_excerpt_bytes
            <= self.derived_bytes
            <= (self.excerpts * self.maximum_excerpt_bytes)
        ):
            raise ValueError("excerpt measurements have inconsistent byte totals")
        return self


class WorkerResult(KnowledgeContract):
    """Bounded child-process output; candidates remain original-free even when held."""

    document: CloudStructuredDocument | None = None
    reason: Literal["normalization_rejected", "excerpt_derivation_rejected"] | None = None
    metrics: ExcerptMetrics | None = None

    @model_validator(mode="after")
    def terminal(self) -> Self:
        if self.document is None:
            if self.reason != "normalization_rejected" or self.metrics is not None:
                raise ValueError("missing review document requires a normalization rejection")
        elif self.reason == "normalization_rejected":
            raise ValueError("a rejected normalization cannot claim a document")
        elif self.document.unresolved_dependencies:
            if self.reason is not None or self.metrics is not None:
                raise ValueError("unresolved documents cannot claim excerpt derivation")
        elif (self.metrics is None) != (self.reason == "excerpt_derivation_rejected"):
            raise ValueError("resolved documents require excerpt measurements or a rejection")
        if self.metrics is not None and (
            self.document is None or self.metrics.excerpts != len(self.document.blocks)
        ):
            raise ValueError("excerpt measurements must cover every document block")
        return self


class SourceReview(KnowledgeContract):
    """A per-source processing receipt; absent metrics are unknown, not measured zero."""

    source_id: Identifier
    source_sha256: Digest
    collected_at: datetime
    checked_at: datetime
    outcome: Literal["processable", "held", "not_processed"]
    holds: Annotated[tuple[Identifier, ...], Field(max_length=64)] = ()
    candidate_path: str | None = None
    candidate_sha256: Digest | None = None
    processing_digest: Digest | None = None
    blocks: Annotated[StrictInt, Field(ge=1, le=8192)] | None = None
    excerpts: Annotated[StrictInt, Field(ge=1, le=8192)] | None = None
    maximum_excerpt_bytes: Annotated[StrictInt, Field(ge=1, le=8192)] | None = None
    derived_bytes: Annotated[StrictInt, Field(ge=1, le=16 * 1024 * 1024)] | None = None

    @model_validator(mode="after")
    def disposition(self) -> Self:
        if self.checked_at < self.collected_at or len(set(self.holds)) != len(self.holds):
            raise ValueError("source review chronology or hold identity is invalid")
        if (self.outcome == "processable") != (not self.holds):
            raise ValueError("a non-processable source requires a hold reason")
        if (self.candidate_path is None) != (self.candidate_sha256 is None):
            raise ValueError("candidate paths and hashes must be paired")
        if self.candidate_path is not None:
            relative_path(self.candidate_path)
        if self.outcome == "processable" and (
            self.candidate_path is None
            or self.excerpts is None
            or self.processing_digest is None
            or self.blocks is None
            or self.maximum_excerpt_bytes is None
            or self.derived_bytes is None
        ):
            raise ValueError("processable source requires candidate and excerpt evidence")
        if self.outcome == "not_processed" and any(
            value is not None
            for value in (self.candidate_path, self.processing_digest, self.blocks, self.excerpts)
        ):
            raise ValueError("unprocessed sources cannot claim generated artifacts")
        if self.outcome != "processable" and any(
            value is not None
            for value in (self.excerpts, self.maximum_excerpt_bytes, self.derived_bytes)
        ):
            raise ValueError("non-processable sources cannot claim excerpt measurements")
        return self


class ReviewReport(KnowledgeContract):
    """Complete local accounting, explicitly separate from rights, approvals and answer quality."""

    schema_version: Literal["fdai.cloud-knowledge-review-report.v1"] = (
        "fdai.cloud-knowledge-review-report.v1"
    )
    input_sha256: Digest
    normalizer_version: StructuredNormalizerVersion
    started_at: datetime
    completed_at: datetime
    sources: Annotated[tuple[SourceReview, ...], Field(min_length=1, max_length=256)]
    requested: Annotated[StrictInt, Field(ge=1, le=256)]
    processable: Annotated[StrictInt, Field(ge=0, le=256)]
    held: Annotated[StrictInt, Field(ge=0, le=256)]
    not_processed: Annotated[StrictInt, Field(ge=0, le=256)]
    source_bytes_read: Annotated[StrictInt, Field(ge=0, le=MAX_TOTAL_SOURCE_BYTES)]
    candidate_bytes_written: Annotated[StrictInt, Field(ge=0, le=MAX_TOTAL_OUTPUT_BYTES)]
    review_required: Literal[True] = True
    source_rights_verified: Literal[False] = False
    independent_review_verified: Literal[False] = False
    production_qualified: Literal[False] = False
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def accounting(self) -> Self:
        if self.completed_at < self.started_at or self.requested != len(self.sources):
            raise ValueError("review chronology or denominator is invalid")
        if len({item.source_id for item in self.sources}) != self.requested:
            raise ValueError("review source identities must be unique")
        for outcome in ("processable", "held", "not_processed"):
            if getattr(self, outcome) != sum(item.outcome == outcome for item in self.sources):
                raise ValueError("review counts must match exact source outcomes")
        return self
