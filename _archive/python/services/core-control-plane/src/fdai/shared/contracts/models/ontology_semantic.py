"""Bounded semantic execution contracts for ontology ActionTypes."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import Field, field_validator, model_validator

from ._base import OntologyDeclarationKind, OntologyDeclarationRef, _Base


class ActionTargetCardinality(StrEnum):
    ONE = "one"
    SET = "set"


class ActionParameterRedaction(StrEnum):
    REDACT = "redact"
    AUDIT_SAFE = "audit_safe"


class ActionTransactionMode(StrEnum):
    ATOMIC = "atomic"
    SAGA = "saga"


class ActionLockScope(StrEnum):
    TARGET = "target"
    TARGET_SET = "target_set"


class ActionSemanticEffectKind(StrEnum):
    INTERNAL_WRITE = "internal_write"
    CATALOG_PR = "catalog_pr"
    PROVIDER_COMMAND = "provider_command"
    NOTIFICATION = "notification"
    SCHEDULE = "schedule"


class ActionPostconditionKind(StrEnum):
    PROPERTY = "property"
    METRIC = "metric"
    EVENT = "event"
    FUNCTION = "function"


class ActionTargetSelector(_Base):
    type_ref: OntologyDeclarationRef
    cardinality: ActionTargetCardinality

    @model_validator(mode="after")
    def _targets_object_or_interface(self) -> ActionTargetSelector:
        if self.type_ref.kind not in {
            OntologyDeclarationKind.OBJECT,
            OntologyDeclarationKind.INTERFACE,
        }:
            raise ValueError("action target type_ref MUST name an ObjectType or InterfaceType")
        return self


class ActionParameterDeclaration(_Base):
    name: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
    required: bool = False
    inline_schema: dict[str, Any] | None = None
    schema_ref: OntologyDeclarationRef | None = None
    redaction: ActionParameterRedaction

    @model_validator(mode="after")
    def _has_one_typed_schema(self) -> ActionParameterDeclaration:
        if (self.inline_schema is None) == (self.schema_ref is None):
            raise ValueError(
                "action parameter MUST declare exactly one of inline_schema or schema_ref"
            )
        if self.schema_ref is not None and self.schema_ref.kind not in {
            OntologyDeclarationKind.OBJECT,
            OntologyDeclarationKind.INTERFACE,
        }:
            raise ValueError("action parameter schema_ref MUST name an ObjectType or InterfaceType")
        if self.inline_schema is not None:
            if not self.inline_schema or not any(
                keyword in self.inline_schema for keyword in ("type", "enum", "const", "oneOf")
            ):
                raise ValueError("action parameter inline_schema MUST declare a concrete JSON type")
            if _contains_json_schema_ref(self.inline_schema):
                raise ValueError(
                    "action parameter inline_schema uses schema_ref for declaration references"
                )
            if (
                self.inline_schema.get("type") == "object"
                and self.inline_schema.get("additionalProperties") is not False
            ):
                raise ValueError(
                    "action parameter object inline_schema MUST set additionalProperties to false"
                )
        return self


class ActionReadSetReference(_Base):
    function_ref: OntologyDeclarationRef
    properties: Annotated[
        tuple[Annotated[str, Field(min_length=1, max_length=256)], ...],
        Field(min_length=1, max_length=64),
    ]
    max_objects: int = Field(ge=1, le=1000)

    @field_validator("function_ref")
    @classmethod
    def _references_function(cls, value: OntologyDeclarationRef) -> OntologyDeclarationRef:
        if value.kind is not OntologyDeclarationKind.FUNCTION:
            raise ValueError("action read-set function_ref MUST name a FunctionType")
        return value

    @field_validator("properties")
    @classmethod
    def _properties_are_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        _require_unique("action read-set properties", value)
        return value


class ActionSubmissionCriterion(_Base):
    criterion_ref: Annotated[str, Field(min_length=1, max_length=256)] | None = None
    function_ref: OntologyDeclarationRef | None = None

    @model_validator(mode="after")
    def _has_one_criterion_reference(self) -> ActionSubmissionCriterion:
        if (self.criterion_ref is None) == (self.function_ref is None):
            raise ValueError(
                "action submission criterion MUST declare exactly one criterion_ref or function_ref"
            )
        if (
            self.function_ref is not None
            and self.function_ref.kind is not OntologyDeclarationKind.FUNCTION
        ):
            raise ValueError("action submission criterion function_ref MUST name a FunctionType")
        return self


class ActionEffectSpec(_Base):
    effect_id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_.-]{0,79}$")]
    kind: ActionSemanticEffectKind
    operation_ref: Annotated[str, Field(min_length=1, max_length=256)]
    rollback_operation_ref: Annotated[str, Field(min_length=1, max_length=256)] | None = None
    grants_authority: Literal[False] = False


class ActionPostconditionSpec(_Base):
    postcondition_id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_.-]{0,79}$")]
    kind: ActionPostconditionKind
    observation_ref: Annotated[str, Field(min_length=1, max_length=256)] | None = None
    function_ref: OntologyDeclarationRef | None = None
    evidence_required: Literal[True] = True
    grants_authority: Literal[False] = False

    @model_validator(mode="after")
    def _has_exact_observation_reference(self) -> ActionPostconditionSpec:
        if (self.observation_ref is None) == (self.function_ref is None):
            raise ValueError(
                "action postcondition MUST declare exactly one observation_ref or function_ref"
            )
        if self.kind is ActionPostconditionKind.FUNCTION and self.function_ref is None:
            raise ValueError("function postcondition requires function_ref")
        if self.kind is not ActionPostconditionKind.FUNCTION and self.observation_ref is None:
            raise ValueError("non-function postcondition requires observation_ref")
        if (
            self.function_ref is not None
            and self.function_ref.kind is not OntologyDeclarationKind.FUNCTION
        ):
            raise ValueError("action postcondition function_ref MUST name a FunctionType")
        return self


class ActionTransactionPolicy(_Base):
    mode: ActionTransactionMode
    lock_scope: ActionLockScope
    max_affected_objects: int = Field(ge=1, le=1000)


class ActionSemanticContract(_Base):
    target: ActionTargetSelector
    parameters: Annotated[tuple[ActionParameterDeclaration, ...], Field(max_length=64)] = ()
    read_sets: Annotated[tuple[ActionReadSetReference, ...], Field(max_length=16)] = ()
    submission_criteria: Annotated[tuple[ActionSubmissionCriterion, ...], Field(max_length=16)] = ()
    planner_ref: OntologyDeclarationRef
    effects: Annotated[tuple[ActionEffectSpec, ...], Field(min_length=1, max_length=32)]
    postconditions: Annotated[
        tuple[ActionPostconditionSpec, ...], Field(min_length=1, max_length=32)
    ]
    transaction_policy: ActionTransactionPolicy

    @model_validator(mode="after")
    def _is_bounded_and_unambiguous(self) -> ActionSemanticContract:
        if self.planner_ref.kind is not OntologyDeclarationKind.FUNCTION:
            raise ValueError("action semantic planner_ref MUST name a FunctionType")
        if (
            self.target.cardinality is ActionTargetCardinality.ONE
            and self.transaction_policy.max_affected_objects != 1
        ):
            raise ValueError(
                "one-cardinality action target requires max_affected_objects equal to 1"
            )
        if (
            self.target.cardinality is ActionTargetCardinality.SET
            and self.transaction_policy.lock_scope is not ActionLockScope.TARGET_SET
        ):
            raise ValueError("set-cardinality action target requires target_set lock scope")
        _require_unique("action parameter names", (item.name for item in self.parameters))
        _require_unique(
            "action read-set function refs",
            (item.function_ref for item in self.read_sets),
        )
        _require_unique("action submission criteria", self.submission_criteria)
        _require_unique("action effect ids", (item.effect_id for item in self.effects))
        _require_unique(
            "action postcondition ids",
            (item.postcondition_id for item in self.postconditions),
        )
        return self


def _require_unique(label: str, values: Any) -> None:
    collected = tuple(values)
    if len(collected) != len(set(collected)):
        raise ValueError(f"{label} MUST be unique")


def _contains_json_schema_ref(value: object) -> bool:
    if isinstance(value, dict):
        return "$ref" in value or any(_contains_json_schema_ref(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_json_schema_ref(item) for item in value)
    return False


__all__ = [
    "ActionEffectSpec",
    "ActionLockScope",
    "ActionParameterDeclaration",
    "ActionParameterRedaction",
    "ActionPostconditionKind",
    "ActionPostconditionSpec",
    "ActionReadSetReference",
    "ActionSemanticContract",
    "ActionSemanticEffectKind",
    "ActionSubmissionCriterion",
    "ActionTargetCardinality",
    "ActionTargetSelector",
    "ActionTransactionMode",
    "ActionTransactionPolicy",
]
