"""Tests for the IRP alert-response coordinator (slide 18)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest

from fdai.core.investigation import (
    KIND_AZURE_OPENAI,
    InvestigationCoordinator,
    default_analyzers,
)
from fdai.core.irp import (
    Alert,
    ApprovalDecision,
    IrpCoordinator,
    IrpOutcome,
    MitigationProposal,
)
from fdai.shared.providers.metric import MetricPoint, MetricQuery

_NOW = datetime(2026, 7, 10, 18, 40, tzinfo=UTC)


class _Provider:
    def __init__(self, metrics: dict[str, float]) -> None:
        self._metrics = metrics

    async def query(self, query: MetricQuery) -> AsyncIterator[MetricPoint]:
        if query.metric_name in self._metrics:
            yield MetricPoint(
                metric_name=query.metric_name,
                at=datetime.now(tz=UTC),
                value=self._metrics[query.metric_name],
                labels=dict(query.labels),
            )


class _FixedGate:
    def __init__(self, decision: ApprovalDecision) -> None:
        self.decision = decision
        self.seen: list[MitigationProposal] = []

    async def request(self, proposal: MitigationProposal) -> ApprovalDecision:
        self.seen.append(proposal)
        return self.decision


class _RecordingNotifier:
    def __init__(self) -> None:
        self.sent: list[tuple[tuple[str, ...], str]] = []

    async def notify(self, *, channels, subject, body) -> None:  # noqa: ANN001
        self.sent.append((tuple(channels), subject))


def _alert() -> Alert:
    return Alert(
        alert_id="alert-1",
        signal="rate_limit",
        resources=(("aoai-1", KIND_AZURE_OPENAI),),
        fired_at=_NOW,
    )


def _investigator(metrics: dict[str, float]) -> InvestigationCoordinator:
    return InvestigationCoordinator(analyzers=default_analyzers(_Provider(metrics)))


@pytest.mark.asyncio
async def test_approved_alert_proposes_and_notifies() -> None:
    gate = _FixedGate(ApprovalDecision.APPROVED)
    notifier = _RecordingNotifier()
    coordinator = IrpCoordinator(
        investigator=_investigator({"http_429_rate": 0.4}),
        approval_gate=gate,
        notifier=notifier,
        default_channels=("teams://sre",),
        wall_clock=lambda: _NOW,
    )

    result = await coordinator.respond(_alert())

    assert result.outcome is IrpOutcome.APPROVED
    assert result.proposal is not None
    assert result.proposal.remediation_ref == "aoai.increase_tpm_quota"
    assert gate.seen  # the proposal was routed for approval
    assert notifier.sent and notifier.sent[0][0] == ("teams://sre",)


@pytest.mark.asyncio
async def test_default_gate_rejects_fail_closed() -> None:
    # No approval_gate wired -> DenyByDefaultApprovalGate rejects.
    coordinator = IrpCoordinator(
        investigator=_investigator({"http_429_rate": 0.4}),
        default_channels=("teams://sre",),
        wall_clock=lambda: _NOW,
    )

    result = await coordinator.respond(_alert())

    assert result.outcome is IrpOutcome.REJECTED


@pytest.mark.asyncio
async def test_no_finding_when_resource_healthy() -> None:
    coordinator = IrpCoordinator(
        investigator=_investigator({"http_429_rate": 0.0}),
        approval_gate=_FixedGate(ApprovalDecision.APPROVED),
        wall_clock=lambda: _NOW,
    )

    result = await coordinator.respond(_alert())

    assert result.outcome is IrpOutcome.NO_FINDING
    assert result.proposal is None


@pytest.mark.asyncio
async def test_timeout_decision_maps_to_timeout_outcome() -> None:
    coordinator = IrpCoordinator(
        investigator=_investigator({"http_429_rate": 0.4}),
        approval_gate=_FixedGate(ApprovalDecision.TIMEOUT),
        wall_clock=lambda: _NOW,
    )

    result = await coordinator.respond(_alert())

    assert result.outcome is IrpOutcome.TIMEOUT


@pytest.mark.parametrize("bad_budget", [0.0, -1.0, float("nan"), float("inf")])
def test_rejects_non_finite_or_non_positive_budget(bad_budget: float) -> None:
    # The budget is the bounded-execution stop-condition: an inf budget makes
    # wait_for's timeout never fire (respond() could hang forever), and a
    # non-positive budget makes every investigation time out instantly. Both
    # must fail fast at construction.
    with pytest.raises(ValueError, match="investigation_budget_seconds"):
        IrpCoordinator(
            investigator=_investigator({"http_429_rate": 0.4}),
            investigation_budget_seconds=bad_budget,
        )
