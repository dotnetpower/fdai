"""Scoped ontology SDK generation tests."""

from __future__ import annotations

import json

from fdai.core.ontology_platform import (
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


def test_generated_sdks_are_deterministic_and_proposal_only() -> None:
    object_type = _object_type()
    release = build_ontology_release(object_types=(object_type,))
    interface = OntologyInterfaceType(name="Operable", version="1.0.0")
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


def test_platform_manifest_denies_mutation_authority() -> None:
    object_type = _object_type()
    release = build_ontology_release(object_types=(object_type,))
    interface = OntologyInterfaceType(name="Operable", version="1.0.0")
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
