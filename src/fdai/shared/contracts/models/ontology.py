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

from pydantic import Field, field_validator, model_validator

from ._base import SemVer, _Base
from .enums import (
    ActionCategory,
    ActionInterface,
    Autonomy,
    BlastRadiusComputation,
    BlastRadiusScope,
    CausalEvidenceGrade,
    CeilingRole,
    EnvScope,
    ExecutionPath,
    LinkCardinality,
    Mode,
    Operation,
    PreconditionKind,
    PropertyType,
    RollbackKind,
    TriggerKind,
)
from .safety import ActionStopCondition


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


class ActionPrecondition(_Base):
    kind: PreconditionKind
    value: str | int | float | bool | None = None
    link_type: str | None = None
    property: str | None = None
    tag: str | None = None


class ActionBlastRadius(_Base):
    computation: BlastRadiusComputation
    static_bucket: BlastRadiusScope | None = None
    max_affected_resources: Annotated[int, Field(ge=1)] | None = None
    traversal_depth: Annotated[int, Field(ge=1, le=5)] = 2
    traversal_links: list[str] = Field(default_factory=lambda: ["contains", "depends_on"])


class TriggerKindDecl(_Base):
    """The ``trigger_kind`` axis on an ActionType (action-ontology.md 1)."""

    kind: TriggerKind
    restrict_to_scenarios: list[str] = Field(default_factory=list)


class TierCeiling(_Base):
    """One tier's ceiling: the highest autonomy and the lowest role."""

    max_autonomy: Autonomy
    min_role: CeilingRole


class CeilingByTier(_Base):
    """Per-tier autonomy/role ceilings (execution-model.md 2.2)."""

    t0: TierCeiling | None = None
    t1: TierCeiling | None = None
    t2: TierCeiling | None = None


class ProdDowngrade(_Base):
    """How an ActionType collapses in prod (execution-model.md 2.6).

    ``detection_ref`` resolves to the single environment classifier in
    risk-classification.md; it never defines a second prod rule here.
    """

    mode: Autonomy
    detection_ref: Annotated[str, Field(min_length=1)]

    @field_validator("mode")
    @classmethod
    def _mode_is_a_downgrade(cls, value: Autonomy) -> Autonomy:
        if value is Autonomy.ENFORCE_AUTO:
            raise ValueError(
                "prod_downgrade.mode cannot be enforce_auto (a downgrade never raises autonomy)"
            )
        return value


class OntologyActionType(_Base):
    schema_version: SemVer
    name: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_\.\-]{0,79}$")]
    version: SemVer
    operation: Operation
    interfaces: list[ActionInterface] = Field(default_factory=list)
    rollback_contract: RollbackKind
    irreversible: bool = False
    default_mode: Mode = Mode.SHADOW
    promotion_gate: PromotionGate
    preconditions: list[ActionPrecondition] = Field(default_factory=list)
    stop_conditions: list[ActionStopCondition] = Field(default_factory=list)
    blast_radius: ActionBlastRadius | None = None
    description: str | None = None
    # --- Execution-authority extension (Day-1 non-breaking; all optional) ---
    # Populated by the ontology backfill (action-ontology.md 10); shipped
    # ActionTypes that predate it validate unchanged because every field
    # below is optional and ``exclude_none`` drops the empty ones on dump.
    category: ActionCategory | None = None
    trigger_kind: TriggerKindDecl | None = None
    execution_path: ExecutionPath | None = None
    ceiling_by_tier: CeilingByTier | None = None
    env_scope: EnvScope = EnvScope.ANY
    prod_downgrade: ProdDowngrade | None = None
    argument_schema: dict[str, Any] | None = None
    live_probe_ref: str | None = None
    provenance: OntologyProvenance | None = None


__all__ = [
    "ActionBlastRadius",
    "ActionPrecondition",
    "ActionStopCondition",
    "CeilingByTier",
    "LifecycleCriterion",
    "LifecycleDeduplication",
    "LifecycleOwner",
    "ObjectLifecycle",
    "OntologyActionType",
    "OntologyFunctionKind",
    "OntologyFunctionType",
    "OntologyLinkType",
    "OntologyObjectType",
    "OntologyProvenance",
    "ProdDowngrade",
    "PromotionGate",
    "LogicCapability",
    "LogicExecutionClass",
    "PropertyDecl",
    "TierCeiling",
    "TriggerKindDecl",
]
