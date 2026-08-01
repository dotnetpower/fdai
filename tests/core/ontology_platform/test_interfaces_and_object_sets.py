"""Semantic interface and bounded object-set tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from fdai.core.ontology_platform import (
    InterfaceImplementation,
    ObjectPredicate,
    ObjectSelector,
    ObjectSelectorKind,
    ObjectSetDefinition,
    ObjectSetService,
    OntologyInterfaceType,
    compile_interfaces,
)
from fdai.shared.contracts.models import OntologyObjectType, PropertyDecl, PropertyType
from fdai.shared.providers.ontology_instance import OntologyObjectRecord
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore


def _object_type(name: str, *, include_owner: bool = True) -> OntologyObjectType:
    properties = {
        "id": PropertyDecl(type=PropertyType.STRING, required=True),
        "status": PropertyDecl(type=PropertyType.STRING, required=True),
    }
    if include_owner:
        properties["owner_ref"] = PropertyDecl(type=PropertyType.STRING, required=True)
    return OntologyObjectType(
        schema_version="1.0.0",
        name=name,
        version="1.0.0",
        key="id",
        properties=properties,
    )


def _interfaces():
    ownable = OntologyInterfaceType(
        name="Ownable",
        version="1.0.0",
        properties={"owner_ref": PropertyDecl(type=PropertyType.STRING, required=True)},
    )
    operable = OntologyInterfaceType(
        name="Operable",
        version="1.0.0",
        extends=("Ownable",),
        supported_actions=("ops.restart-service",),
    )
    return ownable, operable


def test_interface_compilation_expands_inheritance() -> None:
    ownable, operable = _interfaces()
    compiled = compile_interfaces(
        interfaces=(ownable, operable),
        implementations=(
            InterfaceImplementation(object_type="Workload", interfaces=("Operable",)),
        ),
        object_types=(_object_type("Workload"),),
    )

    assert compiled.resolve("Operable") == ("Workload",)
    assert compiled.resolve("Ownable") == ("Workload",)
    assert "owner_ref" in compiled.interfaces["Operable"].properties


def test_interface_compilation_rejects_missing_property_and_cycle() -> None:
    ownable, operable = _interfaces()
    with pytest.raises(ValueError, match="missing interface properties"):
        compile_interfaces(
            interfaces=(ownable, operable),
            implementations=(
                InterfaceImplementation(object_type="Workload", interfaces=("Operable",)),
            ),
            object_types=(_object_type("Workload", include_owner=False),),
        )
    cyclic = OntologyInterfaceType(name="Cyclic", version="1.0.0", extends=("Cyclic",))
    with pytest.raises(ValueError, match="inheritance cycle"):
        compile_interfaces(interfaces=(cyclic,), implementations=(), object_types=())


async def test_object_set_materializes_interface_query_with_hard_limit() -> None:
    workload = _object_type("Workload")
    ownable, operable = _interfaces()
    compiled = compile_interfaces(
        interfaces=(ownable, operable),
        implementations=(
            InterfaceImplementation(object_type="Workload", interfaces=("Operable",)),
        ),
        object_types=(workload,),
    )
    store = InMemoryOntologyInstanceStore(object_types=(workload,), link_types=())
    for identifier in ("workload-a", "workload-b"):
        await store.upsert_object(
            OntologyObjectRecord(
                id=identifier,
                object_type="Workload",
                properties={"id": identifier, "status": "ready", "owner_ref": "team-a"},
            )
        )
    service = ObjectSetService(
        store=store,
        interfaces=compiled,
        object_type_names=frozenset({"Workload"}),
    )
    definition = ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.INTERFACE, name="Operable"),
        predicates=(ObjectPredicate(property="status", equals="ready"),),
        as_of=datetime(2026, 8, 1, tzinfo=UTC),
        purpose="operations-review",
        limit=1,
    )

    result = await service.materialize(definition)

    assert [item.id for item in result.graph.objects] == ["workload-a"]
    assert result.truncated is True
    assert result.truncation_reason == "result_limit"


def test_object_set_rejects_unbounded_or_naive_traversal() -> None:
    with pytest.raises(ValueError, match="less than or equal to 1000"):
        ObjectSetDefinition(
            selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Workload"),
            as_of=datetime(2026, 8, 1, tzinfo=UTC),
            purpose="operations-review",
            limit=1001,
        )
