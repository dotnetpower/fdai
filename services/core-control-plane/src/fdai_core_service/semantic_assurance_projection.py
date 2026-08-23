"""Project typed semantic assurance axes without retaining question or answer text."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any, Literal, cast

from fdai.core.conversation.semantic_runtime import (
    SemanticTurnResult as RuntimeSemanticTurnResult,
)
from fdai.core.ontology_platform.query_values import QueryTable
from fdai_service_contracts import (
    SemanticAssuranceFrame,
    SemanticAssuranceObservation,
    SemanticAssurancePath,
    SemanticAssurancePathStep,
)
from fdai_service_contracts.ontology_query import SemanticOperation, content_digest

from .semantic_assurance_claims import project_function_claims

_FUNCTION_CAPABILITY = {
    "query.incident_evidence": "incident_evidence",
    "query.ontology_declaration": "ontology_declaration",
    "query.ontology_evidence_health": "ontology_evidence_health",
    "query.ontology_relationships": "ontology_relationships",
    "query.ontology_release_diff": "ontology_release_diff",
    "query.resource_change_activity": "resource_change_activity",
    "query.resource_current_state": "resource_current_state",
}
_FUNCTION_OBJECT_TYPES = {
    "query.incident_evidence": ("Incident",),
}
_OUTPUT_CAPABILITY = {
    "structured_investigation": "structured_investigation",
    "temporal_comparison": "temporal_comparison",
}
_WINDOWED_OUTPUTS = {
    "resource_change_activity",
    "structured_investigation",
    "target_error_activity_correlation",
    "target_health_assessment",
}
_CURRENT_OUTPUTS = {"target_current_state"}
_HISTORICAL_OUTPUTS = {
    "ontology_release_evidence_health",
    "temporal_comparison",
    "topology_diff",
}
_MACHINE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")


def project_semantic_assurance(
    result: RuntimeSemanticTurnResult,
    *,
    disposition: str,
) -> SemanticAssuranceObservation:
    """Derive bounded assurance evidence from server-verified runtime state only."""

    frame = _project_frame(result)
    capabilities, object_types, link_types, function_types = _plan_declarations(result)
    paths = _ontology_paths(result)
    fact_kinds, limitation_kinds, claim_kinds = _semantic_output_metadata(result)
    execution = result.execution
    read_performed = execution is not None and bool(execution.receipts)
    payload: dict[str, object] = {
        "schema_version": "1.0.0",
        "frame": frame.model_dump(mode="json") if frame is not None else None,
        "capabilities": list(capabilities),
        "object_types": list(object_types),
        "link_types": list(link_types),
        "function_types": list(function_types),
        "ontology_paths": [path.model_dump(mode="json") for path in paths],
        "fact_kinds": list(fact_kinds),
        "limitation_kinds": list(limitation_kinds),
        "claim_kinds": list(claim_kinds),
        "evidence_posture": _evidence_posture(result),
        "authority_posture": (
            "draft_only"
            if disposition == "action_draft"
            or getattr(getattr(result.planning, "frame", None), "operation", None)
            is SemanticOperation.ACTION_DRAFT
            else "read_only"
        ),
        "read_performed": read_performed,
        "execution_authority": False,
    }
    payload["observation_digest"] = content_digest(payload)
    return SemanticAssuranceObservation.model_validate(payload)


def _project_frame(result: RuntimeSemanticTurnResult) -> SemanticAssuranceFrame | None:
    frame = getattr(result.planning, "frame", None)
    operation = getattr(frame, "operation", None)
    output_shape = getattr(frame, "output_shape", None)
    frame_digest = getattr(frame, "frame_digest", None)
    if (
        not isinstance(operation, SemanticOperation)
        or not isinstance(output_shape, str)
        or not isinstance(frame_digest, str)
    ):
        return None
    subjects = _subject_types(getattr(frame, "subject_constraints", ()))
    measures = _measure_concepts(getattr(frame, "measure_concepts", ()))
    return SemanticAssuranceFrame(
        operation=operation,
        subject_types=subjects,
        measure_concepts=measures,
        temporal_scope=_temporal_scope(frame, output_shape=output_shape),
        output_shape=output_shape,
        frame_digest=frame_digest,
    )


def _temporal_scope(
    frame: object,
    *,
    output_shape: str,
) -> Literal["none", "current", "windowed", "historical"]:
    temporal = getattr(frame, "temporal_scope", None)
    if isinstance(temporal, Mapping) and temporal:
        keys = set(temporal)
        values = {item.casefold() for item in temporal.values() if isinstance(item, str) and item}
        if values & {"historical", "history", "past"}:
            return "historical"
        if values & {"current", "now"}:
            return "current"
        if values & {"windowed", "window", "range", "bounded"}:
            return "windowed"
        if keys & {"baseline", "current", "from", "to", "window", "lookback"}:
            return "windowed"
        if keys & {"as_of", "previous_release", "known_at"}:
            return "historical"
        return "current"
    if output_shape in _HISTORICAL_OUTPUTS:
        return "historical"
    if output_shape in _WINDOWED_OUTPUTS:
        return "windowed"
    if output_shape in _CURRENT_OUTPUTS:
        return "current"
    return "none"


def _plan_declarations(
    result: RuntimeSemanticTurnResult,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    capabilities: set[str] = set()
    object_types: set[str] = set()
    link_types: set[str] = set()
    function_types: set[str] = set()
    plan = getattr(result.planning, "plan", None)
    for node in getattr(plan, "nodes", ()):
        kind = getattr(getattr(node, "kind", None), "value", None)
        if isinstance(kind, str):
            capabilities.add(kind)
        arguments = _arguments(node)
        selector_type = _selector_type(arguments)
        if selector_type is not None:
            object_types.add(selector_type)
        raw_link_types = arguments.get("link_types")
        if isinstance(raw_link_types, list):
            link_types.update(item for item in raw_link_types if isinstance(item, str) and item)
        function_name = arguments.get("function_name")
        if isinstance(function_name, str) and function_name:
            function_types.add(function_name)
            capabilities.add(_FUNCTION_CAPABILITY.get(function_name, function_name))
            object_types.update(_FUNCTION_OBJECT_TYPES.get(function_name, ()))
        function_arguments = arguments.get("arguments")
        if isinstance(function_arguments, Mapping):
            raw_object_types = function_arguments.get("object_types")
            if isinstance(raw_object_types, list):
                object_types.update(
                    item for item in raw_object_types if isinstance(item, str) and item
                )
    frame = getattr(result.planning, "frame", None)
    output_shape = getattr(frame, "output_shape", None)
    if isinstance(output_shape, str) and output_shape in _OUTPUT_CAPABILITY:
        capabilities.add(_OUTPUT_CAPABILITY[output_shape])
    if getattr(result.planning, "investigation_intent", None) is not None:
        capabilities.add("structured_investigation")
    return (
        tuple(sorted(capabilities)),
        tuple(sorted(object_types)),
        tuple(sorted(link_types)),
        tuple(sorted(function_types)),
    )


def _ontology_paths(result: RuntimeSemanticTurnResult) -> tuple[SemanticAssurancePath, ...]:
    paths: dict[tuple[tuple[str, str, str, str], ...], SemanticAssurancePath] = {}
    plan = getattr(result.planning, "plan", None)
    source_types: dict[str, str] = {}
    for node in getattr(plan, "nodes", ()):
        node_id = getattr(node, "node_id", None)
        arguments = _arguments(node)
        target_type = _selector_type(arguments)
        if isinstance(node_id, str) and target_type is not None:
            source_types[node_id] = target_type
        raw_link_types = arguments.get("link_types")
        direction = arguments.get("direction")
        dependencies = getattr(node, "depends_on", ())
        if (
            not isinstance(raw_link_types, list)
            or len(raw_link_types) != 1
            or direction not in {"incoming", "outgoing"}
            or not isinstance(dependencies, tuple)
            or len(dependencies) != 1
            or target_type is None
        ):
            continue
        source_type = source_types.get(dependencies[0])
        link_type = raw_link_types[0]
        if source_type is None or not isinstance(link_type, str):
            continue
        _add_path(
            paths,
            ((source_type, link_type, cast(str, direction), target_type),),
        )
    execution = result.execution
    if execution is not None:
        for node_result in execution.results.values():
            value = node_result.value
            if not isinstance(value, Mapping):
                continue
            relationships = value.get("relationships")
            if not isinstance(relationships, list):
                continue
            for relationship in relationships:
                if not isinstance(relationship, Mapping):
                    continue
                source = relationship.get("from_type")
                link_type = relationship.get("link_type")
                target = relationship.get("to_type")
                if all(isinstance(item, str) and item for item in (source, link_type, target)):
                    _add_path(
                        paths,
                        ((cast(str, source), cast(str, link_type), "outgoing", cast(str, target)),),
                    )
    return tuple(sorted(paths.values(), key=lambda item: item.path_id))


def _add_path(
    paths: dict[tuple[tuple[str, str, str, str], ...], SemanticAssurancePath],
    steps: tuple[tuple[str, str, str, str], ...],
) -> None:
    if steps in paths:
        return
    digest = content_digest(steps)
    paths[steps] = SemanticAssurancePath(
        path_id=f"path-{digest.removeprefix('sha256:')[:16]}",
        steps=tuple(
            SemanticAssurancePathStep(
                from_type=source,
                link_type=link_type,
                direction=cast(Literal["incoming", "outgoing"], direction),
                to_type=target,
            )
            for source, link_type, direction, target in steps
        ),
    )


def _semantic_output_metadata(
    result: RuntimeSemanticTurnResult,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    facts: set[str] = set()
    limitations: set[str] = set()
    claims: set[str] = set()
    execution = result.execution
    if execution is None:
        return (), (), ()
    plan = getattr(result.planning, "plan", None)
    nodes_by_id = {
        node_id: node
        for node in getattr(plan, "nodes", ())
        if isinstance(node_id := getattr(node, "node_id", None), str)
    }
    for node_id, node_result in execution.results.items():
        value = node_result.value
        node = nodes_by_id.get(node_id)
        arguments = _arguments(node) if node is not None else {}
        function_name = arguments.get("function_name")
        if isinstance(function_name, str):
            projected = project_function_claims(function_name, value)
            facts.update(projected.fact_kinds)
            limitations.update(projected.limitation_kinds)
            claims.update(projected.claim_kinds)
    return tuple(sorted(facts)), tuple(sorted(limitations)), tuple(sorted(claims))


def _evidence_posture(
    result: RuntimeSemanticTurnResult,
) -> Literal["fresh", "stale", "incomplete", "conflicting", "unavailable"]:
    execution = result.execution
    if execution is None or not execution.receipts:
        return "unavailable"
    saw_incomplete = execution.status != "completed"
    saw_stale = False
    saw_conflict = False
    for node_result in execution.results.values():
        value = node_result.value
        if isinstance(value, QueryTable):
            saw_incomplete = saw_incomplete or not value.complete
            saw_stale = saw_stale or _contains_stale(value.truncation_reason)
            for row in value.rows:
                saw_conflict = saw_conflict or _mapping_has_conflict(row.values)
                saw_stale = saw_stale or _mapping_has_stale_reason(row.values)
        elif isinstance(value, Mapping):
            complete = value.get("complete")
            saw_incomplete = saw_incomplete or complete is False
            saw_incomplete = saw_incomplete or value.get("truncated") is True
            gaps = value.get("evidence_gaps")
            saw_incomplete = saw_incomplete or isinstance(gaps, list) and bool(gaps)
            saw_conflict = saw_conflict or _mapping_has_conflict(value)
            saw_stale = saw_stale or _mapping_has_stale_reason(value)
        else:
            complete = getattr(value, "complete", None)
            saw_incomplete = saw_incomplete or complete is False
            saw_stale = saw_stale or _contains_stale(getattr(value, "reason", None))
    if saw_conflict:
        return "conflicting"
    if saw_stale:
        return "stale"
    if saw_incomplete:
        return "incomplete"
    return "fresh"


def _arguments(node: object) -> Mapping[str, Any]:
    try:
        arguments = cast(Any, node).arguments
    except Exception:  # noqa: BLE001 - malformed test or runtime node yields no assurance
        return {}
    return arguments if isinstance(arguments, Mapping) else {}


def _selector_type(arguments: Mapping[str, Any]) -> str | None:
    definition = arguments.get("definition")
    selector = definition.get("selector") if isinstance(definition, Mapping) else None
    if not isinstance(selector, Mapping):
        selector = arguments.get("selector")
    name = selector.get("name") if isinstance(selector, Mapping) else None
    return name if isinstance(name, str) and name else None


def _subject_types(values: object) -> tuple[str, ...]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        return ()
    subjects = {
        candidate
        for value in values
        if isinstance(value, str)
        if (candidate := value.split(":", 1)[0]).replace("_", "").isalnum()
        and candidate[:1].isupper()
    }
    return tuple(sorted(subjects))


def _ordered_strings(values: object) -> tuple[str, ...]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        return ()
    return tuple(sorted({item for item in values if isinstance(item, str) and item}))


def _measure_concepts(values: object) -> tuple[str, ...]:
    """Project verified concepts to collision-resistant machine tokens."""

    concepts = _ordered_strings(values)
    return tuple(
        sorted(
            {
                item
                if _MACHINE_TOKEN.fullmatch(item) is not None
                else f"concept:{content_digest(item).removeprefix('sha256:')}"
                for item in concepts
            }
        )
    )


def _mapping_has_conflict(value: Mapping[str, Any]) -> bool:
    conflicts = value.get("conflicts")
    if conflicts not in (None, False, 0, "", [], (), {}):
        return True
    return any(
        _value_has_conflict(item)
        for item in value.values()
        if isinstance(item, Mapping | list | tuple)
    )


def _value_has_conflict(value: object) -> bool:
    if isinstance(value, Mapping):
        return _mapping_has_conflict(value)
    if isinstance(value, list | tuple):
        return any(_value_has_conflict(item) for item in value)
    return False


def _mapping_has_stale_reason(value: Mapping[str, Any]) -> bool:
    if any(
        _contains_stale(item)
        for key, item in value.items()
        if key in {"reason", "status", "evidence_state", "truncation_reason"}
    ):
        return True
    return any(
        _value_has_stale_reason(item)
        for item in value.values()
        if isinstance(item, Mapping | list | tuple)
    )


def _value_has_stale_reason(value: object) -> bool:
    if isinstance(value, Mapping):
        return _mapping_has_stale_reason(value)
    if isinstance(value, list | tuple):
        return any(_value_has_stale_reason(item) for item in value)
    return False


def _contains_stale(value: object) -> bool:
    return isinstance(value, str) and "stale" in value.casefold()


__all__ = ["project_semantic_assurance"]
