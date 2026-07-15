"""Datasource-adapter tests using upstream fakes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fdai.core.report_feed.feed import ReportFeed, StaticSignalSource
from fdai.core.report_feed.models import ReportCategory, ReportSignal, SignalKind
from fdai.core.reporting.datasources import (
    AuditDataSource,
    LogQueryDataSource,
    MetricDataSource,
    NoopDataSource,
    ReportFeedDataSource,
    StaticDataSource,
)
from fdai.core.reporting.models import DataSet, QuerySpec, Series
from fdai.delivery.read_api.read_model import InMemoryConsoleReadModel
from fdai.shared.contracts.models import Severity
from fdai.shared.providers.log_query import (
    LogRecord,
    StaticLogQueryProvider,
)
from fdai.shared.providers.metric import (
    MetricPoint,
    NoopMetricProvider,
    StaticMetricProvider,
)

_NOW = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)
_HOUR_AGO = _NOW - timedelta(hours=1)


class TestStaticAndNoop:
    async def test_static_returns_fixed_dataset(self) -> None:
        ds = StaticDataSource(name="s", dataset=DataSet(scalar=99))
        result = await ds.query(
            QuerySpec(datasource="s"),
            since=_HOUR_AGO,
            until=_NOW,
            variables={},
        )
        assert result.scalar == 99

    async def test_noop_returns_empty(self) -> None:
        ds = NoopDataSource()
        result = await ds.query(
            QuerySpec(datasource="noop"),
            since=_HOUR_AGO,
            until=_NOW,
            variables={},
        )
        assert result == DataSet()


class TestAuditDataSource:
    def _seeded_reader(self) -> InMemoryConsoleReadModel:
        reader = InMemoryConsoleReadModel()
        for i, (kind, mode, actor) in enumerate(
            [
                ("execute_action", "shadow", "thor"),
                ("execute_action", "enforce", "thor"),
                ("approve_action", "enforce", "var"),
            ]
        ):
            reader.record_audit_entry(
                {
                    "event_id": f"00000000-0000-0000-0000-{i:012d}",
                    "recorded_at": (_NOW - timedelta(minutes=(2 - i) * 10)).isoformat(),
                },
                actor=actor,
                action_kind=kind,
                mode=mode,
            )
        return reader

    async def test_rows_projection_covers_window(self) -> None:
        reader = self._seeded_reader()
        ds = AuditDataSource(reader=reader)
        result = await ds.query(
            QuerySpec(datasource="audit", parameters={"projection": "rows"}),
            since=_NOW - timedelta(hours=1),
            until=_NOW + timedelta(minutes=1),
            variables={},
        )
        assert len(result.rows) == 3
        assert "seq" in result.columns

    async def test_count_by_action_kind(self) -> None:
        reader = self._seeded_reader()
        ds = AuditDataSource(reader=reader)
        result = await ds.query(
            QuerySpec(
                datasource="audit",
                parameters={"projection": "count_by_action_kind"},
            ),
            since=_HOUR_AGO,
            until=_NOW + timedelta(minutes=1),
            variables={},
        )
        by_kind = {row["action_kind"]: row["value"] for row in result.rows}
        assert by_kind == {"execute_action": 2, "approve_action": 1}

    async def test_count_total_is_scalar(self) -> None:
        reader = self._seeded_reader()
        ds = AuditDataSource(reader=reader)
        result = await ds.query(
            QuerySpec(
                datasource="audit",
                parameters={"projection": "count_total"},
            ),
            since=_HOUR_AGO,
            until=_NOW + timedelta(minutes=1),
            variables={},
        )
        assert result.scalar == 3

    async def test_rca_dossier_projections_are_correlation_scoped(self) -> None:
        reader = InMemoryConsoleReadModel()
        reader.record_audit_entry(
            {
                "event_id": "00000000-0000-0000-0000-000000000001",
                "correlation_id": "corr-target",
                "rca_tier": "t1",
                "rca_outcome": "grounded",
                "rca_cause": "configuration change preceded failure",
                "rca_confidence": 0.82,
                "incident_id": "incident-1",
                "incident_title": "API latency after rollout",
                "severity": "critical",
                "status": "resolved",
                "vertical": "change_safety",
                "rca_citations": [
                    {
                        "kind": "change",
                        "ref": "change-1",
                        "summary": "Connection limit changed",
                        "freshness": "current",
                    }
                ],
                "rca_causal_chain": {
                    "hops": [
                        {
                            "cause_event_id": "change-1",
                            "cause_resource_ref": "service-a",
                            "relationship": "dependency",
                            "effect_event_id": "failure-1",
                            "effect_resource_ref": "service-b",
                            "lead_seconds": 75.0,
                            "confidence": 0.82,
                        }
                    ]
                },
                "rca_impact": [
                    {
                        "metric": "API p95 latency",
                        "observed": 1840,
                        "threshold": 750,
                        "unit": "ms",
                        "impact": "Latency objective breached",
                        "evidence_ref": "metric:latency",
                    }
                ],
                "rca_contributing_factors": [
                    {"category": "capacity", "factor": "No pool headroom alert"}
                ],
                "rca_alternative_hypotheses": [
                    {"hypothesis": "Compute saturation", "status": "excluded"}
                ],
                "rca_recovery_validation": [
                    {"metric": "API p95 latency", "after": "340 ms", "status": "passed"}
                ],
                "rca_control_gaps": [
                    {"control": "Capacity guard", "gap": "No pre-deploy pool check"}
                ],
                "rca_recommendations": [
                    {"priority": "P0", "action": "Add connection headroom preflight"}
                ],
                "rca_limitations": [{"limitation": "Retry volume was sampled", "status": "open"}],
                "recorded_at": _NOW.isoformat(),
            },
            action_kind="rca.hypothesis",
        )
        reader.record_audit_entry(
            {
                "event_id": "00000000-0000-0000-0000-000000000002",
                "correlation_id": "corr-other",
                "rca_tier": "t0",
                "recorded_at": _NOW.isoformat(),
            },
            action_kind="rca.hypothesis",
        )
        datasource = AuditDataSource(reader=reader)
        common = {
            "since": _HOUR_AGO,
            "until": _NOW + timedelta(minutes=1),
            "variables": {"correlation_id": "corr-target"},
        }
        hypotheses = await datasource.query(
            QuerySpec(datasource="audit", parameters={"projection": "rca_hypotheses"}),
            **common,
        )
        citations = await datasource.query(
            QuerySpec(datasource="audit", parameters={"projection": "rca_citations"}),
            **common,
        )
        hops = await datasource.query(
            QuerySpec(datasource="audit", parameters={"projection": "rca_causal_hops"}),
            **common,
        )
        assert len(hypotheses.rows) == 1
        assert hypotheses.rows[0]["tier"] == "t1"
        assert citations.rows[0]["ref"] == "change-1"
        assert citations.rows[0]["summary"] == "Connection limit changed"
        assert hops.rows[0]["lead_seconds"] == 75.0

        async def projection(name: str) -> DataSet:
            return await datasource.query(
                QuerySpec(datasource="audit", parameters={"projection": name}),
                **common,
            )

        profile = await projection("rca_incident_profile")
        impact = await projection("rca_impact")
        factors = await projection("rca_contributing_factors")
        alternatives = await projection("rca_alternative_hypotheses")
        recovery = await projection("rca_recovery_validation")
        gaps = await projection("rca_control_gaps")
        recommendations = await projection("rca_recommendations")
        limitations = await projection("rca_limitations")
        assert profile.rows[0]["incident_id"] == "incident-1"
        assert impact.rows[0]["observed"] == 1840
        assert factors.rows[0]["category"] == "capacity"
        assert alternatives.rows[0]["status"] == "excluded"
        assert recovery.rows[0]["status"] == "passed"
        assert gaps.rows[0]["control"] == "Capacity guard"
        assert recommendations.rows[0]["priority"] == "P0"
        assert limitations.rows[0]["status"] == "open"


class TestReportFeedDataSource:
    def _feed(self) -> ReportFeed:
        signals = [
            ReportSignal(
                signal_id="s1",
                kind=SignalKind.INVESTIGATION,
                category=ReportCategory.WORKLOAD,
                severity=Severity.HIGH,
                resource_ref="rg-a/vm-01",
                title="cpu spike",
                detail="",
                occurred_at=_NOW - timedelta(minutes=30),
            ),
            ReportSignal(
                signal_id="s2",
                kind=SignalKind.SECURITY_ASSESSMENT,
                category=ReportCategory.SECURITY,
                severity=Severity.CRITICAL,
                resource_ref="rg-a/kv-01",
                title="public endpoint",
                detail="",
                occurred_at=_NOW - timedelta(minutes=15),
            ),
        ]
        return ReportFeed((StaticSignalSource("test", signals),))

    async def test_rows_projection_carries_all_signals(self) -> None:
        ds = ReportFeedDataSource(feed=self._feed())
        result = await ds.query(
            QuerySpec(datasource="report_feed"),
            since=_HOUR_AGO,
            until=_NOW + timedelta(minutes=1),
            variables={},
        )
        titles = {row["title"] for row in result.rows}
        assert titles == {"cpu spike", "public endpoint"}

    async def test_category_filter_forwarded(self) -> None:
        ds = ReportFeedDataSource(feed=self._feed())
        result = await ds.query(
            QuerySpec(
                datasource="report_feed",
                parameters={"category": "security"},
            ),
            since=_HOUR_AGO,
            until=_NOW + timedelta(minutes=1),
            variables={},
        )
        assert len(result.rows) == 1
        assert result.rows[0]["category"] == "security"

    async def test_count_by_severity(self) -> None:
        ds = ReportFeedDataSource(feed=self._feed())
        result = await ds.query(
            QuerySpec(
                datasource="report_feed",
                parameters={"projection": "count_by_severity"},
            ),
            since=_HOUR_AGO,
            until=_NOW + timedelta(minutes=1),
            variables={},
        )
        by_sev = {row["severity"]: row["value"] for row in result.rows}
        assert by_sev == {"high": 1, "critical": 1}


class TestMetricDataSource:
    async def test_series_grouped_by_label(self) -> None:
        samples = [
            MetricPoint(
                metric_name="cpu.pct",
                at=_NOW - timedelta(minutes=10),
                value=10.0,
                labels={"host": "a"},
            ),
            MetricPoint(
                metric_name="cpu.pct",
                at=_NOW - timedelta(minutes=5),
                value=20.0,
                labels={"host": "a"},
            ),
            MetricPoint(
                metric_name="cpu.pct",
                at=_NOW - timedelta(minutes=5),
                value=99.0,
                labels={"host": "b"},
            ),
        ]
        provider = StaticMetricProvider(samples)
        ds = MetricDataSource(provider=provider)
        result = await ds.query(
            QuerySpec(
                datasource="metric",
                parameters={"metric_name": "cpu.pct", "group_by": ["host"]},
            ),
            since=_HOUR_AGO,
            until=_NOW,
            variables={},
        )
        series_by_host = {s.labels.get("host"): s for s in result.series}
        assert set(series_by_host) == {"a", "b"}
        assert len(series_by_host["a"].points) == 2

    async def test_scalar_sum_projection(self) -> None:
        provider = StaticMetricProvider(
            [
                MetricPoint(
                    metric_name="cost.usd",
                    at=_NOW - timedelta(minutes=15),
                    value=3.5,
                ),
                MetricPoint(
                    metric_name="cost.usd",
                    at=_NOW - timedelta(minutes=5),
                    value=1.5,
                ),
            ]
        )
        ds = MetricDataSource(provider=provider)
        result = await ds.query(
            QuerySpec(
                datasource="metric",
                parameters={
                    "metric_name": "cost.usd",
                    "projection": "scalar_sum",
                },
            ),
            since=_HOUR_AGO,
            until=_NOW,
            variables={},
        )
        assert result.scalar == pytest.approx(5.0)

    async def test_missing_metric_name_returns_error_metadata(self) -> None:
        ds = MetricDataSource(provider=NoopMetricProvider())
        result = await ds.query(
            QuerySpec(datasource="metric", parameters={}),
            since=_HOUR_AGO,
            until=_NOW,
            variables={},
        )
        assert result.metadata.get("error") == "metric_name required"

    async def test_ungrouped_falls_into_single_series(self) -> None:
        provider = StaticMetricProvider(
            [
                MetricPoint(
                    metric_name="requests",
                    at=_NOW - timedelta(minutes=1),
                    value=1.0,
                ),
            ]
        )
        ds = MetricDataSource(provider=provider)
        result = await ds.query(
            QuerySpec(
                datasource="metric",
                parameters={"metric_name": "requests"},
            ),
            since=_HOUR_AGO,
            until=_NOW,
            variables={},
        )
        assert len(result.series) == 1
        assert result.series[0].label == "all"


class TestLogQueryDataSource:
    def _provider(self) -> StaticLogQueryProvider:
        return StaticLogQueryProvider(
            (
                LogRecord(at=_NOW, body="error boom", severity="error"),
                LogRecord(at=_NOW, body="warning ", severity="warning"),
                LogRecord(at=_NOW, body="error other", severity="error"),
            )
        )

    async def test_rows_projection(self) -> None:
        ds = LogQueryDataSource(provider=self._provider())
        result = await ds.query(
            QuerySpec(
                datasource="log_query",
                parameters={"expression": "error", "limit": 100},
            ),
            since=_HOUR_AGO,
            until=_NOW + timedelta(minutes=1),
            variables={},
        )
        assert len(result.rows) == 2
        assert result.rows[0]["severity"] == "error"

    async def test_count_by_severity_projection(self) -> None:
        ds = LogQueryDataSource(provider=self._provider())
        result = await ds.query(
            QuerySpec(
                datasource="log_query",
                parameters={
                    "expression": "error",
                    "projection": "count_by_severity",
                },
            ),
            since=_HOUR_AGO,
            until=_NOW + timedelta(minutes=1),
            variables={},
        )
        # Static provider filters by substring; both matching records
        # are severity=error.
        by_sev = {row["severity"]: row["value"] for row in result.rows}
        assert by_sev == {"error": 2}

    async def test_missing_expression_returns_error(self) -> None:
        ds = LogQueryDataSource(provider=self._provider())
        result = await ds.query(
            QuerySpec(datasource="log_query", parameters={}),
            since=_HOUR_AGO,
            until=_NOW,
            variables={},
        )
        assert result.metadata.get("error") == "expression required"


def test_series_shape_unaffected_by_datasource() -> None:
    # A regression sanity check: the widget builders (tested separately)
    # depend on `Series` being tuple-of-tuples. Nothing in this module
    # should implicitly change that shape.
    dataset = DataSet(series=(Series(label="x", points=((1.0, 2.0),)),))
    assert isinstance(dataset.series[0].points, tuple)
