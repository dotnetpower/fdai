"""Read-only FunctionType for verified state filtering over a Resource collection."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from fdai.core.ontology_platform.functions import (
    ContextualOntologyFunction,
    FunctionInvocationContext,
)
from fdai.core.ontology_platform.query_gateway import SecuredObjectSetQueryResult
from fdai.core.ontology_platform.query_values import QueryRow, QueryTable
from fdai.shared.contracts.models import (
    CeilingRole,
    LogicExecutionClass,
    OntologyDeclarationKind,
    OntologyFunctionKind,
    OntologyFunctionType,
    OntologyRelease,
)
from fdai.shared.providers.ontology_instance import OntologyObjectRecord
from fdai.shared.providers.state_evidence import (
    STATE_FACT_METADATA_PROPERTY,
    StateFactLane,
    StateFactMetadata,
)

RESOURCE_STATE_FUNCTION_NAME = "query.resource_state_inventory"
RESOURCE_STATE_MEASURE_CONCEPTS = (
    "resource_state.available",
    "resource_state.deallocated",
    "resource_state.degraded",
    "resource_state.failed",
    "resource_state.online",
    "resource_state.paused",
    "resource_state.ready",
    "resource_state.running",
    "resource_state.stopped",
    "resource_state.succeeded",
    "resource_state.unavailable",
)
RESOURCE_STATE_OBSERVED_CONCEPT = "resource_state.observed"
RESOURCE_STATE_QUERY_CONCEPTS = (
    *RESOURCE_STATE_MEASURE_CONCEPTS,
    RESOURCE_STATE_OBSERVED_CONCEPT,
)
RESOURCE_STATE_MEASURE_TERMS = {
    "resource_state.available": ("available", "사용 가능"),
    "resource_state.deallocated": ("deallocated", "할당 해제", "할당 해제된"),
    "resource_state.degraded": ("degraded", "성능 저하", "저하된"),
    "resource_state.failed": ("failed", "failed state", "failure", "실패", "실패 상태"),
    "resource_state.online": ("online", "온라인"),
    "resource_state.paused": ("paused", "paused state", "일시 중지", "일시 중지된"),
    "resource_state.ready": ("ready", "ready state", "준비됨"),
    "resource_state.running": ("running", "running state", "실행 중"),
    "resource_state.stopped": (
        "not running",
        "stopped",
        "stopped state",
        "멈춰",
        "멈춘",
        "정지",
        "중지",
        "중지된",
    ),
    "resource_state.succeeded": ("succeeded", "성공"),
    "resource_state.unavailable": ("unavailable", "사용 불가능", "이용 불가"),
    RESOURCE_STATE_OBSERVED_CONCEPT: (
        "status",
        "current state",
        "상태",
        "상태 확인",
        "현재 상태",
    ),
}
_STATE_NAMES = frozenset(concept.rsplit(".", 1)[-1] for concept in RESOURCE_STATE_MEASURE_CONCEPTS)


def resource_state_function_type() -> OntologyFunctionType:
    """Declare bounded state filtering over an already secured Resource set."""

    return OntologyFunctionType(
        name=RESOURCE_STATE_FUNCTION_NAME,
        version="1.1.0",
        kind=OntologyFunctionKind.QUERY,
        artifact_digest=f"sha256:{hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}",
        publisher="fdai",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["query_result", "state_concepts"],
            "properties": {
                "query_result": {"type": "object", "x-fdai-dependency-only": True},
                "state_concepts": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": len(RESOURCE_STATE_QUERY_CONCEPTS),
                    "uniqueItems": True,
                    "items": {"enum": list(RESOURCE_STATE_QUERY_CONCEPTS)},
                },
            },
        },
        output_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["rows", "complete", "truncation_reason"],
            "x-fdai-measure-concepts": list(RESOURCE_STATE_QUERY_CONCEPTS),
            "x-fdai-measure-value-groups": [
                {"concept": concept, "terms": list(RESOURCE_STATE_MEASURE_TERMS[concept])}
                for concept in RESOURCE_STATE_QUERY_CONCEPTS
            ],
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
        timeout_seconds=5,
        cpu_millis=250,
        memory_bytes=67_108_864,
        max_output_bytes=1_048_576,
        network_allowed=False,
        credentials_allowed=False,
    )


def resource_state_inventory_function(
    ontology_release: OntologyRelease,
) -> ContextualOntologyFunction:
    """Filter verified observed state without provider I/O or health inference."""

    ontology_release.type_ref(
        OntologyDeclarationKind.FUNCTION,
        RESOURCE_STATE_FUNCTION_NAME,
    )

    async def evaluate(
        arguments: Mapping[str, Any],
        invocation_context: FunctionInvocationContext,
    ) -> object:
        if invocation_context.purposes != ("operations-review",):
            raise PermissionError("resource-state purpose does not match invocation context")
        secured = SecuredObjectSetQueryResult.model_validate(arguments["query_result"])
        if secured.receipt.truncated or not secured.receipt.complete:
            return _table((), complete=False, reason="resource_scope_incomplete")
        requested = frozenset(str(item) for item in arguments["state_concepts"])
        include_all_observed = requested == {RESOURCE_STATE_OBSERVED_CONCEPT}
        rows: list[QueryRow] = []
        incomplete = False
        for target in sorted(secured.materialization.graph.objects, key=lambda item: item.id):
            values = verified_resource_state_values(
                target,
                observation_cutoff=secured.receipt.observation_cutoff,
            )
            if values is None:
                incomplete = True
                continue
            if not include_all_observed and values["state_concept"] not in requested:
                continue
            rows.append(
                QueryRow.from_values(
                    f"resource-state-{len(rows) + 1:04d}",
                    values,
                )
            )
        return _table(
            tuple(rows),
            complete=not incomplete,
            reason="resource_state_evidence_incomplete" if incomplete else None,
        )

    return evaluate


def verified_resource_state_values(
    target: OntologyObjectRecord,
    *,
    observation_cutoff: Any,
) -> dict[str, object] | None:
    """Project one fresh conflict-free observed state without inferring health."""

    provider = _mapping(target.properties.get("properties"))
    raw_state = _text(provider.get("state"))
    state_concept = _state_concept(raw_state)
    metadata = _verified_state_metadata(
        provider.get(STATE_FACT_METADATA_PROPERTY),
        observation_cutoff=observation_cutoff,
    )
    if state_concept is None or metadata is None:
        return None
    return {
        "name": _text(target.properties.get("name")),
        "type": _text(target.properties.get("type")),
        "observed_state": raw_state,
        "state_concept": state_concept,
        "source_observed_at": metadata.effective_at.isoformat(),
        "inventory_read_at": observation_cutoff.isoformat(),
        "execution_authority": False,
    }


def _state_concept(value: str | None) -> str | None:
    if value is None:
        return None
    matched = _STATE_NAMES.intersection(re.findall(r"[a-z0-9]+", value.casefold()))
    if len(matched) != 1:
        return None
    return f"resource_state.{next(iter(matched))}"


def _verified_state_metadata(
    value: object,
    *,
    observation_cutoff: Any,
) -> StateFactMetadata | None:
    if not isinstance(value, Mapping):
        return None
    try:
        metadata = StateFactMetadata.from_mapping(value)
    except (TypeError, ValueError):
        return None
    age_seconds = (observation_cutoff - metadata.effective_at).total_seconds()
    if (
        metadata.lane is not StateFactLane.OBSERVED
        or metadata.synthetic
        or metadata.conflicts
        or metadata.completeness < 1.0
        or metadata.evidence_cutoff > observation_cutoff
        or metadata.recorded_at > observation_cutoff
        or not 0 <= age_seconds <= metadata.freshness_ceiling_seconds
    ):
        return None
    return metadata


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


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
    "RESOURCE_STATE_FUNCTION_NAME",
    "RESOURCE_STATE_MEASURE_CONCEPTS",
    "RESOURCE_STATE_MEASURE_TERMS",
    "RESOURCE_STATE_OBSERVED_CONCEPT",
    "RESOURCE_STATE_QUERY_CONCEPTS",
    "resource_state_function_type",
    "resource_state_inventory_function",
    "verified_resource_state_values",
]
