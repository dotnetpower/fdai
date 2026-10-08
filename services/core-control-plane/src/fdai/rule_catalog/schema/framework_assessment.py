"""Strict reviewed catalogs for WAF, CAF, and MCSB evidence-governed assessment."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

_IDENTIFIER = r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,255}$"
_LOWER_IDENTIFIER = r"^[a-z0-9][a-z0-9._:-]{0,255}$"
_SHA256 = r"^sha256:[a-f0-9]{64}$"
_DATE_VERSION = r"^\d{4}-\d{2}-\d{2}$"


def canonical_digest(value: object) -> str:
    """Return a stable SHA-256 digest for JSON-compatible assessment data."""

    encoded = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


class FrameworkScopeKind(StrEnum):
    WORKLOAD = "workload"
    CLOUD_ESTATE = "cloud-estate"


class FrameworkRequirementKind(StrEnum):
    RULE = "rule"
    ARTIFACT = "artifact"
    METRIC = "metric"
    DRILL = "drill"
    APPROVAL = "approval"
    OBSERVATION = "observation"


class FrameworkEvidenceRole(StrEnum):
    DECISIVE = "decisive"
    SUPPORTING_ONLY = "supporting_only"


class FrameworkProcessPhase(StrEnum):
    NONE = "none"
    PROCEDURE = "procedure"
    EXECUTION = "execution"


class FrameworkGenerationContract(StrEnum):
    INVENTORY = "inventory"
    HIERARCHY = "hierarchy"
    NONE = "none"


class FrameworkCrosswalkKind(StrEnum):
    BEST_PRACTICE = "best_practice"
    RULE = "rule"
    WAF = "waf"
    MCSB = "mcsb"
    CONTROL_OBJECTIVE = "control_objective"
    AZURE_POLICY = "azure_policy"
    OBSERVATION = "observation"
    MANUAL_EVIDENCE = "manual_evidence"


class FrameworkRelationshipState(StrEnum):
    FULL = "full"
    PARTIAL = "partial"
    SUPPORTING_ONLY = "supporting_only"
    UNMAPPED = "unmapped"


class FrameworkEvidenceSpecification(BaseModel):
    """One reviewed evidence path for a framework control requirement."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    requirement_id: Annotated[str, Field(pattern=_LOWER_IDENTIFIER)]
    kind: FrameworkRequirementKind
    source_ref: Annotated[str, Field(pattern=_IDENTIFIER)]
    authoritative_producer: Annotated[str, Field(pattern=_LOWER_IDENTIFIER)] | None = None
    blocked_dependency: Annotated[str, Field(pattern=_LOWER_IDENTIFIER)] | None = None
    scope_contract: Annotated[str, Field(pattern=r"^exact-(workload|estate)$")]
    generation_contract: FrameworkGenerationContract
    freshness_ceiling_seconds: int = Field(ge=60, le=31_536_000)
    completeness_required: Annotated[bool, Field(strict=True)]
    owner_slot: Annotated[str, Field(pattern=_LOWER_IDENTIFIER)]
    approval_roles: tuple[Annotated[str, Field(pattern=_LOWER_IDENTIFIER)], ...]
    failure_behavior: Annotated[str, Field(pattern=r"^unknown$")]
    evidence_role: FrameworkEvidenceRole
    process_phase: FrameworkProcessPhase = FrameworkProcessPhase.NONE

    @model_validator(mode="after")
    def validate_evidence_path(self) -> Self:
        if (self.authoritative_producer is None) == (self.blocked_dependency is None):
            raise ValueError(
                "framework evidence requires exactly one producer or blocked dependency"
            )
        if not self.approval_roles:
            raise ValueError("framework evidence requires at least one approval role")
        if self.approval_roles != tuple(sorted(set(self.approval_roles))):
            raise ValueError("framework evidence approval_roles MUST be unique and ordered")
        return self


class FrameworkCrosswalkReference(BaseModel):
    """One reviewed semantic relationship without inferred equivalence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    target_kind: FrameworkCrosswalkKind
    target_ref: Annotated[str, Field(pattern=_IDENTIFIER)] | None = None
    relationship: FrameworkRelationshipState

    @model_validator(mode="after")
    def validate_target(self) -> Self:
        if (self.relationship is FrameworkRelationshipState.UNMAPPED) != (self.target_ref is None):
            raise ValueError("unmapped framework relationships cannot carry a target")
        return self


class FrameworkControlSpecification(BaseModel):
    """Reviewed evidence and crosswalk contract for one framework control."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    control_id: Annotated[str, Field(pattern=_IDENTIFIER)]
    title: Annotated[str, Field(min_length=1, max_length=256)]
    area: Annotated[str, Field(pattern=_LOWER_IDENTIFIER)]
    requirement_mode: Annotated[str, Field(pattern=r"^(all|any)$")]
    cadence_days: int = Field(ge=1, le=365)
    owner_slot: Annotated[str, Field(pattern=_LOWER_IDENTIFIER)]
    evidence: tuple[FrameworkEvidenceSpecification, ...] = Field(min_length=1)
    crosswalk: tuple[FrameworkCrosswalkReference, ...] = Field(min_length=1)
    reviewer: Annotated[str, Field(pattern=_LOWER_IDENTIFIER)]
    review_state: Annotated[str, Field(pattern=r"^reviewed$")]
    specification_digest: Annotated[str, Field(pattern=_SHA256)]

    @model_validator(mode="after")
    def validate_control(self) -> Self:
        requirement_ids = tuple(item.requirement_id for item in self.evidence)
        if requirement_ids != tuple(sorted(set(requirement_ids))):
            raise ValueError("framework evidence requirement ids MUST be unique and ordered")
        crosswalk_keys = tuple(
            (item.target_kind.value, item.target_ref or "", item.relationship.value)
            for item in self.crosswalk
        )
        if crosswalk_keys != tuple(sorted(set(crosswalk_keys))):
            raise ValueError("framework crosswalk references MUST be unique and ordered")
        material = self.model_dump(mode="json")
        material.pop("specification_digest")
        if self.specification_digest != canonical_digest(material):
            raise ValueError(f"{self.control_id}: framework specification digest mismatch")
        return self


class FrameworkAssessmentCatalog(BaseModel):
    """Content-addressed complete assessment contract for one framework."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Annotated[str, Field(pattern=r"^1\.0\.0$")]
    framework_id: Annotated[str, Field(pattern=r"^azure-(waf|caf|mcsb)$")]
    framework_version: Annotated[str, Field(pattern=_DATE_VERSION)]
    framework_scope: FrameworkScopeKind
    source_revision_digest: Annotated[str, Field(pattern=_SHA256)]
    framework_definition_digest: Annotated[str, Field(pattern=_SHA256)]
    expected_control_count: int = Field(ge=1)
    controls: tuple[FrameworkControlSpecification, ...] = Field(min_length=1)
    reviewer: Annotated[str, Field(pattern=_LOWER_IDENTIFIER)]
    review_state: Annotated[str, Field(pattern=r"^reviewed$")]
    catalog_digest: Annotated[str, Field(pattern=_SHA256)]

    @model_validator(mode="after")
    def validate_catalog(self) -> Self:
        ids = tuple(item.control_id for item in self.controls)
        if ids != tuple(sorted(set(ids))):
            raise ValueError("framework assessment controls MUST be unique and ordered")
        if len(ids) != self.expected_control_count:
            raise ValueError("framework assessment control count mismatch")
        expected_scope = (
            FrameworkScopeKind.WORKLOAD
            if self.framework_id in {"azure-waf", "azure-mcsb"}
            else FrameworkScopeKind.CLOUD_ESTATE
        )
        if self.framework_scope is not expected_scope:
            raise ValueError("framework assessment scope does not match framework identity")
        material = self.model_dump(mode="json")
        material.pop("catalog_digest")
        if self.catalog_digest != canonical_digest(material):
            raise ValueError("framework assessment catalog digest mismatch")
        return self


def load_framework_assessment_catalog(path: Path) -> FrameworkAssessmentCatalog:
    """Load one generated catalog and reject malformed or stale digest material."""

    raw: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return FrameworkAssessmentCatalog.model_validate(raw)


__all__ = [
    "FrameworkAssessmentCatalog",
    "FrameworkControlSpecification",
    "FrameworkCrosswalkKind",
    "FrameworkCrosswalkReference",
    "FrameworkEvidenceRole",
    "FrameworkEvidenceSpecification",
    "FrameworkGenerationContract",
    "FrameworkProcessPhase",
    "FrameworkRelationshipState",
    "FrameworkRequirementKind",
    "FrameworkScopeKind",
    "canonical_digest",
    "load_framework_assessment_catalog",
]
