"""Typed constraint slots shared by semantic judgment and planning frames."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ConstraintSlotRole(StrEnum):
    TIME_WINDOW = "time_window"
    LOCATION = "location"
    PROPERTY_PREDICATE = "property_predicate"
    LIFECYCLE_STATUS = "lifecycle_status"
    GROUP_BY = "group_by"
    RELATION_PATH = "relation_path"
    PRIOR_RESULT = "prior_result"
    ORDINAL = "ordinal"


class SemanticConstraintSlot(BaseModel):
    """One grounded or explicitly unbound slot copied from the blind reading."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    role: ConstraintSlotRole
    source_start: Annotated[int, Field(ge=0, le=32_000)]
    source_end: Annotated[int, Field(gt=0, le=32_000)]
    grounded: bool
    value: Annotated[str, Field(min_length=1, max_length=256)] | None = None
    object_type: Annotated[str, Field(min_length=1, max_length=128)] | None = None
    unbound_reason: (
        Literal[
            "concept_unavailable",
            "ambiguous",
            "unsupported",
            "out_of_domain",
        ]
        | None
    ) = None

    @model_validator(mode="after")
    def _consistent(self) -> SemanticConstraintSlot:
        if self.source_end <= self.source_start:
            raise ValueError("constraint slot source span MUST be ordered")
        if self.grounded:
            if self.value is None or self.unbound_reason is not None:
                raise ValueError("grounded constraint slots require value only")
        elif self.unbound_reason is None:
            raise ValueError("unbound constraint slots require a reason")
        return self


__all__ = ["ConstraintSlotRole", "SemanticConstraintSlot"]
