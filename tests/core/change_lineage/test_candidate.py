"""Candidate-only learning boundaries for canonical Change lineage."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta

import pytest

from fdai.core.change_lineage import (
    ChangeDecisionTrace,
    ChangeLineageRecord,
    ChangeObjectiveTrace,
    ChangeResilienceTrace,
    compute_change_lineage_id,
    extract_learning_candidate,
)

NOW = datetime(2026, 8, 7, 8, 0, tzinfo=UTC)


def _lineage() -> ChangeLineageRecord:
    effect = ChangeObjectiveTrace(
        objective_id="objective:availability",
        utility=0.8,
        confidence=0.9,
        metric="availability",
        expected_min=0.99,
        expected_max=1.0,
        observation_window_seconds=300,
    )
    decision = ChangeDecisionTrace(
        context_snapshot_id="context:one",
        selected_option_id="option:scale",
        option_scores=(("option:scale", 0.8),),
        margin=0.8,
        requires_human_approval=False,
        reason="selected",
        protected_objective_ids=(effect.objective_id,),
        active_constraint_ids=("constraint:one",),
        selected_effects=(effect,),
        violated_constraint_ids=(),
        proposing_agents=("forseti",),
        logic_receipt_refs=("logic:one",),
        simulation_receipt_refs=("simulation:one",),
        constraint_evaluation_refs=("constraint-evaluation:one",),
        assumptions=(),
        process_id=None,
        logic_release_digest="b" * 64,
    )
    resilience = ChangeResilienceTrace(
        execution_mode="shadow",
        blast_radius_scope="resource",
        blast_radius_count=1,
        rollback_kind="scripted",
        verification_status="hold",
        execution_outcome="shadowed",
        predicted_at=None,
        observation_deadline=None,
        observed_at=None,
        rollback_succeeded=None,
    )
    evidence_refs = ("evidence:one", "evidence:two")
    lineage_id = compute_change_lineage_id(
        change_id="change:one",
        change_source="github",
        change_ref="commit:abc",
        correlation_id="correlation:one",
        assessment_digest="c" * 64,
        decision_case_id="decision:one",
        selected_option_id=decision.selected_option_id,
        action_id="action:one",
        event_id="event:one",
        action_type_id="ops.scale-out",
        target_digest="d" * 64,
        outcome_id="outcome:one",
        outcome_label="unscorable",
        decision=decision,
        resilience=resilience,
        evidence_refs=evidence_refs,
    )
    return ChangeLineageRecord(
        lineage_id=lineage_id,
        change_id="change:one",
        change_source="github",
        change_ref="commit:abc",
        correlation_id="correlation:one",
        assessment_digest="c" * 64,
        decision_case_id="decision:one",
        selected_option_id=decision.selected_option_id,
        action_id="action:one",
        event_id="event:one",
        action_type_id="ops.scale-out",
        target_digest="d" * 64,
        outcome_id="outcome:one",
        outcome_label="unscorable",
        change_at=NOW,
        decision_at=NOW + timedelta(seconds=1),
        action_at=NOW + timedelta(seconds=2),
        outcome_at=NOW + timedelta(seconds=3),
        decision=decision,
        resilience=resilience,
        evidence_refs=evidence_refs,
    )


def test_extracts_deterministic_sealed_case_gated_candidate() -> None:
    lineage = _lineage()

    first = extract_learning_candidate(lineage)
    second = extract_learning_candidate(lineage)

    assert first == second
    assert first.candidate_id.startswith("change-learning-candidate:")
    assert first.lineage_id == lineage.lineage_id
    assert first.change_source == "github"
    assert first.action_type_id == "ops.scale-out"
    assert first.selected_objective_ids == ("objective:availability",)
    assert first.outcome_label == "unscorable"
    assert first.verification_status == "hold"
    assert first.execution_mode == "shadow"
    assert first.candidate_only is first.requires_sealed_case is True
    assert first.execution_authority is first.promotion_authority is False
    assert first.to_mapping()["operational_reuse_eligible"] is False
    with pytest.raises(FrozenInstanceError):
        first.action_type_id = "ops.restart"  # type: ignore[misc]


def test_candidate_identity_binds_lineage_and_evidence() -> None:
    lineage = _lineage()

    with pytest.raises(ValueError, match="identity material"):
        replace(lineage, lineage_id=f"change-lineage:{'f' * 64}")
    with pytest.raises(ValueError, match="identity material"):
        replace(lineage, evidence_refs=("evidence:one", "evidence:three"))


def test_candidate_cannot_bypass_learning_or_authority_gates() -> None:
    candidate = extract_learning_candidate(_lineage())

    with pytest.raises(ValueError, match="candidate-only"):
        replace(candidate, candidate_only=False)
    with pytest.raises(ValueError, match="candidate-only"):
        replace(candidate, requires_sealed_case=False)
    with pytest.raises(ValueError, match="candidate-only"):
        replace(candidate, operational_reuse_eligible=True)
    with pytest.raises(ValueError, match="candidate-only"):
        replace(candidate, execution_authority=True)
    with pytest.raises(ValueError, match="candidate-only"):
        replace(candidate, promotion_authority=True)
