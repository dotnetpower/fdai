"""Read-only FunctionType for exact screen and resource-group collections."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from fdai_service_contracts import context_selection_digest

from fdai.shared.contracts.models import (
    CeilingRole,
    LogicExecutionClass,
    OntologyDeclarationKind,
    OntologyFunctionKind,
    OntologyFunctionType,
    OntologyRelease,
)

from .functions import ContextualOntologyFunction, FunctionInvocationContext
from .query_gateway import SecuredObjectSetQueryResult
from .query_values import QueryRow, QueryTable

CONTEXTUAL_RESOURCE_FUNCTION_NAME = "query.contextual_resources"
_MAX_CONTEXT_IDS = 10_000
_MAX_RESOURCES = 10_000


def contextual_resource_function_type() -> OntologyFunctionType:
    """Declare a context-bound Resource collection read."""

    return OntologyFunctionType(
        name=CONTEXTUAL_RESOURCE_FUNCTION_NAME,
        version="1.0.0",
        kind=OntologyFunctionKind.QUERY,
        artifact_digest=f"sha256:{hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}",
        publisher="fdai",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": [
                "query_result",
                "context_kind",
                "context_id",
                "resource_ids",
                "principal_id",
                "principal_scope_digest",
                "ontology_release_digest",
                "source_generation",
                "selection_digest",
                "complete",
            ],
            "properties": {
                "query_result": {"type": "object", "x-fdai-dependency-only": True},
                "context_kind": {"enum": ["screen", "resource_group"]},
                "context_id": {"type": "string", "minLength": 1, "maxLength": 256},
                "resource_ids": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": _MAX_CONTEXT_IDS,
                    "uniqueItems": True,
                    "items": {"type": "string", "minLength": 1, "maxLength": 256},
                },
                "principal_id": {"type": "string", "minLength": 1, "maxLength": 256},
                "principal_scope_digest": {"type": "string", "pattern": r"^sha256:[a-f0-9]{64}$"},
                "ontology_release_digest": {"type": "string", "pattern": r"^sha256:[a-f0-9]{64}$"},
                "source_generation": {"type": "string", "minLength": 1, "maxLength": 256},
                "selection_digest": {"type": "string", "pattern": r"^sha256:[a-f0-9]{64}$"},
                "complete": {"const": True},
            },
        },
        output_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["rows", "complete", "truncation_reason"],
            "properties": {
                "rows": {"type": "array", "maxItems": _MAX_RESOURCES},
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


def contextual_resource_function(
    ontology_release: OntologyRelease,
) -> ContextualOntologyFunction:
    """Project only the exact server-selected context collection."""

    ontology_release.type_ref(
        OntologyDeclarationKind.FUNCTION,
        CONTEXTUAL_RESOURCE_FUNCTION_NAME,
    )

    async def evaluate(
        arguments: Mapping[str, Any],
        invocation_context: FunctionInvocationContext,
    ) -> object:
        if invocation_context.purposes != ("operations-review",):
            raise PermissionError("contextual resource purpose does not match invocation context")
        secured = SecuredObjectSetQueryResult.model_validate(arguments["query_result"])
        expected_ids = tuple(str(item) for item in arguments["resource_ids"])
        expected_digest = context_selection_digest(
            kind=arguments["context_kind"],
            principal_id=arguments["principal_id"],
            principal_scope_digest=arguments["principal_scope_digest"],
            ontology_release_digest=arguments["ontology_release_digest"],
            source_generation=arguments["source_generation"],
            complete=arguments["complete"],
            screen_id=arguments["context_id"] if arguments["context_kind"] == "screen" else None,
            resource_group_id=(
                arguments["context_id"] if arguments["context_kind"] == "resource_group" else None
            ),
            resource_ids=expected_ids,
        )
        if arguments["selection_digest"] != expected_digest:
            return _table((), complete=False, reason="context_identity_mismatch")
        if arguments["ontology_release_digest"] != secured.receipt.ontology_release.digest:
            return _table((), complete=False, reason="context_release_mismatch")
        if arguments["source_generation"] != secured.receipt.source_generation:
            return _table((), complete=False, reason="context_generation_mismatch")
        actual_ids = tuple(item.id for item in secured.materialization.graph.objects)
        if (
            len(actual_ids) != len(set(actual_ids))
            or len(expected_ids) != len(set(expected_ids))
            or not set(actual_ids) <= set(expected_ids)
        ):
            return _table((), complete=False, reason="context_scope_mismatch")
        if secured.receipt.truncated or not secured.receipt.complete:
            return _table((), complete=False, reason="context_scope_incomplete")
        rows = tuple(
            QueryRow.from_values(
                f"contextual-resource-{index:04d}",
                _scalar_properties(item.properties),
            )
            for index, item in enumerate(secured.materialization.graph.objects, start=1)
        )
        return _table(rows, complete=True, reason=None)

    return evaluate


def _scalar_properties(properties: Mapping[str, object]) -> dict[str, object]:
    """Keep context results readable without exposing provider bags."""
    return {
        key: value
        for key, value in properties.items()
        if isinstance(value, str | int | float | bool) or value is None
    }


def _table(
    rows: tuple[QueryRow, ...],
    *,
    complete: bool,
    reason: str | None,
) -> dict[str, object]:
    table = QueryTable(rows=rows, complete=complete, truncation_reason=reason)
    return cast(dict[str, object], json.loads(table.canonical_json()))


__all__ = [
    "CONTEXTUAL_RESOURCE_FUNCTION_NAME",
    "contextual_resource_function",
    "contextual_resource_function_type",
]
