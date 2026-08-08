"""Deterministic proposal-only Python and TypeScript ontology SDK generation."""

from __future__ import annotations

import json
import keyword
import re
from collections.abc import Sequence
from dataclasses import dataclass

from fdai.shared.contracts.models import (
    OntologyActionType,
    OntologyDeclarationKind,
    OntologyInterfaceType,
    OntologyObjectType,
    OntologyRelease,
)

from .interfaces import CompiledInterfaceCatalog
from .kinetics import OntologyFunctionType


@dataclass(frozen=True, slots=True)
class GeneratedOntologySdk:
    release_digest: str
    python: str
    typescript: str
    manifest_json: str


def generate_ontology_sdk(
    *,
    release: OntologyRelease,
    object_types: Sequence[OntologyObjectType],
    action_types: Sequence[OntologyActionType],
    functions: Sequence[OntologyFunctionType],
    interfaces: CompiledInterfaceCatalog,
) -> GeneratedOntologySdk:
    """Generate stable scoped bindings with proposal-only write methods."""

    objects = tuple(sorted(object_types, key=lambda item: item.name))
    actions = tuple(sorted(action_types, key=lambda item: item.name))
    function_types = tuple(sorted(functions, key=lambda item: item.name))
    interface_types = tuple(interfaces.interfaces[name] for name in sorted(interfaces.interfaces))
    interface_manifest = _interface_manifest(
        release=release,
        interfaces=interfaces,
        interface_types=interface_types,
    )
    python_lines = [
        '"""Generated FDAI ontology SDK. Do not edit."""',
        "from typing import Any, NotRequired, Protocol, TypedDict",
        "",
        f'ONTOLOGY_RELEASE = "{release.digest}"',
        "",
    ]
    typescript_lines = [
        "// Generated FDAI ontology SDK. Do not edit.",
        f'export const ontologyRelease = "{release.digest}" as const;',
        "",
    ]
    for interface_type in interface_types:
        python_lines.extend(_python_interface(interface_type))
        typescript_lines.extend(_typescript_interface(interface_type))
    for object_type in objects:
        python_lines.extend(_python_object(object_type))
        typescript_lines.extend(_typescript_object(object_type))
    python_lines.extend(_python_interface_metadata(interfaces, interface_types))
    typescript_lines.extend(_typescript_interface_metadata(interfaces, interface_types))
    python_lines.extend(
        [
            "class OntologyClient(Protocol):",
            "    async def query(self, object_set: dict[str, Any]) -> list[dict[str, Any]]: ...",
            "    async def propose_action(self, action_type: str, "
            "arguments: dict[str, Any]) -> str: ...",
            "",
        ]
    )
    typescript_lines.extend(
        [
            "export interface OntologyClient {",
            "  query(objectSet: Readonly<Record<string, unknown>>): Promise<readonly unknown[]>;",
            "  proposeAction(actionType: string, "
            "args: Readonly<Record<string, unknown>>): Promise<string>;",
            "}",
            "",
        ]
    )
    manifest = {
        "release_digest": release.digest,
        "object_types": [item.name for item in objects],
        "action_types": [item.name for item in actions],
        "functions": [item.name for item in function_types],
        "interfaces": interface_manifest,
        "write_surface": "proposal_only",
    }
    return GeneratedOntologySdk(
        release_digest=release.digest,
        python="\n".join(python_lines),
        typescript="\n".join(typescript_lines),
        manifest_json=json.dumps(manifest, sort_keys=True, separators=(",", ":")),
    )


def _interface_manifest(
    *,
    release: OntologyRelease,
    interfaces: CompiledInterfaceCatalog,
    interface_types: tuple[OntologyInterfaceType, ...],
) -> dict[str, object]:
    manifest: dict[str, object] = {}
    for interface_type in interface_types:
        try:
            type_ref = release.type_ref(OntologyDeclarationKind.INTERFACE, interface_type.name)
        except KeyError as exc:
            raise ValueError(
                f"InterfaceType {interface_type.name!r} is not pinned by the ontology release"
            ) from exc
        if type_ref.version != interface_type.version:
            raise ValueError(
                f"InterfaceType {interface_type.name!r} version does not match ontology release"
            )
        manifest[interface_type.name] = {
            "type_ref": type_ref.model_dump(mode="json"),
            "extends": sorted(interface_type.extends),
            "concrete_types": list(interfaces.resolve(interface_type.name)),
            "supported_actions": sorted(interface_type.supported_actions),
        }
    return manifest


def _python_interface(interface_type: OntologyInterfaceType) -> list[str]:
    lines = [f"class {interface_type.name}(TypedDict):"]
    identifiers: set[str] = set()
    for name, declaration in sorted(interface_type.properties.items()):
        identifier = _identifier(name)
        if identifier in identifiers:
            raise ValueError(f"InterfaceType {interface_type.name!r} has colliding SDK properties")
        identifiers.add(identifier)
        annotation = _python_type(declaration.type.value)
        if not declaration.required:
            annotation = f"NotRequired[{annotation}]"
        lines.append(f"    {identifier}: {annotation}")
    if not interface_type.properties:
        lines.append("    pass")
    return [*lines, ""]


def _typescript_interface(interface_type: OntologyInterfaceType) -> list[str]:
    lines = [f"export interface {interface_type.name} {{"]
    for name, declaration in sorted(interface_type.properties.items()):
        optional = "" if declaration.required else "?"
        property_name = _typescript_property_name(name)
        lines.append(
            f"  readonly {property_name}{optional}: {_typescript_type(declaration.type.value)};"
        )
    return [*lines, "}", ""]


def _python_interface_metadata(
    interfaces: CompiledInterfaceCatalog,
    interface_types: tuple[OntologyInterfaceType, ...],
) -> list[str]:
    lines = ["INTERFACE_OBJECT_TYPES: dict[str, tuple[str, ...]] = {"]
    for interface_type in interface_types:
        concrete_types = _python_string_tuple(interfaces.resolve(interface_type.name))
        lines.append(f'    "{interface_type.name}": {concrete_types},')
    lines.extend(["}", "", "INTERFACE_SUPPORTED_ACTIONS: dict[str, tuple[str, ...]] = {"])
    for interface_type in interface_types:
        supported_actions = _python_string_tuple(tuple(sorted(interface_type.supported_actions)))
        lines.append(f'    "{interface_type.name}": {supported_actions},')
    lines.extend(
        [
            "}",
            "",
            "def resolve_interface(interface_name: str) -> tuple[str, ...]:",
            "    try:",
            "        return INTERFACE_OBJECT_TYPES[interface_name]",
            "    except KeyError as exc:",
            '        raise KeyError(f"unknown ontology interface {interface_name!r}") from exc',
            "",
        ]
    )
    return lines


def _typescript_interface_metadata(
    interfaces: CompiledInterfaceCatalog,
    interface_types: tuple[OntologyInterfaceType, ...],
) -> list[str]:
    names = " | ".join(json.dumps(item.name) for item in interface_types) or "never"
    lines = [f"export type OntologyInterfaceName = {names};", ""]
    lines.append(
        "export const interfaceObjectTypes: "
        "Readonly<Record<OntologyInterfaceName, readonly string[]>> = {"
    )
    for interface_type in interface_types:
        concrete_types = _typescript_string_array(interfaces.resolve(interface_type.name))
        lines.append(f"  {interface_type.name}: {concrete_types},")
    lines.extend(
        [
            "};",
            "",
            "export const interfaceSupportedActions: ",
            "Readonly<Record<OntologyInterfaceName, readonly string[]>> = {",
        ]
    )
    for interface_type in interface_types:
        supported_actions = _typescript_string_array(
            tuple(sorted(interface_type.supported_actions))
        )
        lines.append(f"  {interface_type.name}: {supported_actions},")
    lines.extend(
        [
            "};",
            "",
            "export function resolveInterface(",
            "  interfaceName: OntologyInterfaceName,",
            "): readonly string[] {",
            "  return interfaceObjectTypes[interfaceName];",
            "}",
            "",
        ]
    )
    return lines


def _python_object(object_type: OntologyObjectType) -> list[str]:
    lines = [f"class {object_type.name}(TypedDict, total=False):"]
    identifiers: set[str] = set()
    for name, declaration in sorted(object_type.properties.items()):
        identifier = _identifier(name)
        if identifier in identifiers:
            raise ValueError(f"ObjectType {object_type.name!r} has colliding SDK properties")
        identifiers.add(identifier)
        lines.append(f"    {identifier}: {_python_type(declaration.type.value)}")
    return [*lines, ""]


def _typescript_object(object_type: OntologyObjectType) -> list[str]:
    lines = [f"export interface {object_type.name} {{"]
    for name, declaration in sorted(object_type.properties.items()):
        optional = "" if declaration.required else "?"
        property_name = _typescript_property_name(name)
        lines.append(
            f"  readonly {property_name}{optional}: {_typescript_type(declaration.type.value)};"
        )
    return [*lines, "}", ""]


def _identifier(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_]", "_", value)
    if normalized[:1].isdigit() or keyword.iskeyword(normalized):
        return f"field_{normalized}"
    return normalized


def _typescript_property_name(value: str) -> str:
    if re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", value):
        return value
    return json.dumps(value)


def _python_string_tuple(values: tuple[str, ...]) -> str:
    items = ", ".join(json.dumps(value) for value in values)
    suffix = "," if len(values) == 1 else ""
    return f"({items}{suffix})"


def _typescript_string_array(values: tuple[str, ...]) -> str:
    return f"[{', '.join(json.dumps(value) for value in values)}]"


def _python_type(value: str) -> str:
    return {
        "string": "str",
        "integer": "int",
        "number": "float",
        "boolean": "bool",
        "array": "list[Any]",
        "object": "dict[str, Any]",
        "datetime": "str",
    }[value]


def _typescript_type(value: str) -> str:
    return {
        "string": "string",
        "integer": "number",
        "number": "number",
        "boolean": "boolean",
        "array": "readonly unknown[]",
        "object": "Readonly<Record<string, unknown>>",
        "datetime": "string",
    }[value]


__all__ = ["GeneratedOntologySdk", "generate_ontology_sdk"]
