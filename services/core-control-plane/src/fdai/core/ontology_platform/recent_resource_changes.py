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
from fdai.shared.contracts.models import (
    CeilingRole,
    LogicExecutionClass,
    OntologyDeclarationKind,
    OntologyFunctionKind,
    OntologyFunctionType,
    OntologyRelease,
)

RECENT_RESOURCE_CHANGES_FUNCTION_NAME = "query.recent_resource_changes"
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


class RecentResourceChangeReader(Protocol):
    async def read_recent_resource_changes(
        self,
        *,
        start_at: datetime,
        end_at: datetime,
        known_at: datetime,
        limit: int,
    ) -> RecentResourceChangeRead: ...


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
        read = await reader.read_recent_resource_changes(
            start_at=_time(arguments["start_at"], "start_at"),
            end_at=_time(arguments["end_at"], "end_at"),
            known_at=_time(arguments["known_at"], "known_at"),
            limit=int(arguments["limit"]),
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
        return cast(
            dict[str, object],
            json.loads(
                QueryTable(
                    rows=rows,
                    complete=read.complete,
                    truncation_reason=read.limitation,
                ).canonical_json()
            ),
        )

    return evaluate


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
    "RecentResourceChange",
    "RecentResourceChangeRead",
    "RecentResourceChangeReader",
    "recent_resource_changes_function",
    "recent_resource_changes_function_type",
]
