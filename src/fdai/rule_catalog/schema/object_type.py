"""ObjectType catalog loader - reads YAML instances from
``rule-catalog/vocabulary/object-types/`` and validates each against the
``ontology/object-type`` JSON Schema plus the :class:`OntologyObjectType`
pydantic model. Aggregates every issue in a single
:class:`ObjectTypeCatalogError`.

Placement rationale mirrors :mod:`fdai.rule_catalog.schema.action_type`:
this module is pure I/O + validation, so the T0 engine, assurance twin,
and any fork-side extension (see
[downstream-fork-guide.md § 5.8](../../../../docs/roadmap/fork-and-sequencing/downstream-fork-guide.md#58-rule-catalog-additions))
consume the loaded tuple without re-parsing YAML.

Why this exists
---------------
The ontology declares four upstream ObjectTypes today (``Resource``,
``Rule``, ``Signal``, ``Finding``). A fork that adds a non-Resource
business object (e.g. an architecture-review proposal) MUST register
it as a first-class ObjectType so the assurance twin, the operator
console, and any downstream graph traversal can dispatch on it. Before
this loader existed the schema and pydantic model were reachable but
there was no code path that turned a YAML declaration into a runtime
registry - a fork had to hand-roll one. This closes that gap upstream
so every fork consumes the same seam.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from fdai.rule_catalog.schema.ontology_provenance import ontology_provenance_error
from fdai.shared.contracts.models import OntologyObjectType
from fdai.shared.contracts.registry import SchemaRegistry

_OBJECT_TYPE_SCHEMA_NAME = "ontology/object-type"


@dataclass(frozen=True, slots=True)
class ObjectTypeIssue:
    key: str
    message: str


class ObjectTypeCatalogError(ValueError):
    """Aggregate error surfaced when loading an ObjectType YAML fails."""

    def __init__(self, issues: list[ObjectTypeIssue]) -> None:
        self.issues = issues
        preview = "; ".join(f"{i.key}: {i.message}" for i in issues[:5])
        suffix = f" (+{len(issues) - 5} more)" if len(issues) > 5 else ""
        super().__init__(f"object-type catalog validation failed: {preview}{suffix}")


def _yaml_load(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_object_type_from_mapping(
    raw: Mapping[str, Any],
    *,
    schema_registry: SchemaRegistry,
    origin: str = "<mapping>",
) -> OntologyObjectType:
    """Validate a single ObjectType mapping and return the pydantic model.

    Aggregates JSON Schema violations and pydantic errors under one
    :class:`ObjectTypeCatalogError`. Also enforces the ontology invariant
    that ``key`` names a property declared in ``properties`` - the schema
    alone cannot express that cross-reference.
    """
    issues: list[ObjectTypeIssue] = []

    schema = schema_registry.get(_OBJECT_TYPE_SCHEMA_NAME)
    validator = Draft202012Validator(dict(schema))
    for err in sorted(validator.iter_errors(dict(raw)), key=lambda e: list(e.path)):
        path = ".".join(str(p) for p in err.absolute_path) or "<root>"
        issues.append(ObjectTypeIssue(key=f"{origin}:{path}", message=err.message))

    if issues:
        raise ObjectTypeCatalogError(issues)

    try:
        model = OntologyObjectType.model_validate(raw)
    except ValueError as exc:
        errors = getattr(exc, "errors", None)
        if callable(errors):
            for e in errors():
                loc = ".".join(str(p) for p in e.get("loc", ()))
                issues.append(ObjectTypeIssue(key=f"{origin}:{loc}", message=e["msg"]))
        else:
            issues.append(ObjectTypeIssue(key=f"{origin}:<root>", message=str(exc)))
        raise ObjectTypeCatalogError(issues) from exc

    if model.key not in model.properties:
        raise ObjectTypeCatalogError(
            [
                ObjectTypeIssue(
                    key=f"{origin}:key",
                    message=(
                        f"'key' names {model.key!r} which is not a declared property "
                        "of this ObjectType"
                    ),
                )
            ]
        )

    return model


def _iter_yaml_files(root: Path) -> Iterator[Path]:
    yield from sorted(root.glob("*.yaml"))


def load_object_type_catalog(
    root: Path,
    *,
    schema_registry: SchemaRegistry,
) -> tuple[OntologyObjectType, ...]:
    """Load every ObjectType YAML under ``root`` (non-recursive), fail-closed.

    Aggregates every issue in every file into a single
    :class:`ObjectTypeCatalogError`. Duplicate ``name`` across files is a
    hard error - the ontology dispatch layer relies on ``name`` being
    globally unique across upstream and every fork's additions.
    """
    aggregated: list[ObjectTypeIssue] = []
    loaded: list[OntologyObjectType] = []
    seen_names: dict[str, str] = {}

    for path in _iter_yaml_files(root):
        try:
            raw = _yaml_load(path)
        except yaml.YAMLError as exc:
            aggregated.append(ObjectTypeIssue(key=path.name, message=f"invalid YAML: {exc}"))
            continue
        if not isinstance(raw, Mapping):
            aggregated.append(ObjectTypeIssue(key=path.name, message="top-level must be a mapping"))
            continue
        try:
            model = load_object_type_from_mapping(
                raw, schema_registry=schema_registry, origin=path.name
            )
        except ObjectTypeCatalogError as exc:
            aggregated.extend(exc.issues)
            continue

        prior = seen_names.get(model.name)
        if prior is not None:
            aggregated.append(
                ObjectTypeIssue(
                    key=path.name,
                    message=f"duplicate ObjectType name {model.name!r} (also in {prior})",
                )
            )
            continue
        seen_names[model.name] = path.name
        provenance_error = ontology_provenance_error(model)
        if provenance_error is not None:
            aggregated.append(
                ObjectTypeIssue(key=f"{path.name}:provenance", message=provenance_error)
            )
            continue
        loaded.append(model)

    if aggregated:
        raise ObjectTypeCatalogError(aggregated)

    return tuple(loaded)


def object_type_names(catalog: Iterable[OntologyObjectType]) -> set[str]:
    return {o.name for o in catalog}


__all__ = [
    "ObjectTypeCatalogError",
    "ObjectTypeIssue",
    "load_object_type_catalog",
    "load_object_type_from_mapping",
    "object_type_names",
]
