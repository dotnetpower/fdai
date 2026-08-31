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
    scope: Annotated[str, Field(min_length=1, max_length=512)] | None = None
    evidence_refs: tuple[str, ...] = ()
    observed_at: datetime | None = None
    recorded_at: datetime | None = None
    source_identity: Annotated[str, Field(min_length=1, max_length=512)] | None = None
    evidence_digest: Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")] | None = None
    not_applicable_reason: Annotated[str, Field(min_length=1, max_length=2048)] | None = None
    not_applicable_approved_by: Annotated[str, Field(min_length=1, max_length=512)] | None = None

    @model_validator(mode="after")
    def _validate_times_and_not_applicable_fields(self) -> Self:
        for field_name, value in (
            ("observed_at", self.observed_at),
            ("recorded_at", self.recorded_at),
        ):
            if value is not None and value.tzinfo is None:
                raise ValueError(f"RequirementOutcome.{field_name} MUST be timezone-aware")
        if self.status is not RequirementStatus.NOT_APPLICABLE and (
            self.not_applicable_reason is not None or self.not_applicable_approved_by is not None
        ):
            raise ValueError("not-applicable justification fields require NOT_APPLICABLE status")
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
