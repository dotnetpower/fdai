"""Contracts for semantic interfaces and bounded object sets."""

from __future__ import annotations

import json
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, cast

from pydantic import (
    Field,
    SerializerFunctionWrapHandler,
    field_validator,
    model_serializer,
    model_validator,
)

from fdai.shared.contracts.models import ContractBase, PropertyDecl, SemVer
from fdai.shared.providers.ontology_instance import (
    OntologyDirection,
    OntologyGraphSnapshot,
    normalize_json_value,
)

_MAX_PREDICATE_OPERAND_BYTES = 65_536
_MAX_PREDICATES = 32
_MAX_IN_VALUES = 1_000
_MAX_ROOT_IDS = 1_000
_MAX_LINK_TYPES = 64


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


class ObjectPredicateOperator(StrEnum):
    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    IN = "in"
    EXISTS = "exists"
    ABSENT = "absent"
    AT_LEAST = "at_least"
    AT_MOST = "at_most"
    CONTAINS = "contains"


class ObjectPredicate(ContractBase):
    property: Annotated[str, Field(min_length=1, max_length=256)]
    operator: ObjectPredicateOperator = ObjectPredicateOperator.EQUALS
    equals: Any = None
    values: Annotated[tuple[Any, ...], Field(max_length=_MAX_IN_VALUES)] = ()

    @field_validator("equals", mode="before")
    @classmethod
    def _normalize_equals(cls, value: Any) -> Any:
        return _bounded_json_operand(value, path="object_predicate.equals")

    @field_validator("values", mode="before")
    @classmethod
    def _normalize_values(cls, value: Any) -> Any:
        return _bounded_json_operand(value, path="object_predicate.values")

    @model_validator(mode="after")
    def _operands_match_operator(self) -> ObjectPredicate:
        has_equals = "equals" in self.model_fields_set
        single_operand = {
            ObjectPredicateOperator.EQUALS,
            ObjectPredicateOperator.NOT_EQUALS,
            ObjectPredicateOperator.AT_LEAST,
            ObjectPredicateOperator.AT_MOST,
            ObjectPredicateOperator.CONTAINS,
        }
        if self.operator in single_operand:
            if not has_equals or self.equals is None or self.values:
                raise ValueError(
                    f"object predicate {self.operator.value} requires non-null equals "
                    "and forbids values"
                )
        elif self.operator is ObjectPredicateOperator.IN:
            if has_equals or not self.values:
                raise ValueError("object predicate in requires non-empty values and forbids equals")
        elif has_equals or self.values:
            raise ValueError(f"object predicate {self.operator.value} does not accept operands")
        return self

    @model_serializer(mode="wrap")
    def _serialize_operands(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        serialized = cast(dict[str, Any], handler(self))
        if self.operator is ObjectPredicateOperator.IN:
            serialized.pop("equals", None)
        elif self.operator in {
            ObjectPredicateOperator.EXISTS,
            ObjectPredicateOperator.ABSENT,
        }:
            serialized.pop("equals", None)
            serialized.pop("values", None)
        else:
            serialized.pop("values", None)
        return serialized


class ObjectTraversal(ContractBase):
    link_types: Annotated[
        tuple[Annotated[str, Field(min_length=1, max_length=64)], ...],
        Field(min_length=1, max_length=_MAX_LINK_TYPES),
    ]
    direction: OntologyDirection = "outgoing"
    max_depth: int = Field(default=1, ge=1, le=5)


class ObjectSetDefinition(ContractBase):
    selector: ObjectSelector
    predicates: Annotated[tuple[ObjectPredicate, ...], Field(max_length=_MAX_PREDICATES)] = ()
    traversal: ObjectTraversal | None = None
    root_ids: Annotated[
        tuple[Annotated[str, Field(min_length=1, max_length=512)], ...],
        Field(max_length=_MAX_ROOT_IDS),
    ] = ()
    as_of: datetime
    purpose: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")]
    limit: int = Field(default=100, ge=1, le=1000)

    @model_validator(mode="after")
    def _traversal_requires_roots(self) -> ObjectSetDefinition:
        if self.traversal is not None and not self.root_ids:
            raise ValueError("object-set traversal requires root_ids")
        if self.traversal is None and self.root_ids:
            raise ValueError("object-set root_ids require traversal")
        if self.as_of.tzinfo is None:
            raise ValueError("object-set as_of MUST be timezone-aware")
        return self


class ObjectSetTruncationReason(StrEnum):
    RESULT_LIMIT = "result_limit"
    CANDIDATE_LIMIT = "candidate_limit"
    TRAVERSAL_LIMIT = "traversal_limit"


class ObjectSetMaterialization(ContractBase):
    definition: ObjectSetDefinition
    graph: OntologyGraphSnapshot
    concrete_types: tuple[str, ...]
    truncated: bool
    truncation_reason: ObjectSetTruncationReason | None = None

    @model_validator(mode="after")
    def _truncation_reason_matches_state(self) -> ObjectSetMaterialization:
        if self.truncated != (self.truncation_reason is not None):
            raise ValueError("object-set truncation reason MUST match truncated state")
        return self


def _bounded_json_operand(value: Any, *, path: str) -> Any:
    normalized = normalize_json_value(value, path=path)
    encoded = json.dumps(
        normalized,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    if len(encoded) > _MAX_PREDICATE_OPERAND_BYTES:
        raise ValueError(
            f"{path} exceeds maximum encoded size {_MAX_PREDICATE_OPERAND_BYTES} bytes"
        )
    return normalized


__all__ = [
    "InterfaceImplementation",
    "ObjectPredicate",
    "ObjectPredicateOperator",
    "ObjectSelector",
    "ObjectSelectorKind",
    "ObjectSetDefinition",
    "ObjectSetMaterialization",
    "ObjectSetTruncationReason",
    "ObjectTraversal",
    "OntologyInterfaceType",
]
