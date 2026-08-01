"""Deterministic semantic-interface compilation."""

from __future__ import annotations

from dataclasses import dataclass

from fdai.shared.contracts.models import OntologyObjectType, PropertyDecl

from .models import InterfaceImplementation, OntologyInterfaceType


@dataclass(frozen=True, slots=True)
class CompiledInterfaceCatalog:
    interfaces: dict[str, OntologyInterfaceType]
    concrete_types: dict[str, tuple[str, ...]]

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
) -> CompiledInterfaceCatalog:
    """Validate inheritance and concrete implementations all-before-return."""

    by_name = _unique_interfaces(interfaces)
    objects = {item.name: item for item in object_types}
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
            for inherited_name in _interface_closure(interface_name, by_name):
                concrete[inherited_name].add(object_type.name)
    return CompiledInterfaceCatalog(
        interfaces=expanded,
        concrete_types={name: tuple(sorted(values)) for name, values in concrete.items()},
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
