"""Tests for the read-only Operator Decision Queue projection and cost-of-delay ranking."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fdai.core.decision_case.decision_queue import (
    DecisionQueueApprovalControl,
    build_decision_queue_item,
    build_decision_queue_projection,
)
from fdai.core.decision_case.models import (
    ActionOption,
    DecisionCase,
    DecisionSelection,
    ObjectiveEffect,
)
from fdai.core.ontology_platform.decision_functions import (
    CostOfDelayEvidence,
    assess_cost_of_delay,
)

NOW = datetime(2026, 11, 4, 12, tzinfo=UTC)


def _case(case_id: str, *, confidence: float = 0.9, created_at: datetime = NOW) -> DecisionCase:
    effect = ObjectiveEffect(
        objective_id="objective.resilience.mttr",
        utility=0.8,
        confidence=confidence,
        metric="mttr_seconds",
        expected_min=-360.0,
        expected_max=-180.0,
        observation_window_seconds=1800,
    )
    baseline = ObjectiveEffect(
        objective_id="objective.resilience.mttr",
        utility=-0.5,
        confidence=0.95,
        metric="mttr_seconds",
        expected_min=0.0,
        expected_max=600.0,
        observation_window_seconds=1800,
    )
    option = ActionOption(
        option_id="opt-scale-in",
        action_type="ops.scale-in",
        effects=(effect,),
        evidence_refs=(f"evidence:{case_id}:option",),
    )
    return DecisionCase(
        case_id=case_id,
        correlation_id=f"corr-{case_id}",
        context_snapshot_id=f"snap-{case_id}",
        created_at=created_at,
        no_action_effects=(baseline,),
        options=(option,),
        protected_objective_ids=("objective.resilience.mttr",),
        active_constraint_ids=("constraint.change-window",),
        evidence_refs=(f"evidence:{case_id}:case",),
        process_id=f"proc-{case_id}",
    )


def _selection() -> DecisionSelection:
    return DecisionSelection(
        selected_option_id="opt-scale-in",
        objective_scores=(("opt-scale-in", 0.8),),
        margin=0.8,
        requires_human_approval=True,
        reason="highest_expected_utility",
    )


def _approval() -> DecisionQueueApprovalControl:
    return DecisionQueueApprovalControl(
        requires_human_approval=True,
        required_role="owner",
        quorum=2,
        no_self_approval=True,
    )


def test_decision_queue_ranks_by_cost_of_delay_signal_then_blast_radius() -> None:
    low_cost = assess_cost_of_delay(
        CostOfDelayEvidence(Decimal("15"), "USD", "basis:low", NOW),
        target_ref="res-low",
        delay_hours=4,
    )
    high_cost = assess_cost_of_delay(
        CostOfDelayEvidence(Decimal("120"), "USD", "basis:high", NOW),
        target_ref="res-high",
        delay_hours=4,
    )
    unobserved_cost = assess_cost_of_delay(
        CostOfDelayEvidence(None, None, "basis:none", NOW),
        target_ref="res-unpriced",
        delay_hours=4,
    )

    item_low = build_decision_queue_item(
        case=_case("case-low", confidence=0.85, created_at=NOW - timedelta(minutes=10)),
        selection=_selection(),
        target_resource_ref="res-low",
        approval_control=_approval(),
        blast_radius_tier="medium",
        change_risk_tier="low",
        cost_of_delay_reading=low_cost,
    )
    item_high = build_decision_queue_item(
        case=_case("case-high", confidence=0.92, created_at=NOW - timedelta(minutes=2)),
        selection=_selection(),
        target_resource_ref="res-high",
        approval_control=_approval(),
        blast_radius_tier="low",
        change_risk_tier="low",
        cost_of_delay_reading=high_cost,
    )
    item_unpriced_critical = build_decision_queue_item(
        case=_case("case-unpriced-crit", confidence=0.75, created_at=NOW - timedelta(minutes=1)),
        selection=_selection(),
        target_resource_ref="res-unpriced-crit",
        approval_control=_approval(),
        blast_radius_tier="critical",
        change_risk_tier="medium",
        cost_of_delay_reading=unobserved_cost,
    )
    item_unpriced_low = build_decision_queue_item(
        case=_case("case-unpriced-low", confidence=0.80, created_at=NOW - timedelta(minutes=20)),
        selection=_selection(),
        target_resource_ref="res-unpriced-low",
        approval_control=_approval(),
        blast_radius_tier="low",
        change_risk_tier="low",
        cost_of_delay_reading=None,
    )

    queue = build_decision_queue_projection(
        (item_unpriced_low, item_low, item_unpriced_critical, item_high),
        as_of=NOW,
    )

    assert queue.read_only is True
    assert queue.execution_authority is False
    assert queue.ranking_currency == "USD"
    assert [item.case_id for item in queue.items] == [
        "case-high",
        "case-low",
        "case-unpriced-crit",
        "case-unpriced-low",
    ]
    assert queue.items[0].cost_of_delay_amount == Decimal("480")
    assert queue.items[0].uncertainty == pytest.approx(0.08)
    assert queue.items[0].approval_control.quorum == 2
    assert queue.projection_digest.startswith("sha256:")


def test_decision_queue_is_order_independent_and_rejects_duplicate_cases() -> None:
    item_a = build_decision_queue_item(
        case=_case("case-a"),
        selection=_selection(),
        target_resource_ref="res-a",
        approval_control=_approval(),
    )
    item_b = build_decision_queue_item(
        case=_case("case-b"),
        selection=_selection(),
        target_resource_ref="res-b",
        approval_control=_approval(),
    )
    first = build_decision_queue_projection((item_a, item_b), as_of=NOW)
    second = build_decision_queue_projection((item_b, item_a), as_of=NOW)
    assert first.projection_digest == second.projection_digest

    with pytest.raises(ValueError, match="MUST be unique"):
        build_decision_queue_projection((item_a, item_a), as_of=NOW)
