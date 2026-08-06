"""Never-raising MSCP authority ceiling tests."""

from __future__ import annotations

import itertools

import pytest

from fdai.core.mscp_profile import (
    MscpAuthorityCeiling,
    MscpAuthorityReason,
    combine_mscp_authority,
)
from fdai.core.risk_gate.ceiling import AxisLevel
from fdai.core.risk_gate.evaluator import UnifiedRiskDecision, combine
from fdai.core.risk_gate.gate import RiskDecision, RiskDecisionOutcome
from fdai.shared.contracts.models import Mode


def _existing(level: AxisLevel) -> UnifiedRiskDecision:
    outcomes = {
        AxisLevel.ENFORCE_AUTO: (RiskDecisionOutcome.AUTO, Mode.ENFORCE),
        AxisLevel.ENFORCE_HIL: (RiskDecisionOutcome.HIL, Mode.ENFORCE),
        AxisLevel.SHADOW_ONLY: (RiskDecisionOutcome.AUTO, Mode.SHADOW),
        AxisLevel.DENY: (RiskDecisionOutcome.DENY, Mode.ENFORCE),
    }
    outcome, mode = outcomes[level]
    return combine(
        RiskDecision(
            outcome=outcome,
            action_id="action-1",
            effective_mode=mode,
        ),
        None,
    )


@pytest.mark.parametrize(
    ("existing_level", "ceiling"),
    tuple(itertools.product(AxisLevel, MscpAuthorityCeiling)),
)
def test_every_combination_preserves_or_lowers_existing_authority(
    existing_level: AxisLevel,
    ceiling: MscpAuthorityCeiling,
) -> None:
    existing = _existing(existing_level)

    result = combine_mscp_authority(
        existing,
        ceiling=ceiling,
        reason=MscpAuthorityReason.STRUCTURAL_HOLD,
    )

    assert result.level <= existing.level
    assert result.existing is existing
    assert result.lowered is (result.level < existing.level)


@pytest.mark.parametrize(
    ("ceiling", "expected"),
    [
        (MscpAuthorityCeiling.PRESERVE, AxisLevel.ENFORCE_AUTO),
        (MscpAuthorityCeiling.HUMAN_APPROVAL, AxisLevel.ENFORCE_HIL),
        (MscpAuthorityCeiling.HOLD, AxisLevel.SHADOW_ONLY),
        (MscpAuthorityCeiling.DENY, AxisLevel.DENY),
    ],
)
def test_ceiling_lowers_auto_to_declared_level(
    ceiling: MscpAuthorityCeiling,
    expected: AxisLevel,
) -> None:
    result = combine_mscp_authority(
        _existing(AxisLevel.ENFORCE_AUTO),
        ceiling=ceiling,
        reason=MscpAuthorityReason.CHECKS_PASSED,
    )

    assert result.level is expected


def test_audit_projection_preserves_both_decisions_and_profile_provenance() -> None:
    result = combine_mscp_authority(
        _existing(AxisLevel.ENFORCE_AUTO),
        ceiling=MscpAuthorityCeiling.HOLD,
        reason=MscpAuthorityReason.STRUCTURAL_HOLD,
    )

    assert result.as_audit_dict() == {
        "safety_profile": "mscp-operational-v1",
        "existing_decision": "auto",
        "ceiling": "hold",
        "reason": "structural_hold",
        "decision": "shadow",
        "lowered": True,
    }
