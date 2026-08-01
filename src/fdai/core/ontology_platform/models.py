"""Contracts for semantic interfaces and bounded object sets."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any

from pydantic import Field, model_validator

from fdai.shared.contracts.models import ContractBase, PropertyDecl, SemVer
from fdai.shared.providers.ontology_instance import OntologyDirection, OntologyGraphSnapshot


class OntologyInterfaceType(ContractBase):
    name: Annotated[str, Field(pattern=r"^[A-Z][A-Za-z0-9]{0,63}$")]
    version: SemVer
    properties: dict[str, PropertyDecl] = Field(default_factory=dict)
    required_links: tuple[str, ...] = ()
    supported_actions: tuple[str, ...] = ()
    extends: tuple[str, ...] = ()


class InterfaceImplementation(ContractBase):
    object_type: Annotated[str, Field(min_length=1)]
    interfaces: tuple[Annotated[str, Field(min_length=1)], ...]


class ObjectSelectorKind(StrEnum):
    OBJECT_TYPE = "object_type"
    INTERFACE = "interface"


class ObjectSelector(ContractBase):
    kind: ObjectSelectorKind
    name: Annotated[str, Field(min_length=1)]


class ObjectPredicate(ContractBase):
    property: Annotated[str, Field(min_length=1)]
    equals: Any


class ObjectTraversal(ContractBase):
    link_types: tuple[Annotated[str, Field(min_length=1)], ...]
    direction: OntologyDirection = "outgoing"
    max_depth: int = Field(default=1, ge=1, le=5)


class ObjectSetDefinition(ContractBase):
    selector: ObjectSelector
    predicates: tuple[ObjectPredicate, ...] = ()
    traversal: ObjectTraversal | None = None
    root_ids: tuple[str, ...] = ()
    as_of: datetime
    purpose: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")]
    limit: int = Field(default=100, ge=1, le=1000)

    @model_validator(mode="after")
    def _traversal_requires_roots(self) -> ObjectSetDefinition:
        if self.traversal is not None and not self.root_ids:
            raise ValueError("object-set traversal requires root_ids")
        if self.as_of.tzinfo is None:
            raise ValueError("object-set as_of MUST be timezone-aware")
        return self


class ObjectSetMaterialization(ContractBase):
    definition: ObjectSetDefinition
    graph: OntologyGraphSnapshot
    concrete_types: tuple[str, ...]
    truncated: bool
    truncation_reason: str | None = None

    @model_validator(mode="after")
    def _truncation_reason_matches_state(self) -> ObjectSetMaterialization:
        if self.truncated != (self.truncation_reason is not None):
            raise ValueError("object-set truncation reason MUST match truncated state")
        return self


__all__ = [
    "InterfaceImplementation",
    "ObjectPredicate",
    "ObjectSelector",
    "ObjectSelectorKind",
    "ObjectSetDefinition",
    "ObjectSetMaterialization",
    "ObjectTraversal",
    "OntologyInterfaceType",
]
