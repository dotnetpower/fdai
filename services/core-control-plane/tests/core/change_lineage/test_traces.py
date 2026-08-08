"""Boundary validation for immutable Change lineage trace values."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.change_lineage import (
    ChangeDecisionTrace,
    ChangeObjectiveTrace,
    ChangeResilienceTrace,
)

NOW = datetime(2026, 8, 7, 8, 0, tzinfo=UTC)


def _resilience_trace() -> ChangeResilienceTrace:
    return ChangeResilienceTrace(
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


def _decision_trace() -> ChangeDecisionTrace:
    effect = ChangeObjectiveTrace(
        objective_id="objective:availability",
        utility=0.8,
        confidence=0.9,
        metric="availability",
        expected_min=0.99,
        expected_max=1.0,
        observation_window_seconds=300,
    )
    return ChangeDecisionTrace(
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
        proposing_agents=(),
        logic_receipt_refs=(),
        simulation_receipt_refs=(),
        constraint_evaluation_refs=(),
        assumptions=(),
        process_id=None,
        logic_release_digest=None,
    )


def test_resilience_trace_rejects_invalid_observation_windows() -> None:
    trace = _resilience_trace()

    with pytest.raises(ValueError, match="timezone-aware"):
        replace(trace, predicted_at=NOW.replace(tzinfo=None))
    with pytest.raises(ValueError, match="supplied together"):
        replace(trace, predicted_at=NOW)
    with pytest.raises(ValueError, match="MUST NOT precede"):
        replace(
            trace,
            predicted_at=NOW + timedelta(minutes=1),
            observation_deadline=NOW,
        )
    with pytest.raises(ValueError, match="requires a prediction window"):
        replace(trace, observed_at=NOW)


def test_decision_trace_rejects_duplicate_score_identity() -> None:
    trace = _decision_trace()

    with pytest.raises(ValueError, match="option scores"):
        replace(
            trace,
            option_scores=(
                ("option:scale", 0.8),
                ("option:scale", 0.7),
            ),
        )
