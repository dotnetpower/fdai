"""Action proposal contract - the state change an executor may evaluate.

The proposal carries stop, rollback, impact, idempotency, and target identity.
Execution paths add their content-addressed dry-run receipt, logical-target lock,
and pre-effect/terminal audit lifecycle. An incomplete path MUST NOT apply a
side effect.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from pydantic import Field, model_validator

from ._base import IdempotencyKey, OntologyDeclarationKind, OntologyTypeRef, SemVer, _Base
from .enums import BlastRadiusScope, Mode, Operation, RollbackKind
from .safety import ActionStopCondition


class RollbackRef(_Base):
    kind: RollbackKind
    reference: str | None = None


class BlastRadius(_Base):
    scope: BlastRadiusScope
    count: int | None = Field(default=None, ge=1)
    rate_per_minute: int | None = Field(default=None, ge=1)


class Action(_Base):
    """Autonomous action proposed by a tier, subject to the risk gate."""

    schema_version: SemVer
    action_id: UUID
    idempotency_key: IdempotencyKey
    event_id: UUID
    action_type: Annotated[str, Field(min_length=1)]
    target_resource_ref: Annotated[str, Field(min_length=1)]
    operation: Operation
    params: dict[str, Any] = Field(default_factory=dict)
    stop_condition: Annotated[str, Field(min_length=1)]
    stop_conditions: Annotated[list[ActionStopCondition], Field(min_length=1)]
    rollback_ref: RollbackRef
    blast_radius: BlastRadius
    mode: Mode
    citing_rules: Annotated[list[str], Field(min_length=1)]
    created_at: datetime
    action_type_ref: OntologyTypeRef | None = None
    executor_identity_ref: Annotated[str, Field(min_length=1)] | None = None

    @model_validator(mode="after")
    def _stop_condition_shorthand_matches_contract(self) -> Action:
        if self.stop_conditions and self.stop_condition != self.stop_conditions[0].kind.value:
            raise ValueError("stop_condition MUST match the first structured stop condition")
        return self

    @model_validator(mode="after")
    def _action_type_reference_matches_name(self) -> Action:
        if self.action_type_ref is None:
            return self
        if self.action_type_ref.kind is not OntologyDeclarationKind.ACTION:
            raise ValueError("action_type_ref.kind MUST be action")
        if self.action_type_ref.name != self.action_type:
            raise ValueError("action_type_ref.name MUST match action_type")
        return self


__all__ = ["Action", "BlastRadius", "RollbackRef"]
