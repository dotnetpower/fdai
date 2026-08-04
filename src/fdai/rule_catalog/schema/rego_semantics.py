"""Structured semantic facts extracted from authored Rego policies."""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_MAX_POLICY_BYTES = 1_000_000
_MAX_AST_BYTES = 8_000_000


@dataclass(frozen=True, slots=True)
class RegoSemantics:
    package: str
    rule_id: str
    title: str
    description: str
    property_paths: tuple[str, ...]
    content_digest: str


class RegoSemanticsError(ValueError):
    """Raised when a policy cannot produce bounded, typed semantics."""


def load_rego_semantics(
    path: Path,
    *,
    opa_binary: str = "opa",
    timeout_seconds: float = 5.0,
) -> RegoSemantics:
    """Parse one policy through OPA and return its reviewable semantic facts."""

    body = path.read_bytes()
    if not body or len(body) > _MAX_POLICY_BYTES:
        raise RegoSemanticsError("Rego policy size MUST be within 1..1000000 bytes")
    try:
        completed = subprocess.run(  # noqa: S603 - argv only; no shell or policy execution
            [opa_binary, "parse", "--format=json", str(path)],
            check=False,
            capture_output=True,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RegoSemanticsError(f"OPA parse unavailable: {type(exc).__name__}") from exc
    if completed.returncode != 0:
        raise RegoSemanticsError("OPA rejected the authored Rego policy")
    if not completed.stdout or len(completed.stdout) > _MAX_AST_BYTES:
        raise RegoSemanticsError("OPA AST size MUST be within 1..8000000 bytes")
    try:
        ast = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RegoSemanticsError("OPA returned invalid JSON") from exc
    if not isinstance(ast, Mapping):
        raise RegoSemanticsError("OPA AST root MUST be an object")

    package = _package(ast.get("package"))
    annotation = _package_annotation(ast.get("annotations"))
    custom = annotation.get("custom")
    if not isinstance(custom, Mapping):
        raise RegoSemanticsError("Rego package metadata custom block MUST be an object")
    rule_id = _required_text(custom, "rule_id")
    title = _required_text(annotation, "title")
    description = _required_text(annotation, "description")
    properties = tuple(sorted(set(_property_paths(ast))))
    if not properties:
        raise RegoSemanticsError("Rego policy MUST read at least one input.resource.props path")
    return RegoSemantics(
        package=package,
        rule_id=rule_id,
        title=title,
        description=description,
        property_paths=properties,
        content_digest=hashlib.sha256(body).hexdigest(),
    )


def property_ref(resource_type: str, path: str) -> str:
    """Return the canonical ontology Property identity used by Rule.evaluates."""

    if not resource_type or not path:
        raise ValueError("property resource_type and path MUST be non-empty")
    return f"property.{resource_type}.{path}"


def property_path(resource_type: str, reference: str) -> str:
    """Resolve one canonical Property identity back to its Rego path."""

    prefix = f"property.{resource_type}."
    if not reference.startswith(prefix) or len(reference) == len(prefix):
        raise ValueError(f"invalid Property reference for {resource_type!r}: {reference!r}")
    return reference[len(prefix) :]


def _package(raw: object) -> str:
    if not isinstance(raw, Mapping):
        raise RegoSemanticsError("Rego package MUST be present")
    path = raw.get("path")
    if not isinstance(path, Sequence) or isinstance(path, (str, bytes)):
        raise RegoSemanticsError("Rego package path MUST be a sequence")
    parts = tuple(_term_text(item) for item in path)
    if not parts or parts[0] != "data":
        raise RegoSemanticsError("Rego package path MUST start with data")
    return ".".join(parts[1:])


def _package_annotation(raw: object) -> Mapping[str, Any]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise RegoSemanticsError("Rego package metadata MUST be present")
    matches = tuple(
        item for item in raw if isinstance(item, Mapping) and item.get("scope") == "package"
    )
    if len(matches) != 1:
        raise RegoSemanticsError("Rego policy MUST carry exactly one package metadata block")
    return matches[0]


def _property_paths(value: object) -> Iterator[str]:
    if isinstance(value, Mapping):
        if value.get("type") == "ref":
            raw_terms = value.get("value")
            if isinstance(raw_terms, Sequence) and not isinstance(raw_terms, (str, bytes)):
                parts: list[str] = []
                for term in raw_terms:
                    if not isinstance(term, Mapping) or term.get("type") not in {"var", "string"}:
                        break
                    parts.append(str(term.get("value", "")))
                if parts[:3] == ["input", "resource", "props"] and len(parts) > 3:
                    yield ".".join(parts[3:])
        for child in value.values():
            yield from _property_paths(child)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for child in value:
            yield from _property_paths(child)


def _term_text(raw: object) -> str:
    if not isinstance(raw, Mapping) or raw.get("type") not in {"var", "string"}:
        raise RegoSemanticsError("Rego package term MUST be a string or variable")
    value = raw.get("value")
    if not isinstance(value, str) or not value:
        raise RegoSemanticsError("Rego package term MUST be non-empty")
    return value


def _required_text(raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > 4096:
        raise RegoSemanticsError(f"Rego metadata {key} MUST be bounded and non-empty")
    return value.strip()


__all__ = [
    "RegoSemantics",
    "RegoSemanticsError",
    "load_rego_semantics",
    "property_path",
    "property_ref",
]
