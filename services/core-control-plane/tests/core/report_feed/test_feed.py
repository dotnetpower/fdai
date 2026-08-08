"""Tests for the report-signal feed (slide 22)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.chaos.contract import ExperimentOutcome, ExperimentResult
from fdai.core.investigation.contract import (
    AnalyzerFinding,
    InvestigationOutcome,
    InvestigationReport,
)
from fdai.core.report_feed import (
    ReportCategory,
    ReportFeed,
    ReportSignal,
    SignalKind,
    StaticSignalSource,
    signal_from_experiment,
    signals_from_investigation,
)
from fdai.shared.contracts.models import Mode, Severity

_T0 = datetime(2026, 7, 10, 18, 0, tzinfo=UTC)


def _signal(
    sid: str,
    *,
    severity: Severity,
    category: ReportCategory = ReportCategory.WORKLOAD,
    at: datetime = _T0,
) -> ReportSignal:
    return ReportSignal(
        signal_id=sid,
        kind=SignalKind.ANOMALY,
        category=category,
        severity=severity,
        resource_ref="r",
        title="t",
        detail="d",
        occurred_at=at,
    )


class _RaisingSource:
    @property
    def name(self) -> str:
        return "bad"

    async def signals(self, *, since, until) -> Sequence[ReportSignal]:  # noqa: ANN001
        raise RuntimeError("feed backend down")


@pytest.mark.asyncio
async def test_collect_sorts_by_severity_then_recency() -> None:
    src = StaticSignalSource(
        "s",
        [
            _signal("low", severity=Severity.LOW, at=_T0),
            _signal("crit", severity=Severity.CRITICAL, at=_T0),
            _signal("high-older", severity=Severity.HIGH, at=_T0),
            _signal("high-newer", severity=Severity.HIGH, at=_T0 + timedelta(minutes=5)),
        ],
    )
    feed = ReportFeed([src])

    result = await feed.collect(since=_T0 - timedelta(hours=1), until=_T0 + timedelta(hours=1))

    order = [s.signal_id for s in result.signals]
    assert order[0] == "crit"
    # Among HIGH, the newer one comes first.
    assert order.index("high-newer") < order.index("high-older")
    assert order[-1] == "low"


@pytest.mark.asyncio
async def test_category_filter_splits_workload_and_security() -> None:
    src = StaticSignalSource(
        "s",
        [
            _signal("w", severity=Severity.HIGH, category=ReportCategory.WORKLOAD),
            _signal("sec", severity=Severity.HIGH, category=ReportCategory.SECURITY),
        ],
    )
    feed = ReportFeed([src])

    result = await feed.collect(
        since=_T0 - timedelta(hours=1),
        until=_T0 + timedelta(hours=1),
        category=ReportCategory.SECURITY,
    )

    assert [s.signal_id for s in result.signals] == ["sec"]


@pytest.mark.asyncio
async def test_window_excludes_out_of_range_signals() -> None:
    src = StaticSignalSource(
        "s",
        [_signal("old", severity=Severity.HIGH, at=_T0 - timedelta(days=2))],
    )
    feed = ReportFeed([src])

    result = await feed.collect(since=_T0 - timedelta(hours=1), until=_T0 + timedelta(hours=1))

    assert result.signals == ()


@pytest.mark.asyncio
async def test_failing_source_is_isolated() -> None:
    good = StaticSignalSource("good", [_signal("ok", severity=Severity.HIGH)])
    feed = ReportFeed([_RaisingSource(), good])

    result = await feed.collect(since=_T0 - timedelta(hours=1), until=_T0 + timedelta(hours=1))

    assert [s.signal_id for s in result.signals] == ["ok"]
    assert result.source_errors and result.source_errors[0][0] == "bad"


@pytest.mark.asyncio
async def test_counts_by_category() -> None:
    src = StaticSignalSource(
        "s",
        [
            _signal("w1", severity=Severity.HIGH, category=ReportCategory.WORKLOAD),
            _signal("w2", severity=Severity.LOW, category=ReportCategory.WORKLOAD),
            _signal("s1", severity=Severity.HIGH, category=ReportCategory.SECURITY),
        ],
    )
    feed = ReportFeed([src])

    result = await feed.collect(since=_T0 - timedelta(hours=1), until=_T0 + timedelta(hours=1))

    assert result.counts_by_category() == {"workload": 2, "security": 1}


def test_signals_from_investigation_maps_findings() -> None:
    report = InvestigationReport(
        investigation_id="inv-1",
        requested_by="op",
        requested_at=_T0,
        window_seconds=3600.0,
        resources=(("appgw-1", "application_gateway"),),
        outcome=InvestigationOutcome.COMPLETED,
        findings=(
            AnalyzerFinding(
                resource_ref="appgw-1",
                resource_kind="application_gateway",
                signal="backend_health",
                observation="collapsed",
                severity=Severity.CRITICAL,
                occurred_at=_T0,
            ),
        ),
        timeline=(),
        correlation=(),
        root_cause=None,
        recommendations=(),
        elapsed_seconds=1.0,
        budget_seconds=300.0,
    )

    signals = signals_from_investigation(report)

    assert len(signals) == 1
    assert signals[0].kind is SignalKind.INVESTIGATION
    assert signals[0].severity is Severity.CRITICAL


def test_signal_from_experiment_flags_detection_gap() -> None:
    result = ExperimentResult(
        experiment_id="chaos-1",
        scenario_id="aks-pod-cpu-spike",
        mode=Mode.ENFORCE,
        targets=("pod-a",),
        outcome=ExperimentOutcome.NOT_DETECTED,
        expected_signal="node_cpu",
        detected=False,
        started_at=_T0,
        ended_at=_T0 + timedelta(minutes=2),
        injected=True,
        stopped=True,
    )

    signal = signal_from_experiment(result)

    assert signal.kind is SignalKind.CHAOS
    assert signal.severity is Severity.HIGH  # a detection gap is high severity


def test_signal_from_experiment_rollback_failed_is_critical() -> None:
    # A live-fault-left experiment is the most dangerous state - it MUST NOT
    # fall back to the default MEDIUM severity in the report feed.
    result = ExperimentResult(
        experiment_id="chaos-2",
        scenario_id="aks-pod-cpu-spike",
        mode=Mode.ENFORCE,
        targets=("pod-a",),
        outcome=ExperimentOutcome.ROLLBACK_FAILED,
        expected_signal="node_cpu",
        detected=True,
        started_at=_T0,
        ended_at=_T0 + timedelta(minutes=2),
        injected=True,
        stopped=False,
    )

    signal = signal_from_experiment(result)

    assert signal.kind is SignalKind.CHAOS
    assert signal.severity is Severity.CRITICAL
