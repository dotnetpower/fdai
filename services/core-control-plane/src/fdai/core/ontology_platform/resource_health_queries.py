"""Read-only FunctionType for Resource Health over one secured collection."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from fdai.core.ontology_platform.functions import (
    ContextualOntologyFunction,
    FunctionInvocationContext,
)
from fdai.core.ontology_platform.query_gateway import SecuredObjectSetQueryResult
from fdai.core.ontology_platform.query_values import QueryRow, QueryTable
from fdai.core.ontology_platform.resource_health_evidence import (
    ResourceHealthAvailabilityState,
    ResourceHealthCollection,
    ResourceHealthCollectionReader,
    ResourceHealthCoverage,
    ResourceHealthCoverageStatus,
    ResourceHealthObservation,
)
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
from fdai.shared.providers.state_evidence import (
    STATE_FACT_METADATA_PROPERTY,
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)

RESOURCE_HEALTH_FUNCTION_NAME = "query.resource_health_inventory"
_MAX_CONCEPTS = 16
_MAX_RESOURCES = 1000
_MAX_OUTPUT_ROWS = 1000
_RESOURCE_HEALTH_NOT_APPLICABLE_TYPES = frozenset({"application-insights"})


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
        stored_health: list[dict[str, object]] = []
        missing_targets: list[Any] = []
        for target in objects:
            target_type = _text(target.properties.get("type"))
            if target_type in _RESOURCE_HEALTH_NOT_APPLICABLE_TYPES:
                stored_health.append(_not_modeled_health_values(target, target_type=target_type))
                continue
            stored = _stored_health_values(
                target,
                observation_cutoff=secured.receipt.observation_cutoff,
            )
            if stored is None:
                missing_targets.append(target)
                continue
            matching_concepts = _matching_concepts(
                str(stored["availability_state"]),
                requested_health=requested_health,
                groups=normalized_groups,
            )
            concept = matching_concepts[0] if matching_concepts else None
            if (
                concept is None
                and stored["availability_state"] == ResourceHealthAvailabilityState.AVAILABLE.value
            ):
                continue
            stored_health.append(
                {
                    **stored,
                    "health_concept": concept,
                    "matching_health_concepts": list(matching_concepts),
                }
            )
        resource_ids = tuple(item.id for item in missing_targets)
        collection = await reader.read_current(resource_ids=resource_ids) if resource_ids else None
        if collection is not None and collection.resource_ids != resource_ids:
            raise ValueError("Resource Health reader changed the secured resource scope")
        by_id = {item.id: item for item in missing_targets}
        inventory_rows: list[dict[str, object]] = []
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
                inventory_rows.append(
                    {
                        **state_values,
                        "evidence_family": "current_inventory",
                        "health_concept": None,
                        "matching_health_concepts": [],
                        "availability_state": None,
                        "coverage_state": None,
                    }
                )
        health_rows = stored_health
        if collection is not None:
            observations = {item.resource_id: item for item in collection.observations}
            for coverage in collection.coverage:
                target = by_id[coverage.resource_id]
                observation = observations.get(coverage.resource_id)
                if coverage.status is not ResourceHealthCoverageStatus.OBSERVED:
                    health_rows.append(
                        _health_row_values(
                            target=target,
                            coverage=coverage,
                            observation=observation,
                            health_concept=None,
                            matching_health_concepts=(),
                            collection=collection,
                        )
                    )
                    continue
                if observation is None:
                    raise ValueError("Resource Health observed coverage is missing its observation")
                matching_concepts = _matching_concepts(
                    observation.availability_state.value,
                    requested_health=requested_health,
                    groups=normalized_groups,
                )
                concept = matching_concepts[0] if matching_concepts else None
                if (
                    concept is None
                    and observation.availability_state is ResourceHealthAvailabilityState.AVAILABLE
                ):
                    continue
                health_rows.append(
                    _health_row_values(
                        target=target,
                        coverage=coverage,
                        observation=observation,
                        health_concept=concept,
                        matching_health_concepts=matching_concepts,
                        collection=collection,
                    )
                )
        row_values = health_rows + inventory_rows
        row_limit_reached = len(row_values) > _MAX_OUTPUT_ROWS
        rows = tuple(
            QueryRow.from_values(f"resource-health-{index:04d}", values)
            for index, values in enumerate(row_values[:_MAX_OUTPUT_ROWS], start=1)
        )
        reasons = [item for item in ((collection.limitation if collection else None),) if item]
        if state_incomplete:
            reasons.append("resource_state_evidence_incomplete")
        if row_limit_reached:
            reasons.append("resource_health_row_limit")
        complete = (
            (collection is None or collection.complete)
            and not state_incomplete
            and not row_limit_reached
        )
        return _table(
            rows,
            complete=complete,
            reason=None if complete else "+".join(dict.fromkeys(reasons)) or "incomplete",
        )

    return evaluate


def _not_modeled_health_values(target: Any, *, target_type: str) -> dict[str, object]:
    return {
        "name": _text(target.properties.get("name")),
        "type": target_type,
        "availability_state": None,
        "coverage_state": ResourceHealthCoverageStatus.NOT_MODELED.value,
        "state_concept": None,
        "health_concept": None,
        "matching_health_concepts": [],
        "health_kind": None,
        "provider_observed_at": None,
        "source_observed_at": None,
        "collection_started_at": None,
        "collection_completed_at": None,
        "evidence_family": "resource_health",
        "authority": "ontology_catalog",
        "evidence_ref": f"resource-health-applicability:{target_type}",
        "execution_authority": False,
    }


def _stored_health_values(
    target: Any,
    *,
    observation_cutoff: datetime,
) -> dict[str, object] | None:
    provider = target.properties.get("properties")
    if not isinstance(provider, Mapping):
        return None
    raw_state = provider.get("availabilityState")
    normalized = _machine_token(raw_state) if isinstance(raw_state, str) else ""
    try:
        state = ResourceHealthAvailabilityState(normalized)
    except ValueError:
        return None
    metadata_root = provider.get(STATE_FACT_METADATA_PROPERTY)
    metadata_value = (
        metadata_root.get("availabilityState") if isinstance(metadata_root, Mapping) else None
    )
    if not isinstance(metadata_value, Mapping):
        return None
    try:
        metadata = StateFactMetadata.from_mapping(metadata_value)
    except (TypeError, ValueError):
        return None
    age_seconds = (observation_cutoff - metadata.effective_at).total_seconds()
    if (
        metadata.lane is not StateFactLane.OBSERVED
        or metadata.authority is not StateFactAuthority.PROVIDER
        or metadata.source_identity != "azure-resource-health"
        or metadata.completeness < 1.0
        or metadata.synthetic
        or metadata.conflicts
        or metadata.recorded_at > observation_cutoff
        or metadata.evidence_cutoff > observation_cutoff
        or not 0 <= age_seconds <= metadata.freshness_ceiling_seconds
    ):
        return None
    return {
        "name": _text(target.properties.get("name")),
        "type": _text(target.properties.get("type")),
        "availability_state": state.value,
        "coverage_state": ResourceHealthCoverageStatus.OBSERVED.value,
        "state_concept": None,
        "health_concept": None,
        "matching_health_concepts": [],
        "health_kind": _text(provider.get("availabilityReasonKind")) or "status_only",
        "provider_observed_at": metadata.effective_at.isoformat(),
        "source_observed_at": metadata.effective_at.isoformat(),
        "collection_started_at": metadata.effective_at.isoformat(),
        "collection_completed_at": metadata.recorded_at.isoformat(),
        "evidence_family": "resource_health",
        "authority": "provider",
        "evidence_ref": metadata.evidence_refs[0],
        "execution_authority": False,
    }


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


def _matching_concepts(
    state: str,
    *,
    requested_health: tuple[str, ...],
    groups: Mapping[str, frozenset[str]],
) -> tuple[str, ...]:
    normalized = _machine_token(state)
    matches = [concept for concept in requested_health if normalized in groups[concept]]
    return tuple(sorted(matches, key=lambda item: (len(groups[item]), item)))


def _health_row_values(
    *,
    target: Any,
    coverage: ResourceHealthCoverage,
    observation: ResourceHealthObservation | None,
    health_concept: str | None,
    matching_health_concepts: tuple[str, ...],
    collection: ResourceHealthCollection,
) -> dict[str, object]:
    provider_observed_at = (
        observation.provider_observed_at.isoformat()
        if observation is not None and observation.provider_observed_at is not None
        else None
    )
    return {
        "name": _text(target.properties.get("name")),
        "type": _text(target.properties.get("type")),
        "availability_state": (
            observation.availability_state.value if observation is not None else None
        ),
        "coverage_state": coverage.status.value,
        "state_concept": None,
        "health_concept": health_concept,
        "matching_health_concepts": list(matching_health_concepts),
        "health_kind": observation.reason_kind if observation is not None else None,
        "provider_observed_at": provider_observed_at,
        "source_observed_at": provider_observed_at,
        "collection_started_at": collection.started_at.isoformat(),
        "collection_completed_at": collection.completed_at.isoformat(),
        "evidence_family": "resource_health",
        "authority": "provider",
        "evidence_ref": (
            observation.evidence_ref if observation is not None else collection.attempt_ref
        ),
        "execution_authority": False,
    }


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
    "ResourceHealthAvailabilityState",
    "ResourceHealthCollection",
    "ResourceHealthCollectionReader",
    "ResourceHealthCoverage",
    "ResourceHealthCoverageStatus",
    "ResourceHealthObservation",
    "resource_health_function_type",
    "resource_health_inventory_function",
]
