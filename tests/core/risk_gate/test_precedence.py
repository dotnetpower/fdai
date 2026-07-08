"""PrecedenceResolver - cross-vertical conflict handling."""

from __future__ import annotations

import pytest

from fdai.core.risk_gate import (
    CandidateAction,
    PrecedenceOutcome,
    PrecedenceResolver,
    Vertical,
)


def _c(
    *,
    action_id: str,
    vertical: Vertical,
    resource_id: str = "res-1",
    deferrable: bool = True,
) -> CandidateAction:
    return CandidateAction(
        action_id=action_id,
        resource_id=resource_id,
        vertical=vertical,
        deferrable=deferrable,
    )


def test_single_candidate_always_wins() -> None:
    resolver = PrecedenceResolver()
    decisions = resolver.resolve([_c(action_id="a1", vertical=Vertical.COST)])
    assert len(decisions) == 1
    assert decisions[0].outcome is PrecedenceOutcome.WIN


def test_resilience_safety_hold_beats_change_safety_and_cost() -> None:
    resolver = PrecedenceResolver()
    decisions = resolver.resolve(
        [
            _c(action_id="cost", vertical=Vertical.COST),
            _c(action_id="change", vertical=Vertical.CHANGE_SAFETY),
            _c(action_id="hold", vertical=Vertical.RESILIENCE_SAFETY_HOLD),
        ]
    )
    winners = [d for d in decisions if d.outcome is PrecedenceOutcome.WIN]
    losers = [d for d in decisions if d.outcome is PrecedenceOutcome.DEFER]
    assert len(winners) == 1
    assert winners[0].action_id == "hold"
    assert {d.action_id for d in losers} == {"cost", "change"}


def test_change_safety_beats_cost() -> None:
    resolver = PrecedenceResolver()
    decisions = resolver.resolve(
        [
            _c(action_id="cost", vertical=Vertical.COST),
            _c(action_id="change", vertical=Vertical.CHANGE_SAFETY),
        ]
    )
    winner = next(d for d in decisions if d.outcome is PrecedenceOutcome.WIN)
    loser = next(d for d in decisions if d.outcome is PrecedenceOutcome.DEFER)
    assert winner.action_id == "change"
    assert loser.action_id == "cost"


def test_resilience_beats_change_safety() -> None:
    resolver = PrecedenceResolver()
    decisions = resolver.resolve(
        [
            _c(action_id="dr", vertical=Vertical.RESILIENCE),
            _c(action_id="change", vertical=Vertical.CHANGE_SAFETY),
        ]
    )
    winner = next(d for d in decisions if d.outcome is PrecedenceOutcome.WIN)
    assert winner.vertical is Vertical.RESILIENCE


def test_non_deferrable_loser_escalates_to_hil() -> None:
    resolver = PrecedenceResolver()
    decisions = resolver.resolve(
        [
            _c(action_id="dr", vertical=Vertical.RESILIENCE),
            _c(
                action_id="change-must-run",
                vertical=Vertical.CHANGE_SAFETY,
                deferrable=False,
            ),
        ]
    )
    loser = next(d for d in decisions if d.action_id == "change-must-run")
    assert loser.outcome is PrecedenceOutcome.ESCALATE_HIL
    assert "not_safely_deferrable" in loser.reasons


def test_candidates_on_distinct_resources_all_win() -> None:
    resolver = PrecedenceResolver()
    decisions = resolver.resolve(
        [
            _c(action_id="a", vertical=Vertical.COST, resource_id="res-a"),
            _c(action_id="b", vertical=Vertical.COST, resource_id="res-b"),
            _c(action_id="c", vertical=Vertical.COST, resource_id="res-c"),
        ]
    )
    assert all(d.outcome is PrecedenceOutcome.WIN for d in decisions)


def test_deterministic_tie_break_within_same_vertical() -> None:
    """Two Change-Safety actions on one resource → alphabetical action_id wins."""
    resolver = PrecedenceResolver()
    decisions = resolver.resolve(
        [
            _c(action_id="zebra", vertical=Vertical.CHANGE_SAFETY),
            _c(action_id="alpha", vertical=Vertical.CHANGE_SAFETY),
        ]
    )
    winner = next(d for d in decisions if d.outcome is PrecedenceOutcome.WIN)
    # Tie broken by the SMALLEST (earliest) action_id → 'alpha' wins.
    assert winner.action_id == "alpha"


def test_precedence_decision_is_immutable() -> None:
    resolver = PrecedenceResolver()
    decision = resolver.resolve([_c(action_id="a", vertical=Vertical.COST)])[0]
    with pytest.raises((AttributeError, TypeError)):
        decision.outcome = PrecedenceOutcome.DEFER  # type: ignore[misc]


def test_reasons_carry_conflict_context_on_defer() -> None:
    resolver = PrecedenceResolver()
    decisions = resolver.resolve(
        [
            _c(action_id="cost", vertical=Vertical.COST),
            _c(action_id="dr", vertical=Vertical.RESILIENCE),
        ]
    )
    loser = next(d for d in decisions if d.outcome is PrecedenceOutcome.DEFER)
    assert any("winner_action_id=dr" in r for r in loser.reasons)
