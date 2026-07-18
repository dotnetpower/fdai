"""Deep security-assessment datasource and report rendering tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fdai.core.report_feed import ReportFeed, StaticSignalSource
from fdai.core.report_feed.models import (
    ReportCategory,
    ReportSignal,
    SignalKind,
)
from fdai.core.reporting.composition import default_reporting_engine
from fdai.core.reporting.datasources import SecurityAssessmentDataSource
from fdai.core.reporting.models import QuerySpec, RenderedWidget
from fdai.shared.contracts.models import Severity

_NOW = datetime(2026, 7, 18, 0, 0, tzinfo=UTC)


class _FailingSource:
    @property
    def name(self) -> str:
        return "policy-compliance"

    async def signals(self, *, since: datetime, until: datetime):
        del since, until
        raise RuntimeError("provider unavailable")


def _control(
    signal_id: str,
    *,
    status: str,
    severity: Severity,
    evidence: tuple[str, ...] = ("arg:snapshot",),
    **metadata: str,
) -> ReportSignal:
    return ReportSignal(
        signal_id=signal_id,
        kind=SignalKind.SECURITY_ASSESSMENT,
        category=ReportCategory.SECURITY,
        severity=severity,
        resource_ref=metadata.pop("resource_ref", "rg-example/aks-example"),
        title=metadata.pop("title", signal_id.replace("-", " ").title()),
        detail=metadata.pop("detail", "Observed configuration differs from the baseline."),
        occurred_at=_NOW,
        evidence_refs=evidence,
        metadata={
            "control_id": signal_id,
            "control_category": metadata.pop("category", "identity"),
            "status": status,
            "resource_type": metadata.pop("resource_type", "kubernetes-cluster"),
            "current_value": metadata.pop("current_value", "disabled"),
            "expected_value": metadata.pop("expected_value", "enabled"),
            "source": metadata.pop("source", "inventory"),
            **metadata,
        },
    )


def _feed() -> ReportFeed:
    signals = (
        _control(
            "private-api",
            status="pass",
            severity=Severity.HIGH,
            current_value="enabled",
            compliance_controls="CIS-1.1",
        ),
        _control(
            "identity-integration",
            status="fail",
            severity=Severity.HIGH,
            priority="critical",
            due_days="1",
            remediation="Enable managed identity integration.",
            validation="Verify group-based access.",
            cve_ids="CVE-2099-0001",
            patch_status="affected",
            compliance_controls="CIS-2.1,MCSB-IM-1",
            source_urls="https://example.com/advisory",
        ),
        _control(
            "patch-evidence",
            status="unknown",
            severity=Severity.MEDIUM,
            evidence=(),
            source="vulnerability-feed",
            applicability="unknown",
        ),
        ReportSignal(
            signal_id="waf-event",
            kind=SignalKind.INVESTIGATION,
            category=ReportCategory.SECURITY,
            severity=Severity.CRITICAL,
            resource_ref="rg-example/gateway-example",
            title="Blocked injection pattern",
            detail="WAF blocked a confirmed injection signature.",
            occurred_at=_NOW,
            evidence_refs=("log:waf-event",),
            metadata={"rule_id": "appgw-waf:942100", "resource_type": "application-gateway"},
        ),
    )
    return ReportFeed((StaticSignalSource("security-controls", signals), _FailingSource()))


async def _query(projection: str, **parameters: str):
    source = SecurityAssessmentDataSource(feed=_feed())
    return await source.query(
        QuerySpec(
            datasource="security_assessment",
            parameters={"projection": projection, **parameters},
        ),
        since=_NOW - timedelta(days=1),
        until=_NOW + timedelta(minutes=1),
        variables={"scope": "subscription"},
    )


@pytest.mark.parametrize(
    ("field", "expected"),
    (
        ("verdict", "critical"),
        ("completion_status", "partial"),
        ("control_count", 3),
        ("affected_resource_count", 2),
        ("recommendation_count", 1),
        ("applicable_cve_count", 1),
    ),
)
async def test_summary_projections(field: str, expected: object) -> None:
    result = await _query("summary_value", field=field)
    assert result.scalar == expected


@pytest.mark.parametrize(
    "projection",
    (
        "severity_counts",
        "category_counts",
        "resource_type_counts",
        "control_status",
        "control_rows",
        "recommendation_rows",
        "cve_rows",
        "source_rows",
        "positive_rows",
        "gap_rows",
        "resource_rows",
        "compliance_rows",
        "evidence_rows",
    ),
)
async def test_tabular_projections_are_populated(projection: str) -> None:
    result = await _query(projection)
    assert result.rows


async def test_control_rows_preserve_reference_document_depth() -> None:
    result = await _query("control_rows")
    by_control = {row["control"]: row for row in result.rows}
    failed = by_control["Identity Integration"]
    assert failed["status"] == "fail"
    assert failed["current_value"] == "disabled"
    assert failed["expected_value"] == "enabled"
    assert failed["source"] == "inventory"
    assert failed["resource_type"] == "kubernetes-cluster"


async def test_source_failure_and_unknown_control_remain_visible() -> None:
    sources = await _query("source_rows")
    by_source = {row["source"]: row for row in sources.rows}
    assert by_source["inventory"]["status"] == "available"
    assert by_source["policy-compliance"]["status"] == "unavailable"

    gaps = await _query("gap_rows")
    subjects = {row["subject"] for row in gaps.rows}
    assert {"patch-evidence", "subscription"} <= subjects


async def test_security_assessment_report_renders_every_widget() -> None:
    engine, _ = default_reporting_engine(
        reports_root=__import__("pathlib").Path(__file__).resolve().parents[3]
        / "rule-catalog"
        / "reports",
        report_feed=_feed(),
    )
    rendered = await engine.render("security-assessment", variables={"scope": "subscription"})
    widgets = tuple(_walk(rendered.widgets))
    assert len(widgets) >= 20
    assert all(widget.error is None for widget in widgets)
    assert rendered.provenance.availability == "available"
    by_id = {widget.id: widget for widget in widgets}
    assert by_id["verdict"].data["value"] == "critical"
    assert by_id["controls"].data["total_rows"] == 3
    assert by_id["gaps"].data["total_rows"] >= 2


def _walk(widgets: tuple[RenderedWidget, ...]):
    for widget in widgets:
        yield widget
        yield from _walk(widget.children)
