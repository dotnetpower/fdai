"""Pure reducers - findings -> timeline + prioritized recommendations.

Deterministic and I/O-free so "these findings produce this report" is
exhaustively testable. The timeline is a severity-tagged, time-ordered
projection of the findings; recommendations are ranked P1..P3 from finding
severity and de-duplicated per ``(resource_ref, signal)``.
"""

from __future__ import annotations

from collections.abc import Sequence

from fdai.core.investigation.contract import (
    AnalyzerFinding,
    Priority,
    Recommendation,
    TimelineEntry,
    priority_for,
    priority_rank,
    severity_rank,
)


def build_timeline(findings: Sequence[AnalyzerFinding]) -> tuple[TimelineEntry, ...]:
    """Project findings onto a time-ordered timeline (stable, deterministic)."""
    entries = [
        TimelineEntry(
            occurred_at=f.occurred_at,
            resource_ref=f.resource_ref,
            resource_kind=f.resource_kind,
            description=f.observation,
            severity=f.severity,
        )
        for f in findings
    ]
    # Sort by time, then severity (critical first), then resource for stability.
    entries.sort(key=lambda e: (e.occurred_at, severity_rank(e.severity), e.resource_ref))
    return tuple(entries)


def build_recommendations(
    findings: Sequence[AnalyzerFinding],
) -> tuple[Recommendation, ...]:
    """Rank findings into P1..P3 recommendations, de-duplicated per signal.

    One recommendation per ``(resource_ref, signal)``; when the same signal
    fires more than once the most severe wins. Output is sorted P1 first,
    then by resource for a stable, reviewable report.
    """
    best: dict[tuple[str, str], AnalyzerFinding] = {}
    for finding in findings:
        key = (finding.resource_ref, finding.signal)
        current = best.get(key)
        if current is None or severity_rank(finding.severity) < severity_rank(current.severity):
            best[key] = finding

    recommendations = [
        Recommendation(
            priority=priority_for(finding.severity),
            title=f"[{finding.resource_kind}] {finding.signal}",
            detail=finding.observation,
            resource_ref=finding.resource_ref,
            remediation_ref=finding.remediation_ref,
            citations=finding.evidence_refs,
        )
        for finding in best.values()
    ]
    recommendations.sort(key=lambda r: (priority_rank(r.priority), r.resource_ref, r.title))
    return tuple(recommendations)


def summarize_priorities(
    recommendations: Sequence[Recommendation],
) -> dict[Priority, int]:
    """Count recommendations per priority (P1..P3) for the report header."""
    counts = {Priority.P1: 0, Priority.P2: 0, Priority.P3: 0}
    for rec in recommendations:
        counts[rec.priority] += 1
    return counts


__all__ = [
    "build_recommendations",
    "build_timeline",
    "summarize_priorities",
]
