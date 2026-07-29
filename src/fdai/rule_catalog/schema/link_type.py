"""LinkType catalog loader - reads YAML instances from
``rule-catalog/vocabulary/link-types/`` and validates each against the
``ontology/link-type`` JSON Schema plus the :class:`OntologyLinkType`
pydantic model. Cross-checks ``from_type`` / ``to_type`` against a supplied
ObjectType registry (``load_object_type_catalog(...)``) so a typo in a
link declaration fails at load, not at first traversal.

Rationale mirrors
:mod:`fdai.rule_catalog.schema.object_type`: the schema + model existed
upstream but no code path turned a YAML declaration into a runtime
registry. This module closes the gap so a fork extending the ontology
uses the same seam upstream itself uses.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from fdai.rule_catalog.schema.ontology_provenance import ontology_provenance_error
from fdai.shared.contracts.models import (
    OntologyLinkType,
    OntologyObjectType,
    PropertyType,
)
from fdai.shared.contracts.registry import SchemaRegistry

_LINK_TYPE_SCHEMA_NAME = "ontology/link-type"


@dataclass(frozen=True, slots=True)
class LinkTypeIssue:
    key: str
    message: str


class LinkTypeCatalogError(ValueError):
    """Aggregate error surfaced when loading a LinkType YAML fails."""

    def __init__(self, issues: list[LinkTypeIssue]) -> None:
        self.issues = issues
        preview = "; ".join(f"{i.key}: {i.message}" for i in issues[:5])
        suffix = f" (+{len(issues) - 5} more)" if len(issues) > 5 else ""
        super().__init__(f"link-type catalog validation failed: {preview}{suffix}")


def _yaml_load(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _cross_reference_issues(
    link: OntologyLinkType,
    *,
    origin: str,
    object_type_names: set[str],
    object_types_by_name: Mapping[str, OntologyObjectType] | None = None,
) -> list[LinkTypeIssue]:
    issues: list[LinkTypeIssue] = []
    if link.from_type not in object_type_names:
        issues.append(
            LinkTypeIssue(
                key=f"{origin}:from_type",
                message=(
                    f"unknown from_type {link.from_type!r} "
                    "(not in rule-catalog/vocabulary/object-types/)"
                ),
            )
        )
    if link.to_type not in object_type_names:
        issues.append(
            LinkTypeIssue(
                key=f"{origin}:to_type",
                message=(
                    f"unknown to_type {link.to_type!r} "
                    "(not in rule-catalog/vocabulary/object-types/)"
                ),
            )
        )
    elif link.temporal_order and object_types_by_name is not None:
        target = object_types_by_name[link.to_type]
        order_property = link.order_by_property
        declaration = target.properties.get(order_property or "")
        if declaration is None:
            issues.append(
                LinkTypeIssue(
                    key=f"{origin}:order_by_property",
                    message=(
                        f"unknown target property {order_property!r} on ObjectType {target.name!r}"
                    ),
                )
            )
        elif declaration.type not in {
            PropertyType.DATETIME,
            PropertyType.INTEGER,
            PropertyType.NUMBER,
            PropertyType.STRING,
        }:
            issues.append(
                LinkTypeIssue(
                    key=f"{origin}:order_by_property",
                    message=(
                        f"target property {target.name}.{order_property} MUST use an "
                        "ordered scalar type"
                    ),
                )
            )
    return issues


def load_link_type_from_mapping(
    raw: Mapping[str, Any],
    *,
    schema_registry: SchemaRegistry,
    object_type_names: set[str],
    object_types_by_name: Mapping[str, OntologyObjectType] | None = None,
    origin: str = "<mapping>",
) -> OntologyLinkType:
    """Validate a single LinkType mapping and return the pydantic model.

    Aggregates JSON Schema violations, pydantic errors, and ObjectType
    cross-reference misses under one :class:`LinkTypeCatalogError`. The
    cross-reference set MUST be supplied - this function does NOT read
    the ObjectType catalog itself so tests can inject stubs.
    """
    issues: list[LinkTypeIssue] = []

    schema = schema_registry.get(_LINK_TYPE_SCHEMA_NAME)
    validator = Draft202012Validator(dict(schema))
    for err in sorted(validator.iter_errors(dict(raw)), key=lambda e: list(e.path)):
        path = ".".join(str(p) for p in err.absolute_path) or "<root>"
        issues.append(LinkTypeIssue(key=f"{origin}:{path}", message=err.message))

    if issues:
        raise LinkTypeCatalogError(issues)

    try:
        model = OntologyLinkType.model_validate(raw)
    except ValueError as exc:
        errors = getattr(exc, "errors", None)
        if callable(errors):
            for e in errors():
                loc = ".".join(str(p) for p in e.get("loc", ()))
                issues.append(LinkTypeIssue(key=f"{origin}:{loc}", message=e["msg"]))
        else:
            issues.append(LinkTypeIssue(key=f"{origin}:<root>", message=str(exc)))
        raise LinkTypeCatalogError(issues) from exc

    xref_issues = _cross_reference_issues(
        model,
        origin=origin,
        object_type_names=object_type_names,
        object_types_by_name=object_types_by_name,
    )
    if xref_issues:
        raise LinkTypeCatalogError(xref_issues)

    return model


def _iter_yaml_files(root: Path) -> Iterator[Path]:
    yield from sorted(root.glob("*.yaml"))


def load_link_type_catalog(
    root: Path,
    *,
    schema_registry: SchemaRegistry,
    object_types: Iterable[OntologyObjectType],
) -> tuple[OntologyLinkType, ...]:
    """Load every LinkType YAML under ``root`` (non-recursive), fail-closed.

    Duplicate ``name`` across files is a hard error. Every LinkType MUST
    resolve both endpoints against the ObjectType registry supplied by
    the caller (typically the result of
    :func:`load_object_type_catalog`).
    """
    object_types_by_name = {item.name: item for item in object_types}
    object_type_names_set = set(object_types_by_name)

    aggregated: list[LinkTypeIssue] = []
    loaded: list[OntologyLinkType] = []
    seen_names: dict[str, str] = {}

    for path in _iter_yaml_files(root):
        try:
            raw = _yaml_load(path)
        except yaml.YAMLError as exc:
            aggregated.append(LinkTypeIssue(key=path.name, message=f"invalid YAML: {exc}"))
            continue
        if not isinstance(raw, Mapping):
            aggregated.append(LinkTypeIssue(key=path.name, message="top-level must be a mapping"))
            continue
        try:
            model = load_link_type_from_mapping(
                raw,
                schema_registry=schema_registry,
                object_type_names=object_type_names_set,
                object_types_by_name=object_types_by_name,
                origin=path.name,
            )
        except LinkTypeCatalogError as exc:
            aggregated.extend(exc.issues)
            continue

        prior = seen_names.get(model.name)
        if prior is not None:
            aggregated.append(
                LinkTypeIssue(
                    key=path.name,
                    message=f"duplicate LinkType name {model.name!r} (also in {prior})",
                )
            )
            continue
        seen_names[model.name] = path.name
        provenance_error = ontology_provenance_error(model)
        if provenance_error is not None:
            aggregated.append(
                LinkTypeIssue(key=f"{path.name}:provenance", message=provenance_error)
            )
            continue
        loaded.append(model)

    if aggregated:
        raise LinkTypeCatalogError(aggregated)

    return tuple(loaded)


def link_type_names(catalog: Iterable[OntologyLinkType]) -> set[str]:
    return {link.name for link in catalog}


__all__ = [
    "LinkTypeCatalogError",
    "LinkTypeIssue",
    "link_type_names",
    "load_link_type_catalog",
    "load_link_type_from_mapping",
]
