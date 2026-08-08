"""Scoped ontology SDK generation tests."""

from __future__ import annotations

import json

import pytest

from fdai.core.ontology_platform import (
    CompiledInterfaceCatalog,
    InterfaceImplementation,
    OntologyInterfaceType,
    compile_interfaces,
    generate_ontology_sdk,
    platform_manifest,
)
from fdai.shared.contracts.models import OntologyObjectType, PropertyDecl, PropertyType
from fdai.shared.ontology.release import build_ontology_release


def _object_type() -> OntologyObjectType:
    return OntologyObjectType(
        schema_version="1.0.0",
        name="Workload",
        version="1.0.0",
        key="id",
        properties={
            "id": PropertyDecl(type=PropertyType.STRING, required=True),
            "replicas": PropertyDecl(type=PropertyType.INTEGER),
        },
    )


def _interface_types() -> tuple[OntologyInterfaceType, OntologyInterfaceType]:
    ownable = OntologyInterfaceType(
        name="Ownable",
        version="1.0.0",
        properties={
            "owner_ref": PropertyDecl(type=PropertyType.STRING, required=True),
        },
    )
    operable = OntologyInterfaceType(
        name="Operable",
        version="2.0.0",
        extends=("Ownable",),
        properties={
            "status": PropertyDecl(type=PropertyType.STRING, required=True),
        },
        supported_actions=("ops.scale-out", "ops.restart-service"),
    )
    return ownable, operable


def _interface_catalog(*, reverse: bool = False) -> CompiledInterfaceCatalog:
    ownable, operable = _interface_types()
    interface_types = (operable, ownable) if reverse else (ownable, operable)
    return compile_interfaces(
        interfaces=interface_types,
        implementations=(
            InterfaceImplementation(object_type="Workload", interfaces=("Operable",)),
        ),
        object_types=(
            _object_type().model_copy(
                update={
                    "properties": {
                        **_object_type().properties,
                        "owner_ref": PropertyDecl(type=PropertyType.STRING, required=True),
                        "status": PropertyDecl(type=PropertyType.STRING, required=True),
                    }
                }
            ),
        ),
    )


def test_generated_sdks_are_deterministic_and_proposal_only() -> None:
    object_type = _object_type()
    interface = OntologyInterfaceType(name="Operable", version="1.0.0")
    release = build_ontology_release(object_types=(object_type,), interface_types=(interface,))
    interfaces = compile_interfaces(
        interfaces=(interface,),
        implementations=(
            InterfaceImplementation(object_type="Workload", interfaces=("Operable",)),
        ),
        object_types=(object_type,),
    )

    first = generate_ontology_sdk(
        release=release,
        object_types=(object_type,),
        action_types=(),
        functions=(),
        interfaces=interfaces,
    )
    second = generate_ontology_sdk(
        release=release,
        object_types=(object_type,),
        action_types=(),
        functions=(),
        interfaces=interfaces,
    )

    assert first == second
    assert "class Workload(TypedDict" in first.python
    assert "export interface Workload" in first.typescript
    assert "propose_action" in first.python
    assert "proposeAction" in first.typescript
    assert "execute_action" not in first.python
    assert "executeAction" not in first.typescript
    assert json.loads(first.manifest_json)["write_surface"] == "proposal_only"
    compile(first.python, "<generated-ontology-sdk>", "exec")


def test_generated_sdks_emit_deterministic_semantic_interface_bindings() -> None:
    object_type = _object_type().model_copy(
        update={
            "properties": {
                **_object_type().properties,
                "owner_ref": PropertyDecl(type=PropertyType.STRING, required=True),
                "status": PropertyDecl(type=PropertyType.STRING, required=True),
            }
        }
    )
    interface_catalog = _interface_catalog()
    release = build_ontology_release(
        object_types=(object_type,),
        interface_types=_interface_types(),
    )

    first = generate_ontology_sdk(
        release=release,
        object_types=(object_type,),
        action_types=(),
        functions=(),
        interfaces=interface_catalog,
    )
    reordered = generate_ontology_sdk(
        release=release,
        object_types=(object_type,),
        action_types=(),
        functions=(),
        interfaces=_interface_catalog(reverse=True),
    )

    assert first == reordered
    assert "class Operable(TypedDict):" in first.python
    assert "    owner_ref: str" in first.python
    assert "    status: str" in first.python
    assert "INTERFACE_OBJECT_TYPES: dict[str, tuple[str, ...]] = {" in first.python
    assert '    "Operable": ("Workload",),' in first.python
    assert "INTERFACE_SUPPORTED_ACTIONS: dict[str, tuple[str, ...]] = {" in first.python
    assert '    "Operable": ("ops.restart-service", "ops.scale-out"),' in first.python
    assert "export interface Operable" in first.typescript
    assert "  readonly owner_ref: string;" in first.typescript
    assert "  readonly status: string;" in first.typescript
    assert "export const interfaceObjectTypes:" in first.typescript
    assert '  Operable: ["Workload"],' in first.typescript
    assert "export const interfaceSupportedActions:" in first.typescript
    assert '  Operable: ["ops.restart-service", "ops.scale-out"],' in first.typescript
    assert "execute_action" not in first.python
    assert "executeAction" not in first.typescript
    compile(first.python, "<generated-ontology-sdk>", "exec")
    _assert_typescript_structure(first.typescript)


def test_sdk_manifest_maps_interfaces_to_exact_release_metadata() -> None:
    object_type = _object_type().model_copy(
        update={
            "properties": {
                **_object_type().properties,
                "owner_ref": PropertyDecl(type=PropertyType.STRING, required=True),
                "status": PropertyDecl(type=PropertyType.STRING, required=True),
            }
        }
    )
    interface_catalog = _interface_catalog()
    release = build_ontology_release(
        object_types=(object_type,),
        interface_types=_interface_types(),
    )
    generated = generate_ontology_sdk(
        release=release,
        object_types=(object_type,),
        action_types=(),
        functions=(),
        interfaces=interface_catalog,
    )

    manifest = json.loads(generated.manifest_json)

    assert manifest["release_digest"] == release.digest
    assert manifest["interfaces"] == {
        "Operable": {
            "concrete_types": ["Workload"],
            "extends": ["Ownable"],
            "supported_actions": ["ops.restart-service", "ops.scale-out"],
            "type_ref": {
                "catalog_digest": release.digest,
                "kind": "interface",
                "name": "Operable",
                "version": "2.0.0",
            },
        },
        "Ownable": {
            "concrete_types": ["Workload"],
            "extends": [],
            "supported_actions": [],
            "type_ref": {
                "catalog_digest": release.digest,
                "kind": "interface",
                "name": "Ownable",
                "version": "1.0.0",
            },
        },
    }


def test_sdk_rejects_interface_catalog_not_pinned_by_release() -> None:
    object_type = _object_type().model_copy(
        update={
            "properties": {
                **_object_type().properties,
                "owner_ref": PropertyDecl(type=PropertyType.STRING, required=True),
                "status": PropertyDecl(type=PropertyType.STRING, required=True),
            }
        }
    )
    release = build_ontology_release(object_types=(object_type,))

    with pytest.raises(ValueError, match="not pinned by the ontology release"):
        generate_ontology_sdk(
            release=release,
            object_types=(object_type,),
            action_types=(),
            functions=(),
            interfaces=_interface_catalog(),
        )


def _assert_typescript_structure(source: str) -> None:
    assert source.count("{") == source.count("}")
    assert source.count("[") == source.count("]")
    assert source.count("(") == source.count(")")
    assert "export const ontologyRelease" in source
    assert "export interface OntologyClient" in source


def test_platform_manifest_denies_mutation_authority() -> None:
    object_type = _object_type()
    interface = OntologyInterfaceType(name="Operable", version="1.0.0")
    release = build_ontology_release(object_types=(object_type,), interface_types=(interface,))
    interfaces = compile_interfaces(
        interfaces=(interface,),
        implementations=(
            InterfaceImplementation(object_type="Workload", interfaces=("Operable",)),
        ),
        object_types=(object_type,),
    )

    manifest = platform_manifest(
        release=release,
        interfaces=interfaces,
        action_types=(),
        functions=(),
    )

    assert manifest["mutation_authority"] is False
    assert manifest["release_digest"] == release.digest
    assert manifest["interfaces"] == {"Operable": ["Workload"]}
    assert manifest["write_surface"] == "typed_proposal"


def test_generated_sdk_escapes_reserved_and_punctuated_properties() -> None:
    object_type = _object_type().model_copy(
        update={
            "properties": {
                "id": PropertyDecl(type=PropertyType.STRING, required=True),
                "class": PropertyDecl(type=PropertyType.STRING),
                "cost-center": PropertyDecl(type=PropertyType.STRING),
            }
        }
    )
    release = build_ontology_release(object_types=(object_type,))
    interfaces = compile_interfaces(interfaces=(), implementations=(), object_types=(object_type,))

    generated = generate_ontology_sdk(
        release=release,
        object_types=(object_type,),
        action_types=(),
        functions=(),
        interfaces=interfaces,
    )

    compile(generated.python, "<generated-ontology-sdk>", "exec")
    assert "field_class" in generated.python
    assert 'readonly "cost-center"?' in generated.typescript
