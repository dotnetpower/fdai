"""Ontology declarations - ObjectType, LinkType, ActionType wire shapes.

These pydantic models are the typed view of the ontology JSON Schemas
under ``shared/contracts/ontology/``. Cross-references (e.g. an
``ActionType.action_type_ref`` inside a workflow step) are enforced by the
catalog loader, not by these models - the models only guarantee shape.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any

from pydantic import Field, model_validator

from ._base import SemVer, _Base
from .enums import (
    CausalEvidenceGrade,
    CeilingRole,
    LinkCardinality,
    PropertyType,
)


class PropertyDecl(_Base):
    type: PropertyType
    required: bool = False
    description: str | None = None
    access_scope: CeilingRole = CeilingRole.READER
    purpose_binding: list[Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")]] = Field(
        default_factory=list
    )


class OntologyProvenance(_Base):
    source_url: Annotated[str, Field(min_length=1)]
    resolved_ref: Annotated[str, Field(min_length=1)]
    content_hash: Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]
    license: Annotated[str, Field(min_length=1)]
    retrieved_at: datetime


class LifecycleCriterion(_Base):
    code: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
    when: Annotated[str, Field(min_length=1)]
    result: Annotated[str, Field(min_length=1)]
    source_refs: list[Annotated[str, Field(min_length=1)]] = Field(min_length=1)


class LifecycleDeduplication(_Base):
    strategy: Annotated[str, Field(min_length=1)]
    fields: list[Annotated[str, Field(min_length=1)]] = Field(min_length=1)
    on_repeat: Annotated[str, Field(min_length=1)]


class LifecycleOwner(StrEnum):
    ODIN = "Odin"
    THOR = "Thor"
    FORSETI = "Forseti"
    HUGINN = "Huginn"
    HEIMDALL = "Heimdall"
    VAR = "Var"
    VIDAR = "Vidar"
    BRAGI = "Bragi"
    SAGA = "Saga"
    MIMIR = "Mimir"
    NORNS = "Norns"
    MUNINN = "Muninn"
    NJORD = "Njord"
    FREYR = "Freyr"
    LOKI = "Loki"


class ObjectLifecycle(_Base):
    owner: LifecycleOwner
    creation: list[LifecycleCriterion] = Field(min_length=1)
    deduplication: LifecycleDeduplication | None = None
    closure: list[LifecycleCriterion] = Field(default_factory=list)
    authority_refs: list[Annotated[str, Field(min_length=1)]] = Field(min_length=1)


class OntologyObjectType(_Base):
    schema_version: SemVer
    name: Annotated[str, Field(pattern=r"^[A-Z][A-Za-z0-9]{0,63}$")]
    version: SemVer
    key: Annotated[str, Field(min_length=1)]
    properties: dict[str, PropertyDecl]
    description: str | None = None
    lifecycle: ObjectLifecycle | None = None
    provenance: OntologyProvenance | None = None


class OntologyLinkType(_Base):
    schema_version: SemVer
    name: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
    version: SemVer
    from_type: Annotated[str, Field(min_length=1)]
    to_type: Annotated[str, Field(min_length=1)]
    cardinality: LinkCardinality
    is_transitive: bool = False
    is_causal: bool = False
    temporal_order: bool = False
    order_by_property: str | None = None
    description: str | None = None
    provenance: OntologyProvenance | None = None


class OntologyInterfaceType(_Base):
    """Versioned polymorphic capability shared by ontology object types."""

    name: Annotated[str, Field(pattern=r"^[A-Z][A-Za-z0-9]{0,63}$")]
    version: SemVer
    properties: dict[str, PropertyDecl] = Field(default_factory=dict)
    required_links: tuple[str, ...] = ()
    supported_actions: tuple[str, ...] = ()
    extends: tuple[str, ...] = ()


class PromotionGate(_Base):
    min_shadow_days: Annotated[int, Field(ge=1)]
    min_samples: Annotated[int, Field(ge=1)]
    min_accuracy: Annotated[float, Field(ge=0.0, le=1.0)]
    max_policy_escapes: Annotated[int, Field(ge=0)]


class OntologyFunctionKind(StrEnum):
    QUERY = "query"
    DERIVE = "derive"
    VALIDATE = "validate"
    PLAN = "plan"


class LogicCapability(StrEnum):
    PREDICT = "predict"
    OPTIMIZE = "optimize"
    SIMULATE = "simulate"


class LogicExecutionClass(StrEnum):
    DETERMINISTIC = "deterministic"
    SEEDED_STOCHASTIC = "seeded_stochastic"


class OntologyFunctionType(_Base):
    schema_version: SemVer = "1.0.0"
    name: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_.-]{0,79}$")]
    version: SemVer
    kind: OntologyFunctionKind
    capabilities: list[LogicCapability] = Field(default_factory=list)
    artifact_digest: Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]
    publisher: Annotated[str, Field(min_length=1)]
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    read_sets: list[Annotated[str, Field(min_length=1)]] = Field(default_factory=list)
    execution_class: LogicExecutionClass = LogicExecutionClass.DETERMINISTIC
    seed_field: str | None = None
    required_role: CeilingRole = CeilingRole.READER
    purpose_bindings: list[Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")]] = Field(
        default_factory=list
    )
    allowed_agents: list[Annotated[str, Field(pattern=r"^[A-Z][A-Za-z0-9]{0,63}$")]] = Field(
        default_factory=list
    )
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    cpu_millis: int = Field(default=1000, ge=1, le=64_000)
    memory_bytes: int = Field(default=134_217_728, ge=1, le=1_073_741_824)
    max_output_bytes: int = Field(default=262_144, ge=1, le=5_000_000)
    network_allowed: bool = False
    credentials_allowed: bool = False
    learned_through: datetime | None = None
    evidence_grade: CausalEvidenceGrade | None = None
    promotion_gate: PromotionGate | None = None

    @model_validator(mode="after")
    def _function_contract(self) -> OntologyFunctionType:
        collections = (
            ("capabilities", self.capabilities),
            ("read_sets", self.read_sets),
            ("purpose_bindings", self.purpose_bindings),
            ("allowed_agents", self.allowed_agents),
        )
        for name, values in collections:
            if len(values) != len(set(values)):
                raise ValueError(f"ontology function {name} MUST be unique")
        if self.learned_through is not None and self.learned_through.tzinfo is None:
            raise ValueError("ontology function learned_through MUST be timezone-aware")
        if self.execution_class is LogicExecutionClass.DETERMINISTIC:
            if self.seed_field is not None:
                raise ValueError("deterministic ontology function MUST NOT declare seed_field")
        else:
            if not self.seed_field:
                raise ValueError("seeded ontology function requires seed_field")
            properties = self.input_schema.get("properties")
            required = self.input_schema.get("required")
            if not isinstance(properties, dict) or self.seed_field not in properties:
                raise ValueError("seed_field MUST be declared in input_schema properties")
            seed_schema = properties[self.seed_field]
            if not isinstance(seed_schema, dict) or seed_schema.get("type") != "integer":
                raise ValueError("seed_field input schema MUST use integer type")
            if not isinstance(required, list) or self.seed_field not in required:
                raise ValueError("seed_field MUST be required by input_schema")
        if self.credentials_allowed and not self.network_allowed:
            raise ValueError("credentialed ontology function requires network access")
        return self


__all__ = [
    "LifecycleCriterion",
    "LifecycleDeduplication",
    "LifecycleOwner",
    "ObjectLifecycle",
    "OntologyFunctionKind",
    "OntologyFunctionType",
    "OntologyInterfaceType",
    "OntologyLinkType",
    "OntologyObjectType",
    "OntologyProvenance",
    "PromotionGate",
    "LogicCapability",
    "LogicExecutionClass",
    "PropertyDecl",
]
