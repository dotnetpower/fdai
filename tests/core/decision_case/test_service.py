from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fdai.core.decision_case import (
    ActionOption,
    ObjectiveEffect,
    build_decision_case,
    close_decision,
    select_action_option,
)
from fdai.core.operational_context import OperationalContextSnapshot
from fdai.shared.contracts.models import (
    Autonomy,
    Mode,
    ResponseOutcome,
    ResponseOutcomeLabel,
    ResponseVerificationStatus,
)

NOW = datetime(2026, 7, 31, tzinfo=UTC)


def _effect(objective: str, utility: float, metric: str) -> ObjectiveEffect:
    return ObjectiveEffect(
        objective_id=objective,
        utility=utility,
        confidence=0.9,
        metric=metric,
        expected_min=0.9,
        expected_max=1.0,
        observation_window_seconds=300,
    )


def _context() -> OperationalContextSnapshot:
    return OperationalContextSnapshot(
        snapshot_id="a" * 64,
        target_resource_id="resource-example",
        cutoff=NOW,
        recorded_at=NOW,
        catalog_versions=(("ontology", "1.0.0"),),
        service_ids=("service-example",),
        workload_ids=("workload-example",),
        objective_ids=("reliability", "cost"),
        constraint_ids=("constraint-private-network",),
        ownership_ids=("owner-example",),
        dependency_ids=(),
        stale_sources=(),
        conflicts=(),
        autonomy_ceiling=Autonomy.ENFORCE_AUTO,
    )


def test_cost_option_cannot_trade_away_protected_reliability() -> None:
    safe = ActionOption(
        option_id="scale-out",
        action_type="ops.scale-out",
        effects=(_effect("reliability", 0.8, "availability"), _effect("cost", -0.2, "usd")),
        evidence_refs=("forecast:capacity",),
    )
    unsafe_savings = ActionOption(
        option_id="scale-in",
        action_type="ops.scale-in",
        effects=(_effect("reliability", -0.4, "availability"), _effect("cost", 1.0, "usd")),
        evidence_refs=("forecast:cost",),
    )
    case = build_decision_case(
        correlation_id="correlation-example",
        context=_context(),
        created_at=NOW,
        no_action_effects=(_effect("reliability", -0.8, "availability"),),
        options=(unsafe_savings, safe),
        protected_objective_ids=("reliability",),
        evidence_refs=("forecast:capacity", "forecast:cost"),
    )

    selected = select_action_option(
        case,
        objective_weights={"reliability": 1.0, "cost": 0.7},
    )

    assert selected.selected_option_id == "scale-out"
    assert selected.requires_human_approval is False
    assert "scale-in:protected_objective" in selected.reason


def test_verified_response_outcome_closes_case_as_reusable() -> None:
    option = ActionOption(
        option_id="scale-out",
        action_type="ops.scale-out",
        effects=(_effect("reliability", 0.8, "availability"),),
        evidence_refs=("forecast:capacity",),
    )
    case = build_decision_case(
        correlation_id="correlation-example",
        context=_context(),
        created_at=NOW,
        no_action_effects=(_effect("reliability", -0.8, "availability"),),
        options=(option,),
        protected_objective_ids=("reliability",),
        evidence_refs=("forecast:capacity",),
    )
    selected = select_action_option(case, objective_weights={"reliability": 1.0})
    action_id = uuid4()
    outcome = ResponseOutcome(
        schema_version="1.0.0",
        outcome_id=uuid4(),
        idempotency_key=f"response-outcome:{action_id}",
        action_id=action_id,
        event_id=uuid4(),
        action_type_id="ops.scale-out",
        target_digest="a" * 64,
        prediction_id="prediction-example",
        metric="availability",
        expected_min=0.9,
        expected_max=1.0,
        observed_value=0.999,
        predicted_at=NOW,
        observation_deadline=NOW + timedelta(minutes=5),
        observed_at=NOW + timedelta(minutes=4),
        label=ResponseOutcomeLabel.VERIFIED,
        verification_status=ResponseVerificationStatus.VERIFIED,
        verification_reason="within_expected_range",
        execution_mode=Mode.ENFORCE,
        execution_outcome="success",
        decision="auto",
        rollback_succeeded=None,
        evidence_refs=("metric:availability",),
        recorded_at=NOW + timedelta(minutes=5),
    )

    closure = close_decision(case, selected, outcome)

    assert closure.effect_verified is True
    assert closure.guard_regression is False
    assert closure.reusable is True
