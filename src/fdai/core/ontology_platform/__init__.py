"""Typed operational ontology platform primitives."""

from .interfaces import CompiledInterfaceCatalog, compile_interfaces
from .models import (
    InterfaceImplementation,
    ObjectPredicate,
    ObjectSelector,
    ObjectSelectorKind,
    ObjectSetDefinition,
    ObjectSetMaterialization,
    ObjectTraversal,
    OntologyInterfaceType,
)
from .object_sets import ObjectSetService

__all__ = [
    "CompiledInterfaceCatalog",
    "InterfaceImplementation",
    "ObjectPredicate",
    "ObjectSelector",
    "ObjectSelectorKind",
    "ObjectSetDefinition",
    "ObjectSetMaterialization",
    "ObjectSetService",
    "ObjectTraversal",
    "OntologyInterfaceType",
    "compile_interfaces",
]
