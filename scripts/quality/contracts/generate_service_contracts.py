#!/usr/bin/env python3
"""Generate deterministic Python and TypeScript views of service JSON Schemas."""

from __future__ import annotations

import argparse
import hashlib
import json
import keyword
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
POLICY_PATH = REPO_ROOT / "packages" / "service-contracts" / "contract-generation.json"
GENERATOR_VERSION = "1.1.0"
_IDENTIFIER_PARTS = re.compile(r"[^A-Za-z0-9]+")


class GenerationError(ValueError):
    """Report an invalid generation policy or unsupported schema shape."""


def _json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GenerationError(f"cannot load JSON object: {path}") from exc
    if not isinstance(value, dict):
        raise GenerationError(f"JSON root must be an object: {path}")
    return value


def _sha256(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _pascal(value: str) -> str:
    parts = [part for part in _IDENTIFIER_PARTS.split(value) if part]
    if not parts:
        raise GenerationError(f"cannot derive a type name from {value!r}")
    rendered = "".join(part[:1].upper() + part[1:] for part in parts)
    return f"V{rendered}" if rendered[0].isdigit() else rendered


def _version_suffix(version: str) -> str:
    if re.fullmatch(r"\d+\.\d+\.\d+", version) is None:
        raise GenerationError(f"schema version is not semantic: {version!r}")
    return "V" + version.replace(".", "_")


def _python_literal(value: object) -> str:
    if value is None:
        return "None"
    if value is True:
        return "True"
    if value is False:
        return "False"
    return repr(value)


def _typescript_literal(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


def _schema_pointer(root: Mapping[str, Any], reference: str) -> Mapping[str, Any]:
    if not reference.startswith("#/"):
        raise GenerationError(f"only local schema references are supported: {reference}")
    current: object = root
    for encoded in reference[2:].split("/"):
        part = encoded.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, Mapping) or part not in current:
            raise GenerationError(f"schema reference does not resolve: {reference}")
        current = current[part]
    if not isinstance(current, Mapping):
        raise GenerationError(f"schema reference must resolve to an object: {reference}")
    return current


class _SchemaRenderer:
    def __init__(self, schema: Mapping[str, Any], root_name: str) -> None:
        self.schema = schema
        self.root_name = root_name
        self.python_definitions: dict[str, str] = {}
        self.typescript_definitions: dict[str, str] = {}
        self._python_active: set[str] = set()
        self._typescript_active: set[str] = set()

    def python_type(self, node: Mapping[str, Any], name: str) -> str:
        reference = node.get("$ref")
        if isinstance(reference, str):
            target_name = f"{self.root_name}{_pascal(reference.rsplit('/', 1)[-1])}"
            return self.python_type(_schema_pointer(self.schema, reference), target_name)
        if "const" in node:
            return f"Literal[{_python_literal(node['const'])}]"
        enum = node.get("enum")
        if isinstance(enum, list) and enum:
            return f"Literal[{', '.join(_python_literal(value) for value in enum)}]"
        union = node.get("anyOf") or node.get("oneOf")
        if isinstance(union, list) and union:
            return self._python_union(union, name)
        raw_type = node.get("type")
        if isinstance(raw_type, list):
            return self._python_union(
                [{**node, "type": member} for member in raw_type],
                name,
            )
        if raw_type == "string":
            return "str"
        if raw_type == "integer":
            return "int"
        if raw_type == "number":
            return "float"
        if raw_type == "boolean":
            return "bool"
        if raw_type == "null":
            return "None"
        if raw_type == "array":
            items = node.get("items")
            item_type = (
                self.python_type(items, f"{name}Item") if isinstance(items, Mapping) else "object"
            )
            return f"tuple[{item_type}, ...]"
        if raw_type == "object" or isinstance(node.get("properties"), Mapping):
            properties = node.get("properties")
            if isinstance(properties, Mapping) and properties:
                self._python_typed_dict(name, properties, node.get("required"))
                return name
            additional = node.get("additionalProperties")
            value_type = (
                self.python_type(additional, f"{name}Value")
                if isinstance(additional, Mapping)
                else "object"
            )
            return f"dict[str, {value_type}]"
        return "object"

    def _python_union(self, options: Sequence[object], name: str) -> str:
        rendered = []
        for index, option in enumerate(options):
            if not isinstance(option, Mapping):
                raise GenerationError(f"schema union entry must be an object: {name}")
            candidate = self.python_type(option, f"{name}Option{index + 1}")
            if candidate not in rendered:
                rendered.append(candidate)
        return " | ".join(rendered)

    def _python_typed_dict(
        self,
        name: str,
        properties: Mapping[str, object],
        required_value: object,
    ) -> None:
        if name in self.python_definitions or name in self._python_active:
            return
        self._python_active.add(name)
        required = set(required_value) if isinstance(required_value, list) else set()
        fields: list[str] = []
        for field_name, field_schema in properties.items():
            if (
                not isinstance(field_name, str)
                or not field_name.isidentifier()
                or keyword.iskeyword(field_name)
            ):
                raise GenerationError(f"Python field is not an identifier: {field_name!r}")
            if not isinstance(field_schema, Mapping):
                raise GenerationError(f"schema property must be an object: {field_name}")
            annotation = self.python_type(field_schema, f"{name}{_pascal(field_name)}")
            if field_name not in required:
                annotation = f"NotRequired[{annotation}]"
            fields.append(f"    {field_name}: {annotation}")
        self.python_definitions[name] = "\n".join([f"class {name}(TypedDict):", *fields])
        self._python_active.remove(name)

    def typescript_type(self, node: Mapping[str, Any], name: str) -> str:
        reference = node.get("$ref")
        if isinstance(reference, str):
            target_name = f"{self.root_name}{_pascal(reference.rsplit('/', 1)[-1])}"
            return self.typescript_type(_schema_pointer(self.schema, reference), target_name)
        if "const" in node:
            return _typescript_literal(node["const"])
        enum = node.get("enum")
        if isinstance(enum, list) and enum:
            return " | ".join(_typescript_literal(value) for value in enum)
        union = node.get("anyOf") or node.get("oneOf")
        if isinstance(union, list) and union:
            return self._typescript_union(union, name)
        raw_type = node.get("type")
        if isinstance(raw_type, list):
            return self._typescript_union(
                [{**node, "type": member} for member in raw_type],
                name,
            )
        if raw_type == "string":
            return "string"
        if raw_type in {"integer", "number"}:
            return "number"
        if raw_type == "boolean":
            return "boolean"
        if raw_type == "null":
            return "null"
        if raw_type == "array":
            items = node.get("items")
            item_type = (
                self.typescript_type(items, f"{name}Item")
                if isinstance(items, Mapping)
                else "unknown"
            )
            return f"ReadonlyArray<{item_type}>"
        if raw_type == "object" or isinstance(node.get("properties"), Mapping):
            properties = node.get("properties")
            if isinstance(properties, Mapping) and properties:
                self._typescript_interface(name, properties, node.get("required"))
                return name
            additional = node.get("additionalProperties")
            value_type = (
                self.typescript_type(additional, f"{name}Value")
                if isinstance(additional, Mapping)
                else "unknown"
            )
            return f"Readonly<Record<string, {value_type}>>"
        return "unknown"

    def _typescript_union(self, options: Sequence[object], name: str) -> str:
        rendered = []
        for index, option in enumerate(options):
            if not isinstance(option, Mapping):
                raise GenerationError(f"schema union entry must be an object: {name}")
            candidate = self.typescript_type(option, f"{name}Option{index + 1}")
            if candidate not in rendered:
                rendered.append(candidate)
        return " | ".join(rendered)

    def _typescript_interface(
        self,
        name: str,
        properties: Mapping[str, object],
        required_value: object,
    ) -> None:
        if name in self.typescript_definitions or name in self._typescript_active:
            return
        self._typescript_active.add(name)
        required = set(required_value) if isinstance(required_value, list) else set()
        fields: list[str] = []
        for field_name, field_schema in properties.items():
            if not isinstance(field_name, str) or not isinstance(field_schema, Mapping):
                raise GenerationError(f"invalid TypeScript schema property: {field_name!r}")
            key = (
                field_name
                if re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", field_name)
                else repr(field_name)
            )
            optional = "" if field_name in required else "?"
            annotation = self.typescript_type(
                field_schema,
                f"{name}{_pascal(field_name)}",
            )
            fields.append(f"  readonly {key}{optional}: {annotation};")
        self.typescript_definitions[name] = "\n".join([f"export interface {name} {{", *fields, "}"])
        self._typescript_active.remove(name)


def _schema_entries(
    policy: Mapping[str, Any],
    repo_root: Path,
) -> tuple[tuple[str, str, Path, Mapping[str, Any]], ...]:
    source = policy.get("source")
    if not isinstance(source, Mapping) or not isinstance(source.get("manifest"), str):
        raise GenerationError("generation policy source.manifest is required")
    manifest_path = repo_root / source["manifest"]
    manifest = _json_object(manifest_path)
    contracts = manifest.get("contracts")
    if not isinstance(contracts, list):
        raise GenerationError("compatibility manifest contracts must be an array")
    entries: dict[tuple[str, str], tuple[str, str, Path, Mapping[str, Any]]] = {}
    for contract in contracts:
        if not isinstance(contract, Mapping) or not isinstance(contract.get("id"), str):
            raise GenerationError("compatibility manifest contract id is invalid")
        schemas = contract.get("producer_schemas")
        if not isinstance(schemas, Mapping):
            raise GenerationError(f"{contract['id']} producer_schemas must be an object")
        for schema_ref in schemas.values():
            if (
                not isinstance(schema_ref, Mapping)
                or not isinstance(schema_ref.get("version"), str)
                or not isinstance(schema_ref.get("path"), str)
            ):
                raise GenerationError(f"{contract['id']} schema reference is invalid")
            key = (contract["id"], schema_ref["version"])
            path = manifest_path.parent / schema_ref["path"]
            entry = (contract["id"], schema_ref["version"], path, _json_object(path))
            prior = entries.setdefault(key, entry)
            if prior[2] != path:
                raise GenerationError(f"{contract['id']} {schema_ref['version']} is ambiguous")
        accepted = contract.get("consumer_accepts")
        if not isinstance(accepted, Mapping):
            raise GenerationError(f"{contract['id']} consumer_accepts must be an object")
        for versions in accepted.values():
            if not isinstance(versions, list):
                raise GenerationError(f"{contract['id']} consumer versions must be an array")
            for version in versions:
                if not isinstance(version, str):
                    raise GenerationError(f"{contract['id']} consumer version is invalid")
                _version_suffix(version)
                key = (contract["id"], version)
                if key in entries:
                    continue
                path = manifest_path.parent / "schemas" / contract["id"] / f"{version}.json"
                entries[key] = (contract["id"], version, path, _json_object(path))
    return tuple(entries[key] for key in sorted(entries))


def render_artifacts(policy: Mapping[str, Any], repo_root: Path) -> dict[str, str]:
    """Render every policy-owned artifact without writing the worktree."""
    entries = _schema_entries(policy, repo_root)
    python_definitions: list[str] = []
    typescript_definitions: list[str] = []
    exported: list[str] = []
    source_lines: list[str] = []
    for contract_id, version, path, schema in entries:
        root_name = f"{_pascal(contract_id)}{_version_suffix(version)}"
        renderer = _SchemaRenderer(schema, root_name)
        python_root = renderer.python_type(schema, root_name)
        typescript_root = renderer.typescript_type(schema, root_name)
        if python_root != root_name or typescript_root != root_name:
            raise GenerationError(f"top-level schema must generate an object: {path}")
        python_definitions.extend(renderer.python_definitions.values())
        typescript_definitions.extend(renderer.typescript_definitions.values())
        exported.append(root_name)
        source_lines.append(path.relative_to(repo_root).as_posix())

    header = (
        "Generated by scripts/quality/contracts/generate_service_contracts.py "
        f"version {GENERATOR_VERSION}. Do not edit."
    )
    python_output = "\n".join(
        [
            f'"""{header}"""',
            "",
            "# fmt: off",
            "from __future__ import annotations",
            "",
            "from typing import Literal, NotRequired, TypedDict",
            "",
            "",
            "\n\n\n".join(python_definitions),
            "",
            "__all__ = (",
            *(f'    "{name}",' for name in exported),
            ")",
            "# fmt: on",
            "",
        ]
    )
    python_init = "\n".join(
        [
            f'"""{header}"""',
            "",
            "from fdai_service_contracts.generated.contracts import (",
            *(f"    {name}," for name in exported),
            ")",
            "",
            "__all__ = (",
            *(f'    "{name}",' for name in exported),
            ")",
            "",
        ]
    )
    typescript_output = "\n".join(
        [
            f"// {header}",
            "",
            "\n\n".join(typescript_definitions),
            "",
            "export type FdaiServiceContract =",
            *(
                f"  | {name}{';' if index == len(exported) - 1 else ''}"
                for index, name in enumerate(exported)
            ),
            "",
        ]
    )
    targets = policy.get("targets")
    if not isinstance(targets, list):
        raise GenerationError("generation policy targets must be an array")
    outputs: dict[str, str] = {}
    for target in targets:
        if not isinstance(target, Mapping) or not isinstance(target.get("language"), str):
            raise GenerationError("generation target is invalid")
        language = target["language"]
        if language == "python":
            output = target.get("output")
            package_init = target.get("package_init")
            if not isinstance(output, str) or not isinstance(package_init, str):
                raise GenerationError("Python target output and package_init are required")
            outputs[output] = python_output
            outputs[package_init] = python_init
        elif language == "typescript":
            output = target.get("output")
            if not isinstance(output, str):
                raise GenerationError("TypeScript target output is required")
            outputs[output] = typescript_output
        else:
            raise GenerationError(f"unsupported generation target: {language}")
    if len(outputs) != 3:
        raise GenerationError("generation policy must declare Python, package init, and TypeScript")
    return outputs


def validate_policy(policy: Mapping[str, Any], repo_root: Path) -> None:
    """Validate the pinned generator identity and target ownership."""
    if policy.get("schema_version") != "1.0.0":
        raise GenerationError("generation policy schema_version must be 1.0.0")
    generator = policy.get("generator")
    if not isinstance(generator, Mapping):
        raise GenerationError("generation policy generator is required")
    if generator.get("version") != GENERATOR_VERSION:
        raise GenerationError("generation policy generator version is stale")
    implementation = generator.get("implementation")
    if not isinstance(implementation, str):
        raise GenerationError("generation policy generator implementation is required")
    expected_digest = generator.get("sha256")
    if expected_digest != _sha256(repo_root / implementation):
        raise GenerationError("generation policy generator checksum is stale")
    targets = policy.get("targets")
    if not isinstance(targets, list) or {target.get("language") for target in targets} != {
        "python",
        "typescript",
    }:
        raise GenerationError("generation policy must declare Python and TypeScript targets")
    consumers = {
        str(consumer)
        for target in targets
        if isinstance(target, Mapping) and isinstance(target.get("consumers"), list)
        for consumer in target["consumers"]
    }
    if consumers != {
        "console",
        "core-control-plane",
        "document-ingestion-api",
        "document-processing-worker",
        "isolated-executor",
        "operator-service",
    }:
        raise GenerationError("generation policy must assign all five services and Console")


def check_artifacts(rendered: Mapping[str, str], repo_root: Path) -> list[str]:
    """Return deterministic drift errors for generated artifacts."""
    errors: list[str] = []
    for relative, expected in sorted(rendered.items()):
        path = repo_root / relative
        try:
            actual = path.read_text(encoding="utf-8")
        except OSError:
            errors.append(f"generated artifact is missing: {relative}")
            continue
        if actual != expected:
            errors.append(f"generated artifact is stale or hand-edited: {relative}")
    return errors


def write_artifacts(rendered: Mapping[str, str], repo_root: Path) -> None:
    """Write generated artifacts after policy validation succeeds."""
    for relative, content in sorted(rendered.items()):
        path = repo_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="reject generated artifact drift")
    args = parser.parse_args(argv)
    try:
        policy = _json_object(POLICY_PATH)
        validate_policy(policy, REPO_ROOT)
        rendered = render_artifacts(policy, REPO_ROOT)
        if args.check:
            errors = check_artifacts(rendered, REPO_ROOT)
            if errors:
                for error in errors:
                    print(f"service-contract-generation: ERROR: {error}", file=sys.stderr)
                return 1
        else:
            write_artifacts(rendered, REPO_ROOT)
    except GenerationError as exc:
        print(f"service-contract-generation: ERROR: {exc}", file=sys.stderr)
        return 1
    mode = "check" if args.check else "write"
    print(f"service-contract-generation: OK (mode={mode} artifacts={len(rendered)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
