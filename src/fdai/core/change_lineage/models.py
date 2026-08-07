"""Immutable lineage joining one canonical Change to its observed outcome."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fdai.core.decision_case import DecisionCase, DecisionSelection
from fdai.core.impact_analysis import ChangeAssessment
from fdai.shared.contracts.models import Action, ResponseOutcome
from fdai.shared.providers.change_feed import ChangeRecord


@dataclass(frozen=True, slots=True)
class ChangeResilienceTrace:
    """Bounded resilience intent and observed recovery state for replay."""

    execution_mode: str
    blast_radius_scope: str
    blast_radius_count: int | None
    rollback_kind: str
    verification_status: str
    execution_outcome: str
    predicted_at: datetime | None
    observation_deadline: datetime | None
    observed_at: datetime | None
    rollback_succeeded: bool | None

    def __post_init__(self) -> None:
        text_values = (
            self.execution_mode,
            self.blast_radius_scope,
            self.rollback_kind,
            self.verification_status,
            self.execution_outcome,
        )
        if any(not value.strip() for value in text_values):
            raise ValueError("change resilience trace values MUST be non-empty")
        if self.blast_radius_count is not None and self.blast_radius_count < 1:
            raise ValueError("change resilience blast radius count MUST be positive")
        timestamps = (self.predicted_at, self.observation_deadline, self.observed_at)
        if any(value is not None and value.tzinfo is None for value in timestamps):
            raise ValueError("change resilience timestamps MUST be timezone-aware")
        if (self.predicted_at is None) != (self.observation_deadline is None):
            raise ValueError("change resilience prediction window MUST be supplied together")
        if (
            self.predicted_at is not None
            and self.observation_deadline is not None
            and self.predicted_at > self.observation_deadline
        ):
            raise ValueError("change resilience deadline MUST NOT precede prediction")
        if self.observed_at is not None:
            if self.predicted_at is None or self.observation_deadline is None:
                raise ValueError("change resilience observation requires a prediction window")
            if not self.predicted_at <= self.observed_at <= self.observation_deadline:
                raise ValueError("change resilience observation MUST fall inside its effect window")

    def to_mapping(self) -> dict[str, Any]:
        """Return the canonical mapping included in lineage identity and projections."""

        return {
            "execution_mode": self.execution_mode,
            "blast_radius_scope": self.blast_radius_scope,
            "blast_radius_count": self.blast_radius_count,
            "rollback_kind": self.rollback_kind,
            "verification_status": self.verification_status,
            "execution_outcome": self.execution_outcome,
            "predicted_at": self.predicted_at.isoformat() if self.predicted_at else None,
            "observation_deadline": (
                self.observation_deadline.isoformat() if self.observation_deadline else None
            ),
            "observed_at": self.observed_at.isoformat() if self.observed_at else None,
            "rollback_succeeded": self.rollback_succeeded,
        }


@dataclass(frozen=True, slots=True)
class ChangeLineageRecord:
    """Replay-stable evidence chain with no execution or promotion authority."""

    lineage_id: str
    change_id: str
    change_source: str
    change_ref: str
    correlation_id: str
    assessment_digest: str
    decision_case_id: str
    selected_option_id: str
    action_id: str
    event_id: str
    action_type_id: str
    target_digest: str
    outcome_id: str
    outcome_label: str
    change_at: datetime
    decision_at: datetime
    action_at: datetime
    outcome_at: datetime
    resilience: ChangeResilienceTrace
    evidence_refs: tuple[str, ...]
    execution_authority: bool = False
    promotion_authority: bool = False

    def __post_init__(self) -> None:
        text_values = (
            self.lineage_id,
            self.change_id,
            self.change_source,
            self.change_ref,
            self.correlation_id,
            self.assessment_digest,
            self.decision_case_id,
            self.selected_option_id,
            self.action_id,
            self.event_id,
            self.action_type_id,
            self.target_digest,
            self.outcome_id,
            self.outcome_label,
        )
        if any(not value.strip() for value in text_values):
            raise ValueError("change lineage identities MUST be non-empty")
        if any(
            value.tzinfo is None
            for value in (self.change_at, self.decision_at, self.action_at, self.outcome_at)
        ):
            raise ValueError("change lineage timestamps MUST be timezone-aware")
        if not self.change_at <= self.decision_at <= self.action_at <= self.outcome_at:
            raise ValueError("change lineage timestamps MUST preserve causal order")
        if not self.evidence_refs or self.evidence_refs != tuple(sorted(set(self.evidence_refs))):
            raise ValueError("change lineage evidence refs MUST be sorted and unique")
        if self.execution_authority or self.promotion_authority:
            raise ValueError("change lineage MUST NOT grant execution or promotion authority")

    def to_mapping(self) -> dict[str, Any]:
        """Return the bounded read-only projection used by replay consumers."""

        return {
            "lineage_id": self.lineage_id,
            "change_id": self.change_id,
            "change_source": self.change_source,
            "change_ref": self.change_ref,
            "correlation_id": self.correlation_id,
            "assessment_digest": self.assessment_digest,
            "decision_case_id": self.decision_case_id,
            "selected_option_id": self.selected_option_id,
            "action_id": self.action_id,
            "event_id": self.event_id,
            "action_type_id": self.action_type_id,
            "target_digest": self.target_digest,
            "outcome_id": self.outcome_id,
            "outcome_label": self.outcome_label,
            "change_at": self.change_at.isoformat(),
            "decision_at": self.decision_at.isoformat(),
            "action_at": self.action_at.isoformat(),
            "outcome_at": self.outcome_at.isoformat(),
            "resilience": self.resilience.to_mapping(),
            "evidence_refs": list(self.evidence_refs),
            "execution_authority": False,
            "promotion_authority": False,
        }


def build_change_lineage(
    *,
    change: ChangeRecord,
    assessment: ChangeAssessment,
    decision_case: DecisionCase,
    selection: DecisionSelection,
    action: Action,
    outcome: ResponseOutcome,
) -> ChangeLineageRecord:
    """Validate and join existing immutable records into one lineage."""

    if change.change_id != assessment.change_id or change.at != assessment.occurred_at:
        raise ValueError("change assessment does not match the canonical Change")
    if assessment.correlation_id != decision_case.correlation_id:
        raise ValueError("decision case correlation does not match the Change assessment")
    selected = next(
        (
            option
            for option in decision_case.options
            if option.option_id == selection.selected_option_id
        ),
        None,
    )
    if selected is None or selected.action_type is None:
        raise ValueError("change lineage requires one selected executable option")
    if selected.action_type != action.action_type:
        raise ValueError("selected option action type does not match the Action")
    if assessment.target_ref != action.target_resource_ref:
        raise ValueError("Change assessment target does not match the Action target")
    expected_target_digest = hashlib.sha256(action.target_resource_ref.encode()).hexdigest()
    if outcome.target_digest != expected_target_digest:
        raise ValueError("response outcome target does not match the Action target")
    if (
        outcome.action_id != action.action_id
        or outcome.event_id != action.event_id
        or outcome.action_type_id != action.action_type
        or outcome.execution_mode is not action.mode
    ):
        raise ValueError("response outcome identity does not match the Action")
    if action.created_at < decision_case.created_at or outcome.recorded_at < action.created_at:
        raise ValueError("change lineage records do not preserve causal order")

    evidence_refs = tuple(
        sorted(
            {
                f"change-assessment:{assessment.evidence_digest}",
                *decision_case.evidence_refs,
                *selected.evidence_refs,
                *outcome.evidence_refs,
            }
        )
    )
    resilience = ChangeResilienceTrace(
        execution_mode=action.mode.value,
        blast_radius_scope=action.blast_radius.scope.value,
        blast_radius_count=action.blast_radius.count,
        rollback_kind=action.rollback_ref.kind.value,
        verification_status=outcome.verification_status.value,
        execution_outcome=outcome.execution_outcome,
        predicted_at=outcome.predicted_at,
        observation_deadline=outcome.observation_deadline,
        observed_at=outcome.observed_at,
        rollback_succeeded=outcome.rollback_succeeded,
    )
    identity_material = {
        "change_id": change.change_id,
        "change_source": change.source,
        "change_ref": change.ref,
        "correlation_id": assessment.correlation_id,
        "assessment_digest": assessment.evidence_digest,
        "decision_case_id": decision_case.case_id,
        "selected_option_id": selected.option_id,
        "action_id": str(action.action_id),
        "event_id": str(action.event_id),
        "action_type_id": action.action_type,
        "target_digest": expected_target_digest,
        "outcome_id": str(outcome.outcome_id),
        "outcome_label": outcome.label.value,
        "resilience": resilience.to_mapping(),
        "evidence_refs": evidence_refs,
    }
    digest = hashlib.sha256(
        json.dumps(identity_material, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    return ChangeLineageRecord(
        lineage_id=f"change-lineage:{digest}",
        change_id=change.change_id,
        change_source=change.source,
        change_ref=change.ref,
        correlation_id=assessment.correlation_id,
        assessment_digest=assessment.evidence_digest,
        decision_case_id=decision_case.case_id,
        selected_option_id=selected.option_id,
        action_id=str(action.action_id),
        event_id=str(action.event_id),
        action_type_id=action.action_type,
        target_digest=expected_target_digest,
        outcome_id=str(outcome.outcome_id),
        outcome_label=outcome.label.value,
        change_at=change.at,
        decision_at=decision_case.created_at,
        action_at=action.created_at,
        outcome_at=outcome.recorded_at,
        resilience=resilience,
        evidence_refs=evidence_refs,
    )


__all__ = ["ChangeLineageRecord", "ChangeResilienceTrace", "build_change_lineage"]
