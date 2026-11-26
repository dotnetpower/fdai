"""Query recent provider-observed Resource changes without conflating state transitions."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, cast

from fdai.core.ontology_platform.functions import (
    ContextualOntologyFunction,
    FunctionInvocationContext,
)
from fdai.core.ontology_platform.query_values import QueryRow, QueryTable
from fdai.core.ontology_platform.recent_resource_change_continuations import (
    ContinuationInvalidError,
    RecentResourceChangeContinuationIssuer,
    RecentResourceChangeContinuationRequest,
)
from fdai.shared.contracts.models import (
    CeilingRole,
    LogicExecutionClass,
    OntologyDeclarationKind,
    OntologyFunctionKind,
    OntologyFunctionType,
    OntologyRelease,
)

RECENT_RESOURCE_CHANGES_FUNCTION_NAME = "query.recent_resource_changes"
RECENT_RESOURCE_CHANGES_PAGE_FUNCTION_NAME = "query.recent_resource_changes.page"
ARG_RESOURCE_CHANGE_SOURCE_IDENTITY = "fdai.delivery.azure.arg_resource_changes"
ACTIVITY_LOG_RESOURCE_CHANGE_SOURCE_IDENTITY = "azure_event_grid.resource_change"


@dataclass(frozen=True, slots=True)
class RecentResourceChange:
    subject_ref: str
    subject_name: str | None
    subject_type: str
    operation: str | None
    operation_status: str | None
    mutation_kind: str
    observation_kind: str
    occurred_at: datetime
    source_identity: str
    evidence_ref: str


@dataclass(frozen=True, slots=True)
class RecentResourceChangeRead:
    changes: tuple[RecentResourceChange, ...]
    complete: bool
    limitation: str | None = None
    # The exact number of changed Resources in the window when the row bound cut the read
    # short over complete source coverage; ``None`` when that count is unknown.
    total: int | None = None


@dataclass(frozen=True, slots=True)
class RecentResourceChangePageCursor:
    last_effective_at: datetime
    last_subject_ref: str


@dataclass(frozen=True, slots=True)
class RecentResourceChangePageRead:
    changes: tuple[RecentResourceChange, ...]
    complete: bool
    remaining: int
    cursor: RecentResourceChangePageCursor | None
    limitation: str | None = None


class RecentResourceChangeReader(Protocol):
    async def read_recent_resource_changes(
        self,
        *,
        start_at: datetime,
        end_at: datetime,
        known_at: datetime,
        limit: int,
    ) -> RecentResourceChangeRead: ...

    async def read_recent_resource_change_page(
        self,
        *,
        start_at: datetime,
        end_at: datetime,
        known_at: datetime,
        page_size: int,
        cursor: RecentResourceChangePageCursor,
    ) -> RecentResourceChangePageRead: ...

    def query_version_digest(self) -> str: ...


def recent_resource_changes_function_type() -> OntologyFunctionType:
    return OntologyFunctionType(
        name=RECENT_RESOURCE_CHANGES_FUNCTION_NAME,
        version="1.0.0",
        kind=OntologyFunctionKind.QUERY,
        artifact_digest=f"sha256:{hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}",
        publisher="fdai",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["start_at", "end_at", "known_at", "limit"],
            "properties": {
                "start_at": {"type": "string", "format": "date-time"},
                "end_at": {"type": "string", "format": "date-time"},
                "known_at": {"type": "string", "format": "date-time"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                "continuation_ref": {"type": "string", "minLength": 32, "maxLength": 128},
            },
        },
        output_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["rows", "complete", "truncation_reason"],
            "properties": {
                "rows": {"type": "array", "maxItems": 20},
                "complete": {"type": "boolean"},
                "truncation_reason": {"type": ["string", "null"]},
                "total_rows": {"type": "integer", "minimum": 0},
                "source_remaining_rows": {"type": "integer", "minimum": 0},
                "continuation_ref": {"type": "string", "minLength": 32, "maxLength": 128},
            },
        },
        read_sets=["Resource"],
        execution_class=LogicExecutionClass.DETERMINISTIC,
        required_role=CeilingRole.READER,
        purpose_bindings=["operations-review"],
        timeout_seconds=10,
        cpu_millis=250,
        memory_bytes=67_108_864,
        max_output_bytes=262_144,
        network_allowed=False,
        credentials_allowed=False,
    )


def recent_resource_changes_function(
    release: OntologyRelease,
    *,
    reader: RecentResourceChangeReader,
    continuation_issuer: RecentResourceChangeContinuationIssuer | None = None,
) -> ContextualOntologyFunction:
    release.type_ref(OntologyDeclarationKind.FUNCTION, RECENT_RESOURCE_CHANGES_FUNCTION_NAME)

    async def evaluate(
        arguments: Mapping[str, Any],
        context: FunctionInvocationContext,
    ) -> object:
        if context.purposes != ("operations-review",):
            raise PermissionError(
                "recent Resource changes purpose does not match invocation context"
            )
        continuation_ref = arguments.get("continuation_ref")
        if continuation_ref is not None:
            if continuation_issuer is None or not isinstance(continuation_ref, str):
                return {"disposition": "held", "reason_code": "continuation_invalid"}
            try:
                request = await continuation_issuer.request(
                    continuation_ref=continuation_ref,
                    context=context,
                    page_size=(
                        int(arguments["limit"])
                        if "limit" in arguments and arguments["limit"] is not None
                        else None
                    ),
                    query_version_digest=reader.query_version_digest(),
                )
            except ContinuationInvalidError:
                return {"disposition": "held", "reason_code": "continuation_invalid"}
            return await _evaluate_continuation_page(reader, request)
        read = await reader.read_recent_resource_changes(
            start_at=_time(arguments["start_at"], "start_at"),
            end_at=_time(arguments["end_at"], "end_at"),
            known_at=_time(arguments["known_at"], "known_at"),
            limit=int(arguments["limit"]),
        )
        continuation_ref = None
        if (
            continuation_issuer is not None
            and read.total is not None
            and read.changes
            and not read.complete
        ):
            continuation_ref = await continuation_issuer.issue(
                context=context,
                start_at=_time(arguments["start_at"], "start_at"),
                end_at=_time(arguments["end_at"], "end_at"),
                known_at=_time(arguments["known_at"], "known_at"),
                query_version_digest=reader.query_version_digest(),
                page_size=int(arguments["limit"]),
                cursor=RecentResourceChangePageCursor(
                    last_effective_at=read.changes[-1].occurred_at,
                    last_subject_ref=read.changes[-1].subject_ref,
                ),
                remaining_rows=read.total - len(read.changes),
            )
        rows = tuple(
            QueryRow.from_values(
                change.subject_ref,
                {
                    "subject_ref": change.subject_ref,
                    "subject_name": change.subject_name,
                    "subject_type": change.subject_type,
                    "operation": change.operation,
                    "operation_status": change.operation_status,
                    "mutation_kind": change.mutation_kind,
                    "observation_kind": change.observation_kind,
                    "occurred_at": change.occurred_at.isoformat(),
                    "source_identity": change.source_identity,
                    "evidence_refs": [change.evidence_ref],
                    "execution_authority": False,
                },
            )
            for change in read.changes
        )
        output = cast(
            dict[str, object],
            json.loads(
                QueryTable(
                    rows=rows,
                    complete=read.complete,
                    truncation_reason=read.limitation,
                    total_rows=read.total if read.total is not None and not read.complete else None,
                    source_generation=(
                        f"recent-resource-change-continuation:{continuation_ref}"
                        if continuation_ref is not None
                        else None
                    ),
                ).canonical_json()
            ),
        )
        return output

    return evaluate


async def _evaluate_continuation_page(
    reader: RecentResourceChangeReader,
    request: RecentResourceChangeContinuationRequest,
) -> dict[str, object]:
    page = await reader.read_recent_resource_change_page(
        start_at=request.continuation.window_start,
        end_at=request.continuation.window_end,
        known_at=request.continuation.cutoff,
        page_size=request.page_size,
        cursor=RecentResourceChangePageCursor(
            last_effective_at=request.continuation.keyset_cursor.last_effective_at
            or request.cursor_effective_at,
            last_subject_ref=request.cursor_subject_ref,
        ),
    )
    rows = tuple(
        QueryRow.from_values(
            change.subject_ref,
            {
                "subject_ref": change.subject_ref,
                "subject_name": change.subject_name,
                "subject_type": change.subject_type,
                "operation": change.operation,
                "operation_status": change.operation_status,
                "mutation_kind": change.mutation_kind,
                "observation_kind": change.observation_kind,
                "occurred_at": change.occurred_at.isoformat(),
                "source_identity": change.source_identity,
                "evidence_refs": [change.evidence_ref],
                "execution_authority": False,
            },
        )
        for change in page.changes
    )
    output = cast(
        dict[str, object],
        json.loads(
            QueryTable(
                rows=rows,
                complete=page.complete,
                truncation_reason=page.limitation,
                total_rows=len(rows) + page.remaining if not page.complete else None,
                source_generation=(
                    "recent-resource-change-continuation:"
                    + await request.issuer.advance(
                        previous_ref=request.continuation_ref,
                        context=request.context,
                        continuation=request.continuation,
                        cursor=page.cursor,
                        remaining_rows=page.remaining,
                        page_size=request.page_size,
                    )
                    if page.cursor is not None and not page.complete
                    else None
                ),
            ).canonical_json()
        ),
    )
    return output


def _time(value: object, name: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"recent Resource changes {name} MUST be RFC 3339")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"recent Resource changes {name} MUST include a timezone")
    return parsed


__all__ = [
    "ACTIVITY_LOG_RESOURCE_CHANGE_SOURCE_IDENTITY",
    "ARG_RESOURCE_CHANGE_SOURCE_IDENTITY",
    "RECENT_RESOURCE_CHANGES_FUNCTION_NAME",
    "RECENT_RESOURCE_CHANGES_PAGE_FUNCTION_NAME",
    "RecentResourceChange",
    "RecentResourceChangePageCursor",
    "RecentResourceChangePageRead",
    "RecentResourceChangeRead",
    "RecentResourceChangeReader",
    "recent_resource_changes_function",
    "recent_resource_changes_function_type",
]
