"""Fail-closed loaders for semantic interface declarations and bindings."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from fdai.rule_catalog.schema.ontology_provenance import ontology_provenance_error
from fdai.shared.contracts.models import (
    OntologyInterfaceImplementation,
    OntologyInterfaceType,
    OntologyObjectType,
)
from fdai.shared.contracts.registry import SchemaRegistry

_INTERFACE_TYPE_SCHEMA_NAME = "ontology/interface-type"
_INTERFACE_IMPLEMENTATION_SCHEMA_NAME = "ontology/interface-implementation"


@dataclass(frozen=True, slots=True)
class InterfaceTypeIssue:
    key: str
    message: str


class InterfaceTypeCatalogError(ValueError):
    """Aggregate every interface declaration or binding validation failure."""

    def __init__(self, issues: list[InterfaceTypeIssue]) -> None:
        self.issues = issues
        preview = "; ".join(f"{item.key}: {item.message}" for item in issues[:5])
        suffix = f" (+{len(issues) - 5} more)" if len(issues) > 5 else ""
        super().__init__(f"interface-type catalog validation failed: {preview}{suffix}")


def _yaml_load(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as stream:
        return yaml.safe_load(stream)


def _schema_issues(
    raw: Mapping[str, Any],
    *,
    schema_name: str,
    schema_registry: SchemaRegistry,
    origin: str,
) -> list[InterfaceTypeIssue]:
    validator = Draft202012Validator(dict(schema_registry.get(schema_name)))
    return [
        InterfaceTypeIssue(
            key=f"{origin}:" + (".".join(str(part) for part in error.absolute_path) or "<root>"),
            message=error.message,
        )
        for error in sorted(validator.iter_errors(dict(raw)), key=lambda item: list(item.path))
    ]


def _model_issues(exc: ValueError, *, origin: str) -> list[InterfaceTypeIssue]:
    errors = getattr(exc, "errors", None)
    if not callable(errors):
        return [InterfaceTypeIssue(key=f"{origin}:<root>", message=str(exc))]
    return [
        InterfaceTypeIssue(
            key=f"{origin}:" + ".".join(str(part) for part in error.get("loc", ())),
            message=error["msg"],
        )
        for error in errors()
    ]


def load_interface_type_from_mapping(
    raw: Mapping[str, Any],
    *,
    schema_registry: SchemaRegistry,
    origin: str = "<mapping>",
) -> OntologyInterfaceType:
    """Validate and materialize one semantic InterfaceType declaration."""

    issues = _schema_issues(
        raw,
        schema_name=_INTERFACE_TYPE_SCHEMA_NAME,
        schema_registry=schema_registry,
        origin=origin,
    )
    if issues:
        raise InterfaceTypeCatalogError(issues)
    try:
        return OntologyInterfaceType.model_validate(raw)
    except ValueError as exc:
        raise InterfaceTypeCatalogError(_model_issues(exc, origin=origin)) from exc


def load_interface_type_catalog(
    root: Path,
    *,
    schema_registry: SchemaRegistry,
) -> tuple[OntologyInterfaceType, ...]:
    """Load every semantic InterfaceType declaration under ``root``."""

    aggregated: list[InterfaceTypeIssue] = []
    loaded: list[OntologyInterfaceType] = []
    seen_names: dict[str, str] = {}
    for path in _iter_yaml_files(root):
        raw = _load_mapping(path, aggregated)
        if raw is None:
            continue
        try:
            interface = load_interface_type_from_mapping(
                raw,
                schema_registry=schema_registry,
                origin=path.name,
            )
        except InterfaceTypeCatalogError as exc:
            aggregated.extend(exc.issues)
            continue
        prior = seen_names.get(interface.name)
        if prior is not None:
            aggregated.append(
                InterfaceTypeIssue(
                    key=path.name,
                    message=f"duplicate InterfaceType name {interface.name!r} (also in {prior})",
                )
            )
            continue
        seen_names[interface.name] = path.name
        provenance_error = ontology_provenance_error(interface)
        if provenance_error is not None:
            aggregated.append(
                InterfaceTypeIssue(key=f"{path.name}:provenance", message=provenance_error)
            )
            continue
        loaded.append(interface)
    if aggregated:
        raise InterfaceTypeCatalogError(aggregated)
    return tuple(loaded)


def load_interface_implementation_catalog(
    root: Path,
    *,
    schema_registry: SchemaRegistry,
    interfaces: Iterable[OntologyInterfaceType],
    object_types: Iterable[OntologyObjectType],
) -> tuple[OntologyInterfaceImplementation, ...]:
    """Load explicit ObjectType bindings and reject every dangling reference."""

    interface_names = {item.name for item in interfaces}
    object_type_names = {item.name for item in object_types}
    aggregated: list[InterfaceTypeIssue] = []
    loaded: list[OntologyInterfaceImplementation] = []
    seen_bindings: set[tuple[str, str]] = set()
    for path in _iter_yaml_files(root):
        raw = _load_mapping(path, aggregated)
        if raw is None:
            continue
        issues = _schema_issues(
            raw,
            schema_name=_INTERFACE_IMPLEMENTATION_SCHEMA_NAME,
            schema_registry=schema_registry,
            origin=path.name,
        )
        if issues:
            aggregated.extend(issues)
            continue
        interface_name = str(raw["interface"])
        if interface_name not in interface_names:
            aggregated.append(
                InterfaceTypeIssue(
                    key=f"{path.name}:interface",
                    message=f"unknown InterfaceType {interface_name!r}",
                )
            )
            continue
        for object_type_name in raw["object_types"]:
            if object_type_name not in object_type_names:
                aggregated.append(
                    InterfaceTypeIssue(
                        key=f"{path.name}:object_types",
                        message=f"unknown ObjectType {object_type_name!r}",
                    )
                )
                continue
            binding = (str(object_type_name), interface_name)
            if binding in seen_bindings:
                aggregated.append(
                    InterfaceTypeIssue(
                        key=path.name,
                        message=(
                            f"duplicate interface binding {object_type_name!r} -> "
                            f"{interface_name!r}"
                        ),
                    )
                )
                continue
            seen_bindings.add(binding)
            loaded.append(
                OntologyInterfaceImplementation(
                    object_type=str(object_type_name),
                    interfaces=(interface_name,),
                )
            )
    if aggregated:
        raise InterfaceTypeCatalogError(aggregated)
    return tuple(loaded)


def _load_mapping(
    path: Path,
    aggregated: list[InterfaceTypeIssue],
) -> Mapping[str, Any] | None:
    try:
        raw = _yaml_load(path)
    except yaml.YAMLError as exc:
        aggregated.append(InterfaceTypeIssue(key=path.name, message=f"invalid YAML: {exc}"))
        return None
    if not isinstance(raw, Mapping):
        aggregated.append(InterfaceTypeIssue(key=path.name, message="top-level must be a mapping"))
        return None
    return raw


def _iter_yaml_files(root: Path) -> Iterator[Path]:
    yield from sorted(root.glob("*.yaml"))


__all__ = [
    "InterfaceTypeCatalogError",
    "InterfaceTypeIssue",
    "load_interface_implementation_catalog",
    "load_interface_type_catalog",
    "load_interface_type_from_mapping",
]
