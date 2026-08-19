"""Exact-release declaration query tests."""

from __future__ import annotations

from fdai.core.ontology_platform.declaration_queries import (
    ONTOLOGY_DECLARATION_FUNCTION_NAME,
    ontology_declaration_function,
    ontology_declaration_function_type,
)
from fdai.core.ontology_platform.functions import (
    FunctionInvocationContext,
    OntologyFunctionRegistry,
)
from fdai.shared.contracts.models import (
    CeilingRole,
    OntologyLinkType,
    OntologyObjectType,
    PropertyDecl,
    PropertyType,
)
from fdai.shared.ontology.release import build_ontology_release


def _object() -> OntologyObjectType:
    return OntologyObjectType(
        schema_version="1.0.0",
        name="Resource",
        version="1.0.0",
        key="id",
        properties={
            "id": PropertyDecl(type=PropertyType.STRING, required=True),
            "secret_note": PropertyDecl(
                type=PropertyType.STRING,
                access_scope=CeilingRole.OWNER,
            ),
        },
    )


async def test_declaration_query_filters_properties_and_lists_exact_dependents() -> None:
    resource = _object()
    link = OntologyLinkType(
        schema_version="1.0.0",
        name="depends_on",
        version="1.0.0",
        from_type="Resource",
        to_type="Resource",
        cardinality="many_to_many",
    )
    function_type = ontology_declaration_function_type()
    release = build_ontology_release(
        object_types=(resource,),
        link_types=(link,),
        function_types=(function_type,),
    )
    registry = OntologyFunctionRegistry(release=release)
    registry.register_contextual(
        function_type,
        ontology_declaration_function(
            release,
            object_types=(resource,),
            link_types=(link,),
            action_types=(),
            interface_types=(),
            interface_implementations=(),
        ),
    )
    context = FunctionInvocationContext(
        caller_agent="Bragi",
        caller_role=CeilingRole.READER,
        purposes=("operations-review",),
    )

    detail = await registry.invoke(
        ONTOLOGY_DECLARATION_FUNCTION_NAME,
        {"kind": "object", "name": "Resource", "section": "detail", "limit": 10},
        context=context,
    )
    dependents = await registry.invoke(
        ONTOLOGY_DECLARATION_FUNCTION_NAME,
        {"kind": "object", "name": "Resource", "section": "dependents", "limit": 10},
        context=context,
    )

    values = detail["rows"][0]["values"]
    assert set(values["declaration"]["properties"]) == {"id"}
    assert values["redaction_reasons"] == ["role"]
    assert values["execution_authority"] is False
    assert values["mutation_authority"] is False
    assert dependents["rows"][0]["values"]["dependent_name"] == "depends_on"
    assert dependents["complete"] is True


async def test_declaration_query_rejects_unknown_identity_before_projection() -> None:
    resource = _object()
    function_type = ontology_declaration_function_type()
    release = build_ontology_release(object_types=(resource,), function_types=(function_type,))
    registry = OntologyFunctionRegistry(release=release)
    registry.register_contextual(
        function_type,
        ontology_declaration_function(
            release,
            object_types=(resource,),
            link_types=(),
            action_types=(),
            interface_types=(),
            interface_implementations=(),
        ),
    )

    try:
        await registry.invoke(
            ONTOLOGY_DECLARATION_FUNCTION_NAME,
            {"kind": "object", "name": "Missing", "section": "detail", "limit": 10},
            context=FunctionInvocationContext(
                caller_agent="Bragi",
                caller_role=CeilingRole.READER,
                purposes=("operations-review",),
            ),
        )
    except LookupError as error:
        assert "unknown object declaration" in str(error)
    else:
        raise AssertionError("unknown declaration did not fail closed")
