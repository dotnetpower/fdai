"""Change Safety classifier outcomes."""

from __future__ import annotations

import pytest
from fdai.core.verticals.change_safety import (
    ChangeContext,
    ChangeDecisionOutcome,
    ChangeRisk,
    ChangeSafetyClassifier,
    ChangeSafetyConfig,
)


def _ctx(
    *,
    is_reversible: bool = True,
    is_out_of_band: bool = False,
    env: str = "dev",
) -> ChangeContext:
    return ChangeContext(
        change_id="c-1",
        resource_id="res-1",
        is_reversible=is_reversible,
        is_out_of_band=is_out_of_band,
        target_environment=env,
    )


def test_low_risk_reversible_dev_change_auto_merges() -> None:
    classifier = ChangeSafetyClassifier()
    decision = classifier.classify(_ctx())
    assert decision.risk is ChangeRisk.LOW
    assert decision.outcome is ChangeDecisionOutcome.AUTO
    assert decision.reasons == ()


def test_production_change_forces_hil() -> None:
    classifier = ChangeSafetyClassifier()
    decision = classifier.classify(_ctx(env="prod"))
    assert decision.risk is ChangeRisk.HIGH
    assert decision.outcome is ChangeDecisionOutcome.HIL
    assert "production_environment:prod" in decision.reasons


def test_irreversible_change_forces_hil() -> None:
    classifier = ChangeSafetyClassifier()
    decision = classifier.classify(_ctx(is_reversible=False))
    assert decision.outcome is ChangeDecisionOutcome.HIL
    assert "irreversible_change" in decision.reasons


def test_out_of_band_change_forces_hil_even_if_reversible_dev() -> None:
    classifier = ChangeSafetyClassifier()
    decision = classifier.classify(_ctx(is_out_of_band=True))
    assert decision.outcome is ChangeDecisionOutcome.HIL
    assert "out_of_band_change" in decision.reasons


def test_reasons_accumulate_for_multiple_signals() -> None:
    classifier = ChangeSafetyClassifier()
    decision = classifier.classify(_ctx(is_reversible=False, is_out_of_band=True, env="prod"))
    assert decision.outcome is ChangeDecisionOutcome.HIL
    assert len(decision.reasons) == 3


def test_config_can_extend_production_set() -> None:
    classifier = ChangeSafetyClassifier(
        config=ChangeSafetyConfig(production_environments=frozenset({"prod", "canary"}))
    )
    decision = classifier.classify(_ctx(env="canary"))
    assert decision.outcome is ChangeDecisionOutcome.HIL


def test_record_terminal_produces_reject_record() -> None:
    classifier = ChangeSafetyClassifier()
    decision = classifier.record_terminal(
        change_id="c-1",
        outcome=ChangeDecisionOutcome.REJECT,
        reason="approval_rejected_by_operator",
    )
    assert decision.outcome is ChangeDecisionOutcome.REJECT
    assert decision.risk is ChangeRisk.HIGH


def test_record_terminal_produces_timeout_record() -> None:
    classifier = ChangeSafetyClassifier()
    decision = classifier.record_terminal(
        change_id="c-1",
        outcome=ChangeDecisionOutcome.TIMEOUT,
        reason="approval_window_expired",
    )
    assert decision.outcome is ChangeDecisionOutcome.TIMEOUT


def test_record_terminal_rejects_auto_or_hil_outcomes() -> None:
    classifier = ChangeSafetyClassifier()
    with pytest.raises(ValueError, match="REJECT / TIMEOUT"):
        classifier.record_terminal(
            change_id="c-1", outcome=ChangeDecisionOutcome.AUTO, reason="oops"
        )
    with pytest.raises(ValueError, match="REJECT / TIMEOUT"):
        classifier.record_terminal(
            change_id="c-1", outcome=ChangeDecisionOutcome.HIL, reason="oops"
        )
