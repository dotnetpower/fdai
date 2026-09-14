"""Consumer projection tests for non-terminal control-loop outcomes."""

from __future__ import annotations

from fdai.core.control_loop import ControlLoopOutcome, ControlLoopResult
from fdai.runtime.consumers import _authoritative_decision


def test_pending_execution_is_not_recorded_as_an_authoritative_abstention() -> None:
    result = ControlLoopResult(
        outcome=ControlLoopOutcome.EXECUTION_PENDING,
        tier="t0",
        decision="hold",
        resource_type="compute.vm",
    )

    assert _authoritative_decision(result) is None


def test_proven_no_effect_remains_an_authoritative_no_action_decision() -> None:
    result = ControlLoopResult(
        outcome=ControlLoopOutcome.EXECUTION_NOT_ATTEMPTED,
        tier="t0",
        decision="no-op",
        resource_type="compute.vm",
    )

    assert _authoritative_decision(result) == "abstain"
