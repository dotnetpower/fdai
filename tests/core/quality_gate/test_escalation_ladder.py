"""EscalationLadder - pure policy for climbing to a stronger T2 model.

Mirrors the debate_router test posture: the ladder is a deterministic
function, so every branch of its precedence table is pinned here.
"""

from __future__ import annotations

import pytest

from fdai.core.quality_gate.escalation_ladder import (
    EscalationLadderConfig,
    EscalationRoute,
    EscalationTier,
    decide_escalation,
)
from fdai.core.quality_gate.gate import QualityCandidate


def _candidate(action_type: str = "remediate.tag-add") -> QualityCandidate:
    return QualityCandidate(
        action_type=action_type,
        target_resource_ref="rid-1",
        params={},
        cited_rule_ids=("r.known",),
    )


class TestEscalationLadderConfig:
    def test_rejects_overlapping_allow_deny(self) -> None:
        with pytest.raises(ValueError, match="disjoint"):
            EscalationLadderConfig(
                always_for_action_types=("a",),
                never_for_action_types=("a",),
            )

    def test_rejects_out_of_range_stability_threshold(self) -> None:
        with pytest.raises(ValueError, match=r"\[0.0, 1.0\]"):
            EscalationLadderConfig(on_self_consistency_below=1.5)

    def test_none_stability_threshold_is_allowed(self) -> None:
        cfg = EscalationLadderConfig(on_self_consistency_below=None)
        assert cfg.on_self_consistency_below is None


class TestFailClosed:
    def test_unavailable_escalated_model_stops(self) -> None:
        d = decide_escalation(
            candidate=_candidate(),
            cross_check_disagreed=True,
            escalated_available=False,
        )
        assert d.route is EscalationRoute.STOP
        assert d.reason == "escalated_model_unavailable"
        assert d.to_tier is None

    def test_killswitch_stops(self) -> None:
        d = decide_escalation(
            candidate=_candidate(),
            cross_check_disagreed=True,
            escalated_available=True,
            config=EscalationLadderConfig(enabled=False),
        )
        assert d.route is EscalationRoute.STOP
        assert d.reason == "disabled"


class TestCostBound:
    def test_at_ceiling_stops(self) -> None:
        d = decide_escalation(
            candidate=_candidate(),
            cross_check_disagreed=True,
            escalated_available=True,
            current_tier=EscalationTier.ESCALATED,
        )
        assert d.route is EscalationRoute.STOP
        assert d.reason == "at_ceiling"
        assert d.to_tier is None

    def test_single_rung_climb_from_secondary(self) -> None:
        d = decide_escalation(
            candidate=_candidate(),
            cross_check_disagreed=True,
            escalated_available=True,
            current_tier=EscalationTier.SECONDARY,
        )
        assert d.route is EscalationRoute.ESCALATE
        assert d.from_tier is EscalationTier.SECONDARY
        assert d.to_tier is EscalationTier.ESCALATED

    def test_single_rung_climb_from_primary(self) -> None:
        d = decide_escalation(
            candidate=_candidate(),
            cross_check_disagreed=True,
            escalated_available=True,
            current_tier=EscalationTier.PRIMARY,
        )
        assert d.to_tier is EscalationTier.SECONDARY  # one rung, never leapfrog


class TestTriggers:
    def test_disagreement_escalates(self) -> None:
        d = decide_escalation(
            candidate=_candidate(),
            cross_check_disagreed=True,
            escalated_available=True,
        )
        assert d.route is EscalationRoute.ESCALATE
        assert d.reason == "cross_check_disagreement"

    def test_disagreement_trigger_can_be_disabled(self) -> None:
        d = decide_escalation(
            candidate=_candidate(),
            cross_check_disagreed=True,
            escalated_available=True,
            config=EscalationLadderConfig(on_cross_check_disagreement=False),
        )
        assert d.route is EscalationRoute.STOP
        assert d.reason == "default_stop"

    def test_low_self_consistency_escalates_even_on_agreement(self) -> None:
        d = decide_escalation(
            candidate=_candidate(),
            cross_check_disagreed=False,
            escalated_available=True,
            self_consistency=0.4,
            config=EscalationLadderConfig(on_self_consistency_below=0.6),
        )
        assert d.route is EscalationRoute.ESCALATE
        assert d.reason == "low_self_consistency"

    def test_high_self_consistency_does_not_escalate(self) -> None:
        d = decide_escalation(
            candidate=_candidate(),
            cross_check_disagreed=False,
            escalated_available=True,
            self_consistency=0.9,
            config=EscalationLadderConfig(on_self_consistency_below=0.6),
        )
        assert d.route is EscalationRoute.STOP
        assert d.reason == "default_stop"

    def test_no_trigger_stops(self) -> None:
        d = decide_escalation(
            candidate=_candidate(),
            cross_check_disagreed=False,
            escalated_available=True,
        )
        assert d.route is EscalationRoute.STOP
        assert d.reason == "default_stop"


class TestAllowDenyLists:
    def test_always_list_escalates_without_disagreement(self) -> None:
        d = decide_escalation(
            candidate=_candidate("remediate.delete-resource"),
            cross_check_disagreed=False,
            escalated_available=True,
            config=EscalationLadderConfig(
                always_for_action_types=("remediate.delete-resource",)
            ),
        )
        assert d.route is EscalationRoute.ESCALATE
        assert d.reason == "always_list"

    def test_never_list_wins_over_disagreement(self) -> None:
        d = decide_escalation(
            candidate=_candidate("remediate.tag-add"),
            cross_check_disagreed=True,
            escalated_available=True,
            config=EscalationLadderConfig(never_for_action_types=("remediate.tag-add",)),
        )
        assert d.route is EscalationRoute.STOP
        assert d.reason == "never_list"

    def test_unavailable_beats_never_list(self) -> None:
        # fail-closed precedence sits above the deny list
        d = decide_escalation(
            candidate=_candidate("remediate.tag-add"),
            cross_check_disagreed=True,
            escalated_available=False,
            config=EscalationLadderConfig(never_for_action_types=("remediate.tag-add",)),
        )
        assert d.reason == "escalated_model_unavailable"


def test_decision_is_deterministic() -> None:
    kwargs = dict(
        candidate=_candidate(),
        cross_check_disagreed=True,
        escalated_available=True,
    )
    first = decide_escalation(**kwargs)  # type: ignore[arg-type]
    second = decide_escalation(**kwargs)  # type: ignore[arg-type]
    assert first == second
