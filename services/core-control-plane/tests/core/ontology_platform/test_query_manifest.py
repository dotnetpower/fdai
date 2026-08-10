"""Coverage accounting for release-derived planner descriptors."""

from __future__ import annotations

import pytest
from fdai.core.ontology_platform import build_query_manifest
from fdai.shared.contracts.models import (
    CeilingRole,
    LinkCardinality,
    OntologyFunctionKind,
    OntologyFunctionType,
    OntologyInterfaceType,
    OntologyLinkType,
    OntologyObjectType,
    PropertyDecl,
    PropertyType,
)
from fdai.shared.ontology.release import build_ontology_release

SCOPE_DIGEST = "sha256:" + "f" * 64


def _resource() -> OntologyObjectType:
    return OntologyObjectType(
        schema_version="1.0.0",
        name="Resource",
        version="1.0.0",
        key="id",
        properties={
            "id": PropertyDecl(type=PropertyType.STRING, required=True),
            "secret": PropertyDecl(
                type=PropertyType.STRING,
                access_scope=CeilingRole.OWNER,
                purpose_binding=["security-review"],
            ),
        },
    )


def _observable() -> OntologyInterfaceType:
    return OntologyInterfaceType(
        name="Observable",
        version="1.0.0",
        properties={"observed_at": PropertyDecl(type=PropertyType.DATETIME)},
    )


def _contains() -> OntologyLinkType:
    return OntologyLinkType(
        schema_version="1.0.0",
        name="contains",
        version="1.0.0",
        from_type="Resource",
        to_type="Resource",
        cardinality=LinkCardinality.ONE_TO_MANY,
        is_transitive=True,
    )


def _function(*, role: CeilingRole = CeilingRole.READER) -> OntologyFunctionType:
    return OntologyFunctionType(
        name="query.resources",
        version="1.0.0",
        kind=OntologyFunctionKind.QUERY,
        artifact_digest="sha256:" + "a" * 64,
        publisher="fdai",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        required_role=role,
        purpose_bindings=["operations-review"],
    )


def test_manifest_accounts_for_descriptors_and_unavailable_link_sides() -> None:
    resource = _resource()
    interface = _observable()
    link = _contains()
    function = _function()
    release = build_ontology_release(
        object_types=(resource,),
        link_types=(link,),
        interface_types=(interface,),
        function_types=(function,),
    )

    manifest = build_query_manifest(
        release=release,
        principal_role=CeilingRole.READER,
        purposes=("operations-review",),
        principal_scope_digest=SCOPE_DIGEST,
        object_types=(resource,),
        link_types=(link,),
        interfaces=(interface,),
        functions=(function,),
    )

    assert manifest.coverage_receipt.complete is True
    assert manifest.coverage_receipt.readable_declaration_count == 4
    assert manifest.coverage_receipt.descriptor_count == 3
    assert manifest.coverage_receipt.unavailable_declaration_ids == ("link:contains",)
    object_descriptor = next(item for item in manifest.descriptors if item["kind"] == "object")
    assert set(object_descriptor["properties"]) == {"id"}

    owner_manifest = build_query_manifest(
        release=release,
        principal_role=CeilingRole.OWNER,
        purposes=("operations-review", "security-review"),
        principal_scope_digest=SCOPE_DIGEST,
        object_types=(resource,),
        link_types=(link,),
        interfaces=(interface,),
        functions=(function,),
    )
    owner_object = next(item for item in owner_manifest.descriptors if item["kind"] == "object")
    assert "secret" in owner_object["properties"]


def test_manifest_filters_functions_by_role_and_purpose() -> None:
    owner_function = _function(role=CeilingRole.OWNER)
    release = build_ontology_release(function_types=(owner_function,))

    reader = build_query_manifest(
        release=release,
        principal_role=CeilingRole.READER,
        purposes=("operations-review",),
        principal_scope_digest=SCOPE_DIGEST,
        functions=(owner_function,),
    )
    wrong_purpose = build_query_manifest(
        release=release,
        principal_role=CeilingRole.OWNER,
        purposes=("incident-investigation",),
        principal_scope_digest=SCOPE_DIGEST,
        functions=(owner_function,),
    )
    owner = build_query_manifest(
        release=release,
        principal_role=CeilingRole.OWNER,
        purposes=("operations-review",),
        principal_scope_digest=SCOPE_DIGEST,
        functions=(owner_function,),
    )

    assert reader.coverage_receipt.readable_declaration_count == 0
    assert wrong_purpose.coverage_receipt.readable_declaration_count == 0
    assert owner.coverage_receipt.readable_declaration_count == 1
    assert owner.descriptors[0]["name"] == "query.resources"


def test_manifest_is_order_independent_and_content_addressed() -> None:
    resource = _resource()
    interface = _observable()
    release = build_ontology_release(object_types=(resource,), interface_types=(interface,))

    first = build_query_manifest(
        release=release,
        principal_role=CeilingRole.READER,
        purposes=("operations-review", "incident-investigation"),
        principal_scope_digest=SCOPE_DIGEST,
        object_types=(resource,),
        interfaces=(interface,),
    )
    second = build_query_manifest(
        release=release,
        principal_role=CeilingRole.READER,
        purposes=("incident-investigation", "operations-review"),
        principal_scope_digest=SCOPE_DIGEST,
        interfaces=(interface,),
        object_types=(resource,),
    )

    assert first.manifest_digest == second.manifest_digest
    assert first.coverage_receipt.receipt_digest == second.coverage_receipt.receipt_digest


def test_manifest_rejects_supplied_declaration_absent_from_release() -> None:
    resource = _resource()
    empty_release = build_ontology_release()

    with pytest.raises(ValueError, match="absent from the release"):
        build_query_manifest(
            release=empty_release,
            principal_role=CeilingRole.READER,
            purposes=("operations-review",),
            principal_scope_digest=SCOPE_DIGEST,
            object_types=(resource,),
        )
