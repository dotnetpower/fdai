"""Report-feed models (SRE-agent slide 22).

Slide 22 renders two structured reports - a Workload anomaly report and a
Security Assessment report - from a **live signal feed**. This module
normalizes heterogeneous signals (detection anomalies, investigation
findings, chaos experiment outcomes, IRP responses, security assessments)
into one :class:`ReportSignal` shape the console report views consume.

Everything is inert, read-only projection data - a signal describes what was
observed, it never triggers an action.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from fdai.shared.contracts.models import Severity


class ReportCategory(StrEnum):
    """Which report a signal belongs to."""

    WORKLOAD = "workload"
    SECURITY = "security"


class SignalKind(StrEnum):
    """The producer kind of a report signal."""

    ANOMALY = "anomaly"
    INVESTIGATION = "investigation"
    CHAOS = "chaos"
    IRP = "irp"
    SECURITY_ASSESSMENT = "security_assessment"


# Sort weight for severity (critical first).
_SEVERITY_ORDER: dict[Severity, int] = {
    Severity.CRITICAL: 0,
    Severity.HIGH: 1,
    Severity.MEDIUM: 2,
    Severity.LOW: 3,
}


def severity_rank(severity: Severity) -> int:
    return _SEVERITY_ORDER[severity]


@dataclass(frozen=True, slots=True)
class ReportSignal:
    """One normalized signal for a report.

    ``evidence_refs`` are opaque handles (metric names, audit ids, rule ids),
    never raw payloads or secrets.
    """

    signal_id: str
    kind: SignalKind
    category: ReportCategory
    severity: Severity
    resource_ref: str
    title: str
    detail: str
    occurred_at: datetime
    evidence_refs: tuple[str, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ReportFeedResult:
    """The read-only outcome of collecting the feed over a window."""

    signals: tuple[ReportSignal, ...]
    source_errors: tuple[tuple[str, str], ...] = ()

    @property
    def workload(self) -> tuple[ReportSignal, ...]:
        return tuple(s for s in self.signals if s.category is ReportCategory.WORKLOAD)

    @property
    def security(self) -> tuple[ReportSignal, ...]:
        return tuple(s for s in self.signals if s.category is ReportCategory.SECURITY)

    def counts_by_category(self) -> Mapping[str, int]:
        return {
            ReportCategory.WORKLOAD.value: len(self.workload),
            ReportCategory.SECURITY.value: len(self.security),
        }


__all__ = [
    "ReportCategory",
    "ReportFeedResult",
    "ReportSignal",
    "SignalKind",
    "severity_rank",
]
