"""Contract checks for candidate-only instance retrieval through FunctionRegistry."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fdai.core.ontology_platform.functions import (
    FunctionInvocationContext,
    OntologyFunctionRegistry,
)
from fdai.core.ontology_platform.instance_candidate_queries import (
    INSTANCE_CANDIDATES_FUNCTION_NAME,
    instance_candidates_function,
    instance_candidates_function_type,
)
from fdai.shared.ontology.release import build_ontology_release
from fdai_service_contracts.ontology_query import content_digest


@pytest.mark.parametrize(
    "drift",
    [
        "none",
        "scope",
        "release",
        "query",
        "authority",
        "exhaustive",
        "anonymous",
        "purpose",
        "agent",
        "scope_argument",
        "result",
        "count",
        "truncation",
        "candidate_schema",
        "read_set",
        "blank_principal",
    ],
)
async def test_instance_candidates_bind_scope_release_query_and_read_only_authority(
    drift: str,
) -> None:
    declaration = instance_candidates_function_type(object_type_names=("Resource",))
    assert declaration.read_sets == ["Resource"]
    release = build_ontology_release(function_types=(declaration,))
    context = FunctionInvocationContext(
        caller_agent="Bragi",
        principal_ref="example-reader",
        principal_scope_digest=content_digest("example-scope"),
        purposes=("operations-review",),
    )
    arguments = {"query": "example resource", "limit": 10}
    body = {
        "candidates": [],
        "evidence_refs": [],
        "candidate_count": 0,
        "truncated": False,
        "authority": "candidate_only",
        "execution_authority": False,
        "exhaustive": False,
        "principal_scope_digest": context.principal_scope_digest,
        "ontology_release_digest": release.digest,
        "query_digest": content_digest(arguments),
    }
    body["result_digest"] = content_digest(body)
    field = {
        "scope": "principal_scope_digest",
        "release": "ontology_release_digest",
        "query": "query_digest",
    }.get(drift)
    if field:
        body[field] = content_digest("different")
    elif drift == "authority":
        body["execution_authority"] = True
    elif drift == "exhaustive":
        body["exhaustive"] = True
    elif drift == "anonymous":
        context = context.model_copy(update={"principal_ref": None})
    elif drift == "blank_principal":
        context = context.model_copy(update={"principal_ref": " "})
    elif drift == "purpose":
        context = context.model_copy(update={"purposes": ("incident-response",)})
    elif drift == "agent":
        context = context.model_copy(update={"caller_agent": "Thor"})
    elif drift == "scope_argument":
        arguments["scope"] = "different"  # type: ignore[assignment]
    elif drift == "result":
        body["candidate_count"] = 1
    elif drift == "count":
        body["candidate_count"] = 1
    elif drift == "truncation":
        body["truncated"] = True
    elif drift in {"candidate_schema", "read_set"}:
        body["candidates"] = [
            {
                "id": "example-resource",
                "object_type": "Resource",
                "properties": {},
                "revision": 1,
            }
        ]
        body["candidate_count"] = 1
        body["evidence_refs"] = [content_digest("query-receipt")]
        if drift == "candidate_schema":
            body["candidates"][0]["unexpected"] = True
        else:
            body["candidates"][0]["object_type"] = "Incident"
    if drift in {"count", "truncation", "candidate_schema", "read_set"}:
        body["result_digest"] = content_digest(
            {key: value for key, value in body.items() if key != "result_digest"}
        )
    query = AsyncMock(return_value=body)
    registry = OntologyFunctionRegistry(release=release)
    registry.register_contextual(
        declaration,
        instance_candidates_function(query, ontology_release_digest=release.digest),
    )
    if drift != "none":
        expected_error = (
            TypeError
            if drift in {"candidate_schema", "read_set"}
            else PermissionError
            if drift in {"anonymous", "blank_principal", "purpose", "agent"}
            else ValueError
        )
        with pytest.raises(expected_error):
            await registry.invoke(INSTANCE_CANDIDATES_FUNCTION_NAME, arguments, context=context)
        if drift in {"anonymous", "blank_principal", "purpose", "agent", "scope_argument"}:
            query.assert_not_awaited()
        return
    result, receipt = await registry.invoke_with_receipt(
        INSTANCE_CANDIDATES_FUNCTION_NAME,
        arguments,
        context=context,
    )
    assert result == body
    assert receipt.principal_scope_digest == context.principal_scope_digest
    query.assert_awaited_once_with("example resource", 10, context)
