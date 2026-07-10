"""The IRP coordinator bounds a wedged investigation (fail-safe, no execution)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from fdai.core.investigation import KIND_AZURE_OPENAI, InvestigationRequest
from fdai.core.irp import Alert, ApprovalDecision, IrpCoordinator, IrpOutcome
from fdai.core.irp.coordinator import MitigationProposal

_NOW = datetime(2026, 7, 10, 18, 45, tzinfo=UTC)


class _HangingInvestigator:
    """Duck-typed investigator whose investigate() never returns in time."""

    async def investigate(self, request: InvestigationRequest):  # noqa: ANN201, ARG002
        await asyncio.sleep(10)  # far longer than the coordinator's hard bound
        raise AssertionError("should have been cancelled")  # pragma: no cover


class _RecordingNotifier:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def notify(self, *, channels, subject, body) -> None:  # noqa: ANN001, ARG002
        self.sent.append(subject)


class _NeverGate:
    async def request(self, proposal: MitigationProposal) -> ApprovalDecision:  # noqa: ARG002
        raise AssertionError("approval MUST NOT be requested on a timed-out investigation")


def _alert() -> Alert:
    return Alert(
        alert_id="alert-hang",
        signal="rate_limit",
        resources=(("aoai-1", KIND_AZURE_OPENAI),),
        fired_at=_NOW,
    )


@pytest.mark.asyncio
async def test_wedged_investigation_times_out_fail_safe() -> None:
    notifier = _RecordingNotifier()
    coordinator = IrpCoordinator(
        investigator=_HangingInvestigator(),  # type: ignore[arg-type]
        approval_gate=_NeverGate(),
        notifier=notifier,
        default_channels=("teams://sre",),
        investigation_budget_seconds=0.01,  # -> hard bound 0.02s
        wall_clock=lambda: _NOW,
    )

    result = await coordinator.respond(_alert())

    # Fail-safe: no proposal, no approval requested, operator notified.
    assert result.outcome is IrpOutcome.NO_FINDING
    assert result.proposal is None
    assert result.report.outcome.value == "budget_exceeded"
    assert notifier.sent and "timed out" in notifier.sent[0]
