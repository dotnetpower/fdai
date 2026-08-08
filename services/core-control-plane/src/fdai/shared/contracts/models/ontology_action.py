"""Authority metadata and rollback contracts for ontology ActionTypes."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field, field_validator, model_validator

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
    Mode,
    Operation,
    PreconditionKind,
    RollbackKind,
    TriggerKind,
)
from .ontology import OntologyProvenance, PromotionGate
from .ontology_semantic import ActionSemanticContract
from .safety import ActionStopCondition


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
    """How an ActionType collapses in prod (execution-model.md 2.6)."""

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
    category: ActionCategory | None = None
    trigger_kind: TriggerKindDecl | None = None
    execution_path: ExecutionPath | None = None
    ceiling_by_tier: CeilingByTier | None = None
    env_scope: EnvScope = EnvScope.ANY
    prod_downgrade: ProdDowngrade | None = None
    argument_schema: dict[str, Any] | None = None
    live_probe_ref: str | None = None
    provenance: OntologyProvenance | None = None
    semantic: ActionSemanticContract | None = None

    @model_validator(mode="after")
    def _semantic_rollback_is_explicit(self) -> OntologyActionType:
        if self.semantic is not None and not self.irreversible:
            missing = [
                effect.effect_id
                for effect in self.semantic.effects
                if effect.rollback_operation_ref is None
            ]
            if missing:
                raise ValueError(
                    "reversible semantic action effects require rollback_operation_ref"
                )
        return self


__all__ = [
    "ActionBlastRadius",
    "ActionPrecondition",
    "ActionStopCondition",
    "CeilingByTier",
    "OntologyActionType",
    "ProdDowngrade",
    "TierCeiling",
    "TriggerKindDecl",
]
