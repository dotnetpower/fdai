"""Edge cases for report-feed adapters + sources."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from fdai.core.investigation import Priority
from fdai.core.investigation.contract import (
    InvestigationOutcome,
    InvestigationReport,
)
from fdai.core.irp.coordinator import IrpOutcome, IrpResult
from fdai.core.report_feed import (
    ReportCategory,
    SignalKind,
    StaticSignalSource,
    priority_to_severity,
    signal_from_irp,
)
from fdai.core.report_feed.models import ReportSignal
from fdai.shared.contracts.models import Severity

_T = datetime(2026, 7, 10, 18, 0, tzinfo=UTC)


def _empty_report() -> InvestigationReport:
    return InvestigationReport(
        investigation_id="inv-1",
        requested_by="op",
        requested_at=_T,
        window_seconds=60.0,
        resources=(("r", "k"),),
        outcome=InvestigationOutcome.COMPLETED,
        findings=(),
        timeline=(),
        correlation=(),
        root_cause=None,
        recommendations=(),
        elapsed_seconds=1.0,
        budget_seconds=60.0,
    )


def test_priority_to_severity_maps_all() -> None:
    assert priority_to_severity(Priority.P1) is Severity.CRITICAL
    assert priority_to_severity(Priority.P2) is Severity.HIGH
    assert priority_to_severity(Priority.P3) is Severity.MEDIUM


def test_signal_from_irp_without_proposal_uses_dash() -> None:
    result = IrpResult(
        alert_id="alert-9",
        outcome=IrpOutcome.NO_FINDING,
        report=_empty_report(),
        proposal=None,
        decision=None,
        notified_channels=(),
        started_at=_T,
        ended_at=_T,
        investigation_within_budget=True,
    )

    signal = signal_from_irp(result)

    assert signal.kind is SignalKind.IRP
    assert signal.category is ReportCategory.WORKLOAD
    assert "remediation=-" in signal.detail
    assert signal.severity is Severity.LOW  # NO_FINDING -> low


def test_static_signal_source_exposes_name() -> None:
    src = StaticSignalSource("mysource", ())
    assert src.name == "mysource"


@pytest.mark.asyncio
async def test_static_signal_source_filters_by_window() -> None:
    sig = ReportSignal(
        signal_id="s",
        kind=SignalKind.ANOMALY,
        category=ReportCategory.WORKLOAD,
        severity=Severity.LOW,
        resource_ref="r",
        title="t",
        detail="d",
        occurred_at=_T,
    )
    src = StaticSignalSource("s", [sig])
    inside = await src.signals(since=_T, until=_T)
    outside = await src.signals(
        since=datetime(2026, 7, 11, tzinfo=UTC), until=datetime(2026, 7, 12, tzinfo=UTC)
    )
    assert inside == (sig,)
    assert outside == ()
