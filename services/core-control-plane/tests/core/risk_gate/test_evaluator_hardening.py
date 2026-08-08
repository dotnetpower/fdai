from __future__ import annotations

from dataclasses import replace

import pytest
from fdai.core.risk_gate.ceiling import AxisLevel
from fdai.core.risk_gate.evaluator import combine
from fdai.core.risk_gate.gate import RiskDecision, RiskDecisionOutcome
from fdai.shared.contracts.models import Mode

from tests.core.risk_gate.test_evaluator import _authority


@pytest.mark.parametrize(
    ("outcome", "mode", "gate_level"),
    [
        (RiskDecisionOutcome.DENY, Mode.ENFORCE, AxisLevel.DENY),
        (RiskDecisionOutcome.HIL, Mode.ENFORCE, AxisLevel.ENFORCE_HIL),
        (RiskDecisionOutcome.ABSTAIN, Mode.ENFORCE, AxisLevel.ENFORCE_HIL),
        (RiskDecisionOutcome.AUTO, Mode.SHADOW, AxisLevel.SHADOW_ONLY),
        (RiskDecisionOutcome.AUTO, Mode.ENFORCE, AxisLevel.ENFORCE_AUTO),
    ],
)
@pytest.mark.parametrize("authority_level", list(AxisLevel))
def test_combination_never_exceeds_either_decision(
    outcome: RiskDecisionOutcome,
    mode: Mode,
    gate_level: AxisLevel,
    authority_level: AxisLevel,
) -> None:
    gate = RiskDecision(outcome=outcome, action_id="a1", effective_mode=mode)
    authority = replace(_authority("auto"), final_level=authority_level)

    result = combine(gate, authority)

    assert result.level is min(gate_level, authority_level)
    assert (
        result.decision
        == {
            AxisLevel.DENY: "deny",
            AxisLevel.SHADOW_ONLY: "shadow",
            AxisLevel.ENFORCE_HIL: "hil",
            AxisLevel.ENFORCE_AUTO: "auto",
        }[result.level]
    )
    assert result.is_auto is (result.level is AxisLevel.ENFORCE_AUTO)
    assert result.requires_hil is (result.level is AxisLevel.ENFORCE_HIL)
    assert result.is_denied is (result.level is AxisLevel.DENY)
    assert result.as_audit_dict()["decision"] == result.decision
