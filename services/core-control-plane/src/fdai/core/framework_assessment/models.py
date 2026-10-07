"""Immutable value contracts for WAF and CAF shadow assessment."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from fdai.rule_catalog.schema.framework_assessment import (
    FrameworkEvidenceRole,
    FrameworkProcessPhase,
    FrameworkScopeKind,
    canonical_digest,
)

_SHA256 = re.compile(r"^sha256:[a-f0-9]{64}$")
_LIMITATION_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_RULE_ACTIVATION_GENERATION_ID = re.compile(r"^rule-activation-[a-f0-9]{32}$")


class FrameworkApplicabilityStatus(StrEnum):
    APPLICABLE = "applicable"
    NOT_APPLICABLE = "not_applicable"


class FrameworkEvaluationStatus(StrEnum):
    EVALUATED = "evaluated"
    NOT_EVALUATED = "not_evaluated"
    BLOCKED = "blocked"


class FrameworkSatisfactionStatus(StrEnum):
    SATISFIED = "satisfied"
    FAILED = "failed"
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"


def _require_text(label: str, value: str) -> None:
    if not value.strip():
        raise ValueError(f"{label} MUST be non-empty")


def _require_aware(label: str, value: datetime) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{label} MUST be timezone-aware")


def _require_digest(label: str, value: str) -> None:
    if _SHA256.fullmatch(value) is None:
        raise ValueError(f"{label} MUST be lowercase SHA-256")


@dataclass(frozen=True, slots=True)
class FrameworkApplicabilityDecision:
    control_id: str
    status: FrameworkApplicabilityStatus
    requested_by: str
    owner_slot: str
    cadence_days: int
    justification: str | None = None
    approved_by: str | None = None
    approved_at: datetime | None = None
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        for label, value in (
            ("framework applicability control_id", self.control_id),
            ("framework applicability requested_by", self.requested_by),
            ("framework applicability owner_slot", self.owner_slot),
        ):
            _require_text(label, value)
        if not 1 <= self.cadence_days <= 365:
            raise ValueError("framework applicability cadence_days MUST be in [1, 365]")
        justification = self.justification
        approved_by = self.approved_by
        approved_at = self.approved_at
        expires_at = self.expires_at
        approval_fields = (justification, approved_by, approved_at, expires_at)
        if self.status is FrameworkApplicabilityStatus.APPLICABLE:
            if any(value is not None for value in approval_fields):
                raise ValueError("applicable framework control cannot carry N/A approval fields")
            return
        if any(value is None for value in approval_fields):
            raise ValueError("not-applicable framework control requires complete approval fields")
        if approved_by is None or approved_at is None or expires_at is None:
            raise ValueError("not-applicable framework control approval fields are invalid")
        if self.requested_by == approved_by:
            raise ValueError("framework N/A requester and approver MUST be distinct")
        _require_aware("framework N/A approved_at", approved_at)
        _require_aware("framework N/A expires_at", expires_at)
        if expires_at <= approved_at:
            raise ValueError("framework N/A approval MUST expire after approval")

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "control_id": self.control_id,
            "status": self.status.value,
            "requested_by": self.requested_by,
            "owner_slot": self.owner_slot,
            "cadence_days": self.cadence_days,
        }
        if self.justification is not None:
            value.update(
                {
                    "justification": self.justification,
                    "approved_by": self.approved_by,
                    "approved_at": self.approved_at.isoformat() if self.approved_at else None,
                    "expires_at": self.expires_at.isoformat() if self.expires_at else None,
                }
            )
        return value


@dataclass(frozen=True, slots=True)
class FrameworkOwnerBinding:
    control_id: str
    owner_slot: str
    owner_identity: str

    def __post_init__(self) -> None:
        for label, value in (
            ("framework owner control_id", self.control_id),
            ("framework owner slot", self.owner_slot),
            ("framework owner identity", self.owner_identity),
        ):
            _require_text(label, value)

    def to_dict(self) -> dict[str, str]:
        return {
            "control_id": self.control_id,
            "owner_slot": self.owner_slot,
            "owner_identity": self.owner_identity,
        }


@dataclass(frozen=True, slots=True)
class FrameworkRuleActivationPin:
    """Rule activation generation pinned by the assessment, independent of any receipt."""

    generation_id: str
    generation_digest: str
    rule_catalog_digest: str

    def __post_init__(self) -> None:
        if _RULE_ACTIVATION_GENERATION_ID.fullmatch(self.generation_id) is None:
            raise ValueError("framework Rule activation generation_id is invalid")
        _require_digest("framework Rule activation generation_digest", self.generation_digest)
        _require_digest("framework Rule activation rule_catalog_digest", self.rule_catalog_digest)

    def to_dict(self) -> dict[str, str]:
        return {
            "generation_id": self.generation_id,
            "generation_digest": self.generation_digest,
            "rule_catalog_digest": self.rule_catalog_digest,
        }


@dataclass(frozen=True, slots=True)
class FrameworkRuleProvenance:
    """Activation, Rule revision, and coverage identities carried by one Rule receipt."""

    activation: FrameworkRuleActivationPin
    member_rule_digest: str | None
    coverage_digest: str

    def __post_init__(self) -> None:
        if self.member_rule_digest is not None:
            _require_digest("framework Rule member_rule_digest", self.member_rule_digest)
        _require_digest("framework Rule coverage_digest", self.coverage_digest)


@dataclass(frozen=True, slots=True)
class FrameworkAssessmentProfile:
    profile_id: str
    framework_id: str
    framework_version: str
    catalog_digest: str
    scope_kind: FrameworkScopeKind
    scope_digest: str
    ontology_release: str
    applicability: tuple[FrameworkApplicabilityDecision, ...]
    owners: tuple[FrameworkOwnerBinding, ...]
    reviewed_by: str
    reviewed_at: datetime
    inventory_generation: str | None = None
    hierarchy_generation: str | None = None
    operating_model: str | None = None
    environment_classes: tuple[str, ...] = ()
    regulatory_context: tuple[str, ...] = ()
    rule_activation: FrameworkRuleActivationPin | None = None
    profile_digest: str = ""

    def __post_init__(self) -> None:
        for label, value in (
            ("framework profile_id", self.profile_id),
            ("framework profile framework_id", self.framework_id),
            ("framework profile framework_version", self.framework_version),
            ("framework profile scope_digest", self.scope_digest),
            ("framework profile ontology_release", self.ontology_release),
            ("framework profile reviewed_by", self.reviewed_by),
        ):
            _require_text(label, value)
        _require_digest("framework profile catalog_digest", self.catalog_digest)
        _require_digest("framework profile scope_digest", self.scope_digest)
        _require_aware("framework profile reviewed_at", self.reviewed_at)
        decisions = tuple(item.control_id for item in self.applicability)
        owners = tuple(item.control_id for item in self.owners)
        if decisions != tuple(sorted(set(decisions))) or owners != decisions:
            raise ValueError(
                "framework profile decisions and owners MUST exactly align and be ordered"
            )
        if self.environment_classes != tuple(sorted(set(self.environment_classes))):
            raise ValueError("framework profile environment_classes MUST be unique and ordered")
        if self.regulatory_context != tuple(sorted(set(self.regulatory_context))):
            raise ValueError("framework profile regulatory_context MUST be unique and ordered")
        if self.scope_kind is FrameworkScopeKind.WORKLOAD:
            if not self.inventory_generation or self.hierarchy_generation is not None:
                raise ValueError("WAF profile requires only an inventory generation")
        elif (
            not self.hierarchy_generation
            or self.inventory_generation is not None
            or not self.operating_model
            or not self.environment_classes
        ):
            raise ValueError(
                "CAF profile requires hierarchy, operating model, and environment classes"
            )
        if self.rule_activation is not None and self.scope_kind is not FrameworkScopeKind.WORKLOAD:
            raise ValueError("only a workload profile can pin a Rule activation generation")
        _require_digest("framework profile profile_digest", self.profile_digest)
        if self.profile_digest != canonical_digest(self.to_dict(include_digest=False)):
            raise ValueError("framework profile digest mismatch")

    @classmethod
    def create(cls, **values: Any) -> FrameworkAssessmentProfile:
        applicability = values["applicability"]
        owners = values["owners"]
        reviewed_at = values["reviewed_at"]
        scope_kind = values["scope_kind"]
        material = {
            "profile_id": values["profile_id"],
            "framework_id": values["framework_id"],
            "framework_version": values["framework_version"],
            "catalog_digest": values["catalog_digest"],
            "scope_kind": scope_kind.value,
            "scope_digest": values["scope_digest"],
            "ontology_release": values["ontology_release"],
            "applicability": [item.to_dict() for item in applicability],
            "owners": [item.to_dict() for item in owners],
            "reviewed_by": values["reviewed_by"],
            "reviewed_at": reviewed_at.isoformat(),
            "inventory_generation": values.get("inventory_generation"),
            "hierarchy_generation": values.get("hierarchy_generation"),
            "operating_model": values.get("operating_model"),
            "environment_classes": list(values.get("environment_classes", ())),
            "regulatory_context": list(values.get("regulatory_context", ())),
        }
        rule_activation = values.get("rule_activation")
        if rule_activation is not None:
            # Added only when pinned so existing profile digests stay stable.
            material["rule_activation"] = rule_activation.to_dict()
        return cls(
            **values,
            profile_digest=canonical_digest(material),
        )

    def to_dict(self, *, include_digest: bool = True) -> dict[str, object]:
        value: dict[str, object] = {
            "profile_id": self.profile_id,
            "framework_id": self.framework_id,
            "framework_version": self.framework_version,
            "catalog_digest": self.catalog_digest,
            "scope_kind": self.scope_kind.value,
            "scope_digest": self.scope_digest,
            "ontology_release": self.ontology_release,
            "applicability": [item.to_dict() for item in self.applicability],
            "owners": [item.to_dict() for item in self.owners],
            "reviewed_by": self.reviewed_by,
            "reviewed_at": self.reviewed_at.isoformat(),
            "inventory_generation": self.inventory_generation,
            "hierarchy_generation": self.hierarchy_generation,
            "operating_model": self.operating_model,
            "environment_classes": list(self.environment_classes),
            "regulatory_context": list(self.regulatory_context),
        }
        if self.rule_activation is not None:
            value["rule_activation"] = self.rule_activation.to_dict()
        if include_digest:
            value["profile_digest"] = self.profile_digest
        return value


@dataclass(frozen=True, slots=True)
class FrameworkEvidenceReceipt:
    framework_id: str
    control_id: str
    requirement_id: str
    evidence_ref: str
    evidence_kind: str
    producer: str
    source_identity: str
    scope_digest: str
    observed_at: datetime
    recorded_at: datetime
    evidence_digest: str
    freshness_ceiling_seconds: int
    complete: bool
    truncated: bool
    conflicting: bool
    synthetic: bool
    provider_error: str | None
    outcome: FrameworkSatisfactionStatus
    evidence_role: FrameworkEvidenceRole
    process_phase: FrameworkProcessPhase
    inventory_generation: str | None = None
    hierarchy_generation: str | None = None
    not_applicable_justification: str | None = None
    not_applicable_requested_by: str | None = None
    not_applicable_approved_by: str | None = None
    approval_expires_at: datetime | None = None
    rule_provenance: FrameworkRuleProvenance | None = None
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for label, value in (
            ("framework evidence framework_id", self.framework_id),
            ("framework evidence control_id", self.control_id),
            ("framework evidence requirement_id", self.requirement_id),
            ("framework evidence evidence_ref", self.evidence_ref),
            ("framework evidence kind", self.evidence_kind),
            ("framework evidence producer", self.producer),
            ("framework evidence source_identity", self.source_identity),
        ):
            _require_text(label, value)
        _require_digest("framework evidence scope_digest", self.scope_digest)
        _require_digest("framework evidence evidence_digest", self.evidence_digest)
        _require_aware("framework evidence observed_at", self.observed_at)
        _require_aware("framework evidence recorded_at", self.recorded_at)
        if self.recorded_at < self.observed_at:
            raise ValueError("framework evidence recorded_at MUST follow observed_at")
        if self.freshness_ceiling_seconds < 60:
            raise ValueError("framework evidence freshness ceiling MUST be at least 60 seconds")
        na_fields = (
            self.not_applicable_justification,
            self.not_applicable_requested_by,
            self.not_applicable_approved_by,
            self.approval_expires_at,
        )
        if self.outcome is not FrameworkSatisfactionStatus.NOT_APPLICABLE:
            if any(value is not None for value in na_fields):
                raise ValueError("framework N/A fields require a not_applicable outcome")
        elif any(value is None for value in na_fields):
            raise ValueError("framework N/A evidence requires complete approval fields")
        elif self.not_applicable_requested_by == self.not_applicable_approved_by:
            raise ValueError("framework evidence N/A requester and approver MUST be distinct")
        if self.approval_expires_at is not None:
            _require_aware("framework evidence approval_expires_at", self.approval_expires_at)
        if self.limitations != tuple(sorted(set(self.limitations))) or any(
            _LIMITATION_CODE.fullmatch(item) is None for item in self.limitations
        ):
            raise ValueError("framework evidence limitations MUST be unique, ordered codes")
        if self.limitations and self.outcome is not FrameworkSatisfactionStatus.UNKNOWN:
            raise ValueError("framework evidence with limitations MUST report unknown")


@dataclass(frozen=True, slots=True)
class FrameworkTradeoffRecord:
    tradeoff_id: str
    scope_digest: str
    affected_control_ids: tuple[str, ...]
    decision_owner: str
    rationale_digest: str
    approved_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        _require_text("framework tradeoff id", self.tradeoff_id)
        _require_text("framework tradeoff decision owner", self.decision_owner)
        _require_digest("framework tradeoff scope_digest", self.scope_digest)
        _require_digest("framework tradeoff rationale_digest", self.rationale_digest)
        if self.affected_control_ids != tuple(sorted(set(self.affected_control_ids))):
            raise ValueError("framework tradeoff controls MUST be non-empty, unique, and ordered")
        if not self.affected_control_ids:
            raise ValueError("framework tradeoff requires affected controls")
        _require_aware("framework tradeoff approved_at", self.approved_at)
        _require_aware("framework tradeoff expires_at", self.expires_at)
        if self.expires_at <= self.approved_at:
            raise ValueError("framework tradeoff MUST expire after approval")

    def to_dict(self) -> dict[str, object]:
        return {
            "tradeoff_id": self.tradeoff_id,
            "scope_digest": self.scope_digest,
            "affected_control_ids": list(self.affected_control_ids),
            "decision_owner": self.decision_owner,
            "rationale_digest": self.rationale_digest,
            "approved_at": self.approved_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class FrameworkAssessmentRequest:
    assessment_id: str
    profile: FrameworkAssessmentProfile
    evaluated_at: datetime
    recorded_at: datetime
    evidence: tuple[FrameworkEvidenceReceipt, ...] = ()
    tradeoffs: tuple[FrameworkTradeoffRecord, ...] = ()

    def __post_init__(self) -> None:
        _require_text("framework assessment_id", self.assessment_id)
        _require_aware("framework assessment evaluated_at", self.evaluated_at)
        _require_aware("framework assessment recorded_at", self.recorded_at)
        if self.recorded_at < self.evaluated_at:
            raise ValueError("framework assessment recorded_at MUST follow evaluated_at")
        evidence_keys = tuple(
            (item.control_id, item.requirement_id, item.evidence_ref) for item in self.evidence
        )
        if evidence_keys != tuple(sorted(set(evidence_keys))):
            raise ValueError("framework evidence MUST be unique and ordered")
        tradeoff_ids = tuple(item.tradeoff_id for item in self.tradeoffs)
        if tradeoff_ids != tuple(sorted(set(tradeoff_ids))):
            raise ValueError("framework tradeoffs MUST be unique and ordered")


@dataclass(frozen=True, slots=True)
class FrameworkRequirementResult:
    requirement_id: str
    status: FrameworkSatisfactionStatus
    evidence_refs: tuple[str, ...]
    evidence_digests: tuple[str, ...]
    limitations: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "requirement_id": self.requirement_id,
            "status": self.status.value,
            "evidence_refs": list(self.evidence_refs),
            "evidence_digests": list(self.evidence_digests),
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True, slots=True)
class FrameworkControlResult:
    control_id: str
    title: str
    area: str
    reference_state: str
    mapping_state: str
    applicability: FrameworkApplicabilityStatus
    evaluation: FrameworkEvaluationStatus
    satisfaction: FrameworkSatisfactionStatus
    owner_slot: str
    cadence_days: int
    evidence_complete: bool
    evidence_refs: tuple[str, ...]
    evidence_digests: tuple[str, ...]
    limitations: tuple[str, ...]
    requirements: tuple[FrameworkRequirementResult, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "control_id": self.control_id,
            "title": self.title,
            "area": self.area,
            "reference_state": self.reference_state,
            "mapping_state": self.mapping_state,
            "applicability": self.applicability.value,
            "evaluation": self.evaluation.value,
            "satisfaction": self.satisfaction.value,
            "owner_slot": self.owner_slot,
            "cadence_days": self.cadence_days,
            "evidence_complete": self.evidence_complete,
            "evidence_refs": list(self.evidence_refs),
            "evidence_digests": list(self.evidence_digests),
            "limitations": list(self.limitations),
            "requirements": [item.to_dict() for item in self.requirements],
        }


@dataclass(frozen=True, slots=True)
class FrameworkAssessmentResult:
    assessment_id: str
    mode: str
    execution_authority: bool
    framework_id: str
    framework_version: str
    catalog_digest: str
    profile_id: str
    profile_digest: str
    profile_reviewed_by: str
    profile_reviewed_at: datetime
    applicability_profile: tuple[FrameworkApplicabilityDecision, ...]
    ontology_release: str
    scope_digest: str
    inventory_generation: str | None
    hierarchy_generation: str | None
    evaluated_at: datetime
    recorded_at: datetime
    controls: tuple[FrameworkControlResult, ...]
    tradeoffs: tuple[FrameworkTradeoffRecord, ...]
    aggregate_counts: dict[str, int]
    result_digest: str

    def to_dict(self, *, include_digest: bool = True) -> dict[str, object]:
        value: dict[str, object] = {
            "assessment_id": self.assessment_id,
            "mode": self.mode,
            "execution_authority": self.execution_authority,
            "framework_id": self.framework_id,
            "framework_version": self.framework_version,
            "catalog_digest": self.catalog_digest,
            "profile_id": self.profile_id,
            "profile_digest": self.profile_digest,
            "profile_reviewed_by": self.profile_reviewed_by,
            "profile_reviewed_at": self.profile_reviewed_at.isoformat(),
            "applicability_profile": [item.to_dict() for item in self.applicability_profile],
            "ontology_release": self.ontology_release,
            "scope_digest": self.scope_digest,
            "inventory_generation": self.inventory_generation,
            "hierarchy_generation": self.hierarchy_generation,
            "evaluated_at": self.evaluated_at.isoformat(),
            "recorded_at": self.recorded_at.isoformat(),
            "controls": [item.to_dict() for item in self.controls],
            "tradeoffs": [item.to_dict() for item in self.tradeoffs],
            "aggregate_counts": dict(sorted(self.aggregate_counts.items())),
        }
        if include_digest:
            value["result_digest"] = self.result_digest
        return value


__all__ = [
    "FrameworkApplicabilityDecision",
    "FrameworkApplicabilityStatus",
    "FrameworkAssessmentProfile",
    "FrameworkAssessmentRequest",
    "FrameworkAssessmentResult",
    "FrameworkControlResult",
    "FrameworkEvaluationStatus",
    "FrameworkEvidenceReceipt",
    "FrameworkOwnerBinding",
    "FrameworkRequirementResult",
    "FrameworkSatisfactionStatus",
    "FrameworkTradeoffRecord",
]
