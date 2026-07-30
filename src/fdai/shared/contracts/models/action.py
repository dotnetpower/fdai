"""Action contract - the autonomous change the executor may apply.

The four safety-invariant fields (``stop_condition``, ``rollback_ref``,
``blast_radius``, plus the audit entry that consumers of this model MUST
write when they persist the action) are mandatory. An action missing any
of them is incomplete and MUST NOT execute.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from pydantic import Field, model_validator

from ._base import IdempotencyKey, SemVer, _Base
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

    @model_validator(mode="after")
    def _stop_condition_shorthand_matches_contract(self) -> Action:
        if self.stop_conditions and self.stop_condition != self.stop_conditions[0].kind.value:
            raise ValueError("stop_condition MUST match the first structured stop condition")
        return self


__all__ = ["Action", "BlastRadius", "RollbackRef"]
