"""Deterministic proposal-only Python and TypeScript ontology SDK generation."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass

from fdai.shared.contracts.models import OntologyActionType, OntologyObjectType, OntologyRelease

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
    python_lines = [
        '"""Generated FDAI ontology SDK. Do not edit."""',
        "from typing import Any, Protocol, TypedDict",
        "",
        f'ONTOLOGY_RELEASE = "{release.digest}"',
        "",
    ]
    typescript_lines = [
        "// Generated FDAI ontology SDK. Do not edit.",
        f'export const ontologyRelease = "{release.digest}" as const;',
        "",
    ]
    for object_type in objects:
        python_lines.extend(_python_object(object_type))
        typescript_lines.extend(_typescript_object(object_type))
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
        "interfaces": sorted(interfaces.interfaces),
        "write_surface": "proposal_only",
    }
    return GeneratedOntologySdk(
        release_digest=release.digest,
        python="\n".join(python_lines),
        typescript="\n".join(typescript_lines),
        manifest_json=json.dumps(manifest, sort_keys=True, separators=(",", ":")),
    )


def _python_object(object_type: OntologyObjectType) -> list[str]:
    lines = [f"class {object_type.name}(TypedDict, total=False):"]
    for name, declaration in sorted(object_type.properties.items()):
        lines.append(f"    {_identifier(name)}: {_python_type(declaration.type.value)}")
    return [*lines, ""]


def _typescript_object(object_type: OntologyObjectType) -> list[str]:
    lines = [f"export interface {object_type.name} {{"]
    for name, declaration in sorted(object_type.properties.items()):
        optional = "" if declaration.required else "?"
        lines.append(f"  readonly {name}{optional}: {_typescript_type(declaration.type.value)};")
    return [*lines, "}", ""]


def _identifier(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_]", "_", value)
    return f"field_{normalized}" if normalized[:1].isdigit() else normalized


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
