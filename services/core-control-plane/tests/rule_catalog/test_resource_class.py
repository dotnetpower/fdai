"""ResourceClass taxonomy validation and closure tests."""

from __future__ import annotations

import pytest
from fdai.core.ontology_platform.functions import (
    FunctionInvocationContext,
    OntologyFunctionRegistry,
)
from fdai.core.ontology_platform.resource_class_closure import (
    RESOURCE_CLASS_CLOSURE_FUNCTION_NAME,
    compile_resource_class_closure,
    resource_class_closure_function,
    resource_class_closure_function_type,
)
from fdai.rule_catalog.schema.resource_class import (
    ResourceClassRegistryError,
    load_resource_class_registry_from_mapping,
)
from fdai.rule_catalog.schema.resource_type import (
    ResourceTypeCategory,
    ResourceTypeEntry,
    ResourceTypeRegistry,
)
from fdai.shared.contracts.models import CeilingRole
from fdai.shared.ontology.release import build_ontology_release


def _resource_types() -> ResourceTypeRegistry:
    return ResourceTypeRegistry(
        schema_version="1.0.0",
        version="1.0.0",
        types=(
            ResourceTypeEntry(
                id="compute.vm",
                category=ResourceTypeCategory.COMPUTE,
                description="Virtual machine.",
            ),
            ResourceTypeEntry(
                id="compute.container-app",
                category=ResourceTypeCategory.COMPUTE,
                description="Container application.",
            ),
            ResourceTypeEntry(
                id="network.private-endpoint",
                category=ResourceTypeCategory.NETWORK,
                description="Private endpoint.",
            ),
        ),
    )


def _registry() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "version": "1.0.0",
        "classes": [
            {
                "id": "class.workload",
                "description": "Resource that runs application work.",
            },
            {
                "id": "class.compute-workload",
                "description": "Compute-hosted workload.",
                "members": ["compute.vm", "compute.container-app"],
                "specializes": ["class.workload"],
            },
            {
                "id": "class.network-endpoint",
                "description": "Network endpoint with independent identity.",
                "members": ["network.private-endpoint"],
            },
        ],
    }


def test_resource_class_closure_uses_only_explicit_membership() -> None:
    registry = load_resource_class_registry_from_mapping(
        _registry(),
        resource_types=_resource_types(),
    )

    assert registry.closure("class.workload") == ("compute.container-app", "compute.vm")
    assert registry.closure("class.network-endpoint") == ("network.private-endpoint",)


def test_resource_class_closure_receipt_pins_release_and_exact_members() -> None:
    registry = load_resource_class_registry_from_mapping(
        _registry(),
        resource_types=_resource_types(),
    )
    release_digest = "sha256:" + ("a" * 64)

    receipt = compile_resource_class_closure(
        registry=registry,
        resource_class_id="class.workload",
        ontology_release_digest=release_digest,
    )

    assert receipt.ontology_release_digest == release_digest
    assert receipt.registry_version == registry.version
    assert receipt.registry_digest == registry.content_digest
    assert receipt.class_ids == ("class.compute-workload", "class.workload")
    assert receipt.resource_type_ids == ("compute.container-app", "compute.vm")
    assert receipt.closure_digest.startswith("sha256:")
    assert receipt.complete is True
    assert receipt.execution_authority is False


async def test_resource_class_closure_function_is_exact_release_and_no_authority() -> None:
    registry = load_resource_class_registry_from_mapping(
        _registry(),
        resource_types=_resource_types(),
    )
    declaration = resource_class_closure_function_type()
    release = build_ontology_release(function_types=(declaration,))
    functions = OntologyFunctionRegistry(release=release)
    functions.register_contextual(
        declaration,
        resource_class_closure_function(release, registry=registry),
    )

    result = await functions.invoke(
        RESOURCE_CLASS_CLOSURE_FUNCTION_NAME,
        {"resource_class_id": "class.workload"},
        context=FunctionInvocationContext(
            caller_agent="Bragi",
            caller_role=CeilingRole.READER,
            purposes=("operations-review",),
        ),
    )

    assert result["ontology_release_digest"] == release.digest
    assert result["registry_digest"] == registry.content_digest
    assert result["resource_type_ids"] == ["compute.container-app", "compute.vm"]
    assert result["execution_authority"] is False


def test_resource_class_rejects_unknown_member() -> None:
    raw = _registry()
    raw["classes"][1]["members"].append("compute.unknown")  # type: ignore[index,union-attr]

    with pytest.raises(ResourceClassRegistryError, match="unknown ResourceType"):
        load_resource_class_registry_from_mapping(raw, resource_types=_resource_types())


def test_resource_type_rejects_an_id_too_long_for_closure_receipts() -> None:
    with pytest.raises(ValueError, match="at most 128 characters"):
        ResourceTypeEntry(
            id="compute." + ("a" * 121),
            category=ResourceTypeCategory.COMPUTE,
            description="Oversized type identity.",
        )


def test_resource_class_rejects_an_unreserved_global_object_id() -> None:
    raw = _registry()
    raw["classes"][0]["id"] = "workload"  # type: ignore[index]

    with pytest.raises(ResourceClassRegistryError, match="does not match"):
        load_resource_class_registry_from_mapping(raw, resource_types=_resource_types())


def test_resource_class_rejects_specialization_cycle() -> None:
    raw = _registry()
    raw["classes"][0]["specializes"] = ["class.compute-workload"]  # type: ignore[index]

    with pytest.raises(ResourceClassRegistryError, match="specialization cycle"):
        load_resource_class_registry_from_mapping(raw, resource_types=_resource_types())


def test_resource_class_rejects_an_unbounded_membership_projection() -> None:
    raw = {
        "schema_version": "1.0.0",
        "version": "1.0.0",
        "classes": [
            {
                "id": f"class.group-{index:03d}",
                "description": "Bounded synthetic taxonomy class.",
                "members": ["compute.vm", "compute.container-app"],
            }
            for index in range(129)
        ],
    }

    with pytest.raises(ResourceClassRegistryError, match="total memberships exceed 256"):
        load_resource_class_registry_from_mapping(raw, resource_types=_resource_types())
