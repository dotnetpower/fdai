"""Principal-scoped governed document retrieval for semantic conversations."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Protocol, cast

from fdai_service_contracts.ontology_query import content_digest

from fdai.core.ontology_platform.functions import (
    ContextualOntologyFunction,
    FunctionInvocationContext,
)
from fdai.core.ontology_platform.query_values import QueryRow, QueryTable
from fdai.shared.contracts.models import (
    CeilingRole,
    LogicExecutionClass,
    OntologyDeclarationKind,
    OntologyFunctionKind,
    OntologyFunctionType,
    OntologyRelease,
)

GOVERNED_DOCUMENT_FUNCTION_NAME = "query.governed_documents"
GOVERNED_DOCUMENT_MEASURE_CONCEPT = "document.governed_excerpt"
GOVERNED_DOCUMENT_EVIDENCE_MODES = frozenset({"optional", "required", "explicit"})
GOVERNED_DOCUMENT_MAX_EXCERPTS = 8
_MAX_EXCERPT_BYTES = 8_192
_MAX_REF_LENGTH = 512
_EVIDENCE_REF = re.compile(r"document:sha256:[a-f0-9]{64}")
_DOCUMENT_REVISION = re.compile(
    r"version:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}:"
    r"sha256:[a-f0-9]{64}"
)


@dataclass(frozen=True, slots=True)
class GovernedDocumentExcerpt:
    """One authorized immutable document excerpt with exact citation identity."""

    evidence_ref: str
    document_revision: str
    source_name: str
    source_ref: str
    locator: str
    chunk_id: str
    text: str
    content_digest: str
    score: float
    instruction_authority: Literal[False] = False

    def __post_init__(self) -> None:
        for name, value in (
            ("evidence_ref", self.evidence_ref),
            ("document_revision", self.document_revision),
            ("source_name", self.source_name),
            ("source_ref", self.source_ref),
            ("locator", self.locator),
            ("chunk_id", self.chunk_id),
        ):
            if not value.strip() or len(value) > _MAX_REF_LENGTH:
                raise ValueError(f"governed document {name} MUST be bounded and non-empty")
        if not self.text or len(self.text.encode("utf-8")) > _MAX_EXCERPT_BYTES:
            raise ValueError("governed document excerpt text MUST be bounded and non-empty")
        if not self.content_digest.startswith("sha256:") or len(self.content_digest) != 71:
            raise ValueError("governed document content digest MUST be SHA-256")
        if _EVIDENCE_REF.fullmatch(self.evidence_ref) is None:
            raise ValueError("governed document evidence ref MUST be content-addressed")
        if _DOCUMENT_REVISION.fullmatch(self.document_revision) is None:
            raise ValueError("governed document revision MUST be immutable and content-addressed")
        if not math.isfinite(self.score):
            raise ValueError("governed document score MUST be finite")
        if self.instruction_authority is not False:
            raise ValueError("governed document excerpts MUST NOT have instruction authority")


@dataclass(frozen=True, slots=True)
class GovernedDocumentCollection:
    """Bounded authorized retrieval result and its index/access identity."""

    excerpts: tuple[GovernedDocumentExcerpt, ...]
    observed_at: datetime
    complete: bool
    limitation: str | None
    index_generation: str
    access_scope_digest: str
    retrieval_mode: Literal["lexical", "hybrid"]

    def __post_init__(self) -> None:
        if len(self.excerpts) > GOVERNED_DOCUMENT_MAX_EXCERPTS:
            raise ValueError("governed document collection exceeds its excerpt bound")
        ordering = tuple(
            (-item.score, item.document_revision, item.chunk_id) for item in self.excerpts
        )
        if ordering != tuple(sorted(ordering)):
            raise ValueError("governed document excerpts MUST be deterministically ordered")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("governed document observation time MUST be timezone-aware")
        if self.complete == (self.limitation is not None):
            raise ValueError("governed document completeness and limitation are inconsistent")
        for name, value in (
            ("index_generation", self.index_generation),
            ("access_scope_digest", self.access_scope_digest),
        ):
            if not value.strip() or len(value) > _MAX_REF_LENGTH:
                raise ValueError(f"governed document {name} MUST be bounded and non-empty")
        if (
            not self.access_scope_digest.startswith("sha256:")
            or len(self.access_scope_digest) != 71
        ):
            raise ValueError("governed document access scope digest MUST be SHA-256")


class GovernedDocumentReader(Protocol):
    """Read only document excerpts authorized for one server-resolved principal."""

    async def search(
        self,
        *,
        query: str,
        principal_ref: str,
        principal_role: CeilingRole,
        principal_groups: frozenset[str],
        purpose: str,
        limit: int,
    ) -> GovernedDocumentCollection: ...


def governed_document_function_type() -> OntologyFunctionType:
    """Declare the exact-release governed document search contract."""

    return OntologyFunctionType(
        name=GOVERNED_DOCUMENT_FUNCTION_NAME,
        version="1.0.0",
        kind=OntologyFunctionKind.QUERY,
        artifact_digest=f"sha256:{hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}",
        publisher="fdai",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["query", "evidence_mode"],
            "properties": {
                "query": {"type": "string", "minLength": 1, "maxLength": 20_000},
                "evidence_mode": {
                    "type": "string",
                    "enum": sorted(GOVERNED_DOCUMENT_EVIDENCE_MODES),
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": GOVERNED_DOCUMENT_MAX_EXCERPTS,
                },
            },
        },
        output_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["rows", "complete", "truncation_reason"],
            "x-fdai-measure-concepts": [GOVERNED_DOCUMENT_MEASURE_CONCEPT],
            "properties": {
                "rows": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": GOVERNED_DOCUMENT_MAX_EXCERPTS + 1,
                },
                "complete": {"type": "boolean"},
                "truncation_reason": {"type": ["string", "null"]},
            },
        },
        read_sets=[],
        execution_class=LogicExecutionClass.DETERMINISTIC,
        required_role=CeilingRole.READER,
        purpose_bindings=["operations-review"],
        timeout_seconds=10,
        cpu_millis=250,
        memory_bytes=67_108_864,
        max_output_bytes=131_072,
        network_allowed=False,
        credentials_allowed=False,
    )


def governed_document_function(
    ontology_release: OntologyRelease,
    *,
    reader: GovernedDocumentReader,
) -> ContextualOntologyFunction:
    """Return authorized excerpts as untrusted, citation-ready query rows."""

    ontology_release.type_ref(
        OntologyDeclarationKind.FUNCTION,
        GOVERNED_DOCUMENT_FUNCTION_NAME,
    )

    async def evaluate(
        arguments: Mapping[str, Any],
        invocation_context: FunctionInvocationContext,
    ) -> object:
        if invocation_context.purposes != ("operations-review",):
            raise PermissionError("governed document purpose does not match invocation context")
        principal_ref = invocation_context.principal_ref
        if principal_ref is None:
            raise PermissionError("governed document search requires a principal identity")
        query = arguments.get("query")
        evidence_mode = arguments.get("evidence_mode")
        limit = arguments.get("limit", GOVERNED_DOCUMENT_MAX_EXCERPTS)
        if not isinstance(query, str) or not query.strip() or len(query) > 20_000:
            raise ValueError("governed document query MUST be bounded and non-empty")
        if evidence_mode not in GOVERNED_DOCUMENT_EVIDENCE_MODES:
            raise ValueError("governed document evidence mode is invalid")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 8:
            raise ValueError("governed document limit MUST be in [1, 8]")

        collection = await reader.search(
            query=query,
            principal_ref=principal_ref,
            principal_role=invocation_context.caller_role,
            principal_groups=frozenset(invocation_context.principal_groups),
            purpose=invocation_context.purposes[0],
            limit=limit,
        )
        if len(collection.excerpts) > limit:
            raise ValueError("governed document reader exceeded the requested limit")

        summary = QueryRow.from_values(
            "governed-document-summary",
            {
                "record_kind": "summary",
                "evidence_mode": evidence_mode,
                "query_digest": content_digest({"query": query}),
                "excerpt_count": len(collection.excerpts),
                "count_posture": "exact" if collection.complete else "minimum",
                "observed_at": collection.observed_at.isoformat(),
                "index_generation": collection.index_generation,
                "access_scope_digest": collection.access_scope_digest,
                "retrieval_mode": collection.retrieval_mode,
                "instruction_authority": False,
                "execution_authority": False,
            },
        )
        excerpt_rows = tuple(
            QueryRow.from_values(
                f"governed-document-excerpt-{index:04d}",
                {
                    "record_kind": "excerpt",
                    "evidence_ref": excerpt.evidence_ref,
                    "document_revision": excerpt.document_revision,
                    "source_name": excerpt.source_name,
                    "source_ref": excerpt.source_ref,
                    "locator": excerpt.locator,
                    "chunk_id": excerpt.chunk_id,
                    "text": excerpt.text,
                    "content_digest": excerpt.content_digest,
                    "score": excerpt.score,
                    "index_generation": collection.index_generation,
                    "access_scope_digest": collection.access_scope_digest,
                    "retrieval_mode": collection.retrieval_mode,
                    "instruction_authority": False,
                    "execution_authority": False,
                },
            )
            for index, excerpt in enumerate(collection.excerpts, start=1)
        )
        table = QueryTable(
            rows=(summary, *excerpt_rows),
            complete=collection.complete,
            truncation_reason=collection.limitation,
        )
        return cast(dict[str, object], json.loads(table.canonical_json()))

    return evaluate


__all__ = [
    "GOVERNED_DOCUMENT_EVIDENCE_MODES",
    "GOVERNED_DOCUMENT_FUNCTION_NAME",
    "GOVERNED_DOCUMENT_MAX_EXCERPTS",
    "GOVERNED_DOCUMENT_MEASURE_CONCEPT",
    "GovernedDocumentCollection",
    "GovernedDocumentExcerpt",
    "GovernedDocumentReader",
    "governed_document_function",
    "governed_document_function_type",
]
