"""Security Assessment report - fuse security findings into a graded report.

Design contract: ``docs/roadmap/operations/assurance-twin.md`` (assessment output) and
the Azure SRE Agent parity note in
``docs/internals/sre-agent-gap-analysis.md`` (P3-9). Azure SRE Agent emits a
"Security Assessment" (for example an Application Gateway backend rated
CRITICAL, a detected vulnerability-scan attack). FDAI already assembles a
posture report from projection findings; this module is the security-scoped
counterpart: a deterministic fold over security-category
:class:`~fdai.shared.providers.projection.Finding` values into a graded,
grounded :class:`SecurityAssessment`.

Design invariants (identical to the posture report)
---------------------------------------------------

- **Read-only, pure**: a deterministic fold over a bounded
  ``Sequence[Finding]``; no I/O, no cloud SDK, no LLM. Same input yields
  identical output.
- **Grounded by construction**: every entry keeps the ``rule_id`` (cited
  evidence) and the source resource; the module never invents a finding
  or a recommendation.
- **Shadow-first**: ``blocks_action`` is ``True`` only when the pass ran in
  ``enforce`` mode AND the assessment is at or above the blocking
  threshold. A shadow pass records the truthful verdict but never gates an
  autonomous action.
- **CSP-neutral**: consumes only ``shared/providers/projection`` types.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

from fdai.core.security.observations import (
    ApplicabilityStatus,
    ControlStatus,
    RemediationPriority,
    SecurityControlObservation,
    SecurityRecommendation,
    SecuritySourceCoverage,
    SourceStatus,
)
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.projection import Finding, Severity

_SEVERITY_ORDER: tuple[Severity, ...] = ("low", "medium", "high", "critical")
# str-keyed (not Severity-keyed) so the fail-safe _severity_rank() below can
# look up an off-list severity string without a type error - the same shape the
# readiness coordinator uses.
_SEVERITY_RANK: dict[str, int] = {s: i for i, s in enumerate(_SEVERITY_ORDER)}
# An unrecognized severity outranks every known one, so a finding whose severity
# this fold does not understand fails toward safety (treated as blocking) rather
# than crashing. Severity is a Literal, not a runtime-checked enum, so a fork
# projection or a deserialized finding can carry an unexpected value - matching
# the readiness coordinator / posture report guard this module claims parity with.
_UNKNOWN_SEVERITY_RANK = len(_SEVERITY_ORDER)
# A finding at or above this severity is a blocker for the verdict.
_BLOCKING_SEVERITY: Severity = "high"
_PRIORITY_RANK: dict[RemediationPriority, int] = {
    RemediationPriority.CRITICAL: 0,
    RemediationPriority.HIGH: 1,
    RemediationPriority.MEDIUM: 2,
    RemediationPriority.LOW: 3,
    RemediationPriority.NONE: 4,
}


def _severity_rank(severity: str) -> int:
    return _SEVERITY_RANK.get(severity, _UNKNOWN_SEVERITY_RANK)


class SecurityVerdict(StrEnum):
    """Aggregate verdict for a security assessment."""

    CLEAR = "clear"
    """No finding at or above the blocking severity."""

    ATTENTION = "attention"
    """At least one ``high`` finding, no ``critical``."""

    CRITICAL = "critical"
    """At least one ``critical`` finding."""


@dataclass(frozen=True, slots=True)
class SecurityFindingEntry:
    """One security finding rendered for the report (grounded)."""

    rule_id: str
    resource_type: str
    resource_ref: str
    severity: Severity
    reason: str
    evidence_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SecurityAssessment:
    """Graded security assessment over a bounded finding set."""

    scope: str
    assessed_at: datetime
    mode: Mode
    verdict: SecurityVerdict
    highest_severity: Severity | None
    counts_by_severity: Mapping[Severity, int]
    entries: tuple[SecurityFindingEntry, ...]
    blocks_action: bool = False
    summary: str = ""
    finding_count: int = 0
    rule_count: int = 0
    affected_resource_count: int = 0
    affected_resource_type_count: int = 0
    evidence_reference_count: int = 0
    findings_without_evidence: int = 0
    controls_without_evidence: int = 0
    controls: tuple[SecurityControlObservation, ...] = ()
    control_count: int = 0
    control_status_counts: Mapping[str, int] = field(default_factory=dict)
    category_counts: Mapping[str, int] = field(default_factory=dict)
    resource_type_counts: Mapping[str, int] = field(default_factory=dict)
    positive_controls: tuple[SecurityControlObservation, ...] = ()
    unknown_controls: tuple[SecurityControlObservation, ...] = ()
    recommendations: tuple[SecurityRecommendation, ...] = ()
    source_coverage: tuple[SecuritySourceCoverage, ...] = ()
    completion_status: str = "unmeasured"
    control_pass_rate_percent: float | None = None
    evidence_coverage_percent: float | None = None
    source_coverage_percent: float | None = None
    available_source_count: int = 0
    partial_source_count: int = 0
    unavailable_source_count: int = 0
    stale_source_count: int = 0
    cve_count: int = 0
    applicable_cve_count: int = 0
    compliance_control_count: int = 0
    recommendation_count: int = 0
    critical_recommendation_count: int = 0
    high_recommendation_count: int = 0

    def to_dict(self) -> dict[str, object]:
        """Return the canonical JSON-friendly assessment projection."""

        return _assessment_to_dict(self)


def _verdict(highest: Severity | None) -> SecurityVerdict:
    if highest == "critical":
        return SecurityVerdict.CRITICAL
    if highest is not None and _severity_rank(highest) >= _severity_rank(_BLOCKING_SEVERITY):
        return SecurityVerdict.ATTENTION
    return SecurityVerdict.CLEAR


def build_security_assessment(
    findings: Sequence[Finding],
    *,
    scope: str,
    assessed_at: datetime,
    mode: Mode = Mode.SHADOW,
    controls: Sequence[SecurityControlObservation] = (),
    source_coverage: Sequence[SecuritySourceCoverage] = (),
) -> SecurityAssessment:
    """Fold security ``findings`` into a graded assessment (pure).

    Entries are sorted most-severe first, then by ``rule_id`` for a stable
    order. ``blocks_action`` is ``True`` only in enforce mode when the
    verdict is at or above the blocking severity - shadow never gates.
    """
    counts: dict[Severity, int] = dict.fromkeys(_SEVERITY_ORDER, 0)
    highest: Severity | None = None
    entries: list[SecurityFindingEntry] = []

    for finding in findings:
        # Fail toward safety on an off-list severity: count it under its own
        # key (never crash) and rank an unknown value as most-severe.
        counts[finding.severity] = counts.get(finding.severity, 0) + 1
        if highest is None or _severity_rank(finding.severity) > _severity_rank(highest):
            highest = finding.severity
        entries.append(
            SecurityFindingEntry(
                rule_id=finding.rule_id,
                resource_type=finding.resource.resource_type,
                resource_ref=finding.resource.ref,
                severity=finding.severity,
                reason=finding.reason,
                evidence_refs=finding.evidence_refs,
            )
        )

    frozen_controls = tuple(
        sorted(
            controls,
            key=lambda control: (
                -_severity_rank(control.severity),
                control.category,
                control.control_id,
                control.resource_ref,
            ),
        )
    )
    for control in frozen_controls:
        if control.status in {ControlStatus.FAIL, ControlStatus.WARNING} and (
            highest is None or _severity_rank(control.severity) > _severity_rank(highest)
        ):
            highest = control.severity

    entries.sort(key=lambda e: (-_severity_rank(e.severity), e.rule_id))
    verdict = _verdict(highest)
    blocking = mode is Mode.ENFORCE and verdict is not SecurityVerdict.CLEAR
    status_counts = _control_status_counts(frozen_controls)
    summary = _summary(
        verdict=verdict,
        counts=counts,
        total=len(entries),
        control_counts=status_counts,
    )
    recommendations = _recommendations(frozen_controls, assessed_at=assessed_at)
    frozen_sources = tuple(sorted(source_coverage, key=lambda source: source.source))
    all_evidence_items = len(entries) + len(frozen_controls)
    evidenced_items = sum(bool(entry.evidence_refs) for entry in entries) + sum(
        bool(control.evidence_refs) for control in frozen_controls
    )
    cves = {cve for control in frozen_controls for cve in control.cve_ids}
    applicable_cves = {
        cve
        for control in frozen_controls
        if control.applicability is ApplicabilityStatus.APPLICABLE
        for cve in control.cve_ids
    }

    return SecurityAssessment(
        scope=scope,
        assessed_at=assessed_at,
        mode=mode,
        verdict=verdict,
        highest_severity=highest,
        counts_by_severity=counts,
        entries=tuple(entries),
        blocks_action=blocking,
        summary=summary,
        finding_count=len(entries),
        rule_count=len({entry.rule_id for entry in entries}),
        affected_resource_count=len(
            {entry.resource_ref for entry in entries}
            | {control.resource_ref for control in frozen_controls}
        ),
        affected_resource_type_count=len(
            {entry.resource_type for entry in entries}
            | {control.resource_type for control in frozen_controls}
        ),
        evidence_reference_count=sum(len(entry.evidence_refs) for entry in entries)
        + sum(len(control.evidence_refs) for control in frozen_controls),
        findings_without_evidence=sum(not entry.evidence_refs for entry in entries),
        controls_without_evidence=sum(not control.evidence_refs for control in frozen_controls),
        controls=frozen_controls,
        control_count=len(frozen_controls),
        control_status_counts=status_counts,
        category_counts=_count_by(frozen_controls, "category"),
        resource_type_counts=_count_by(frozen_controls, "resource_type"),
        positive_controls=tuple(
            control for control in frozen_controls if control.status is ControlStatus.PASS
        ),
        unknown_controls=tuple(
            control for control in frozen_controls if control.status is ControlStatus.UNKNOWN
        ),
        recommendations=recommendations,
        source_coverage=frozen_sources,
        completion_status=_completion_status(
            entries=entries,
            controls=frozen_controls,
            sources=frozen_sources,
        ),
        control_pass_rate_percent=_control_pass_rate(status_counts),
        evidence_coverage_percent=_percent(evidenced_items, all_evidence_items),
        source_coverage_percent=_source_coverage_percent(frozen_sources),
        available_source_count=sum(
            source.status is SourceStatus.AVAILABLE for source in frozen_sources
        ),
        partial_source_count=sum(
            source.status is SourceStatus.PARTIAL for source in frozen_sources
        ),
        unavailable_source_count=sum(
            source.status is SourceStatus.UNAVAILABLE for source in frozen_sources
        ),
        stale_source_count=sum(source.fresh is False for source in frozen_sources),
        cve_count=len(cves),
        applicable_cve_count=len(applicable_cves),
        compliance_control_count=len(
            {
                compliance
                for control in frozen_controls
                for compliance in control.compliance_controls
            }
        ),
        recommendation_count=len(recommendations),
        critical_recommendation_count=sum(
            item.priority is RemediationPriority.CRITICAL for item in recommendations
        ),
        high_recommendation_count=sum(
            item.priority is RemediationPriority.HIGH for item in recommendations
        ),
    )


def _summary(
    *,
    verdict: SecurityVerdict,
    counts: Mapping[Severity, int],
    total: int,
    control_counts: Mapping[str, int],
) -> str:
    control_total = sum(control_counts.values())
    if total == 0 and control_total == 0:
        return "No security findings in scope."
    parts = ", ".join(f"{counts[s]} {s}" for s in reversed(_SEVERITY_ORDER) if counts[s] > 0)
    finding_summary = f"{total} finding(s)" + (f" ({parts})" if parts else "")
    if control_total == 0:
        return f"{verdict.value.upper()}: {finding_summary}."
    return (
        f"{verdict.value.upper()}: {finding_summary}; {control_total} control(s) "
        f"({control_counts[ControlStatus.PASS.value]} pass, "
        f"{control_counts[ControlStatus.FAIL.value]} fail, "
        f"{control_counts[ControlStatus.WARNING.value]} warning, "
        f"{control_counts[ControlStatus.NOT_APPLICABLE.value]} not applicable, "
        f"{control_counts[ControlStatus.UNKNOWN.value]} unknown)."
    )


def _control_status_counts(
    controls: Sequence[SecurityControlObservation],
) -> dict[str, int]:
    counts = {status.value: 0 for status in ControlStatus}
    for control in controls:
        counts[control.status.value] += 1
    return counts


def _count_by(controls: Sequence[SecurityControlObservation], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for control in controls:
        value = str(getattr(control, field))
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _recommendations(
    controls: Sequence[SecurityControlObservation], *, assessed_at: datetime
) -> tuple[SecurityRecommendation, ...]:
    recommendations = [
        SecurityRecommendation(
            control_id=control.control_id,
            resource_ref=control.resource_ref,
            priority=control.priority,
            severity=control.severity,
            action=control.remediation,
            validation=control.validation,
            due_at=(
                assessed_at + timedelta(days=control.due_days)
                if control.due_days is not None
                else None
            ),
            evidence_refs=control.evidence_refs,
        )
        for control in controls
        if control.status in {ControlStatus.FAIL, ControlStatus.WARNING} and control.remediation
    ]
    recommendations.sort(
        key=lambda item: (
            _PRIORITY_RANK[item.priority],
            -_severity_rank(item.severity),
            item.control_id,
            item.resource_ref,
        )
    )
    return tuple(recommendations)


def _control_pass_rate(counts: Mapping[str, int]) -> float | None:
    applicable = (
        counts[ControlStatus.PASS.value]
        + counts[ControlStatus.FAIL.value]
        + counts[ControlStatus.WARNING.value]
    )
    return _percent(counts[ControlStatus.PASS.value], applicable)


def _percent(numerator: float, denominator: float) -> float | None:
    if denominator == 0:
        return None
    return round(100.0 * numerator / denominator, 1)


def _source_coverage_percent(sources: Sequence[SecuritySourceCoverage]) -> float | None:
    if not sources:
        return None
    score = sum(
        1.0
        if source.status is SourceStatus.AVAILABLE
        else 0.5
        if source.status is SourceStatus.PARTIAL
        else 0.0
        for source in sources
    )
    return _percent(score, len(sources))


def _completion_status(
    *,
    entries: Sequence[SecurityFindingEntry],
    controls: Sequence[SecurityControlObservation],
    sources: Sequence[SecuritySourceCoverage],
) -> str:
    if not entries and not controls:
        return "unmeasured"
    if sources and all(source.status is SourceStatus.UNAVAILABLE for source in sources):
        return "incomplete"
    if (
        any(control.status is ControlStatus.UNKNOWN for control in controls)
        or any(source.status is not SourceStatus.AVAILABLE for source in sources)
        or any(not entry.evidence_refs for entry in entries)
        or any(not control.evidence_refs for control in controls)
    ):
        return "partial"
    return "complete"


def _assessment_to_dict(report: SecurityAssessment) -> dict[str, object]:
    return {
        "scope": report.scope,
        "assessed_at": report.assessed_at.isoformat(),
        "mode": report.mode.value,
        "verdict": report.verdict.value,
        "blocks_action": report.blocks_action,
        "summary": report.summary,
        "highest_severity": report.highest_severity,
        "finding_count": report.finding_count,
        "rule_count": report.rule_count,
        "affected_resource_count": report.affected_resource_count,
        "affected_resource_type_count": report.affected_resource_type_count,
        "counts_by_severity": dict(report.counts_by_severity),
        "evidence_reference_count": report.evidence_reference_count,
        "findings_without_evidence": report.findings_without_evidence,
        "controls_without_evidence": report.controls_without_evidence,
        "control_count": report.control_count,
        "control_status_counts": dict(report.control_status_counts),
        "category_counts": dict(report.category_counts),
        "resource_type_counts": dict(report.resource_type_counts),
        "completion_status": report.completion_status,
        "control_pass_rate_percent": report.control_pass_rate_percent,
        "evidence_coverage_percent": report.evidence_coverage_percent,
        "source_coverage_percent": report.source_coverage_percent,
        "available_source_count": report.available_source_count,
        "partial_source_count": report.partial_source_count,
        "unavailable_source_count": report.unavailable_source_count,
        "stale_source_count": report.stale_source_count,
        "cve_count": report.cve_count,
        "applicable_cve_count": report.applicable_cve_count,
        "compliance_control_count": report.compliance_control_count,
        "recommendation_count": report.recommendation_count,
        "critical_recommendation_count": report.critical_recommendation_count,
        "high_recommendation_count": report.high_recommendation_count,
        "entries": [_finding_to_dict(entry) for entry in report.entries],
        "controls": [_control_to_dict(control) for control in report.controls],
        "positive_controls": [control.control_id for control in report.positive_controls],
        "unknown_controls": [control.control_id for control in report.unknown_controls],
        "recommendations": [_recommendation_to_dict(item) for item in report.recommendations],
        "source_coverage": [_source_to_dict(source) for source in report.source_coverage],
    }


def _finding_to_dict(entry: SecurityFindingEntry) -> dict[str, object]:
    return {
        "rule_id": entry.rule_id,
        "resource_type": entry.resource_type,
        "resource_ref": entry.resource_ref,
        "severity": entry.severity,
        "reason": entry.reason,
        "evidence_refs": list(entry.evidence_refs),
    }


def _control_to_dict(control: SecurityControlObservation) -> dict[str, object]:
    return {
        "control_id": control.control_id,
        "title": control.title,
        "category": control.category,
        "resource_type": control.resource_type,
        "resource_ref": control.resource_ref,
        "status": control.status.value,
        "severity": control.severity,
        "current_value": control.current_value,
        "expected_value": control.expected_value,
        "rationale": control.rationale,
        "source": control.source,
        "collected_at": control.collected_at.isoformat(),
        "evidence_refs": list(control.evidence_refs),
        "remediation": control.remediation,
        "validation": control.validation,
        "priority": control.priority.value,
        "due_days": control.due_days,
        "applicability": control.applicability.value,
        "cve_ids": list(control.cve_ids),
        "compliance_controls": list(control.compliance_controls),
        "source_urls": list(control.source_urls),
        "managed_service_note": control.managed_service_note,
        "patch_status": control.patch_status,
    }


def _recommendation_to_dict(item: SecurityRecommendation) -> dict[str, object]:
    return {
        "control_id": item.control_id,
        "resource_ref": item.resource_ref,
        "priority": item.priority.value,
        "severity": item.severity,
        "action": item.action,
        "validation": item.validation,
        "due_at": item.due_at.isoformat() if item.due_at is not None else None,
        "evidence_refs": list(item.evidence_refs),
    }


def _source_to_dict(source: SecuritySourceCoverage) -> dict[str, object]:
    return {
        "source": source.source,
        "status": source.status.value,
        "record_count": source.record_count,
        "as_of": source.as_of.isoformat() if source.as_of is not None else None,
        "scope": source.scope,
        "error": source.error,
        "fresh": source.fresh,
    }


__all__ = [
    "SecurityAssessment",
    "SecurityFindingEntry",
    "SecurityVerdict",
    "build_security_assessment",
]
