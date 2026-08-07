"""Replay and authority invariants for canonical Change lineage."""

from __future__ import annotations

import hashlib
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from fdai.core.change_lineage import build_change_lineage
from fdai.core.decision_case import (
    ActionOption,
    DecisionCase,
    DecisionSelection,
    ObjectiveEffect,
)
from fdai.core.impact_analysis import AffectedSet, ChangeAssessment
from fdai.shared.contracts.models import (
    Action,
    ActionStopCondition,
    BlastRadius,
    BlastRadiusScope,
    Mode,
    Operation,
    ResponseOutcome,
    ResponseOutcomeLabel,
    ResponseVerificationStatus,
    RollbackKind,
    RollbackRef,
    StopConditionKind,
)
from fdai.shared.providers.change_feed import ChangeRecord

NOW = datetime(2026, 8, 7, 8, 0, tzinfo=UTC)
ACTION_ID = UUID("00000000-0000-0000-0000-000000000201")
EVENT_ID = UUID("00000000-0000-0000-0000-000000000202")
OUTCOME_ID = UUID("00000000-0000-0000-0000-000000000203")


def _fixtures() -> tuple[
    ChangeRecord,
    ChangeAssessment,
    DecisionCase,
    DecisionSelection,
    Action,
    ResponseOutcome,
]:
    change = ChangeRecord(
        change_id="change-1",
        at=NOW,
        source="github",
        ref="commit:abc",
        summary="Scale the service",
        metadata={"environment": "dev"},
    )
    affected = AffectedSet(
        direct_targets=("resource:one",),
        runtime_dependents=(),
        protected_services=("service:one",),
        protected_objectives=("objective:availability",),
        control_dependencies=(),
        graph_revision="graph-1",
    )
    assessment = ChangeAssessment(
        change_id=change.change_id,
        correlation_id="correlation-1",
        target_ref="resource:one",
        occurred_at=change.at,
        affected_set=affected,
        review_required=False,
        reasons=(),
        evidence_digest="a" * 64,
    )
    effect = ObjectiveEffect(
        objective_id="objective:availability",
        utility=0.8,
        confidence=0.9,
        metric="availability",
        expected_min=0.99,
        expected_max=1.0,
        observation_window_seconds=300,
    )
    option = ActionOption(
        option_id="option:scale",
        action_type="ops.scale-out",
        effects=(effect,),
        evidence_refs=("evidence:option-b", "evidence:option-a"),
    )
    decision_case = DecisionCase(
        case_id="decision:1",
        correlation_id=assessment.correlation_id,
        context_snapshot_id="context:1",
        created_at=NOW + timedelta(seconds=1),
        no_action_effects=(replace(effect, utility=-0.8),),
        options=(option,),
        protected_objective_ids=(effect.objective_id,),
        active_constraint_ids=("constraint:one",),
        evidence_refs=("evidence:decision",),
    )
    selection = DecisionSelection(
        selected_option_id=option.option_id,
        objective_scores=((option.option_id, 0.8),),
        margin=0.8,
        requires_human_approval=False,
        reason="selected",
    )
    assert option.action_type is not None
    action = Action(
        schema_version="1.0.0",
        action_id=ACTION_ID,
        idempotency_key="action:1",
        event_id=EVENT_ID,
        action_type=option.action_type,
        target_resource_ref=assessment.target_ref,
        operation=Operation.SCALE,
        stop_condition=StopConditionKind.PROVIDER_API_ERROR_STREAK.value,
        stop_conditions=[
            ActionStopCondition(
                kind=StopConditionKind.PROVIDER_API_ERROR_STREAK,
                count=3,
            )
        ],
        rollback_ref=RollbackRef(kind=RollbackKind.SCRIPTED, reference="rollback:1"),
        blast_radius=BlastRadius(scope=BlastRadiusScope.RESOURCE, count=1),
        mode=Mode.SHADOW,
        citing_rules=["rule:scale"],
        created_at=NOW + timedelta(seconds=2),
    )
    outcome = ResponseOutcome(
        schema_version="1.0.0",
        outcome_id=OUTCOME_ID,
        idempotency_key="outcome:1",
        action_id=action.action_id,
        event_id=action.event_id,
        action_type_id=action.action_type,
        target_digest=hashlib.sha256(action.target_resource_ref.encode()).hexdigest(),
        label=ResponseOutcomeLabel.UNSCORABLE,
        verification_status=ResponseVerificationStatus.HOLD,
        verification_reason="shadow_only",
        execution_mode=action.mode,
        execution_outcome="shadowed",
        decision="auto",
        evidence_refs=("evidence:outcome",),
        recorded_at=NOW + timedelta(seconds=3),
    )
    return change, assessment, decision_case, selection, action, outcome


def test_builds_replay_stable_authority_free_lineage() -> None:
    change, assessment, decision_case, selection, action, outcome = _fixtures()

    first = build_change_lineage(
        change=change,
        assessment=assessment,
        decision_case=decision_case,
        selection=selection,
        action=action,
        outcome=outcome,
    )
    second = build_change_lineage(
        change=replace(change, metadata={"environment": "production"}),
        assessment=assessment,
        decision_case=replace(
            decision_case,
            evidence_refs=tuple(reversed(decision_case.evidence_refs)),
        ),
        selection=selection,
        action=action,
        outcome=outcome,
    )

    assert first == second
    assert first.lineage_id.startswith("change-lineage:")
    assert first.execution_authority is first.promotion_authority is False
    assert first.to_mapping()["execution_authority"] is False
    with pytest.raises(FrozenInstanceError):
        first.change_id = "other"  # type: ignore[misc]


def test_rejects_change_and_assessment_identity_mismatch() -> None:
    change, assessment, decision_case, selection, action, outcome = _fixtures()

    with pytest.raises(ValueError, match="canonical Change"):
        build_change_lineage(
            change=change,
            assessment=replace(assessment, change_id="change:other"),
            decision_case=decision_case,
            selection=selection,
            action=action,
            outcome=outcome,
        )


def test_rejects_decision_correlation_mismatch() -> None:
    change, assessment, decision_case, selection, action, outcome = _fixtures()

    with pytest.raises(ValueError, match="correlation"):
        build_change_lineage(
            change=change,
            assessment=assessment,
            decision_case=replace(decision_case, correlation_id="correlation:other"),
            selection=selection,
            action=action,
            outcome=outcome,
        )


def test_rejects_action_target_mismatch() -> None:
    change, assessment, decision_case, selection, action, outcome = _fixtures()

    with pytest.raises(ValueError, match="Action target"):
        build_change_lineage(
            change=change,
            assessment=assessment,
            decision_case=decision_case,
            selection=selection,
            action=action.model_copy(update={"target_resource_ref": "resource:other"}),
            outcome=outcome,
        )


def test_rejects_outcome_action_identity_mismatch() -> None:
    change, assessment, decision_case, selection, action, outcome = _fixtures()

    with pytest.raises(ValueError, match="identity"):
        build_change_lineage(
            change=change,
            assessment=assessment,
            decision_case=decision_case,
            selection=selection,
            action=action,
            outcome=outcome.model_copy(
                update={"action_id": UUID("00000000-0000-0000-0000-000000000299")}
            ),
        )


def test_rejects_target_digest_and_causal_time_mismatch() -> None:
    change, assessment, decision_case, selection, action, outcome = _fixtures()

    with pytest.raises(ValueError, match="response outcome target"):
        build_change_lineage(
            change=change,
            assessment=assessment,
            decision_case=decision_case,
            selection=selection,
            action=action,
            outcome=outcome.model_copy(update={"target_digest": "0" * 64}),
        )
    with pytest.raises(ValueError, match="causal order"):
        build_change_lineage(
            change=change,
            assessment=assessment,
            decision_case=decision_case,
            selection=selection,
            action=action.model_copy(update={"created_at": NOW - timedelta(seconds=1)}),
            outcome=outcome,
        )


def test_record_cannot_be_constructed_with_authority() -> None:
    change, assessment, decision_case, selection, action, outcome = _fixtures()
    lineage = build_change_lineage(
        change=change,
        assessment=assessment,
        decision_case=decision_case,
        selection=selection,
        action=action,
        outcome=outcome,
    )

    with pytest.raises(ValueError, match="MUST NOT grant"):
        replace(lineage, execution_authority=True)
