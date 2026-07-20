"""Ontology declarations - ObjectType, LinkType, ActionType wire shapes.

These pydantic models are the typed view of the ontology JSON Schemas
under ``shared/contracts/ontology/``. Cross-references (e.g. an
``ActionType.action_type_ref`` inside a workflow step) are enforced by the
catalog loader, not by these models - the models only guarantee shape.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field, field_validator

from ._base import SemVer, _Base
from .enums import (
    ActionCategory,
    ActionInterface,
    Autonomy,
    BlastRadiusComputation,
    BlastRadiusScope,
    CeilingRole,
    EnvScope,
    ExecutionPath,
    LinkCardinality,
    Mode,
    Operation,
    PreconditionKind,
    PropertyType,
    RollbackKind,
    StopConditionKind,
    TriggerKind,
)


class PropertyDecl(_Base):
    type: PropertyType
    required: bool = False
    description: str | None = None
    access_scope: CeilingRole = CeilingRole.READER
    purpose_binding: list[Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")]] = Field(
        default_factory=list
    )


class LifecycleCriterion(_Base):
    code: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
    when: Annotated[str, Field(min_length=1)]
    result: Annotated[str, Field(min_length=1)]
    source_refs: list[Annotated[str, Field(min_length=1)]] = Field(min_length=1)


class LifecycleDeduplication(_Base):
    strategy: Annotated[str, Field(min_length=1)]
    fields: list[Annotated[str, Field(min_length=1)]] = Field(min_length=1)
    on_repeat: Annotated[str, Field(min_length=1)]


class ObjectLifecycle(_Base):
    owner: Annotated[str, Field(min_length=1)]
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
    description: str | None = None


class PromotionGate(_Base):
    min_shadow_days: Annotated[int, Field(ge=1)]
    min_samples: Annotated[int, Field(ge=1)]
    min_accuracy: Annotated[float, Field(ge=0.0, le=1.0)]
    max_policy_escapes: Annotated[int, Field(ge=0)]


class ActionPrecondition(_Base):
    kind: PreconditionKind
    value: str | int | float | bool | None = None
    link_type: str | None = None
    property: str | None = None
    tag: str | None = None


class ActionStopCondition(_Base):
    kind: StopConditionKind
    threshold: float | None = None
    window_seconds: Annotated[int, Field(ge=1)] | None = None
    seconds: Annotated[int, Field(ge=1)] | None = None
    count: Annotated[int, Field(ge=1)] | None = None


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


__all__ = [
    "ActionBlastRadius",
    "ActionPrecondition",
    "ActionStopCondition",
    "CeilingByTier",
    "LifecycleCriterion",
    "LifecycleDeduplication",
    "ObjectLifecycle",
    "OntologyActionType",
    "OntologyLinkType",
    "OntologyObjectType",
    "ProdDowngrade",
    "PromotionGate",
    "PropertyDecl",
    "TierCeiling",
    "TriggerKindDecl",
]
