"""Retained exact-release semantic diff tests."""

from __future__ import annotations

import pytest
from fdai.core.ontology_platform.functions import (
    FunctionInvocationContext,
    OntologyFunctionRegistry,
)
from fdai.core.ontology_platform.release_diff_queries import (
    ONTOLOGY_RELEASE_DIFF_FUNCTION_NAME,
    ontology_release_diff_function,
    ontology_release_diff_function_type,
)
from fdai.shared.contracts.models import CeilingRole, OntologyObjectType, PropertyDecl, PropertyType
from fdai.shared.ontology.release import build_ontology_release


def _object(name: str) -> OntologyObjectType:
    return OntologyObjectType(
        schema_version="1.0.0",
        name=name,
        version="1.0.0",
        key="id",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
    )


async def test_release_diff_uses_retained_refs_and_exposes_no_authority() -> None:
    function_type = ontology_release_diff_function_type()
    base = build_ontology_release(object_types=(_object("Resource"),))
    candidate = build_ontology_release(
        object_types=(_object("Resource"), _object("Service")),
        function_types=(function_type,),
    )
    registry = OntologyFunctionRegistry(release=candidate)
    registry.register_contextual(
        function_type,
        ontology_release_diff_function(
            candidate,
            retained_releases=(base, candidate),
        ),
    )

    result = await registry.invoke(
        ONTOLOGY_RELEASE_DIFF_FUNCTION_NAME,
        {
            "base_release_digest": base.digest,
            "candidate_release_digest": candidate.digest,
            "limit": 100,
        },
        context=FunctionInvocationContext(
            caller_agent="Bragi",
            caller_role=CeilingRole.READER,
            purposes=("operations-review",),
        ),
    )

    assert result["complete"] is True
    values = result["rows"][0]["values"]
    assert values["change_kind"] == "added"
    assert values["historical_schema_detail"] == "declaration_refs_only"
    assert values["execution_authority"] is False
    assert values["mutation_authority"] is False


async def test_release_diff_rejects_unretained_or_same_release() -> None:
    function_type = ontology_release_diff_function_type()
    active = build_ontology_release(
        object_types=(_object("Resource"),),
        function_types=(function_type,),
    )
    registry = OntologyFunctionRegistry(release=active)
    registry.register_contextual(
        function_type,
        ontology_release_diff_function(active, retained_releases=(active,)),
    )
    context = FunctionInvocationContext(
        caller_agent="Bragi",
        caller_role=CeilingRole.READER,
        purposes=("operations-review",),
    )

    with pytest.raises(ValueError, match="distinct"):
        await registry.invoke(
            ONTOLOGY_RELEASE_DIFF_FUNCTION_NAME,
            {
                "base_release_digest": active.digest,
                "candidate_release_digest": active.digest,
                "limit": 100,
            },
            context=context,
        )
