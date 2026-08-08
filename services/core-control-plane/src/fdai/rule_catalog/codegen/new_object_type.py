"""Pure-function codegen for a new ontology :class:`OntologyObjectType` YAML.

Ships the deterministic YAML rendering + validation. The CLI wrapper
lives in :mod:`fdai.rule_catalog.codegen.new_object_type_cli`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import yaml

from fdai.rule_catalog.schema.object_type import load_object_type_from_mapping
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry

_PASCAL_CASE = re.compile(r"^[A-Z][A-Za-z0-9]{0,63}\Z")
_LOWER_SNAKE_KEBAB = re.compile(r"^[a-z][a-z0-9_-]{0,63}\Z")

_ALLOWED_TYPES: frozenset[str] = frozenset(
    {"string", "integer", "number", "boolean", "object", "array", "datetime"}
)

_ALLOWED_SCOPES: frozenset[str] = frozenset({"reader", "contributor", "approver", "owner"})


@dataclass(frozen=True, slots=True)
class PropertySpec:
    """Declarative shape for one property in the generated ObjectType."""

    name: str
    type: str
    required: bool = False
    description: str | None = None
    access_scope: str = "reader"
    purpose_binding: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ObjectTypeSpec:
    """Declarative input to the codegen renderer."""

    name: str
    key: str
    properties: tuple[PropertySpec, ...]
    description: str | None = None
    version: str = "1.0.0"
    schema_version: str = "1.0.0"
    header_comment: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not _PASCAL_CASE.match(self.name):
            raise ValueError(
                f"ObjectType name {self.name!r} MUST be PascalCase matching {_PASCAL_CASE.pattern}"
            )
        if not self.properties:
            raise ValueError("ObjectType MUST declare at least one property")
        prop_names = {p.name for p in self.properties}
        if self.key not in prop_names:
            raise ValueError(
                f"'key' {self.key!r} MUST name a declared property; "
                f"got properties {sorted(prop_names)!r}"
            )
        for prop in self.properties:
            _validate_property(prop)


def _validate_property(prop: PropertySpec) -> None:
    if not _LOWER_SNAKE_KEBAB.match(prop.name):
        raise ValueError(f"property name {prop.name!r} MUST match {_LOWER_SNAKE_KEBAB.pattern}")
    if prop.type not in _ALLOWED_TYPES:
        raise ValueError(
            f"property {prop.name!r} type {prop.type!r} not in {sorted(_ALLOWED_TYPES)!r}"
        )
    if prop.access_scope not in _ALLOWED_SCOPES:
        raise ValueError(
            f"property {prop.name!r} access_scope {prop.access_scope!r} "
            f"not in {sorted(_ALLOWED_SCOPES)!r}"
        )
    for purpose in prop.purpose_binding:
        if not _LOWER_SNAKE_KEBAB.match(purpose):
            raise ValueError(
                f"property {prop.name!r} purpose {purpose!r} MUST match "
                f"{_LOWER_SNAKE_KEBAB.pattern}"
            )


def render_object_type_yaml(spec: ObjectTypeSpec) -> str:
    """Return the fully-rendered YAML text for ``spec``.

    Validates the rendered document through
    :func:`~fdai.rule_catalog.schema.object_type.load_object_type_from_mapping`
    before returning, so a bug in the renderer surfaces as an
    exception instead of a corrupt file.
    """
    doc: dict[str, Any] = {
        "schema_version": spec.schema_version,
        "name": spec.name,
        "version": spec.version,
        "key": spec.key,
    }
    if spec.description:
        doc["description"] = spec.description
    properties: dict[str, dict[str, Any]] = {}
    for prop in spec.properties:
        entry: dict[str, Any] = {"type": prop.type}
        if prop.required:
            entry["required"] = True
        if prop.description:
            entry["description"] = prop.description
        if prop.access_scope != "reader":
            entry["access_scope"] = prop.access_scope
        if prop.purpose_binding:
            entry["purpose_binding"] = list(prop.purpose_binding)
        properties[prop.name] = entry
    doc["properties"] = properties

    # Round-trip through the loader to catch any renderer regression.
    load_object_type_from_mapping(doc, schema_registry=PackageResourceSchemaRegistry())

    header = _render_header(spec)
    body = yaml.safe_dump(doc, sort_keys=False, default_flow_style=False)
    return f"{header}{body}"


def _render_header(spec: ObjectTypeSpec) -> str:
    if not spec.header_comment:
        return ""
    return "\n".join(f"# {line}" for line in spec.header_comment) + "\n"


__all__ = [
    "ObjectTypeSpec",
    "PropertySpec",
    "render_object_type_yaml",
]
