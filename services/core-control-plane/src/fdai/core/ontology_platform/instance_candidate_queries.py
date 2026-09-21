"""Read-only, principal-bound ontology instance candidate function."""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Any

from fdai_service_contracts.ontology_query import content_digest

from fdai.shared.contracts.models import (
    CeilingRole,
    LogicExecutionClass,
    OntologyFunctionKind,
    OntologyFunctionType,
)

from .functions import ContextualOntologyFunction, FunctionInvocationContext

INSTANCE_CANDIDATES_FUNCTION_NAME = "query.ontology_instance_candidates"
InstanceCandidateQuery = Callable[
    [str, int, FunctionInvocationContext], Awaitable[Mapping[str, Any]]
]


def instance_candidates_function_type(
    *,
    object_type_names: tuple[str, ...],
) -> OntologyFunctionType:
    """Declare bounded candidates without exhaustive-absence or action authority."""
    if not object_type_names or any(not name.strip() for name in object_type_names):
        raise ValueError("ontology candidates require declared object read sets")
    digest_schema = {"type": "string", "pattern": "^sha256:[a-f0-9]{64}$"}
    return OntologyFunctionType(
        name=INSTANCE_CANDIDATES_FUNCTION_NAME,
        version="1.0.0",
        kind=OntologyFunctionKind.QUERY,
        artifact_digest="sha256:" + hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        publisher="fdai",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["query", "limit"],
            "properties": {
                "query": {"type": "string", "minLength": 1, "maxLength": 4096},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            },
        },
        output_schema={
            "type": "object",
            "additionalProperties": False,
            "required": [
                "candidates",
                "evidence_refs",
                "result_digest",
                "truncated",
                "candidate_count",
                "authority",
                "exhaustive",
                "execution_authority",
                "principal_scope_digest",
                "ontology_release_digest",
                "query_digest",
            ],
            "properties": {
                "candidates": {
                    "type": "array",
                    "maxItems": 20,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["id", "object_type", "properties", "revision"],
                        "properties": {
                            "id": {"type": "string", "minLength": 1},
                            "object_type": {"enum": sorted(set(object_type_names))},
                            "properties": {"type": "object"},
                            "revision": {"type": "integer", "minimum": 0},
                        },
                    },
                },
                "evidence_refs": {
                    "type": "array",
                    "maxItems": 16,
                    "uniqueItems": True,
                    "items": digest_schema,
                },
                "result_digest": digest_schema,
                "principal_scope_digest": digest_schema,
                "ontology_release_digest": digest_schema,
                "query_digest": digest_schema,
                "truncated": {"type": "boolean"},
                "candidate_count": {"type": "integer", "minimum": 0, "maximum": 20000},
                "authority": {"const": "candidate_only"},
                "exhaustive": {"const": False},
                "execution_authority": {"const": False},
            },
        },
        read_sets=sorted(set(object_type_names)),
        execution_class=LogicExecutionClass.DETERMINISTIC,
        required_role=CeilingRole.READER,
        purpose_bindings=["operations-review"],
        timeout_seconds=5,
        cpu_millis=1000,
        memory_bytes=134_217_728,
        max_output_bytes=131_072,
        network_allowed=False,
        credentials_allowed=False,
    )


def instance_candidates_function(
    query: InstanceCandidateQuery,
    *,
    ontology_release_digest: str,
) -> ContextualOntologyFunction:
    """Bind trusted principal and release instead of accepting scope as model arguments."""

    async def evaluate(arguments: Mapping[str, Any], context: FunctionInvocationContext) -> object:
        if (
            context.caller_agent != "Bragi"
            or context.purposes != ("operations-review",)
            or not context.principal_ref
            or not context.principal_ref.strip()
            or context.principal_scope_digest is None
        ):
            raise PermissionError("ontology candidates require authenticated presentation scope")
        result = await query(str(arguments["query"]), int(arguments["limit"]), context)
        if (
            result.get("principal_scope_digest") != context.principal_scope_digest
            or result.get("ontology_release_digest") != ontology_release_digest
            or result.get("authority") != "candidate_only"
            or result.get("execution_authority") is not False
            or result.get("exhaustive") is not False
            or result.get("query_digest") != content_digest(dict(arguments))
            or result.get("result_digest")
            != content_digest(
                {key: value for key, value in result.items() if key != "result_digest"}
            )
        ):
            raise ValueError("ontology candidate response scope or authority mismatch")
        candidates = result.get("candidates")
        count = result.get("candidate_count")
        if (
            not isinstance(candidates, list)
            or type(count) is not int
            or len(candidates) != min(count, int(arguments["limit"]))
            or result.get("truncated") is not (count > len(candidates))
            or (candidates and not result.get("evidence_refs"))
        ):
            raise ValueError("ontology candidate response accounting mismatch")
        return result

    return evaluate
