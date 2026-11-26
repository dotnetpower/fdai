"""Deep security-assessment projections over the live report feed."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import datetime, timedelta
from enum import StrEnum
from typing import cast

from fdai.core.report_feed.feed import ReportFeed
from fdai.core.report_feed.models import (
    ReportCategory,
    ReportFeedResult,
    ReportSignal,
    SignalKind,
)
from fdai.core.reporting.models import DataSet, QuerySpec
from fdai.core.security import (
    ApplicabilityStatus,
    ControlStatus,
    RemediationPriority,
    SecurityAssessment,
    SecurityControlObservation,
    SecuritySourceCoverage,
    SourceStatus,
    build_security_assessment,
)
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.projection import Finding, ResourceRef, Severity

_SUMMARY_FIELDS = frozenset(
    {
        "verdict",
        "completion_status",
        "finding_count",
        "rule_count",
        "affected_resource_count",
        "affected_resource_type_count",
        "control_count",
        "control_pass_rate_percent",
        "evidence_coverage_percent",
        "source_coverage_percent",
        "recommendation_count",
        "critical_recommendation_count",
        "high_recommendation_count",
        "cve_count",
        "applicable_cve_count",
        "compliance_control_count",
        "stale_source_count",
    }
)


class SecurityAssessmentDataSource:
    """Build and project a deterministic assessment from security signals."""

    __slots__ = (
        "_cache_key",
        "_cache_deadline",
        "_cache_report",
        "_cache_ttl_seconds",
        "_clock",
        "_feed",
        "_freshness_ttl",
        "_lock",
        "_name",
    )

    def __init__(
        self,
        *,
        feed: ReportFeed,
        name: str = "security_assessment",
        freshness_ttl: timedelta = timedelta(days=1),
        cache_ttl: timedelta = timedelta(seconds=5),
        monotonic_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if freshness_ttl <= timedelta(0):
            raise ValueError("freshness_ttl MUST be positive")
        if cache_ttl <= timedelta(0):
            raise ValueError("cache_ttl MUST be positive")
        self._feed = feed
        self._name = name
        self._freshness_ttl = freshness_ttl
        self._cache_ttl_seconds = cache_ttl.total_seconds()
        self._clock = monotonic_clock
        self._cache_key: tuple[datetime, datetime, str] | None = None
        self._cache_deadline = 0.0
        self._cache_report: SecurityAssessment | None = None
        self._lock = asyncio.Lock()

    @property
    def name(self) -> str:
        return self._name

    async def query(
        self,
        spec: QuerySpec,
        *,
        since: datetime,
        until: datetime,
        variables: Mapping[str, str],
    ) -> DataSet:
        scope = variables.get("scope", str(spec.parameters.get("scope", "monitored-scope")))
        report = await self._assessment(since=since, until=until, scope=scope)
        projection = str(spec.parameters.get("projection", "control_rows"))

        if projection == "summary_value":
            return _summary_value(report, field=str(spec.parameters.get("field", "verdict")))
        if projection == "severity_counts":
            return _count_rows(report.counts_by_severity, label="severity")
        if projection == "category_counts":
            return _count_rows(report.category_counts, label="category")
        if projection == "resource_type_counts":
            return _count_rows(report.resource_type_counts, label="resource_type")
        if projection == "control_status":
            return _control_status(report.controls)
        if projection == "control_rows":
            return _control_rows(report.controls)
        if projection == "recommendation_rows":
            return _recommendation_rows(report)
        if projection == "cve_rows":
            return _cve_rows(report.controls)
        if projection == "source_rows":
            return _source_rows(report.source_coverage)
        if projection == "positive_rows":
            return _control_rows(report.positive_controls)
        if projection == "gap_rows":
            return _gap_rows(report)
        if projection == "resource_rows":
            return _resource_rows(report.controls)
        if projection == "compliance_rows":
            return _compliance_rows(report.controls)
        if projection == "evidence_rows":
            return _evidence_rows(report)
        return DataSet(metadata={"unknown_projection": projection})

    async def _assessment(
        self,
        *,
        since: datetime,
        until: datetime,
        scope: str,
    ) -> SecurityAssessment:
        key = (since, until, scope)
        async with self._lock:
            now = self._clock()
            if (
                self._cache_key == key
                and self._cache_report is not None
                and now < self._cache_deadline
            ):
                return self._cache_report
            result = await self._feed.collect(
                since=since,
                until=until,
                category=ReportCategory.SECURITY,
            )
            report = _build_from_feed(
                result,
                scope=scope,
                assessed_at=until,
                freshness_ttl=self._freshness_ttl,
            )
            self._cache_key = key
            self._cache_report = report
            self._cache_deadline = now + self._cache_ttl_seconds
            return report


def _build_from_feed(
    result: ReportFeedResult,
    *,
    scope: str,
    assessed_at: datetime,
    freshness_ttl: timedelta,
) -> SecurityAssessment:
    control_signals = _latest_control_signals(
        signal for signal in result.signals if signal.kind is SignalKind.SECURITY_ASSESSMENT
    )
    controls = tuple(_signal_to_control(signal) for signal in control_signals)
    findings = tuple(
        _signal_to_finding(signal)
        for signal in result.signals
        if signal.kind is not SignalKind.SECURITY_ASSESSMENT
    )
    coverage = _source_coverage(
        controls,
        result.source_errors,
        scope=scope,
        assessed_at=assessed_at,
        freshness_ttl=freshness_ttl,
    )
    return build_security_assessment(
        findings,
        scope=scope,
        assessed_at=assessed_at,
        mode=Mode.SHADOW,
        controls=controls,
        source_coverage=coverage,
    )


def _latest_control_signals(signals: Iterable[ReportSignal]) -> tuple[ReportSignal, ...]:
    latest: dict[tuple[str, str], ReportSignal] = {}
    for signal in signals:
        key = (signal.metadata.get("control_id", signal.signal_id), signal.resource_ref)
        current = latest.get(key)
        if current is None or (signal.occurred_at, signal.signal_id) > (
            current.occurred_at,
            current.signal_id,
        ):
            latest[key] = signal
    return tuple(latest[key] for key in sorted(latest))


def _signal_to_control(signal: ReportSignal) -> SecurityControlObservation:
    metadata = signal.metadata
    severity = _severity(signal.severity.value)
    status = _enum_or_default(ControlStatus, metadata.get("status"), ControlStatus.UNKNOWN)
    priority = _priority(metadata.get("priority"), severity=severity, status=status)
    return SecurityControlObservation(
        control_id=metadata.get("control_id", signal.signal_id),
        title=signal.title or metadata.get("control_id", signal.signal_id),
        category=metadata.get("control_category", metadata.get("category", "configuration")),
        resource_type=metadata.get("resource_type", "azure-resource"),
        resource_ref=signal.resource_ref or "unknown-resource",
        status=status,
        severity=severity,
        current_value=metadata.get("current_value", "unavailable"),
        expected_value=metadata.get("expected_value", "unavailable"),
        rationale=signal.detail,
        source=metadata.get("source", signal.kind.value),
        collected_at=signal.occurred_at,
        evidence_refs=signal.evidence_refs,
        remediation=metadata.get("remediation", ""),
        validation=metadata.get("validation", ""),
        priority=priority,
        due_days=_non_negative_int(metadata.get("due_days")),
        applicability=_enum_or_default(
            ApplicabilityStatus,
            metadata.get("applicability"),
            ApplicabilityStatus.UNKNOWN,
        ),
        cve_ids=_split(metadata.get("cve_ids", "")),
        compliance_controls=_split(metadata.get("compliance_controls", "")),
        source_urls=_split(metadata.get("source_urls", "")),
        managed_service_note=metadata.get("managed_service_note", ""),
        patch_status=metadata.get("patch_status", ""),
    )


def _signal_to_finding(signal: ReportSignal) -> Finding:
    return Finding(
        rule_id=signal.metadata.get("rule_id", signal.signal_id),
        resource=ResourceRef(
            resource_type=signal.metadata.get("resource_type", "azure-resource"),
            ref=signal.resource_ref or "unknown-resource",
        ),
        severity=_severity(signal.severity.value),
        reason=signal.detail or signal.title,
        evidence_refs=signal.evidence_refs,
    )


def _source_coverage(
    controls: Sequence[SecurityControlObservation],
    errors: Sequence[tuple[str, str]],
    *,
    scope: str,
    assessed_at: datetime,
    freshness_ttl: timedelta,
) -> tuple[SecuritySourceCoverage, ...]:
    records: dict[str, list[SecurityControlObservation]] = {}
    for control in controls:
        records.setdefault(control.source, []).append(control)
    error_by_source = {name: _safe_source_error(error) for name, error in errors}
    names = sorted(set(records) | set(error_by_source))
    return tuple(
        SecuritySourceCoverage(
            source=name,
            status=_coverage_status(records.get(name, ()), has_error=name in error_by_source),
            record_count=len(records.get(name, ())),
            as_of=(
                as_of := max(
                    (item.collected_at for item in records.get(name, ())),
                    default=None,
                )
            ),
            scope=scope,
            error=error_by_source.get(name, ""),
            fresh=_freshness(as_of, assessed_at=assessed_at, ttl=freshness_ttl),
        )
        for name in names
    )


def _freshness(
    as_of: datetime | None,
    *,
    assessed_at: datetime,
    ttl: timedelta,
) -> bool | None:
    if as_of is None:
        return None
    age = assessed_at - as_of
    return timedelta(0) <= age <= ttl


def _safe_source_error(error: str) -> str:
    """Expose only a bounded exception class, never provider error detail."""

    kind = error.partition(":")[0].strip()
    return kind[:100] if kind else "SourceError"


def _coverage_status(
    controls: Sequence[SecurityControlObservation], *, has_error: bool
) -> SourceStatus:
    if not controls:
        return SourceStatus.UNAVAILABLE
    known = sum(control.status is not ControlStatus.UNKNOWN for control in controls)
    if known == 0:
        return SourceStatus.UNAVAILABLE
    if has_error or known < len(controls):
        return SourceStatus.PARTIAL
    return SourceStatus.AVAILABLE


def _summary_value(report: SecurityAssessment, *, field: str) -> DataSet:
    if field not in _SUMMARY_FIELDS:
        return DataSet(metadata={"unknown_summary_field": field})
    value: object = report.verdict.value if field == "verdict" else getattr(report, field)
    if not isinstance(value, (str, int, float)) and value is not None:
        value = str(value)
    return DataSet(scalar=value)


def _count_rows[K](counts: Mapping[K, int], *, label: str) -> DataSet:
    rows = tuple(
        {label: str(key), "label": str(key), "value": value}
        for key, value in sorted(counts.items(), key=lambda item: (-item[1], str(item[0])))
    )
    return DataSet(columns=(label, "value"), rows=rows)


def _control_status(controls: Sequence[SecurityControlObservation]) -> DataSet:
    status_map = {
        ControlStatus.PASS: "ok",
        ControlStatus.FAIL: "fail",
        ControlStatus.WARNING: "warn",
        ControlStatus.NOT_APPLICABLE: "unknown",
        ControlStatus.UNKNOWN: "unknown",
    }
    return DataSet(
        columns=("name", "status", "message", "at"),
        rows=tuple(
            {
                "name": control.title,
                "status": status_map[control.status],
                "message": f"{control.current_value} (expected {control.expected_value})",
                "at": control.collected_at.isoformat(),
            }
            for control in controls
        ),
    )


_CONTROL_COLUMNS = (
    "priority",
    "status",
    "severity",
    "category",
    "control",
    "resource_type",
    "resource_ref",
    "current_value",
    "expected_value",
    "applicability",
    "patch_status",
    "source",
    "collected_at",
    "rationale",
)


def _control_rows(controls: Sequence[SecurityControlObservation]) -> DataSet:
    return DataSet(
        columns=_CONTROL_COLUMNS,
        rows=tuple(
            {
                "priority": control.priority.value,
                "status": control.status.value,
                "severity": control.severity,
                "category": control.category,
                "control": control.title,
                "resource_type": control.resource_type,
                "resource_ref": control.resource_ref,
                "current_value": control.current_value,
                "expected_value": control.expected_value,
                "applicability": control.applicability.value,
                "patch_status": control.patch_status or "not_assessed",
                "source": control.source,
                "collected_at": control.collected_at.isoformat(),
                "rationale": control.rationale,
            }
            for control in controls
        ),
    )


def _recommendation_rows(report: SecurityAssessment) -> DataSet:
    columns = (
        "priority",
        "severity",
        "control_id",
        "resource_ref",
        "action",
        "validation",
        "due_at",
        "evidence_refs",
    )
    return DataSet(
        columns=columns,
        rows=tuple(
            {
                "priority": item.priority.value,
                "severity": item.severity,
                "control_id": item.control_id,
                "resource_ref": item.resource_ref,
                "action": item.action,
                "validation": item.validation,
                "due_at": item.due_at.isoformat() if item.due_at else "unassigned",
                "evidence_refs": ", ".join(item.evidence_refs),
            }
            for item in report.recommendations
        ),
    )


def _cve_rows(controls: Sequence[SecurityControlObservation]) -> DataSet:
    columns = (
        "cve_id",
        "control_id",
        "resource_ref",
        "severity",
        "applicability",
        "patch_status",
        "managed_service_note",
        "source_urls",
    )
    return DataSet(
        columns=columns,
        rows=tuple(
            {
                "cve_id": cve,
                "control_id": control.control_id,
                "resource_ref": control.resource_ref,
                "severity": control.severity,
                "applicability": control.applicability.value,
                "patch_status": control.patch_status or "not_assessed",
                "managed_service_note": control.managed_service_note,
                "source_urls": ", ".join(control.source_urls),
            }
            for control in controls
            for cve in control.cve_ids
        ),
    )


def _source_rows(sources: Sequence[SecuritySourceCoverage]) -> DataSet:
    columns = ("source", "status", "record_count", "as_of", "fresh", "scope", "error")
    return DataSet(
        columns=columns,
        rows=tuple(
            {
                "source": source.source,
                "status": source.status.value,
                "record_count": source.record_count,
                "as_of": source.as_of.isoformat() if source.as_of else "unavailable",
                "fresh": source.fresh if source.fresh is not None else "unknown",
                "scope": source.scope,
                "error": source.error,
            }
            for source in sources
        ),
    )


def _gap_rows(report: SecurityAssessment) -> DataSet:
    rows: list[dict[str, object]] = [
        {
            "gap_type": "control",
            "source": control.source,
            "subject": control.control_id,
            "detail": control.rationale or "Control could not be evaluated.",
        }
        for control in report.unknown_controls
    ]
    rows.extend(
        {
            "gap_type": "data_source",
            "source": source.source,
            "subject": source.scope or report.scope,
            "detail": source.error or source.status.value,
        }
        for source in report.source_coverage
        if source.status is not SourceStatus.AVAILABLE
    )
    rows.extend(
        {
            "gap_type": "finding_evidence",
            "source": "finding",
            "subject": entry.rule_id,
            "detail": "Finding has no evidence reference.",
        }
        for entry in report.entries
        if not entry.evidence_refs
    )
    return DataSet(columns=("gap_type", "source", "subject", "detail"), rows=tuple(rows))


def _resource_rows(controls: Sequence[SecurityControlObservation]) -> DataSet:
    grouped: dict[tuple[str, str], dict[str, object]] = {}
    for control in controls:
        key = (control.resource_type, control.resource_ref)
        row = grouped.setdefault(
            key,
            {
                "resource_type": control.resource_type,
                "resource_ref": control.resource_ref,
                "controls": 0,
                "pass": 0,
                "fail": 0,
                "warning": 0,
                "unknown": 0,
            },
        )
        row["controls"] = _row_int(row["controls"]) + 1
        status_key = (
            control.status.value
            if control.status is not ControlStatus.NOT_APPLICABLE
            else "unknown"
        )
        row[status_key] = _row_int(row[status_key]) + 1
    columns = ("resource_type", "resource_ref", "controls", "pass", "fail", "warning", "unknown")
    return DataSet(columns=columns, rows=tuple(grouped[key] for key in sorted(grouped)))


def _compliance_rows(controls: Sequence[SecurityControlObservation]) -> DataSet:
    columns = ("compliance_control", "control_id", "status", "resource_ref", "evidence_refs")
    return DataSet(
        columns=columns,
        rows=tuple(
            {
                "compliance_control": compliance,
                "control_id": control.control_id,
                "status": control.status.value,
                "resource_ref": control.resource_ref,
                "evidence_refs": ", ".join(control.evidence_refs),
            }
            for control in controls
            for compliance in control.compliance_controls
        ),
    )


def _evidence_rows(report: SecurityAssessment) -> DataSet:
    rows: list[dict[str, object]] = []
    for entry in report.entries:
        rows.extend(
            {
                "subject_type": "finding",
                "subject_id": entry.rule_id,
                "resource_ref": entry.resource_ref,
                "evidence_ref": evidence,
                "source_url": "",
            }
            for evidence in entry.evidence_refs
        )
    for control in report.controls:
        rows.extend(
            {
                "subject_type": "control",
                "subject_id": control.control_id,
                "resource_ref": control.resource_ref,
                "evidence_ref": evidence,
                "source_url": ", ".join(control.source_urls),
            }
            for evidence in control.evidence_refs
        )
    return DataSet(
        columns=("subject_type", "subject_id", "resource_ref", "evidence_ref", "source_url"),
        rows=tuple(rows),
    )


def _priority(
    raw: str | None,
    *,
    severity: Severity,
    status: ControlStatus,
) -> RemediationPriority:
    if raw:
        return _enum_or_default(RemediationPriority, raw, RemediationPriority.NONE)
    if status not in {ControlStatus.FAIL, ControlStatus.WARNING}:
        return RemediationPriority.NONE
    return _enum_or_default(RemediationPriority, severity, RemediationPriority.MEDIUM)


def _enum_or_default[E: StrEnum](enum_type: type[E], raw: str | None, default: E) -> E:
    try:
        return enum_type(str(raw))
    except ValueError:
        return default


def _non_negative_int(raw: str | None) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value >= 0 else None


def _row_int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _split(raw: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item.strip() for item in raw.split(",") if item.strip()))


def _severity(raw: str) -> Severity:
    if raw in {"low", "medium", "high", "critical"}:
        return cast(Severity, raw)
    return "medium"


__all__ = ["SecurityAssessmentDataSource"]
