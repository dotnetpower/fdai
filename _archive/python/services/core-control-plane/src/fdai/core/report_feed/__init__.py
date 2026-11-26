"""Live report-signal feed (SRE-agent slide 22).

Normalizes heterogeneous signals (detection anomalies, investigation
findings, chaos outcomes, IRP responses, security assessments) into one
feed that backs the Workload anomaly report and the Security Assessment
report. Read-only projection - a signal describes what happened, it never
triggers an action.
"""

from __future__ import annotations

from fdai.core.report_feed.adapters import (
    priority_to_severity,
    signal_from_experiment,
    signal_from_irp,
    signals_from_investigation,
)
from fdai.core.report_feed.feed import ReportFeed, SignalSource, StaticSignalSource
from fdai.core.report_feed.models import (
    ReportCategory,
    ReportFeedResult,
    ReportSignal,
    SignalKind,
    severity_rank,
)

__all__ = [
    "ReportCategory",
    "ReportFeed",
    "ReportFeedResult",
    "ReportSignal",
    "SignalKind",
    "SignalSource",
    "StaticSignalSource",
    "priority_to_severity",
    "severity_rank",
    "signal_from_experiment",
    "signal_from_irp",
    "signals_from_investigation",
]
