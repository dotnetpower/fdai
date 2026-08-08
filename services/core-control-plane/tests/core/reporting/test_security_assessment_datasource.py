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
            applicability="applicable",
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
    assert by_source["inventory"]["fresh"] is True
    assert by_source["policy-compliance"]["status"] == "unavailable"
    assert by_source["policy-compliance"]["error"] == "RuntimeError"
    assert "provider unavailable" not in str(by_source["policy-compliance"])

    gaps = await _query("gap_rows")
    subjects = {row["subject"] for row in gaps.rows}
    assert {"patch-evidence", "subscription"} <= subjects


async def test_stale_source_is_counted_and_future_source_is_not_fresh() -> None:
    source = SecurityAssessmentDataSource(feed=_feed(), freshness_ttl=timedelta(minutes=30))
    stale = await source.query(
        QuerySpec(
            datasource="security_assessment",
            parameters={"projection": "summary_value", "field": "stale_source_count"},
        ),
        since=_NOW - timedelta(days=1),
        until=_NOW + timedelta(hours=1),
        variables={"scope": "subscription"},
    )
    assert stale.scalar == 2


def test_freshness_ttl_must_be_positive() -> None:
    with pytest.raises(ValueError, match="freshness_ttl"):
        SecurityAssessmentDataSource(feed=_feed(), freshness_ttl=timedelta(0))


async def test_latest_control_observation_wins_within_report_window() -> None:
    old = _control(
        "network-policy",
        status="fail",
        severity=Severity.HIGH,
        current_value="none",
    )
    new = ReportSignal(
        **{
            field: getattr(old, field)
            for field in old.__dataclass_fields__
            if field not in {"signal_id", "occurred_at", "metadata"}
        },
        signal_id="network-policy-new",
        occurred_at=_NOW + timedelta(minutes=1),
        metadata={**old.metadata, "status": "pass", "current_value": "azure"},
    )
    feed = ReportFeed((StaticSignalSource("history", (old, new)),))
    source = SecurityAssessmentDataSource(feed=feed)
    result = await source.query(
        QuerySpec(datasource="security_assessment", parameters={"projection": "control_rows"}),
        since=_NOW - timedelta(days=1),
        until=_NOW + timedelta(hours=1),
        variables={"scope": "subscription"},
    )

    assert len(result.rows) == 1
    assert result.rows[0]["status"] == "pass"
    assert result.rows[0]["current_value"] == "azure"


async def test_identical_window_cache_expires_and_refetches() -> None:
    class _CountingSource:
        name = "counting"

        def __init__(self) -> None:
            self.calls = 0

        async def signals(self, *, since: datetime, until: datetime):
            del since, until
            self.calls += 1
            return (_control("cache-control", status="pass", severity=Severity.LOW),)

    clock = {"now": 10.0}
    counter = _CountingSource()
    source = SecurityAssessmentDataSource(
        feed=ReportFeed((counter,)),
        cache_ttl=timedelta(seconds=5),
        monotonic_clock=lambda: clock["now"],
    )
    spec = QuerySpec(
        datasource="security_assessment",
        parameters={"projection": "summary_value", "field": "control_count"},
    )
    kwargs = {
        "since": _NOW - timedelta(days=1),
        "until": _NOW + timedelta(minutes=1),
        "variables": {"scope": "subscription"},
    }

    await source.query(spec, **kwargs)
    await source.query(spec, **kwargs)
    assert counter.calls == 1
    clock["now"] = 15.0
    await source.query(spec, **kwargs)
    assert counter.calls == 2


def test_cache_ttl_must_be_positive() -> None:
    with pytest.raises(ValueError, match="cache_ttl"):
        SecurityAssessmentDataSource(feed=_feed(), cache_ttl=timedelta(0))


async def test_security_assessment_report_renders_every_widget() -> None:
    engine, _ = default_reporting_engine(
        reports_root=__import__("pathlib").Path(__file__).resolve().parents[5]
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
