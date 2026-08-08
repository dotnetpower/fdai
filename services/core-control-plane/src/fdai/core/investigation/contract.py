"""Investigation contract - findings, timeline, recommendations, report.

An investigation is a **read-only, cross-resource diagnostic**: it gathers
per-resource findings, correlates them into a timeline + root-cause
hypothesis, and emits prioritized (P1..P3) recommendations. It NEVER
executes a change - every recommendation names an ActionType the normal
pipeline (ActionBuilder + risk-gate + verifier) may act on, and the risk
gate stays the sole authority over "execute".

This mirrors the Azure SRE Agent demo (session notes slides 10-14): one
investigation spans several resources (AppGW, MySQL, Azure OpenAI, AKS,
API Management), correlates a timeline of events, and returns priority
recommendations within a bounded latency budget.

See:
- [architecture.instructions.md](../../../../.github/instructions/architecture.instructions.md)
  (RCA answers "why", the risk gate answers "execute").
- [observability](../../../../docs/roadmap/rules-and-detection/observability-and-detection.md).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from fdai.shared.contracts.models import Severity


class Priority(StrEnum):
    """Recommendation priority, matching the demo's P1..P3 ranking."""

    P1 = "p1"
    P2 = "p2"
    P3 = "p3"


class InvestigationOutcome(StrEnum):
    """Terminal outcome of an investigation run."""

    COMPLETED = "completed"
    """Every requested analyzer ran and the run finished within budget."""

    PARTIAL = "partial"
    """At least one analyzer failed; the report holds what did succeed."""

    BUDGET_EXCEEDED = "budget_exceeded"
    """The latency budget elapsed before all analyzers finished."""

    ABSTAINED = "abstained"
    """No analyzer was registered for any requested resource kind."""


def priority_for(severity: Severity) -> Priority:
    """Map a finding severity onto a recommendation priority (deterministic)."""
    if severity is Severity.CRITICAL:
        return Priority.P1
    if severity is Severity.HIGH:
        return Priority.P2
    return Priority.P3


# Deterministic sort weights (lower = more urgent / more severe).
_PRIORITY_ORDER: dict[Priority, int] = {Priority.P1: 0, Priority.P2: 1, Priority.P3: 2}
_SEVERITY_ORDER: dict[Severity, int] = {
    Severity.CRITICAL: 0,
    Severity.HIGH: 1,
    Severity.MEDIUM: 2,
    Severity.LOW: 3,
}

# Fail-safe rank for a value not in the order maps. A future / foreign
# Severity or Priority value sorts LAST (least urgent) instead of raising
# KeyError and crashing the recommendation reducer for the whole
# investigation. Matches the `_SEVERITY_RANK.get(s, 99)` convention in
# `core/incident/storm.py`.
_UNRANKED: int = 99


def priority_rank(priority: Priority) -> int:
    """Sort weight for a priority (P1 first); unknown values sort last."""
    return _PRIORITY_ORDER.get(priority, _UNRANKED)


def severity_rank(severity: Severity) -> int:
    """Sort weight for a severity (critical first); unknown values sort last."""
    return _SEVERITY_ORDER.get(severity, _UNRANKED)


@dataclass(frozen=True, slots=True)
class AnalyzerFinding:
    """One observation produced by a per-resource analyzer.

    ``evidence_refs`` are opaque metric names / value handles (never a raw
    payload or secret) so a report can cite what it saw without leaking
    telemetry.
    """

    resource_ref: str
    resource_kind: str
    signal: str
    observation: str
    severity: Severity
    occurred_at: datetime
    evidence_refs: tuple[str, ...] = ()
    remediation_ref: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.resource_ref:
            raise ValueError("AnalyzerFinding.resource_ref MUST be non-empty")
        if not self.signal:
            raise ValueError("AnalyzerFinding.signal MUST be non-empty")


@dataclass(frozen=True, slots=True)
class TimelineEntry:
    """One point on the correlated investigation timeline."""

    occurred_at: datetime
    resource_ref: str
    resource_kind: str
    description: str
    severity: Severity


@dataclass(frozen=True, slots=True)
class Recommendation:
    """A prioritized, grounded recommendation - never an executed action.

    ``remediation_ref`` is the ActionType id the recommendation implies (if
    any). The console / operator may route it through the normal pipeline;
    the investigation layer only proposes.
    """

    priority: Priority
    title: str
    detail: str
    resource_ref: str
    remediation_ref: str | None = None
    citations: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class InvestigationReport:
    """The read-only output of one investigation run.

    Holds the correlated timeline, a root-cause hypothesis, prioritized
    recommendations, and the measured latency against the budget. The KPI
    view (:meth:`kpi`) is derived, never a side effect.
    """

    investigation_id: str
    requested_by: str
    requested_at: datetime
    window_seconds: float
    resources: tuple[tuple[str, str], ...]
    outcome: InvestigationOutcome
    findings: tuple[AnalyzerFinding, ...]
    timeline: tuple[TimelineEntry, ...]
    correlation: tuple[str, ...]
    root_cause: str | None
    recommendations: tuple[Recommendation, ...]
    elapsed_seconds: float
    budget_seconds: float
    analyzer_errors: tuple[tuple[str, str], ...] = ()

    @property
    def within_budget(self) -> bool:
        """True iff the run finished at or under its latency budget."""
        return self.elapsed_seconds <= self.budget_seconds

    @property
    def resource_count(self) -> int:
        return len(self.resources)

    def kpi(self) -> Mapping[str, float]:
        """Derived KPI view (latency, coverage, within-budget flag)."""
        return {
            "investigation.latency_seconds": self.elapsed_seconds,
            "investigation.budget_seconds": self.budget_seconds,
            "investigation.within_budget": 1.0 if self.within_budget else 0.0,
            "investigation.resource_count": float(self.resource_count),
            "investigation.finding_count": float(len(self.findings)),
            "investigation.recommendation_count": float(len(self.recommendations)),
        }


__all__ = [
    "AnalyzerFinding",
    "InvestigationOutcome",
    "InvestigationReport",
    "Priority",
    "Recommendation",
    "TimelineEntry",
    "priority_for",
    "priority_rank",
    "severity_rank",
]
