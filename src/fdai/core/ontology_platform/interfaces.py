"""Deterministic semantic-interface compilation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from fdai.shared.contracts.models import (
    CEILING_ROLE_RANK,
    OntologyDeclarationKind,
    OntologyDeclarationRef,
    OntologyObjectType,
    OntologyRelease,
    PropertyDecl,
)
from fdai.shared.ontology.release import build_ontology_release

from .models import InterfaceImplementation, OntologyInterfaceType


@dataclass(frozen=True, slots=True)
class CompiledInterfaceCatalog:
    interfaces: Mapping[str, OntologyInterfaceType]
    concrete_types: Mapping[str, tuple[str, ...]]
    release_digest: str | None = None
    declaration_refs: Mapping[tuple[OntologyDeclarationKind, str], OntologyDeclarationRef] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def resolve(self, interface_name: str) -> tuple[str, ...]:
        try:
            return self.concrete_types[interface_name]
        except KeyError as exc:
            raise KeyError(f"unknown ontology interface {interface_name!r}") from exc


def compile_interfaces(
    *,
    interfaces: tuple[OntologyInterfaceType, ...],
    implementations: tuple[InterfaceImplementation, ...],
    object_types: tuple[OntologyObjectType, ...],
    release: OntologyRelease | None = None,
) -> CompiledInterfaceCatalog:
    """Validate inheritance, release identity, and concrete implementations."""

    by_name = _unique_interfaces(interfaces)
    objects = {item.name: item for item in object_types}
    release_digest, declaration_refs = _release_identity(
        release=release,
        interfaces=interfaces,
        object_types=object_types,
    )
    expanded = {name: _expand(name, by_name, ()) for name in by_name}
    concrete: dict[str, set[str]] = {name: set() for name in by_name}
    for implementation in implementations:
        try:
            object_type = objects[implementation.object_type]
        except KeyError as exc:
            raise ValueError(
                f"interface implementation names unknown ObjectType {implementation.object_type!r}"
            ) from exc
        for interface_name in implementation.interfaces:
            requirements = expanded.get(interface_name)
            if requirements is None:
                raise ValueError(f"unknown ontology interface {interface_name!r}")
            missing = set(requirements.properties) - set(object_type.properties)
            if missing:
                missing_text = ", ".join(sorted(missing))
                raise ValueError(
                    f"{object_type.name} is missing interface properties: {missing_text}"
                )
            for property_name, requirement in requirements.properties.items():
                _validate_property_implementation(
                    object_type=object_type,
                    property_name=property_name,
                    requirement=requirement,
                )
            for inherited_name in _interface_closure(interface_name, by_name):
                concrete[inherited_name].add(object_type.name)
    frozen_interfaces = {
        name: interface.model_copy(
            update={"properties": MappingProxyType(dict(interface.properties))}
        )
        for name, interface in expanded.items()
    }
    return CompiledInterfaceCatalog(
        interfaces=MappingProxyType(frozen_interfaces),
        concrete_types=MappingProxyType(
            {name: tuple(sorted(values)) for name, values in concrete.items()}
        ),
        release_digest=release_digest,
        declaration_refs=declaration_refs,
    )


def _release_identity(
    *,
    release: OntologyRelease | None,
    interfaces: tuple[OntologyInterfaceType, ...],
    object_types: tuple[OntologyObjectType, ...],
) -> tuple[
    str | None,
    Mapping[tuple[OntologyDeclarationKind, str], OntologyDeclarationRef],
]:
    if release is None:
        return None, MappingProxyType({})
    supplied = build_ontology_release(
        object_types=object_types,
        interface_types=interfaces,
    ).declarations
    included_kinds = {
        OntologyDeclarationKind.OBJECT,
        OntologyDeclarationKind.INTERFACE,
    }
    expected = {
        (declaration.kind, declaration.name): declaration
        for declaration in release.declarations
        if declaration.kind in included_kinds
    }
    actual = {(declaration.kind, declaration.name): declaration for declaration in supplied}
    if expected != actual:
        raise ValueError(
            "compiled interface declarations do not exactly match the ontology release"
        )
    return release.digest, MappingProxyType(actual)


def _validate_property_implementation(
    *,
    object_type: OntologyObjectType,
    property_name: str,
    requirement: PropertyDecl,
) -> None:
    implementation = object_type.properties[property_name]
    reason: str | None = None
    if implementation.type is not requirement.type:
        reason = "type"
    elif requirement.required and not implementation.required:
        reason = "requiredness"
    elif (
        CEILING_ROLE_RANK[implementation.access_scope] < CEILING_ROLE_RANK[requirement.access_scope]
    ):
        reason = "access scope"
    else:
        required_purposes = frozenset(requirement.purpose_binding)
        implementation_purposes = frozenset(implementation.purpose_binding)
        if required_purposes and (
            not implementation_purposes or not implementation_purposes <= required_purposes
        ):
            reason = "purpose binding"
    if reason is not None:
        raise ValueError(
            f"{object_type.name} has incompatible interface property "
            f"{property_name!r}: {reason} weakens the interface contract"
        )


def _unique_interfaces(
    interfaces: tuple[OntologyInterfaceType, ...],
) -> dict[str, OntologyInterfaceType]:
    result: dict[str, OntologyInterfaceType] = {}
    for interface in interfaces:
        if interface.name in result:
            raise ValueError(f"duplicate ontology interface {interface.name!r}")
        result[interface.name] = interface
    return result


def _expand(
    name: str,
    interfaces: dict[str, OntologyInterfaceType],
    stack: tuple[str, ...],
) -> OntologyInterfaceType:
    if name in stack:
        raise ValueError(f"ontology interface inheritance cycle: {' -> '.join((*stack, name))}")
    try:
        current = interfaces[name]
    except KeyError as exc:
        raise ValueError(f"unknown inherited ontology interface {name!r}") from exc
    properties: dict[str, PropertyDecl] = {}
    links: set[str] = set()
    actions: set[str] = set()
    for parent_name in current.extends:
        parent = _expand(parent_name, interfaces, (*stack, name))
        conflicts = {
            property_name
            for property_name in set(properties) & set(parent.properties)
            if properties[property_name] != parent.properties[property_name]
        }
        if conflicts:
            raise ValueError(
                f"ontology interface {name!r} inherits conflicting properties: "
                + ", ".join(sorted(conflicts))
            )
        properties.update(parent.properties)
        links.update(parent.required_links)
        actions.update(parent.supported_actions)
    conflicts = {
        property_name
        for property_name in set(properties) & set(current.properties)
        if properties[property_name] != current.properties[property_name]
    }
    if conflicts:
        raise ValueError(
            f"ontology interface {name!r} overrides inherited properties: "
            + ", ".join(sorted(conflicts))
        )
    properties.update(current.properties)
    links.update(current.required_links)
    actions.update(current.supported_actions)
    return current.model_copy(
        update={
            "properties": properties,
            "required_links": tuple(sorted(links)),
            "supported_actions": tuple(sorted(actions)),
        }
    )


def _interface_closure(
    name: str,
    interfaces: dict[str, OntologyInterfaceType],
) -> set[str]:
    result = {name}
    for parent in interfaces[name].extends:
        result.update(_interface_closure(parent, interfaces))
    return result


__all__ = ["CompiledInterfaceCatalog", "compile_interfaces"]
