"""Semantic interface and bounded object-set tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest
from fdai.core.ontology_platform import (
    InterfaceImplementation,
    ObjectPredicate,
    ObjectSelector,
    ObjectSelectorKind,
    ObjectSetDefinition,
    ObjectSetService,
    OntologyInterfaceType,
    RelationshipTraversalDefinition,
    compile_interfaces,
)
from fdai.shared.contracts.models import (
    CeilingRole,
    OntologyObjectType,
    PropertyDecl,
    PropertyType,
)
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


def _interfaces() -> tuple[OntologyInterfaceType, OntologyInterfaceType]:
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


class _TrackingStore(InMemoryOntologyInstanceStore):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.active = 0
        self.max_active = 0

    async def query_objects(self, **kwargs: Any):  # type: ignore[no-untyped-def]
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(0)
            return await super().query_objects(**kwargs)
        finally:
            self.active -= 1


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


def test_compiled_interface_catalog_is_deeply_immutable() -> None:
    ownable, operable = _interfaces()
    compiled = compile_interfaces(
        interfaces=(ownable, operable),
        implementations=(
            InterfaceImplementation(object_type="Workload", interfaces=("Operable",)),
        ),
        object_types=(_object_type("Workload"),),
    )

    with pytest.raises(TypeError):
        compiled.concrete_types["Operable"] = ("Other",)  # type: ignore[index]
    with pytest.raises(TypeError):
        compiled.interfaces["Operable"].properties["injected"] = PropertyDecl(
            type=PropertyType.STRING
        )
    assert compiled.resolve("Operable") == ("Workload",)


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


def test_interface_compilation_rejects_incompatible_parent_properties() -> None:
    left = OntologyInterfaceType(
        name="Left", version="1.0.0", properties={"value": PropertyDecl(type=PropertyType.STRING)}
    )
    right = OntologyInterfaceType(
        name="Right", version="1.0.0", properties={"value": PropertyDecl(type=PropertyType.INTEGER)}
    )
    child = OntologyInterfaceType(name="Child", version="1.0.0", extends=("Left", "Right"))

    with pytest.raises(ValueError, match="conflicting properties"):
        compile_interfaces(interfaces=(left, right, child), implementations=(), object_types=())


@pytest.mark.parametrize(
    ("requirement", "implementation", "reason"),
    [
        (
            PropertyDecl(type=PropertyType.STRING),
            PropertyDecl(type=PropertyType.INTEGER),
            "type",
        ),
        (
            PropertyDecl(type=PropertyType.STRING, required=True),
            PropertyDecl(type=PropertyType.STRING),
            "requiredness",
        ),
        (
            PropertyDecl(type=PropertyType.STRING, access_scope=CeilingRole.APPROVER),
            PropertyDecl(type=PropertyType.STRING, access_scope=CeilingRole.READER),
            "access scope",
        ),
        (
            PropertyDecl(type=PropertyType.STRING, purpose_binding=["incident-response"]),
            PropertyDecl(
                type=PropertyType.STRING,
                purpose_binding=["incident-response", "inventory-review"],
            ),
            "purpose binding",
        ),
    ],
)
def test_interface_compilation_rejects_incompatible_property_contracts(
    requirement: PropertyDecl,
    implementation: PropertyDecl,
    reason: str,
) -> None:
    interface = OntologyInterfaceType(
        name="Observable",
        version="1.0.0",
        properties={"status": requirement},
    )
    object_type = _object_type("Workload").model_copy(
        update={
            "properties": {
                **_object_type("Workload").properties,
                "status": implementation,
            }
        }
    )

    with pytest.raises(ValueError, match=reason):
        compile_interfaces(
            interfaces=(interface,),
            implementations=(
                InterfaceImplementation(object_type="Workload", interfaces=("Observable",)),
            ),
            object_types=(object_type,),
        )


def test_interface_compilation_accepts_more_restrictive_property_contract() -> None:
    interface = OntologyInterfaceType(
        name="Observable",
        version="1.0.0",
        properties={
            "status": PropertyDecl(
                type=PropertyType.STRING,
                purpose_binding=["incident-response", "inventory-review"],
            )
        },
    )
    object_type = _object_type("Workload").model_copy(
        update={
            "properties": {
                **_object_type("Workload").properties,
                "status": PropertyDecl(
                    type=PropertyType.STRING,
                    required=True,
                    access_scope=CeilingRole.APPROVER,
                    purpose_binding=["incident-response"],
                ),
            }
        }
    )

    compiled = compile_interfaces(
        interfaces=(interface,),
        implementations=(
            InterfaceImplementation(object_type="Workload", interfaces=("Observable",)),
        ),
        object_types=(object_type,),
    )

    assert compiled.resolve("Observable") == ("Workload",)


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


async def test_exact_id_membership_reads_beyond_store_candidate_limit() -> None:
    resource_type = _object_type("Resource", include_owner=False).model_copy(
        update={
            "properties": {
                **_object_type("Resource", include_owner=False).properties,
                "name": PropertyDecl(type=PropertyType.STRING),
            }
        }
    )
    store = _TrackingStore(object_types=(resource_type,), link_types=())
    identifiers = tuple(f"resource-{index}" for index in range(1001))
    for identifier in identifiers:
        await store.upsert_object(
            OntologyObjectRecord(
                id=identifier,
                object_type="Resource",
                properties={
                    "id": identifier,
                    "status": "ready",
                    "name": "target" if identifier == "resource-1000" else "other",
                },
            )
        )
    service = ObjectSetService(
        store=store,
        interfaces=compile_interfaces(
            interfaces=(), implementations=(), object_types=(resource_type,)
        ),
        object_type_names=frozenset({"Resource"}),
    )
    definition = ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
        predicates=(
            ObjectPredicate(property="id", operator="in", values=identifiers),
            ObjectPredicate(property="name", equals="target"),
        ),
        as_of=datetime(2026, 8, 1, tzinfo=UTC),
        purpose="operations-review",
        limit=1000,
    )

    result = await service.materialize(definition)

    assert [item.id for item in result.graph.objects] == ["resource-1000"]
    assert result.truncated is False
    assert store.max_active <= 16


def test_object_set_rejects_unbounded_or_naive_traversal() -> None:
    with pytest.raises(ValueError, match="less than or equal to 1000"):
        ObjectSetDefinition(
            selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Workload"),
            as_of=datetime(2026, 8, 1, tzinfo=UTC),
            purpose="operations-review",
            limit=1001,
        )


def test_relationship_traversal_v1_accepts_exactly_one_link_type() -> None:
    definition = RelationshipTraversalDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Workload"),
        link_types=("depends_on",),
        as_of=datetime(2026, 8, 1, tzinfo=UTC),
        purpose="operations-review",
    )

    assert definition.link_types == ("depends_on",)


def test_relationship_traversal_v1_rejects_an_ordered_link_path() -> None:
    with pytest.raises(ValueError, match="at most 1 item"):
        RelationshipTraversalDefinition(
            selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="BusinessService"),
            link_types=("workload_runs_on", "implemented_by"),
            as_of=datetime(2026, 8, 1, tzinfo=UTC),
            purpose="operations-review",
        )
