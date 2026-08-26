"""Read-only FunctionType for Resource Health over one secured collection."""

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
from fdai.core.ontology_platform.query_gateway import SecuredObjectSetQueryResult
from fdai.core.ontology_platform.query_values import QueryRow, QueryTable
from fdai.core.ontology_platform.resource_state_queries import (
    RESOURCE_STATE_MEASURE_CONCEPTS,
    verified_resource_state_values,
)
from fdai.shared.contracts.models import (
    CeilingRole,
    LogicExecutionClass,
    OntologyDeclarationKind,
    OntologyFunctionKind,
    OntologyFunctionType,
    OntologyRelease,
)

RESOURCE_HEALTH_FUNCTION_NAME = "query.resource_health_inventory"
_MAX_CONCEPTS = 16
_MAX_RESOURCES = 1000


@dataclass(frozen=True, slots=True)
class ResourceHealthObservation:
    """One normalized Resource Health status bound to a requested logical resource."""

    resource_id: str
    availability_state: str
    reason_kind: str
    observed_at: datetime
    evidence_ref: str

    def __post_init__(self) -> None:
        for name, value, maximum in (
            ("resource_id", self.resource_id, 1024),
            ("availability_state", self.availability_state, 64),
            ("reason_kind", self.reason_kind, 64),
            ("evidence_ref", self.evidence_ref, 256),
        ):
            if not value.strip() or len(value) > maximum:
                raise ValueError(f"Resource Health {name} MUST be bounded and non-empty")
        if self.observed_at.tzinfo is None:
            raise ValueError("Resource Health observed_at MUST be timezone-aware")


@dataclass(frozen=True, slots=True)
class ResourceHealthCollection:
    """Bounded provider result that repeats the exact requested scope for verification."""

    resource_ids: tuple[str, ...]
    observations: tuple[ResourceHealthObservation, ...]
    observed_at: datetime
    complete: bool
    limitation: str | None
    attempt_ref: str

    def __post_init__(self) -> None:
        if not self.resource_ids or len(self.resource_ids) > _MAX_RESOURCES:
            raise ValueError("Resource Health scope MUST contain between 1 and 1000 resources")
        if self.resource_ids != tuple(sorted(set(self.resource_ids))):
            raise ValueError("Resource Health scope MUST be unique and ordered")
        observed_ids = tuple(item.resource_id for item in self.observations)
        if len(observed_ids) != len(set(observed_ids)):
            raise ValueError("Resource Health observations MUST be unique by resource")
        if not set(observed_ids) <= set(self.resource_ids):
            raise ValueError("Resource Health observations widened the requested scope")
        if self.observed_at.tzinfo is None:
            raise ValueError("Resource Health collection time MUST be timezone-aware")
        if self.complete == (self.limitation is not None):
            raise ValueError("Resource Health completeness and limitation are inconsistent")
        if not self.attempt_ref.strip() or len(self.attempt_ref) > 256:
            raise ValueError("Resource Health attempt_ref MUST be bounded and non-empty")


class ResourceHealthCollectionReader(Protocol):
    """Read current provider health for an exact server-selected resource set."""

    async def read_current(
        self,
        *,
        resource_ids: tuple[str, ...],
    ) -> ResourceHealthCollection: ...


def resource_health_function_type() -> OntologyFunctionType:
    """Declare a bounded collection health read with no caller-supplied provider scope."""

    return OntologyFunctionType(
        name=RESOURCE_HEALTH_FUNCTION_NAME,
        version="1.0.0",
        kind=OntologyFunctionKind.QUERY,
        artifact_digest=f"sha256:{hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}",
        publisher="fdai",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["query_result", "health_concepts", "state_concepts"],
            "properties": {
                "query_result": {"type": "object", "x-fdai-dependency-only": True},
                "health_concepts": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": _MAX_CONCEPTS,
                    "uniqueItems": True,
                    "items": {
                        "type": "string",
                        "pattern": r"^resource_health\.[a-z][a-z0-9_.-]{0,63}$",
                    },
                },
                "state_concepts": {
                    "type": "array",
                    "maxItems": len(RESOURCE_STATE_MEASURE_CONCEPTS),
                    "uniqueItems": True,
                    "items": {"enum": list(RESOURCE_STATE_MEASURE_CONCEPTS)},
                },
            },
        },
        output_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["rows", "complete", "truncation_reason"],
            "properties": {
                "rows": {"type": "array", "maxItems": 1000},
                "complete": {"type": "boolean"},
                "truncation_reason": {"type": ["string", "null"]},
            },
        },
        read_sets=["Resource"],
        execution_class=LogicExecutionClass.DETERMINISTIC,
        required_role=CeilingRole.READER,
        purpose_bindings=["operations-review"],
        timeout_seconds=15,
        cpu_millis=250,
        memory_bytes=67_108_864,
        max_output_bytes=1_048_576,
        network_allowed=False,
        credentials_allowed=False,
    )


def resource_health_inventory_function(
    ontology_release: OntologyRelease,
    *,
    reader: ResourceHealthCollectionReader,
    health_state_values: Mapping[str, tuple[str, ...]],
) -> ContextualOntologyFunction:
    """Join provider health with verified inventory state without inferring readiness."""

    ontology_release.type_ref(
        OntologyDeclarationKind.FUNCTION,
        RESOURCE_HEALTH_FUNCTION_NAME,
    )
    normalized_groups = _validated_groups(health_state_values)

    async def evaluate(
        arguments: Mapping[str, Any],
        invocation_context: FunctionInvocationContext,
    ) -> object:
        if invocation_context.purposes != ("operations-review",):
            raise PermissionError("resource health purpose does not match invocation context")
        secured = SecuredObjectSetQueryResult.model_validate(arguments["query_result"])
        if secured.receipt.truncated or not secured.receipt.complete:
            return _table((), complete=False, reason="resource_scope_incomplete")
        objects = tuple(sorted(secured.materialization.graph.objects, key=lambda item: item.id))
        if not objects:
            return _table((), complete=True, reason=None)
        if len(objects) > _MAX_RESOURCES:
            return _table((), complete=False, reason="resource_health_scope_limit")
        requested_health = tuple(str(item) for item in arguments["health_concepts"])
        if not requested_health or any(item not in normalized_groups for item in requested_health):
            raise ValueError("resource health concept is absent from the configured catalog")
        requested_states = frozenset(str(item) for item in arguments["state_concepts"])
        resource_ids = tuple(item.id for item in objects)
        collection = await reader.read_current(resource_ids=resource_ids)
        if collection.resource_ids != resource_ids:
            raise ValueError("Resource Health reader changed the secured resource scope")
        by_id = {item.id: item for item in objects}
        rows: list[QueryRow] = []
        state_incomplete = False
        for target in objects:
            state_values = verified_resource_state_values(
                target,
                observation_cutoff=secured.receipt.observation_cutoff,
            )
            if state_values is None:
                state_incomplete = state_incomplete or bool(requested_states)
                continue
            if state_values["state_concept"] in requested_states:
                rows.append(
                    QueryRow.from_values(
                        f"resource-health-state-{len(rows) + 1:04d}",
                        {
                            **state_values,
                            "evidence_family": "current_inventory",
                            "health_concept": None,
                        },
                    )
                )
        for observation in collection.observations:
            target = by_id[observation.resource_id]
            concept = _most_specific_concept(
                observation.availability_state,
                requested_health=requested_health,
                groups=normalized_groups,
            )
            if concept is None:
                continue
            rows.append(
                QueryRow.from_values(
                    f"resource-health-provider-{len(rows) + 1:04d}",
                    {
                        "name": _text(target.properties.get("name")),
                        "type": _text(target.properties.get("type")),
                        "observed_state": observation.availability_state,
                        "state_concept": None,
                        "health_concept": concept,
                        "health_kind": observation.reason_kind,
                        "source_observed_at": observation.observed_at.isoformat(),
                        "inventory_read_at": secured.receipt.observation_cutoff.isoformat(),
                        "evidence_family": "resource_health",
                        "authority": "provider",
                        "evidence_ref": observation.evidence_ref,
                        "execution_authority": False,
                    },
                )
            )
        reasons = [item for item in (collection.limitation,) if item]
        if state_incomplete:
            reasons.append("resource_state_evidence_incomplete")
        complete = collection.complete and not state_incomplete
        return _table(
            tuple(rows),
            complete=complete,
            reason=None if complete else "+".join(dict.fromkeys(reasons)) or "incomplete",
        )

    return evaluate


def _validated_groups(
    groups: Mapping[str, tuple[str, ...]],
) -> dict[str, frozenset[str]]:
    if not groups or len(groups) > _MAX_CONCEPTS:
        raise ValueError("Resource Health concept groups MUST be non-empty and bounded")
    normalized: dict[str, frozenset[str]] = {}
    for concept, values in groups.items():
        if not concept.startswith("resource_health.") or not values:
            raise ValueError("Resource Health concept group is invalid")
        states = frozenset(_machine_token(value) for value in values)
        normalized[concept] = states
    return normalized


def _most_specific_concept(
    state: str,
    *,
    requested_health: tuple[str, ...],
    groups: Mapping[str, frozenset[str]],
) -> str | None:
    normalized = _machine_token(state)
    matches = [concept for concept in requested_health if normalized in groups[concept]]
    return min(matches, key=lambda item: (len(groups[item]), item)) if matches else None


def _machine_token(value: str) -> str:
    normalized = "_".join(value.casefold().replace("-", " ").split())
    return normalized[:64] or "unknown"


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _table(
    rows: tuple[QueryRow, ...],
    *,
    complete: bool,
    reason: str | None,
) -> dict[str, object]:
    table = QueryTable(rows=rows, complete=complete, truncation_reason=reason)
    return cast(dict[str, object], json.loads(table.canonical_json()))


__all__ = [
    "RESOURCE_HEALTH_FUNCTION_NAME",
    "ResourceHealthCollection",
    "ResourceHealthCollectionReader",
    "ResourceHealthObservation",
    "resource_health_function_type",
    "resource_health_inventory_function",
]
