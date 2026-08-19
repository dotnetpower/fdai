"""Read-only ObjectType evidence-health queries over sanitized source metadata."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from fdai.shared.contracts.models import (
    CeilingRole,
    LogicExecutionClass,
    OntologyDeclarationKind,
    OntologyFunctionKind,
    OntologyFunctionType,
    OntologyRelease,
)

from .functions import ContextualOntologyFunction, FunctionInvocationContext

ONTOLOGY_EVIDENCE_HEALTH_FUNCTION_NAME = "query.ontology_evidence_health"
ONTOLOGY_EVIDENCE_HEALTH_PURPOSE = "operations-review"


@dataclass(frozen=True, slots=True)
class OntologyEvidenceHealthSnapshot:
    """Sanitized evidence metadata without provider payload or environment identity."""

    source_kind: str
    source_alias: str
    generation: str
    ontology_release_digest: str
    observed_at: datetime
    recorded_at: datetime
    freshness_ceiling_seconds: int | None
    complete: bool
    truncated: bool
    synthetic: bool
    conflicts: tuple[str, ...]
    drop_reasons: tuple[str, ...]
    visible_instance_count: int
    visible_link_count: int
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OntologyEvidenceHealthRead:
    """Available sanitized snapshot or one stable unavailable reason."""

    snapshot: OntologyEvidenceHealthSnapshot | None
    unavailable_reason: str | None = None

    def __post_init__(self) -> None:
        if (self.snapshot is None) != (self.unavailable_reason is not None):
            raise ValueError("ontology evidence health availability is inconsistent")


class OntologyEvidenceHealthReader(Protocol):
    """Read sanitized evidence health for one exact ObjectType and release."""

    async def read(
        self,
        *,
        object_type: str,
        ontology_release_digest: str,
    ) -> OntologyEvidenceHealthRead: ...


def ontology_evidence_health_function_type() -> OntologyFunctionType:
    """Return the bounded no-authority evidence-health FunctionType."""

    return OntologyFunctionType(
        name=ONTOLOGY_EVIDENCE_HEALTH_FUNCTION_NAME,
        version="1.0.0",
        kind=OntologyFunctionKind.QUERY,
        artifact_digest=f"sha256:{hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}",
        publisher="fdai",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["object_type"],
            "properties": {"object_type": {"type": "string", "minLength": 1, "maxLength": 128}},
        },
        output_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["rows", "complete", "truncation_reason"],
            "properties": {
                "rows": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 1,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["row_id", "values"],
                        "properties": {
                            "row_id": {"type": "string", "minLength": 1, "maxLength": 512},
                            "values": {
                                "type": "object",
                                "required": [
                                    "ontology_release_digest",
                                    "object_type",
                                    "availability",
                                    "freshness_state",
                                    "complete",
                                    "execution_authority",
                                    "mutation_authority",
                                ],
                                "properties": {
                                    "ontology_release_digest": {
                                        "type": "string",
                                        "pattern": "^sha256:[a-f0-9]{64}$",
                                    },
                                    "object_type": {"type": "string"},
                                    "availability": {"enum": ["available", "unavailable"]},
                                    "freshness_state": {
                                        "enum": ["current", "stale", "unknown", "unavailable"]
                                    },
                                    "complete": {"type": "boolean"},
                                    "execution_authority": {"const": False},
                                    "mutation_authority": {"const": False},
                                },
                            },
                        },
                    },
                },
                "complete": {"type": "boolean"},
                "truncation_reason": {
                    "type": ["string", "null"],
                    "enum": ["source_incomplete", "source_unavailable", None],
                },
            },
        },
        read_sets=[],
        execution_class=LogicExecutionClass.DETERMINISTIC,
        required_role=CeilingRole.READER,
        purpose_bindings=[ONTOLOGY_EVIDENCE_HEALTH_PURPOSE],
        timeout_seconds=2,
        cpu_millis=100,
        memory_bytes=33_554_432,
        max_output_bytes=131_072,
        network_allowed=False,
        credentials_allowed=False,
    )


def ontology_evidence_health_function(
    ontology_release: OntologyRelease,
    *,
    object_type_names: frozenset[str],
    reader: OntologyEvidenceHealthReader,
    now: Callable[[], datetime] | None = None,
) -> ContextualOntologyFunction:
    """Bind sanitized health metadata while preserving unavailable and zero."""

    ontology_release.type_ref(
        OntologyDeclarationKind.FUNCTION,
        ONTOLOGY_EVIDENCE_HEALTH_FUNCTION_NAME,
    )
    for object_type in object_type_names:
        ontology_release.type_ref(OntologyDeclarationKind.OBJECT, object_type)
    clock = now or (lambda: datetime.now(UTC))

    async def evaluate(
        arguments: Mapping[str, Any],
        invocation_context: FunctionInvocationContext,
    ) -> object:
        if invocation_context.purposes != (ONTOLOGY_EVIDENCE_HEALTH_PURPOSE,):
            raise PermissionError("ontology evidence health purpose does not match context")
        object_type = str(arguments["object_type"])
        if object_type not in object_type_names:
            raise LookupError(f"unknown ObjectType declaration: {object_type}")
        observed_now = clock()
        if observed_now.tzinfo is None:
            raise ValueError("ontology evidence health clock MUST be timezone-aware")
        result = await reader.read(
            object_type=object_type,
            ontology_release_digest=ontology_release.digest,
        )
        values = _health_values(
            object_type=object_type,
            ontology_release=ontology_release,
            result=result,
            now=observed_now,
        )
        complete = values["complete"] is True
        reason = (
            None
            if complete
            else (
                "source_unavailable"
                if values["availability"] == "unavailable"
                else "source_incomplete"
            )
        )
        return {
            "rows": [{"row_id": f"evidence-health:{object_type}", "values": values}],
            "complete": complete,
            "truncation_reason": reason,
        }

    return evaluate


def _health_values(
    *,
    object_type: str,
    ontology_release: OntologyRelease,
    result: OntologyEvidenceHealthRead,
    now: datetime,
) -> dict[str, object]:
    snapshot = result.snapshot
    if snapshot is None:
        return {
            "ontology_release_digest": ontology_release.digest,
            "object_type": object_type,
            "availability": "unavailable",
            "unavailable_reason": result.unavailable_reason,
            "source": None,
            "freshness_state": "unavailable",
            "complete": False,
            "truncated": False,
            "synthetic": None,
            "conflicts": [],
            "drop_reasons": [],
            "visible_instance_count": None,
            "visible_link_count": None,
            "evidence_refs": [],
            "execution_authority": False,
            "mutation_authority": False,
        }
    if snapshot.ontology_release_digest != ontology_release.digest:
        raise ValueError("ontology evidence health source release does not match active release")
    if snapshot.observed_at.tzinfo is None or snapshot.recorded_at.tzinfo is None:
        raise ValueError("ontology evidence health timestamps MUST be timezone-aware")
    if snapshot.observed_at > snapshot.recorded_at:
        raise ValueError("ontology evidence observation MUST NOT follow its record time")
    if snapshot.visible_instance_count < 0 or snapshot.visible_link_count < 0:
        raise ValueError("ontology evidence health counts MUST be non-negative")
    if snapshot.freshness_ceiling_seconds is None:
        freshness_state = "unknown"
    elif snapshot.freshness_ceiling_seconds < 1:
        raise ValueError("ontology evidence freshness ceiling MUST be positive")
    elif snapshot.observed_at < now - timedelta(seconds=snapshot.freshness_ceiling_seconds):
        freshness_state = "stale"
    else:
        freshness_state = "current"
    complete = (
        snapshot.complete
        and not snapshot.truncated
        and not snapshot.synthetic
        and not snapshot.conflicts
        and freshness_state == "current"
    )
    return {
        "ontology_release_digest": ontology_release.digest,
        "object_type": object_type,
        "availability": "available",
        "unavailable_reason": None,
        "source": {
            "kind": snapshot.source_kind,
            "alias": snapshot.source_alias,
            "generation": snapshot.generation,
            "observed_at": snapshot.observed_at.isoformat(),
            "recorded_at": snapshot.recorded_at.isoformat(),
            "freshness_ceiling_seconds": snapshot.freshness_ceiling_seconds,
        },
        "freshness_state": freshness_state,
        "complete": complete,
        "truncated": snapshot.truncated,
        "synthetic": snapshot.synthetic,
        "conflicts": list(snapshot.conflicts),
        "drop_reasons": list(snapshot.drop_reasons),
        "visible_instance_count": snapshot.visible_instance_count,
        "visible_link_count": snapshot.visible_link_count,
        "evidence_refs": list(snapshot.evidence_refs),
        "execution_authority": False,
        "mutation_authority": False,
    }


__all__ = [
    "ONTOLOGY_EVIDENCE_HEALTH_FUNCTION_NAME",
    "ONTOLOGY_EVIDENCE_HEALTH_PURPOSE",
    "OntologyEvidenceHealthRead",
    "OntologyEvidenceHealthReader",
    "OntologyEvidenceHealthSnapshot",
    "ontology_evidence_health_function",
    "ontology_evidence_health_function_type",
]
