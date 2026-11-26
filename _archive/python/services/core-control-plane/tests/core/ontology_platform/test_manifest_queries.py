"""Exact-release principal-manifest query tests."""

from __future__ import annotations

from fdai.core.ontology_platform.functions import (
    FunctionInvocationContext,
    OntologyFunctionRegistry,
)
from fdai.core.ontology_platform.manifest_queries import (
    ONTOLOGY_MANIFEST_FUNCTION_NAME,
    ontology_manifest_function,
    ontology_manifest_function_type,
)
from fdai.core.ontology_platform.query_manifest import QueryManifest, build_query_manifest
from fdai.shared.contracts.models import (
    CeilingRole,
    OntologyDeclarationKind,
    OntologyObjectType,
    PropertyDecl,
    PropertyType,
)
from fdai.shared.ontology.release import build_ontology_release


async def test_manifest_function_lists_role_scoped_exact_release_declarations() -> None:
    resource = OntologyObjectType(
        schema_version="1.0.0",
        name="Resource",
        version="1.0.0",
        key="id",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
    )
    declaration = ontology_manifest_function_type()
    release = build_ontology_release(
        object_types=(resource,),
        function_types=(declaration,),
    )

    def manifest_for_context(
        role: CeilingRole,
        purposes: tuple[str, ...],
    ) -> QueryManifest:
        return build_query_manifest(
            release=release,
            principal_role=role,
            purposes=purposes,
            principal_scope_digest="sha256:" + ("c" * 64),
            object_types=(resource,),
            functions=(declaration,),
            bound_function_names=(ONTOLOGY_MANIFEST_FUNCTION_NAME,),
        )

    registry = OntologyFunctionRegistry(release=release)
    registry.register_contextual(
        declaration,
        ontology_manifest_function(
            release,
            manifest_for_context=manifest_for_context,
        ),
    )
    resource_digest = next(
        item.declaration_digest
        for item in release.declarations
        if item.kind is OntologyDeclarationKind.OBJECT and item.name == "Resource"
    )

    result = await registry.invoke(
        ONTOLOGY_MANIFEST_FUNCTION_NAME,
        {"kinds": ["object"], "limit": 10},
        context=FunctionInvocationContext(
            caller_agent="Bragi",
            caller_role=CeilingRole.READER,
            purposes=("operations-review",),
        ),
    )

    assert result == {
        "rows": [
            {
                "row_id": "object:Resource",
                "values": {
                    "kind": "object",
                    "name": "Resource",
                    "version": "1.0.0",
                    "declaration_digest": resource_digest,
                    "available": True,
                    "execution_authority": False,
                },
            }
        ],
        "complete": True,
        "truncation_reason": None,
    }
