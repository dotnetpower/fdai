"""Scoped ontology SDK generation tests."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from fdai.core.ontology_platform import (
    CompiledInterfaceCatalog,
    GeneratedOntologySdk,
    InterfaceImplementation,
    OntologyInterfaceType,
    compile_interfaces,
    generate_ontology_sdk,
    platform_manifest,
)
from fdai.shared.contracts.models import (
    OntologyActionType,
    OntologyFunctionKind,
    OntologyFunctionType,
    OntologyObjectType,
    OntologyRelease,
    Operation,
    PromotionGate,
    PropertyDecl,
    PropertyType,
    RollbackKind,
)
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


def _action_type(name: str) -> OntologyActionType:
    return OntologyActionType(
        schema_version="1.0.0",
        name=name,
        version="1.0.0",
        operation=Operation.UPDATE,
        rollback_contract=RollbackKind.STATE_FORWARD_ONLY,
        promotion_gate=PromotionGate(
            min_shadow_days=1,
            min_samples=1,
            min_accuracy=1.0,
            max_policy_escapes=0,
        ),
    )


def _action_types() -> tuple[OntologyActionType, OntologyActionType]:
    return _action_type("ops.restart-service"), _action_type("ops.scale-out")


def _function_type(name: str = "query.workloads") -> OntologyFunctionType:
    return OntologyFunctionType(
        name=name,
        version="1.0.0",
        kind=OntologyFunctionKind.QUERY,
        artifact_digest="sha256:" + "a" * 64,
        publisher="fdai",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
    )


def _interface_object_type() -> OntologyObjectType:
    return _object_type().model_copy(
        update={
            "properties": {
                **_object_type().properties,
                "owner_ref": PropertyDecl(type=PropertyType.STRING, required=True),
                "status": PropertyDecl(type=PropertyType.STRING, required=True),
            }
        }
    )


def _interface_catalog(
    *,
    release: OntologyRelease,
    reverse: bool = False,
) -> CompiledInterfaceCatalog:
    ownable, operable = _interface_types()
    interface_types = (operable, ownable) if reverse else (ownable, operable)
    return compile_interfaces(
        interfaces=interface_types,
        implementations=(
            InterfaceImplementation(object_type="Workload", interfaces=("Operable",)),
        ),
        object_types=(_interface_object_type(),),
        release=release,
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
        release=release,
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
    object_type = _interface_object_type()
    action_types = _action_types()
    release = build_ontology_release(
        object_types=(object_type,),
        interface_types=_interface_types(),
        action_types=action_types,
    )
    interface_catalog = _interface_catalog(release=release)

    first = generate_ontology_sdk(
        release=release,
        object_types=(object_type,),
        action_types=action_types,
        functions=(),
        interfaces=interface_catalog,
    )
    reordered = generate_ontology_sdk(
        release=release,
        object_types=(object_type,),
        action_types=action_types,
        functions=(),
        interfaces=_interface_catalog(release=release, reverse=True),
    )

    assert first == reordered
    assert "class Operable(TypedDict):" in first.python
    assert "    owner_ref: Required[str]" in first.python
    assert "    status: Required[str]" in first.python
    assert 'ActionTypeName = Literal["ops.restart-service", "ops.scale-out"]' in first.python
    assert "action_type: ActionTypeName" in first.python
    assert "INTERFACE_OBJECT_TYPES: dict[str, tuple[str, ...]] = {" in first.python
    assert '    "Operable": ("Workload",),' in first.python
    assert "INTERFACE_SUPPORTED_ACTIONS: dict[str, tuple[str, ...]] = {" in first.python
    assert '    "Operable": ("ops.restart-service", "ops.scale-out"),' in first.python
    assert "export interface Operable" in first.typescript
    assert "  readonly owner_ref: string;" in first.typescript
    assert "  readonly status: string;" in first.typescript
    assert (
        'export type ActionTypeName = "ops.restart-service" | "ops.scale-out";' in first.typescript
    )
    assert "actionType: ActionTypeName" in first.typescript
    assert "export const interfaceObjectTypes:" in first.typescript
    assert '  Operable: ["Workload"],' in first.typescript
    assert "export const interfaceSupportedActions:" in first.typescript
    assert '  Operable: ["ops.restart-service", "ops.scale-out"],' in first.typescript
    assert "execute_action" not in first.python
    assert "executeAction" not in first.typescript
    compile(first.python, "<generated-ontology-sdk>", "exec")
    _assert_typescript_structure(first.typescript)


def test_sdk_manifest_maps_interfaces_to_exact_release_metadata() -> None:
    object_type = _interface_object_type()
    action_types = _action_types()
    release = build_ontology_release(
        object_types=(object_type,),
        interface_types=_interface_types(),
        action_types=action_types,
    )
    interface_catalog = _interface_catalog(release=release)
    generated = generate_ontology_sdk(
        release=release,
        object_types=(object_type,),
        action_types=action_types,
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
    object_type = _interface_object_type()
    action_types = _action_types()
    release = build_ontology_release(
        object_types=(object_type,),
        interface_types=_interface_types(),
        action_types=action_types,
    )
    stale_release = release.model_copy(update={"digest": "sha256:" + "f" * 64})

    with pytest.raises(ValueError, match="not bound to the ontology release"):
        generate_ontology_sdk(
            release=stale_release,
            object_types=(object_type,),
            action_types=action_types,
            functions=(),
            interfaces=_interface_catalog(release=release),
        )


def test_sdk_rejects_stale_object_declaration() -> None:
    object_type = _object_type()
    release = build_ontology_release(object_types=(object_type,))
    stale_object_type = object_type.model_copy(
        update={
            "properties": {
                **object_type.properties,
                "region": PropertyDecl(type=PropertyType.STRING),
            }
        }
    )

    with pytest.raises(ValueError, match="ObjectType 'Workload' declaration does not match"):
        generate_ontology_sdk(
            release=release,
            object_types=(stale_object_type,),
            action_types=(),
            functions=(),
            interfaces=compile_interfaces(
                interfaces=(),
                implementations=(),
                object_types=(object_type,),
                release=release,
            ),
        )


def test_sdk_rejects_missing_release_member() -> None:
    object_type = _object_type()
    omitted_type = OntologyObjectType(
        schema_version="1.0.0",
        name="EmptyType",
        version="1.0.0",
        key="id",
        properties={},
    )
    release = build_ontology_release(object_types=(object_type, omitted_type))
    interfaces = compile_interfaces(
        interfaces=(),
        implementations=(),
        object_types=(object_type, omitted_type),
        release=release,
    )

    with pytest.raises(ValueError, match="missing object:EmptyType"):
        generate_ontology_sdk(
            release=release,
            object_types=(object_type,),
            action_types=(),
            functions=(),
            interfaces=interfaces,
        )


def test_sdk_rejects_stale_action_and_function_declarations() -> None:
    object_type = _object_type()
    action_type = _action_type("ops.restart-service")
    function_type = _function_type()
    release = build_ontology_release(
        object_types=(object_type,),
        action_types=(action_type,),
        function_types=(function_type,),
    )
    interfaces = compile_interfaces(
        interfaces=(),
        implementations=(),
        object_types=(object_type,),
        release=release,
    )

    with pytest.raises(ValueError, match="ActionType 'ops.restart-service' declaration"):
        generate_ontology_sdk(
            release=release,
            object_types=(object_type,),
            action_types=(action_type.model_copy(update={"description": "stale"}),),
            functions=(function_type,),
            interfaces=interfaces,
        )
    with pytest.raises(ValueError, match="FunctionType 'query.workloads' declaration"):
        generate_ontology_sdk(
            release=release,
            object_types=(object_type,),
            action_types=(action_type,),
            functions=(function_type.model_copy(update={"publisher": "stale"}),),
            interfaces=interfaces,
        )


def test_interface_catalog_rejects_stale_interface_declaration() -> None:
    object_type = _object_type()
    interface = OntologyInterfaceType(name="Operable", version="1.0.0")
    release = build_ontology_release(
        object_types=(object_type,),
        interface_types=(interface,),
    )

    with pytest.raises(ValueError, match="do not exactly match"):
        compile_interfaces(
            interfaces=(interface.model_copy(update={"version": "1.0.1"}),),
            implementations=(),
            object_types=(object_type,),
            release=release,
        )


def test_sdk_rejects_interface_action_absent_from_active_release() -> None:
    object_type = _object_type()
    interface = OntologyInterfaceType(
        name="Operable",
        version="1.0.0",
        supported_actions=("ops.restart-service",),
    )
    release = build_ontology_release(
        object_types=(object_type,),
        interface_types=(interface,),
    )
    interfaces = compile_interfaces(
        interfaces=(interface,),
        implementations=(),
        object_types=(object_type,),
        release=release,
    )

    with pytest.raises(ValueError, match="references inactive ActionTypes"):
        generate_ontology_sdk(
            release=release,
            object_types=(object_type,),
            action_types=(),
            functions=(),
            interfaces=interfaces,
        )


def test_sdk_rejects_cross_kind_and_reserved_symbol_collisions() -> None:
    shared_object = OntologyObjectType(
        schema_version="1.0.0",
        name="SharedType",
        version="1.0.0",
        key="id",
        properties={},
    )
    shared_interface = OntologyInterfaceType(name="SharedType", version="1.0.0")
    release = build_ontology_release(
        object_types=(shared_object,),
        interface_types=(shared_interface,),
    )
    interfaces = compile_interfaces(
        interfaces=(shared_interface,),
        implementations=(),
        object_types=(shared_object,),
        release=release,
    )

    with pytest.raises(ValueError, match="collides with ObjectType"):
        generate_ontology_sdk(
            release=release,
            object_types=(shared_object,),
            action_types=(),
            functions=(),
            interfaces=interfaces,
        )

    reserved_object = shared_object.model_copy(update={"name": "OntologyClient"})
    reserved_release = build_ontology_release(object_types=(reserved_object,))
    with pytest.raises(ValueError, match="reserved generated SDK symbol"):
        generate_ontology_sdk(
            release=reserved_release,
            object_types=(reserved_object,),
            action_types=(),
            functions=(),
            interfaces=compile_interfaces(
                interfaces=(),
                implementations=(),
                object_types=(reserved_object,),
                release=reserved_release,
            ),
        )


def test_generated_python_types_preserve_requiredness_and_empty_types() -> None:
    object_type = _object_type()
    empty_type = OntologyObjectType(
        schema_version="1.0.0",
        name="EmptyType",
        version="1.0.0",
        key="id",
        properties={},
    )
    interface = OntologyInterfaceType(
        name="Observable",
        version="1.0.0",
        properties={
            "status": PropertyDecl(type=PropertyType.STRING, required=True),
            "detail": PropertyDecl(type=PropertyType.STRING),
        },
    )
    release = build_ontology_release(
        object_types=(object_type, empty_type),
        interface_types=(interface,),
    )
    generated = generate_ontology_sdk(
        release=release,
        object_types=(object_type, empty_type),
        action_types=(),
        functions=(),
        interfaces=compile_interfaces(
            interfaces=(interface,),
            implementations=(),
            object_types=(object_type, empty_type),
            release=release,
        ),
    )

    assert "    id: Required[str]" in generated.python
    assert "    replicas: NotRequired[int]" in generated.python
    assert "class EmptyType(TypedDict, total=False):\n    pass" in generated.python
    assert "    status: Required[str]" in generated.python
    assert "    detail: NotRequired[str]" in generated.python


def test_generated_python_sdk_imports(tmp_path: Path) -> None:
    generated = _complete_generated_sdk()
    module_path = tmp_path / "generated_ontology_sdk.py"
    module_path.write_text(generated.python, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("generated_ontology_sdk", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)


def test_generated_typescript_sdk_compiles_with_tsc(tmp_path: Path) -> None:
    tsc = shutil.which("tsc")
    if tsc is None:
        pytest.skip("tsc is unavailable")
    generated = _complete_generated_sdk()
    source_path = tmp_path / "generated-ontology-sdk.ts"
    source_path.write_text(generated.typescript, encoding="utf-8")

    result = subprocess.run(  # noqa: S603
        [tsc, "--noEmit", "--strict", "--target", "ES2020", str(source_path)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def _complete_generated_sdk() -> GeneratedOntologySdk:
    object_type = _interface_object_type()
    interface_types = _interface_types()
    action_types = _action_types()
    function_types = (_function_type(),)
    release = build_ontology_release(
        object_types=(object_type,),
        interface_types=interface_types,
        action_types=action_types,
        function_types=function_types,
    )
    return generate_ontology_sdk(
        release=release,
        object_types=(object_type,),
        action_types=action_types,
        functions=function_types,
        interfaces=_interface_catalog(release=release),
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
        release=release,
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
    interfaces = compile_interfaces(
        interfaces=(),
        implementations=(),
        object_types=(object_type,),
        release=release,
    )

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
