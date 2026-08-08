"""Best-practice checklist contracts for multi-evidence controls."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Self

from pydantic import Field, model_validator

from ._base import SemVer, _Base
from .enums import Category, Severity
from .rule import Provenance


class RequirementKind(StrEnum):
    """Evidence source that can satisfy one checklist requirement."""

    RULE = "rule"
    PROBE = "probe"
    ARTIFACT = "artifact"
    METRIC = "metric"
    DRILL = "drill"
    APPROVAL = "approval"


class RequirementMode(StrEnum):
    """How requirement outcomes combine into the control outcome."""

    ALL = "all"
    ANY = "any"


class RequirementStatus(StrEnum):
    """Observed state of one checklist requirement."""

    SATISFIED = "satisfied"
    FAILED = "failed"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class BestPracticeRequirement(_Base):
    """One typed requirement referenced by a best-practice control."""

    kind: RequirementKind
    ref: Annotated[str, Field(min_length=1, max_length=256)]
    freshness_days: int | None = Field(default=None, gt=0)


class RequirementOutcome(_Base):
    """Grounded observed outcome supplied to the deterministic evaluator."""

    kind: RequirementKind
    ref: Annotated[str, Field(min_length=1, max_length=256)]
    status: RequirementStatus
    evidence_refs: tuple[str, ...] = ()
    observed_at: datetime | None = None

    @model_validator(mode="after")
    def _validate_observed_at(self) -> Self:
        if self.observed_at is not None and self.observed_at.tzinfo is None:
            raise ValueError("RequirementOutcome.observed_at MUST be timezone-aware")
        return self


class BestPractice(_Base):
    """One provenance-grounded recommendation composed from typed requirements."""

    id: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._-]{1,127}$")]
    version: SemVer
    framework: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._-]{1,63}$")]
    control_id: Annotated[str, Field(min_length=1, max_length=64)]
    title: Annotated[str, Field(min_length=1, max_length=256)]
    rationale: Annotated[str, Field(min_length=1, max_length=4096)]
    severity: Severity
    category: Category
    requirement_mode: RequirementMode
    requirements: Annotated[tuple[BestPracticeRequirement, ...], Field(min_length=1)]
    provenance: Provenance

    @model_validator(mode="after")
    def _validate_requirement_keys(self) -> Self:
        keys = [(requirement.kind, requirement.ref) for requirement in self.requirements]
        if len(keys) != len(set(keys)):
            raise ValueError("BestPractice.requirements MUST NOT contain duplicate references")
        return self


__all__ = [
    "BestPractice",
    "BestPracticeRequirement",
    "RequirementKind",
    "RequirementMode",
    "RequirementOutcome",
    "RequirementStatus",
]
