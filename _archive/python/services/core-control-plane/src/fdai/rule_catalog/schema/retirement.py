"""Validated rule-retirement artifacts and runtime projection."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RetirementMode(StrEnum):
    """Whether a rule remains in shadow or leaves the active catalog."""

    SHADOW_ONLY = "shadow_only"
    RETIRED = "retired"


class RuleRetirement(BaseModel):
    """Reviewed retirement artifact consumed by the governance catalog."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    schema_version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]
    rule_id: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._-]{1,127}$")]
    mode: RetirementMode
    justification: Annotated[str, Field(min_length=20, max_length=500)]
    requested_by: UUID
    approved_by: UUID
    decided_at: datetime

    @model_validator(mode="after")
    def _require_distinct_principals(self) -> RuleRetirement:
        if self.requested_by == self.approved_by:
            raise ValueError("requested_by MUST differ from approved_by")
        if self.decided_at.tzinfo is None or self.decided_at.utcoffset() != UTC.utcoffset(
            self.decided_at
        ):
            raise ValueError("decided_at MUST use UTC")
        return self


def load_retirement_from_mapping(raw: dict[str, object]) -> RuleRetirement:
    """Validate one reviewed retirement mapping."""
    return RuleRetirement.model_validate(raw)


__all__ = ["RetirementMode", "RuleRetirement", "load_retirement_from_mapping"]
