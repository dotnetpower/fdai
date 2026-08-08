"""FinOps guardrail decisions."""

from __future__ import annotations

import pytest
from fdai.core.verticals.cost_governance.finops import (
    FinOpsActionKind,
    FinOpsCandidate,
    FinOpsEnvironment,
    FinOpsGuard,
    FinOpsGuardConfig,
    FinOpsGuardOutcome,
    ResourceContext,
)


def _resource(
    *,
    env: FinOpsEnvironment = FinOpsEnvironment.DEV,
    tags: frozenset[str] = frozenset(),
    capacity: int = 3,
    dependents: tuple[str, ...] = (),
) -> ResourceContext:
    return ResourceContext(
        resource_id="res-1",
        environment=env,
        tags=tags,
        current_capacity=capacity,
        dependent_ids=dependents,
    )


def test_config_rejects_zero_min_capacity_floor() -> None:
    with pytest.raises(ValueError, match="min_capacity_floor"):
        FinOpsGuard(config=FinOpsGuardConfig(min_capacity_floor=0))


def test_allowed_when_dev_and_no_special_tags() -> None:
    guard = FinOpsGuard()
    decision = guard.evaluate(
        FinOpsCandidate(
            action_id="a-1",
            kind=FinOpsActionKind.RIGHT_SIZE,
            resource=_resource(),
            target_capacity=2,
        )
    )
    assert decision.outcome is FinOpsGuardOutcome.ALLOWED
    assert decision.reasons == ()


def test_exclusion_tag_blocks_all_kinds() -> None:
    guard = FinOpsGuard()
    for kind in FinOpsActionKind:
        decision = guard.evaluate(
            FinOpsCandidate(
                action_id=f"a-{kind}",
                kind=kind,
                resource=_resource(tags=frozenset({"finops:opt-out"})),
                target_capacity=2,
            )
        )
        assert decision.outcome is FinOpsGuardOutcome.REJECTED
        assert any("exclusion_tag:finops:opt-out" == r for r in decision.reasons)


def test_production_shutdown_is_blocked() -> None:
    guard = FinOpsGuard()
    decision = guard.evaluate(
        FinOpsCandidate(
            action_id="a-1",
            kind=FinOpsActionKind.SHUTDOWN,
            resource=_resource(env=FinOpsEnvironment.PROD),
        )
    )
    assert decision.outcome is FinOpsGuardOutcome.REJECTED
    assert any("production_environment_locked:prod" == r for r in decision.reasons)


def test_production_right_size_is_blocked() -> None:
    guard = FinOpsGuard()
    decision = guard.evaluate(
        FinOpsCandidate(
            action_id="a-1",
            kind=FinOpsActionKind.RIGHT_SIZE,
            resource=_resource(env=FinOpsEnvironment.PROD),
            target_capacity=2,
        )
    )
    assert decision.outcome is FinOpsGuardOutcome.REJECTED


def test_shutdown_with_dependents_is_blocked() -> None:
    guard = FinOpsGuard()
    decision = guard.evaluate(
        FinOpsCandidate(
            action_id="a-1",
            kind=FinOpsActionKind.SHUTDOWN,
            resource=_resource(dependents=("res-2", "res-3")),
        )
    )
    assert decision.outcome is FinOpsGuardOutcome.REJECTED
    assert any("shutdown_would_strand_dependents" in r for r in decision.reasons)


def test_right_size_missing_target_is_blocked() -> None:
    guard = FinOpsGuard()
    decision = guard.evaluate(
        FinOpsCandidate(
            action_id="a-1",
            kind=FinOpsActionKind.RIGHT_SIZE,
            resource=_resource(),
            target_capacity=None,
        )
    )
    assert decision.outcome is FinOpsGuardOutcome.REJECTED
    assert "right_size_missing_target_capacity" in decision.reasons


def test_right_size_below_floor_is_blocked() -> None:
    guard = FinOpsGuard(config=FinOpsGuardConfig(min_capacity_floor=2))
    decision = guard.evaluate(
        FinOpsCandidate(
            action_id="a-1",
            kind=FinOpsActionKind.RIGHT_SIZE,
            resource=_resource(),
            target_capacity=1,
        )
    )
    assert decision.outcome is FinOpsGuardOutcome.REJECTED
    assert any("min_capacity_floor=2" in r for r in decision.reasons)


def test_autoscale_adjust_allowed_in_prod_without_scale_down_guard() -> None:
    """AUTOSCALE_ADJUST is NOT a shutdown/right-size - it is a policy
    change. It bypasses the production-lock branch on purpose."""
    guard = FinOpsGuard()
    decision = guard.evaluate(
        FinOpsCandidate(
            action_id="a-1",
            kind=FinOpsActionKind.AUTOSCALE_ADJUST,
            resource=_resource(env=FinOpsEnvironment.PROD),
        )
    )
    assert decision.outcome is FinOpsGuardOutcome.ALLOWED


def test_evaluate_all_returns_one_decision_per_candidate() -> None:
    guard = FinOpsGuard()
    decisions = guard.evaluate_all(
        [
            FinOpsCandidate(
                action_id="a-1",
                kind=FinOpsActionKind.SHUTDOWN,
                resource=_resource(),
            ),
            FinOpsCandidate(
                action_id="a-2",
                kind=FinOpsActionKind.SHUTDOWN,
                resource=_resource(env=FinOpsEnvironment.PROD),
            ),
        ]
    )
    assert len(decisions) == 2
    assert decisions[0].outcome is FinOpsGuardOutcome.ALLOWED
    assert decisions[1].outcome is FinOpsGuardOutcome.REJECTED


def test_multiple_reasons_accumulate() -> None:
    guard = FinOpsGuard(config=FinOpsGuardConfig(min_capacity_floor=3))
    decision = guard.evaluate(
        FinOpsCandidate(
            action_id="a-1",
            kind=FinOpsActionKind.RIGHT_SIZE,
            resource=_resource(env=FinOpsEnvironment.PROD, tags=frozenset({"finops:opt-out"})),
            target_capacity=1,
        )
    )
    assert decision.outcome is FinOpsGuardOutcome.REJECTED
    # Exclusion + production + floor breach.
    assert len(decision.reasons) == 3
