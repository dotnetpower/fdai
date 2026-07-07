"""Unit tests for :mod:`aiopspilot.core.quality_gate.debate_router`."""

from __future__ import annotations

import pytest

from aiopspilot.core.quality_gate.debate_router import (
    DebateRoute,
    DebateRouterConfig,
    DebateRoutingDecision,
    decide_debate_route,
)
from aiopspilot.core.quality_gate.gate import QualityCandidate


def _candidate(action_type: str = "remediate.tag-add") -> QualityCandidate:
    return QualityCandidate(
        action_type=action_type,
        target_resource_ref="resource:example/rg/x",
        params={"tag_name": "owner"},
        cited_rule_ids=("rule.a",),
    )


class TestConfig:
    def test_overlapping_allow_and_deny_lists_are_rejected_at_construction(self) -> None:
        with pytest.raises(ValueError, match="disjoint"):
            DebateRouterConfig(
                always_for_action_types=("x", "y"),
                never_for_action_types=("y", "z"),
            )

    def test_default_config_enables_disagreement_routing(self) -> None:
        config = DebateRouterConfig()
        assert config.enabled is True
        assert config.on_cross_check_disagreement is True
        assert config.always_for_action_types == ()
        assert config.never_for_action_types == ()


class TestFailClosed:
    """Orchestrator unavailability MUST short-circuit to SKIP - this
    is the fail-closed invariant that keeps the router from asking
    the caller to route through a null orchestrator."""

    def test_orchestrator_unavailable_short_circuits_even_with_always_list(
        self,
    ) -> None:
        decision = decide_debate_route(
            candidate=_candidate("hot.action"),
            cross_check_disagreed=True,  # would otherwise trigger DEBATE
            orchestrator_available=False,
            config=DebateRouterConfig(always_for_action_types=("hot.action",)),
        )
        assert isinstance(decision, DebateRoutingDecision)
        assert decision.route is DebateRoute.SKIP
        assert decision.reason == "orchestrator_unavailable"
        assert decision.action_type == "hot.action"


class TestKillswitch:
    def test_disabled_config_short_circuits_regardless_of_disagreement(self) -> None:
        decision = decide_debate_route(
            candidate=_candidate(),
            cross_check_disagreed=True,
            orchestrator_available=True,
            config=DebateRouterConfig(enabled=False),
        )
        assert decision.route is DebateRoute.SKIP
        assert decision.reason == "disabled"

    def test_disabled_config_beats_always_list(self) -> None:
        """Killswitch must dominate the fork's allowlist - a fork
        that flips ``enabled=False`` during an incident MUST stop
        every debate call, not just the disagreement-triggered
        ones."""

        decision = decide_debate_route(
            candidate=_candidate("hot.action"),
            cross_check_disagreed=False,
            orchestrator_available=True,
            config=DebateRouterConfig(
                enabled=False,
                always_for_action_types=("hot.action",),
            ),
        )
        assert decision.route is DebateRoute.SKIP
        assert decision.reason == "disabled"


class TestActionTypeLists:
    def test_never_list_skips_even_on_disagreement(self) -> None:
        decision = decide_debate_route(
            candidate=_candidate("cheap.action"),
            cross_check_disagreed=True,
            orchestrator_available=True,
            config=DebateRouterConfig(never_for_action_types=("cheap.action",)),
        )
        assert decision.route is DebateRoute.SKIP
        assert decision.reason == "never_list"

    def test_always_list_debates_without_disagreement(self) -> None:
        decision = decide_debate_route(
            candidate=_candidate("high.severity.action"),
            cross_check_disagreed=False,
            orchestrator_available=True,
            config=DebateRouterConfig(
                always_for_action_types=("high.severity.action",),
            ),
        )
        assert decision.route is DebateRoute.DEBATE
        assert decision.reason == "always_list"


class TestDisagreementSignal:
    def test_default_config_debates_on_disagreement(self) -> None:
        decision = decide_debate_route(
            candidate=_candidate(),
            cross_check_disagreed=True,
            orchestrator_available=True,
        )
        assert decision.route is DebateRoute.DEBATE
        assert decision.reason == "cross_check_disagreement"

    def test_default_config_skips_when_agreed(self) -> None:
        decision = decide_debate_route(
            candidate=_candidate(),
            cross_check_disagreed=False,
            orchestrator_available=True,
        )
        assert decision.route is DebateRoute.SKIP
        assert decision.reason == "default_skip"

    def test_disagreement_axis_can_be_switched_off(self) -> None:
        """A fork that wants ONLY allowlist-based debate (never the
        disagreement trigger) can turn the axis off - useful for
        cost profiling."""

        decision = decide_debate_route(
            candidate=_candidate(),
            cross_check_disagreed=True,
            orchestrator_available=True,
            config=DebateRouterConfig(on_cross_check_disagreement=False),
        )
        assert decision.route is DebateRoute.SKIP
        assert decision.reason == "default_skip"


class TestActionTypeSnapshot:
    def test_decision_snapshots_action_type_verbatim(self) -> None:
        """``DebateRoutingDecision.action_type`` MUST carry the exact
        candidate ``action_type`` at decision time so a future rename
        never breaks a past audit entry."""

        candidate = _candidate("some.action.v1")
        decision = decide_debate_route(
            candidate=candidate,
            cross_check_disagreed=False,
            orchestrator_available=True,
        )
        assert decision.action_type == "some.action.v1"
