"""Validation edge cases for the IRP models + coordinator + HIL gate."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from fdai.core.irp import (
    Alert,
    HilChannelApprovalGate,
    PlanRequirement,
    RequirementKind,
    ResponsePlan,
    ResponseStep,
)
from fdai.shared.providers.testing.hil_channel import InMemoryHilChannel

_T = datetime(2026, 7, 10, tzinfo=UTC)


def test_response_step_rejects_empty_ids() -> None:
    with pytest.raises(ValueError, match="step_id"):
        ResponseStep(step_id="", action_ref="a", description="d")
    with pytest.raises(ValueError, match="action_ref"):
        ResponseStep(step_id="s", action_ref="", description="d")


def _plan(**overrides: object) -> ResponsePlan:
    base = {
        "plan_id": "p",
        "name": "n",
        "trigger_signal": "sig",
        "steps": (ResponseStep(step_id="s", action_ref="a", description="d"),),
        "requirements": (PlanRequirement(kind=RequirementKind.STOP_CONDITION, description="d"),),
        "approver_role": "approver",
        "notify_channels": ("teams://x",),
        "created_by": "op",
        "created_at": _T,
    }
    base.update(overrides)
    return ResponsePlan(**base)  # type: ignore[arg-type]


def test_response_plan_rejects_empty_plan_id() -> None:
    with pytest.raises(ValueError, match="plan_id"):
        _plan(plan_id="")


def test_response_plan_rejects_empty_trigger_signal() -> None:
    with pytest.raises(ValueError, match="trigger_signal"):
        _plan(trigger_signal="")


def test_response_plan_rejects_empty_created_by() -> None:
    with pytest.raises(ValueError, match="created_by"):
        _plan(created_by="")


def test_alert_rejects_empty_alert_id() -> None:
    with pytest.raises(ValueError, match="alert_id"):
        Alert(alert_id="", signal="s", resources=(("r", "k"),), fired_at=_T)


def test_alert_rejects_empty_resources() -> None:
    with pytest.raises(ValueError, match="resources"):
        Alert(alert_id="a", signal="s", resources=(), fired_at=_T)


def test_hil_gate_rejects_nonpositive_interval() -> None:
    with pytest.raises(ValueError, match="poll_interval_seconds"):
        HilChannelApprovalGate(channel=InMemoryHilChannel(), poll_interval_seconds=0.0)


def test_hil_gate_rejects_nonpositive_ttl() -> None:
    with pytest.raises(ValueError, match="ttl_seconds"):
        HilChannelApprovalGate(channel=InMemoryHilChannel(), ttl_seconds=0)
