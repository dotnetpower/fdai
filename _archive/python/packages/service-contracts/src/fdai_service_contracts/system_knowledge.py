"""Versioned no-authority contracts for FDAI system-knowledge queries."""

from __future__ import annotations

import math
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import Field, TypeAdapter, field_validator, model_validator

from fdai_service_contracts.ontology_query import QueryContract, content_digest

Digest = Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]
GitObjectId = Annotated[str, Field(pattern=r"^[a-f0-9]{40}$")]
MachineId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_.-]{0,127}$")]
_MAX_RECORDS = 128
_MAX_MATCHES = 8
_JSON_VALUE = TypeAdapter(Any)


def system_knowledge_digest(value: Any) -> str:
    """Digest Pydantic records and JSON values through one canonical projection."""

    return content_digest(_JSON_VALUE.dump_python(value, mode="json"))


class SystemKnowledgeStatus(StrEnum):
    """Delivery states that keep design and runtime validation distinct."""

    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    IMPLEMENTED = "implemented"
    VALIDATED = "validated"
    DEFERRED = "deferred"
    NOT_APPLICABLE = "not_applicable"


class SystemKnowledgeSourceKind(StrEnum):
    """Tracked source kinds admitted to a compiled catalog."""

    CODE = "code"
    TEST = "test"
    DOC = "doc"
    SCHEMA = "schema"
    CONFIG = "config"


class SystemKnowledgeAuthorityRole(StrEnum):
    """What one citation can prove about a knowledge record."""

    DESIGN = "design"
    IMPLEMENTATION = "implementation"
    VERIFICATION = "verification"
    CONFIGURATION = "configuration"


class SystemKnowledgeSource(QueryContract):
    """One bounded tracked-source citation without source body text."""

    source_kind: SystemKnowledgeSourceKind
    authority_role: SystemKnowledgeAuthorityRole
    path: Annotated[str, Field(min_length=1, max_length=512)]
    symbol: Annotated[str, Field(min_length=1, max_length=256)]
    line_start: Annotated[int, Field(ge=1)]
    line_end: Annotated[int, Field(ge=1)]
    blob_sha: GitObjectId

    @model_validator(mode="after")
    def _source_is_safe(self) -> SystemKnowledgeSource:
        if self.path.startswith("/") or ".." in self.path.split("/"):
            raise ValueError("system knowledge source path MUST be repository-relative")
        if self.line_end < self.line_start:
            raise ValueError("system knowledge source line range MUST be ordered")
        return self

    @property
    def evidence_ref(self) -> str:
        """Return a stable citation identity without exposing source content."""

        return f"repo:{self.blob_sha}:{self.path}:{self.line_start}-{self.line_end}:{self.symbol}"


class SystemKnowledgeRecord(QueryContract):
    """One answerable FDAI design and implementation behavior."""

    knowledge_id: MachineId
    subject_id: MachineId
    title: Annotated[str, Field(min_length=1, max_length=200)]
    status: SystemKnowledgeStatus
    owner: Annotated[str, Field(min_length=1, max_length=128)]
    question_aliases: Annotated[
        tuple[Annotated[str, Field(min_length=1, max_length=300)], ...],
        Field(min_length=1, max_length=24),
    ]
    designed_behavior: Annotated[
        tuple[Annotated[str, Field(min_length=1, max_length=1000)], ...],
        Field(min_length=1, max_length=12),
    ]
    implemented_behavior: Annotated[
        tuple[Annotated[str, Field(min_length=1, max_length=1000)], ...],
        Field(max_length=12),
    ] = ()
    limitations: Annotated[
        tuple[Annotated[str, Field(min_length=1, max_length=1000)], ...],
        Field(max_length=12),
    ] = ()
    sources: Annotated[tuple[SystemKnowledgeSource, ...], Field(min_length=1, max_length=12)]
    record_digest: Digest
    execution_authority: Literal[False] = False

    @field_validator(
        "question_aliases",
        "designed_behavior",
        "implemented_behavior",
        "limitations",
        mode="after",
    )
    @classmethod
    def _text_is_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("system knowledge text entries MUST be unique")
        return values

    @model_validator(mode="after")
    def _record_is_canonical(self) -> SystemKnowledgeRecord:
        source_refs = tuple(source.evidence_ref for source in self.sources)
        if source_refs != tuple(sorted(set(source_refs))):
            raise ValueError("system knowledge sources MUST be ordered and unique")
        expected = system_knowledge_digest(self.model_dump(mode="json", exclude={"record_digest"}))
        if self.record_digest != expected:
            raise ValueError("system knowledge record digest does not match content")
        return self


class SystemKnowledgeCatalog(QueryContract):
    """One immutable catalog compiled for an exact FDAI source revision."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    source_revision: GitObjectId
    generated_at: datetime
    records: Annotated[
        tuple[SystemKnowledgeRecord, ...],
        Field(min_length=1, max_length=_MAX_RECORDS),
    ]
    catalog_digest: Digest
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def _catalog_is_canonical(self) -> SystemKnowledgeCatalog:
        if self.generated_at.tzinfo is None or self.generated_at.utcoffset() is None:
            raise ValueError("system knowledge catalog time MUST be timezone-aware")
        record_ids = tuple(record.knowledge_id for record in self.records)
        if record_ids != tuple(sorted(set(record_ids))):
            raise ValueError("system knowledge records MUST be ordered and unique")
        aliases: set[str] = set()
        for record in self.records:
            for alias in record.question_aliases:
                normalized = alias.casefold().strip()
                if normalized in aliases:
                    raise ValueError("system knowledge exact aliases MUST be unique")
                aliases.add(normalized)
        expected = system_knowledge_digest(self.model_dump(mode="json", exclude={"catalog_digest"}))
        if self.catalog_digest != expected:
            raise ValueError("system knowledge catalog digest does not match content")
        return self


class SystemKnowledgeQueryRequest(QueryContract):
    """One bounded read-only query from an authenticated channel turn."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    query: Annotated[str, Field(min_length=1, max_length=4000)]
    locale: Literal["en", "ko"] = "en"
    limit: Annotated[int, Field(ge=1, le=_MAX_MATCHES)] = 4
    principal_scope_digest: Digest
    purpose: Literal["system-knowledge"] = "system-knowledge"
    execution_authority: Literal[False] = False


class SystemKnowledgeMatch(QueryContract):
    """One ranked catalog record returned without changing its evidence."""

    record: SystemKnowledgeRecord
    score: Annotated[float, Field(ge=0.0, le=10.0)]
    match_kind: Literal["exact_alias", "exact_identifier", "lexical"]

    @field_validator("score")
    @classmethod
    def _score_is_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("system knowledge score MUST be finite")
        return value


class SystemKnowledgeQueryResponse(QueryContract):
    """One terminal query result with catalog and response digests."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    outcome: Literal["answered", "empty", "held"]
    matches: Annotated[tuple[SystemKnowledgeMatch, ...], Field(max_length=_MAX_MATCHES)] = ()
    observed_at: datetime
    source_revision: GitObjectId
    catalog_digest: Digest
    complete: bool
    limitation: Annotated[str, Field(min_length=1, max_length=256)] | None = None
    response_digest: Digest
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def _response_is_canonical(self) -> SystemKnowledgeQueryResponse:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("system knowledge response time MUST be timezone-aware")
        if self.outcome == "answered" and not self.matches:
            raise ValueError("answered system knowledge response requires matches")
        if self.outcome != "answered" and self.matches:
            raise ValueError("non-answered system knowledge response MUST NOT carry matches")
        if self.complete == (self.limitation is not None):
            raise ValueError("system knowledge completeness and limitation are inconsistent")
        scores = tuple(match.score for match in self.matches)
        if scores != tuple(sorted(scores, reverse=True)):
            raise ValueError("system knowledge matches MUST be ordered by score")
        expected = system_knowledge_digest(
            self.model_dump(mode="json", exclude={"response_digest"})
        )
        if self.response_digest != expected:
            raise ValueError("system knowledge response digest does not match content")
        return self


__all__ = [
    "SystemKnowledgeAuthorityRole",
    "SystemKnowledgeCatalog",
    "SystemKnowledgeMatch",
    "SystemKnowledgeQueryRequest",
    "SystemKnowledgeQueryResponse",
    "SystemKnowledgeRecord",
    "SystemKnowledgeSource",
    "SystemKnowledgeSourceKind",
    "SystemKnowledgeStatus",
    "system_knowledge_digest",
]
