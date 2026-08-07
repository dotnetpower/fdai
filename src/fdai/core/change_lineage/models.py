"""Immutable lineage joining one canonical Change to its observed outcome."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fdai.core.decision_case import DecisionCase, DecisionSelection, ObjectiveEffect
from fdai.core.impact_analysis import ChangeAssessment
from fdai.shared.contracts.models import Action, ResponseOutcome
from fdai.shared.providers.change_feed import ChangeRecord

from .traces import ChangeDecisionTrace, ChangeObjectiveTrace, ChangeResilienceTrace

_LINEAGE_PREFIX = "change-lineage:"


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
    decision: ChangeDecisionTrace
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
        lineage_digest = self.lineage_id.removeprefix(_LINEAGE_PREFIX)
        if (
            not self.lineage_id.startswith(_LINEAGE_PREFIX)
            or len(lineage_digest) != 64
            or any(character not in "0123456789abcdef" for character in lineage_digest)
        ):
            raise ValueError("change lineage lineage_id MUST contain a lowercase SHA-256 digest")
        expected_lineage_id = compute_change_lineage_id(
            change_id=self.change_id,
            change_source=self.change_source,
            change_ref=self.change_ref,
            correlation_id=self.correlation_id,
            assessment_digest=self.assessment_digest,
            decision_case_id=self.decision_case_id,
            selected_option_id=self.selected_option_id,
            action_id=self.action_id,
            event_id=self.event_id,
            action_type_id=self.action_type_id,
            target_digest=self.target_digest,
            outcome_id=self.outcome_id,
            outcome_label=self.outcome_label,
            change_at=self.change_at,
            decision_at=self.decision_at,
            action_at=self.action_at,
            outcome_at=self.outcome_at,
            decision=self.decision,
            resilience=self.resilience,
            evidence_refs=self.evidence_refs,
        )
        if self.lineage_id != expected_lineage_id:
            raise ValueError("change lineage lineage_id does not match its identity material")
        if any(
            value.tzinfo is None
            for value in (self.change_at, self.decision_at, self.action_at, self.outcome_at)
        ):
            raise ValueError("change lineage timestamps MUST be timezone-aware")
        if not self.change_at <= self.decision_at <= self.action_at <= self.outcome_at:
            raise ValueError("change lineage timestamps MUST preserve causal order")
        if not self.evidence_refs or self.evidence_refs != tuple(sorted(set(self.evidence_refs))):
            raise ValueError("change lineage evidence refs MUST be sorted and unique")
        assessment_evidence_ref = f"change-assessment:{self.assessment_digest}"
        if assessment_evidence_ref not in self.evidence_refs:
            raise ValueError("change lineage MUST retain its canonical assessment evidence ref")
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
            "decision": self.decision.to_mapping(),
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
    if outcome.prediction_id is not None and not _matches_selected_effect(
        outcome,
        selected.effects,
    ):
        raise ValueError("response outcome prediction does not match a selected objective effect")
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
    decision = ChangeDecisionTrace(
        context_snapshot_id=decision_case.context_snapshot_id,
        selected_option_id=selected.option_id,
        option_scores=tuple(sorted(selection.objective_scores)),
        margin=selection.margin,
        requires_human_approval=selection.requires_human_approval,
        reason=selection.reason,
        protected_objective_ids=tuple(sorted(set(decision_case.protected_objective_ids))),
        active_constraint_ids=tuple(sorted(set(decision_case.active_constraint_ids))),
        selected_effects=tuple(
            sorted(
                (_objective_trace(effect) for effect in selected.effects),
                key=lambda effect: effect.objective_id,
            )
        ),
        violated_constraint_ids=tuple(sorted(set(selected.violated_constraint_ids))),
        proposing_agents=tuple(sorted(set(selected.proposing_agents))),
        logic_receipt_refs=tuple(sorted(set(selected.logic_receipt_refs))),
        simulation_receipt_refs=tuple(sorted(set(selected.simulation_receipt_refs))),
        constraint_evaluation_refs=tuple(sorted(set(selected.constraint_evaluation_refs))),
        assumptions=tuple(sorted(set(selected.assumptions))),
        process_id=decision_case.process_id,
        logic_release_digest=decision_case.logic_release_digest,
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
    lineage_id = compute_change_lineage_id(
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
        decision=decision,
        resilience=resilience,
        evidence_refs=evidence_refs,
    )
    return ChangeLineageRecord(
        lineage_id=lineage_id,
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
        decision=decision,
        resilience=resilience,
        evidence_refs=evidence_refs,
    )


def _objective_trace(effect: ObjectiveEffect) -> ChangeObjectiveTrace:
    return ChangeObjectiveTrace(
        objective_id=effect.objective_id,
        utility=effect.utility,
        confidence=effect.confidence,
        metric=effect.metric,
        expected_min=effect.expected_min,
        expected_max=effect.expected_max,
        observation_window_seconds=effect.observation_window_seconds,
    )


def _matches_selected_effect(
    outcome: ResponseOutcome,
    effects: tuple[ObjectiveEffect, ...],
) -> bool:
    if outcome.predicted_at is None or outcome.observation_deadline is None:
        return False
    observation_window_seconds = int(
        (outcome.observation_deadline - outcome.predicted_at).total_seconds()
    )
    return any(
        effect.metric == outcome.metric
        and effect.expected_min == outcome.expected_min
        and effect.expected_max == outcome.expected_max
        and effect.observation_window_seconds == observation_window_seconds
        for effect in effects
    )


def compute_change_lineage_id(
    *,
    change_id: str,
    change_source: str,
    change_ref: str,
    correlation_id: str,
    assessment_digest: str,
    decision_case_id: str,
    selected_option_id: str,
    action_id: str,
    event_id: str,
    action_type_id: str,
    target_digest: str,
    outcome_id: str,
    outcome_label: str,
    change_at: datetime,
    decision_at: datetime,
    action_at: datetime,
    outcome_at: datetime,
    decision: ChangeDecisionTrace,
    resilience: ChangeResilienceTrace,
    evidence_refs: tuple[str, ...],
) -> str:
    """Return the canonical content-bound identity for one lineage record."""

    identity_material = {
        "change_id": change_id,
        "change_source": change_source,
        "change_ref": change_ref,
        "correlation_id": correlation_id,
        "assessment_digest": assessment_digest,
        "decision_case_id": decision_case_id,
        "selected_option_id": selected_option_id,
        "action_id": action_id,
        "event_id": event_id,
        "action_type_id": action_type_id,
        "target_digest": target_digest,
        "outcome_id": outcome_id,
        "outcome_label": outcome_label,
        "change_at": change_at.isoformat(),
        "decision_at": decision_at.isoformat(),
        "action_at": action_at.isoformat(),
        "outcome_at": outcome_at.isoformat(),
        "decision": decision.to_mapping(),
        "resilience": resilience.to_mapping(),
        "evidence_refs": evidence_refs,
    }
    digest = hashlib.sha256(
        json.dumps(identity_material, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    return f"{_LINEAGE_PREFIX}{digest}"


__all__ = [
    "ChangeDecisionTrace",
    "ChangeLineageRecord",
    "ChangeObjectiveTrace",
    "ChangeResilienceTrace",
    "build_change_lineage",
    "compute_change_lineage_id",
]
