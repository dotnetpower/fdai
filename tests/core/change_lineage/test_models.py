"""Replay and authority invariants for canonical Change lineage."""

from __future__ import annotations

import hashlib
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from fdai.core.change_lineage import build_change_lineage, compute_change_lineage_id
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


def test_captures_resilience_trace_in_replay_identity() -> None:
    change, assessment, decision_case, selection, action, outcome = _fixtures()
    windowed_outcome = ResponseOutcome.model_validate(
        {
            **outcome.model_dump(),
            "prediction_id": "prediction:one",
            "metric": "availability",
            "expected_min": 0.99,
            "expected_max": 1.0,
            "predicted_at": action.created_at,
            "observation_deadline": action.created_at + timedelta(minutes=5),
            "execution_outcome": "rolled_back",
            "rollback_succeeded": True,
        }
    )

    baseline = build_change_lineage(
        change=change,
        assessment=assessment,
        decision_case=decision_case,
        selection=selection,
        action=action,
        outcome=outcome,
    )
    traced = build_change_lineage(
        change=change,
        assessment=assessment,
        decision_case=decision_case,
        selection=selection,
        action=action,
        outcome=windowed_outcome,
    )

    assert traced.resilience.execution_mode == "shadow"
    assert traced.resilience.blast_radius_scope == "resource"
    assert traced.resilience.blast_radius_count == 1
    assert traced.resilience.rollback_kind == "scripted"
    assert traced.resilience.verification_status == "hold"
    assert traced.resilience.execution_outcome == "rolled_back"
    assert traced.resilience.predicted_at == action.created_at
    assert traced.resilience.observation_deadline == action.created_at + timedelta(minutes=5)
    assert traced.resilience.observed_at is None
    assert traced.resilience.rollback_succeeded is True
    assert traced.lineage_id != baseline.lineage_id
    assert (
        traced.to_mapping()["resilience"]["observation_deadline"]
        == (action.created_at + timedelta(minutes=5)).isoformat()
    )


def test_rejects_outcome_prediction_not_declared_by_selected_effect() -> None:
    change, assessment, decision_case, selection, action, outcome = _fixtures()
    contradictory_outcome = ResponseOutcome.model_validate(
        {
            **outcome.model_dump(),
            "prediction_id": "prediction:one",
            "metric": "latency",
            "expected_min": 1.0,
            "expected_max": 2.0,
            "predicted_at": action.created_at,
            "observation_deadline": action.created_at + timedelta(minutes=1),
        }
    )

    with pytest.raises(ValueError, match="selected objective effect"):
        build_change_lineage(
            change=change,
            assessment=assessment,
            decision_case=decision_case,
            selection=selection,
            action=action,
            outcome=contradictory_outcome,
        )


def test_captures_decision_trace_in_replay_identity() -> None:
    change, assessment, decision_case, selection, action, outcome = _fixtures()

    baseline = build_change_lineage(
        change=change,
        assessment=assessment,
        decision_case=decision_case,
        selection=selection,
        action=action,
        outcome=outcome,
    )
    approval_required = build_change_lineage(
        change=change,
        assessment=assessment,
        decision_case=decision_case,
        selection=replace(
            selection,
            requires_human_approval=True,
            reason="selected after human review",
        ),
        action=action,
        outcome=outcome,
    )

    assert baseline.decision.context_snapshot_id == "context:1"
    assert baseline.decision.option_scores == (("option:scale", 0.8),)
    assert baseline.decision.margin == 0.8
    assert baseline.decision.requires_human_approval is False
    assert baseline.decision.reason == "selected"
    assert baseline.decision.protected_objective_ids == ("objective:availability",)
    assert baseline.decision.active_constraint_ids == ("constraint:one",)
    assert baseline.decision.selected_effects[0].objective_id == "objective:availability"
    assert baseline.decision.selected_effects[0].observation_window_seconds == 300
    assert approval_required.lineage_id != baseline.lineage_id
    assert approval_required.to_mapping()["decision"]["requires_human_approval"] is True


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


@pytest.mark.parametrize(
    "lineage_id",
    [
        "lineage:invalid",
        f"change-lineage:{'g' * 64}",
        f"change-lineage:{'A' * 64}",
        f"change-lineage:{'a' * 63}",
    ],
)
def test_record_rejects_noncanonical_lineage_id(lineage_id: str) -> None:
    change, assessment, decision_case, selection, action, outcome = _fixtures()
    lineage = build_change_lineage(
        change=change,
        assessment=assessment,
        decision_case=decision_case,
        selection=selection,
        action=action,
        outcome=outcome,
    )

    with pytest.raises(ValueError, match="lineage_id"):
        replace(lineage, lineage_id=lineage_id)


def test_record_rejects_lineage_digest_material_mismatch() -> None:
    change, assessment, decision_case, selection, action, outcome = _fixtures()
    lineage = build_change_lineage(
        change=change,
        assessment=assessment,
        decision_case=decision_case,
        selection=selection,
        action=action,
        outcome=outcome,
    )

    with pytest.raises(ValueError, match="identity material"):
        replace(lineage, lineage_id=f"change-lineage:{'f' * 64}")
    with pytest.raises(ValueError, match="identity material"):
        replace(lineage, action_type_id="ops.restart")
    with pytest.raises(ValueError, match="identity material"):
        replace(lineage, evidence_refs=(*lineage.evidence_refs, "evidence:z"))


def test_record_rejects_causal_timestamp_identity_mismatch() -> None:
    change, assessment, decision_case, selection, action, outcome = _fixtures()
    lineage = build_change_lineage(
        change=change,
        assessment=assessment,
        decision_case=decision_case,
        selection=selection,
        action=action,
        outcome=outcome,
    )

    with pytest.raises(ValueError, match="identity material"):
        replace(lineage, outcome_at=lineage.outcome_at + timedelta(seconds=1))


def test_record_requires_canonical_assessment_evidence_ref() -> None:
    change, assessment, decision_case, selection, action, outcome = _fixtures()
    lineage = build_change_lineage(
        change=change,
        assessment=assessment,
        decision_case=decision_case,
        selection=selection,
        action=action,
        outcome=outcome,
    )
    evidence_refs = tuple(
        ref for ref in lineage.evidence_refs if not ref.startswith("change-assessment:")
    )
    lineage_id = compute_change_lineage_id(
        change_id=lineage.change_id,
        change_source=lineage.change_source,
        change_ref=lineage.change_ref,
        correlation_id=lineage.correlation_id,
        assessment_digest=lineage.assessment_digest,
        decision_case_id=lineage.decision_case_id,
        selected_option_id=lineage.selected_option_id,
        action_id=lineage.action_id,
        event_id=lineage.event_id,
        action_type_id=lineage.action_type_id,
        target_digest=lineage.target_digest,
        outcome_id=lineage.outcome_id,
        outcome_label=lineage.outcome_label,
        change_at=lineage.change_at,
        decision_at=lineage.decision_at,
        action_at=lineage.action_at,
        outcome_at=lineage.outcome_at,
        decision=lineage.decision,
        resilience=lineage.resilience,
        evidence_refs=evidence_refs,
    )

    with pytest.raises(ValueError, match="assessment evidence"):
        replace(lineage, lineage_id=lineage_id, evidence_refs=evidence_refs)
