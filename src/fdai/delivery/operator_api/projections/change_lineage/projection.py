"""Pure bounded views over canonical Change lineage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from typing import Any

from fdai.core.change_lineage import ChangeLineageRecord, extract_learning_candidate

_MAX_SOURCE_CHARS = 64
_MAX_IDENTIFIER_CHARS = 512
_MAX_ACTION_TYPE_CHARS = 128
_MAX_REASON_CHARS = 512
_MAX_EVIDENCE_REFS = 32
_MAX_OBJECTIVES = 16
_MAX_CONSTRAINTS = 32
_LINEAGE_PREFIX = "change-lineage:"
_CANDIDATE_PREFIX = "change-learning-candidate:"


@dataclass(frozen=True, slots=True)
class ChangeLineageSummaryProjection:
    """Bounded operator summary that preserves every authority ceiling."""

    lineage_id: str
    candidate_id: str
    change_id: str
    change_source: str
    change_ref: str
    action_type_id: str
    outcome_label: str
    outcome_at: datetime
    execution_mode: str
    verification_status: str
    requires_human_approval: bool
    candidate_only: bool = True
    requires_sealed_case: bool = True
    operational_reuse_eligible: bool = False
    execution_authority: bool = False
    promotion_authority: bool = False

    def __post_init__(self) -> None:
        _prefixed_digest("lineage_id", self.lineage_id, prefix=_LINEAGE_PREFIX)
        _prefixed_digest("candidate_id", self.candidate_id, prefix=_CANDIDATE_PREFIX)
        _identity("change_id", self.change_id)
        _identity("change_source", self.change_source, limit=_MAX_SOURCE_CHARS)
        _identity("change_ref", self.change_ref)
        _identity("action_type_id", self.action_type_id, limit=_MAX_ACTION_TYPE_CHARS)
        _identity("outcome_label", self.outcome_label, limit=_MAX_SOURCE_CHARS)
        _identity("execution_mode", self.execution_mode, limit=_MAX_SOURCE_CHARS)
        _identity(
            "verification_status",
            self.verification_status,
            limit=_MAX_SOURCE_CHARS,
        )
        if self.outcome_at.tzinfo is None:
            raise ValueError("change lineage summary outcome_at MUST be timezone-aware")
        if (
            not self.candidate_only
            or not self.requires_sealed_case
            or self.operational_reuse_eligible
            or self.execution_authority
            or self.promotion_authority
        ):
            raise ValueError("change lineage summary MUST preserve candidate and authority gates")

    def to_mapping(self) -> dict[str, Any]:
        """Return the stable bounded summary mapping."""

        return {
            "lineage_id": self.lineage_id,
            "candidate_id": self.candidate_id,
            "change_id": self.change_id,
            "change_source": self.change_source,
            "change_ref": self.change_ref,
            "action_type_id": self.action_type_id,
            "outcome_label": self.outcome_label,
            "outcome_at": self.outcome_at.isoformat(),
            "execution_mode": self.execution_mode,
            "verification_status": self.verification_status,
            "requires_human_approval": self.requires_human_approval,
            "candidate_only": True,
            "requires_sealed_case": True,
            "operational_reuse_eligible": False,
            "execution_authority": False,
            "promotion_authority": False,
        }


@dataclass(frozen=True, slots=True)
class ChangeLineageDetailProjection:
    """Bounded operator detail without raw provider or mutable state."""

    summary: ChangeLineageSummaryProjection
    correlation_id: str
    assessment_digest: str
    decision_case_id: str
    selected_option_id: str
    action_id: str
    event_id: str
    target_digest: str
    outcome_id: str
    decision_reason: str
    decision_reason_truncated: bool
    margin: float
    selected_objective_ids: tuple[str, ...]
    objective_count: int
    objectives_truncated: bool
    active_constraint_ids: tuple[str, ...]
    active_constraint_count: int
    violated_constraint_ids: tuple[str, ...]
    violated_constraint_count: int
    constraints_truncated: bool
    blast_radius_scope: str
    blast_radius_count: int | None
    rollback_kind: str
    rollback_succeeded: bool | None
    predicted_at: datetime | None
    observation_deadline: datetime | None
    observed_at: datetime | None
    evidence_refs: tuple[str, ...]
    evidence_ref_count: int
    evidence_truncated: bool

    def __post_init__(self) -> None:
        for name, value in (
            ("correlation_id", self.correlation_id),
            ("decision_case_id", self.decision_case_id),
            ("selected_option_id", self.selected_option_id),
            ("action_id", self.action_id),
            ("event_id", self.event_id),
            ("outcome_id", self.outcome_id),
        ):
            _identity(name, value)
        _digest("assessment_digest", self.assessment_digest)
        _digest("target_digest", self.target_digest)
        _bounded_text(self.decision_reason, _MAX_REASON_CHARS)
        if len(self.decision_reason) > _MAX_REASON_CHARS:
            raise ValueError("change lineage detail decision reason exceeds its reason bound")
        if self.decision_reason_truncated and len(self.decision_reason) != _MAX_REASON_CHARS:
            raise ValueError("change lineage detail reason truncation metadata is inconsistent")
        if not isfinite(self.margin):
            raise ValueError("change lineage detail margin MUST be finite")
        _validate_collection_metadata(
            "objective",
            self.selected_objective_ids,
            count=self.objective_count,
            truncated=self.objectives_truncated,
            limit=_MAX_OBJECTIVES,
        )
        _validate_collection_metadata(
            "active constraint",
            self.active_constraint_ids,
            count=self.active_constraint_count,
            truncated=self.active_constraint_count > len(self.active_constraint_ids),
            limit=_MAX_CONSTRAINTS,
        )
        _validate_collection_metadata(
            "violated constraint",
            self.violated_constraint_ids,
            count=self.violated_constraint_count,
            truncated=self.violated_constraint_count > len(self.violated_constraint_ids),
            limit=_MAX_CONSTRAINTS,
        )
        expected_constraints_truncated = self.active_constraint_count > len(
            self.active_constraint_ids
        ) or self.violated_constraint_count > len(self.violated_constraint_ids)
        if self.constraints_truncated is not expected_constraints_truncated:
            raise ValueError("change lineage detail constraint truncation metadata is inconsistent")
        _identity("blast_radius_scope", self.blast_radius_scope, limit=_MAX_SOURCE_CHARS)
        _identity("rollback_kind", self.rollback_kind, limit=_MAX_SOURCE_CHARS)
        if self.blast_radius_count is not None and self.blast_radius_count < 1:
            raise ValueError("change lineage detail blast radius count MUST be positive")
        if any(
            value is not None and value.tzinfo is None
            for value in (self.predicted_at, self.observation_deadline, self.observed_at)
        ):
            raise ValueError("change lineage detail timestamps MUST be timezone-aware")
        _validate_collection_metadata(
            "evidence",
            self.evidence_refs,
            count=self.evidence_ref_count,
            truncated=self.evidence_truncated,
            limit=_MAX_EVIDENCE_REFS,
        )

    def to_mapping(self) -> dict[str, Any]:
        """Return the stable bounded detail mapping."""

        return {
            "summary": self.summary.to_mapping(),
            "identity": {
                "correlation_id": self.correlation_id,
                "assessment_digest": self.assessment_digest,
                "decision_case_id": self.decision_case_id,
                "selected_option_id": self.selected_option_id,
                "action_id": self.action_id,
                "event_id": self.event_id,
                "target_digest": self.target_digest,
                "outcome_id": self.outcome_id,
            },
            "decision": {
                "reason": self.decision_reason,
                "reason_truncated": self.decision_reason_truncated,
                "margin": self.margin,
                "selected_objective_ids": list(self.selected_objective_ids),
                "objective_count": self.objective_count,
                "objectives_truncated": self.objectives_truncated,
                "active_constraint_ids": list(self.active_constraint_ids),
                "active_constraint_count": self.active_constraint_count,
                "violated_constraint_ids": list(self.violated_constraint_ids),
                "violated_constraint_count": self.violated_constraint_count,
                "constraints_truncated": self.constraints_truncated,
            },
            "resilience": {
                "blast_radius_scope": self.blast_radius_scope,
                "blast_radius_count": self.blast_radius_count,
                "rollback_kind": self.rollback_kind,
                "rollback_succeeded": self.rollback_succeeded,
                "predicted_at": _timestamp(self.predicted_at),
                "observation_deadline": _timestamp(self.observation_deadline),
                "observed_at": _timestamp(self.observed_at),
            },
            "evidence": {
                "refs": list(self.evidence_refs),
                "count": self.evidence_ref_count,
                "truncated": self.evidence_truncated,
            },
        }


def project_change_lineage_summary(
    lineage: ChangeLineageRecord,
) -> ChangeLineageSummaryProjection:
    """Project one lineage without widening its learning or action authority."""

    candidate = extract_learning_candidate(lineage)
    return ChangeLineageSummaryProjection(
        lineage_id=_identity("lineage_id", lineage.lineage_id),
        candidate_id=_identity("candidate_id", candidate.candidate_id),
        change_id=_identity("change_id", lineage.change_id),
        change_source=_identity(
            "change_source",
            lineage.change_source,
            limit=_MAX_SOURCE_CHARS,
        ),
        change_ref=_identity("change_ref", lineage.change_ref),
        action_type_id=_identity(
            "action_type_id",
            lineage.action_type_id,
            limit=_MAX_ACTION_TYPE_CHARS,
        ),
        outcome_label=_identity(
            "outcome_label",
            lineage.outcome_label,
            limit=_MAX_SOURCE_CHARS,
        ),
        outcome_at=lineage.outcome_at,
        execution_mode=_identity(
            "execution_mode",
            lineage.resilience.execution_mode,
            limit=_MAX_SOURCE_CHARS,
        ),
        verification_status=_identity(
            "verification_status",
            lineage.resilience.verification_status,
            limit=_MAX_SOURCE_CHARS,
        ),
        requires_human_approval=lineage.decision.requires_human_approval,
    )


def project_change_lineage_detail(
    lineage: ChangeLineageRecord,
) -> ChangeLineageDetailProjection:
    """Project bounded replay detail without exposing raw source metadata."""

    summary = project_change_lineage_summary(lineage)
    reason, reason_truncated = _bounded_text(lineage.decision.reason, _MAX_REASON_CHARS)
    objective_ids = tuple(effect.objective_id for effect in lineage.decision.selected_effects)
    selected_objectives, objectives_truncated = _bounded_identities(
        "selected_objective_ids",
        objective_ids,
        limit=_MAX_OBJECTIVES,
    )
    active_constraints, active_truncated = _bounded_identities(
        "active_constraint_ids",
        lineage.decision.active_constraint_ids,
        limit=_MAX_CONSTRAINTS,
    )
    violated_constraints, violated_truncated = _bounded_identities(
        "violated_constraint_ids",
        lineage.decision.violated_constraint_ids,
        limit=_MAX_CONSTRAINTS,
    )
    evidence_refs, evidence_truncated = _bounded_identities(
        "evidence_refs",
        lineage.evidence_refs,
        limit=_MAX_EVIDENCE_REFS,
    )
    return ChangeLineageDetailProjection(
        summary=summary,
        correlation_id=_identity("correlation_id", lineage.correlation_id),
        assessment_digest=_identity("assessment_digest", lineage.assessment_digest),
        decision_case_id=_identity("decision_case_id", lineage.decision_case_id),
        selected_option_id=_identity("selected_option_id", lineage.selected_option_id),
        action_id=_identity("action_id", lineage.action_id),
        event_id=_identity("event_id", lineage.event_id),
        target_digest=_identity("target_digest", lineage.target_digest),
        outcome_id=_identity("outcome_id", lineage.outcome_id),
        decision_reason=reason,
        decision_reason_truncated=reason_truncated,
        margin=lineage.decision.margin,
        selected_objective_ids=selected_objectives,
        objective_count=len(objective_ids),
        objectives_truncated=objectives_truncated,
        active_constraint_ids=active_constraints,
        active_constraint_count=len(lineage.decision.active_constraint_ids),
        violated_constraint_ids=violated_constraints,
        violated_constraint_count=len(lineage.decision.violated_constraint_ids),
        constraints_truncated=active_truncated or violated_truncated,
        blast_radius_scope=_identity(
            "blast_radius_scope",
            lineage.resilience.blast_radius_scope,
            limit=_MAX_SOURCE_CHARS,
        ),
        blast_radius_count=lineage.resilience.blast_radius_count,
        rollback_kind=_identity(
            "rollback_kind",
            lineage.resilience.rollback_kind,
            limit=_MAX_SOURCE_CHARS,
        ),
        rollback_succeeded=lineage.resilience.rollback_succeeded,
        predicted_at=lineage.resilience.predicted_at,
        observation_deadline=lineage.resilience.observation_deadline,
        observed_at=lineage.resilience.observed_at,
        evidence_refs=evidence_refs,
        evidence_ref_count=len(lineage.evidence_refs),
        evidence_truncated=evidence_truncated,
    )


def _identity(name: str, value: str, *, limit: int = _MAX_IDENTIFIER_CHARS) -> str:
    if not value.strip() or len(value) > limit:
        raise ValueError(f"change lineage projection {name} MUST be in [1, {limit}] characters")
    return value


def _digest(name: str, value: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"change lineage projection {name} MUST be a lowercase SHA-256 digest")
    return value


def _prefixed_digest(name: str, value: str, *, prefix: str) -> str:
    if not value.startswith(prefix):
        raise ValueError(f"change lineage projection {name} MUST start with {prefix!r}")
    _digest(name, value.removeprefix(prefix))
    return value


def _bounded_identities(
    name: str,
    values: tuple[str, ...],
    *,
    limit: int,
) -> tuple[tuple[str, ...], bool]:
    for value in values:
        _identity(name, value)
    return values[:limit], len(values) > limit


def _bounded_text(value: str, limit: int) -> tuple[str, bool]:
    if not value:
        raise ValueError("change lineage projection decision reason MUST be non-empty")
    return value[:limit], len(value) > limit


def _validate_collection_metadata(
    name: str,
    values: tuple[str, ...],
    *,
    count: int,
    truncated: bool,
    limit: int,
) -> None:
    _bounded_identities(name, values, limit=limit)
    expected_truncated = count > len(values)
    if count < len(values) or truncated is not expected_truncated:
        raise ValueError(f"change lineage detail {name} count metadata is inconsistent")
    if expected_truncated and len(values) != limit:
        raise ValueError(f"change lineage detail {name} truncation metadata is inconsistent")


def _timestamp(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


__all__ = [
    "ChangeLineageDetailProjection",
    "ChangeLineageSummaryProjection",
    "project_change_lineage_detail",
    "project_change_lineage_summary",
]
