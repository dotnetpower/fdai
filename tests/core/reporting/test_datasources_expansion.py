"""Tests for the batch-7 datasource expansion:
- new audit projections (count_by_correlation, series_hourly, series_daily)
- new report_feed projections (count_by_resource, latest_per_resource)
- metric percentiles projection
- log_query pattern_group, series_hourly projections
- new datasources: CallableDataSource, FilesystemManifestDataSource
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fdai.core.report_feed.feed import ReportFeed, StaticSignalSource
from fdai.core.report_feed.models import ReportCategory, ReportSignal, SignalKind
from fdai.core.reporting.datasources import (
    AuditDataSource,
    CallableDataSource,
    FilesystemManifestDataSource,
    LogQueryDataSource,
    MetricDataSource,
    ReportFeedDataSource,
)
from fdai.core.reporting.models import DataSet, QuerySpec
from fdai.delivery.read_api.read_model import InMemoryConsoleReadModel
from fdai.shared.contracts.models import Severity
from fdai.shared.providers.log_query import LogRecord, StaticLogQueryProvider
from fdai.shared.providers.metric import MetricPoint, StaticMetricProvider

_NOW = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)


class TestAuditProjections:
    async def _reader(self) -> InMemoryConsoleReadModel:
        reader = InMemoryConsoleReadModel()
        for i, corr in enumerate(["c1", "c1", "c2"]):
            reader.record_audit_entry(
                {
                    "event_id": f"00000000-0000-0000-0000-{i:012d}",
                    "correlation_id": corr,
                    "recorded_at": (_NOW - timedelta(minutes=i * 40)).isoformat(),
                },
                actor="thor",
                action_kind="execute_action",
                mode="shadow",
            )
        return reader

    async def test_count_by_correlation(self) -> None:
        reader = await self._reader()
        ds = AuditDataSource(reader=reader)
        result = await ds.query(
            QuerySpec(datasource="audit", parameters={"projection": "count_by_correlation"}),
            since=_NOW - timedelta(hours=6),
            until=_NOW + timedelta(minutes=1),
            variables={},
        )
        by_corr = {row["correlation_id"]: row["value"] for row in result.rows}
        assert by_corr == {"c1": 2, "c2": 1}

    async def test_series_hourly(self) -> None:
        reader = await self._reader()
        ds = AuditDataSource(reader=reader)
        result = await ds.query(
            QuerySpec(datasource="audit", parameters={"projection": "series_hourly"}),
            since=_NOW - timedelta(hours=6),
            until=_NOW + timedelta(minutes=1),
            variables={},
        )
        assert len(result.series) == 1
        # 3 audit entries at 40-min gaps land in 2 hour-buckets.
        assert len(result.series[0].points) >= 1
        assert result.metadata["bucket"] == "hour"

    async def test_series_daily(self) -> None:
        reader = await self._reader()
        ds = AuditDataSource(reader=reader)
        result = await ds.query(
            QuerySpec(datasource="audit", parameters={"projection": "series_daily"}),
            since=_NOW - timedelta(days=1),
            until=_NOW + timedelta(minutes=1),
            variables={},
        )
        assert result.metadata["bucket"] == "day"


class TestReportFeedProjections:
    def _feed(self) -> ReportFeed:
        signals = [
            ReportSignal(
                signal_id="s1",
                kind=SignalKind.INVESTIGATION,
                category=ReportCategory.WORKLOAD,
                severity=Severity.HIGH,
                resource_ref="rg/vm-01",
                title="one",
                detail="",
                occurred_at=_NOW - timedelta(minutes=10),
            ),
            ReportSignal(
                signal_id="s2",
                kind=SignalKind.INVESTIGATION,
                category=ReportCategory.WORKLOAD,
                severity=Severity.CRITICAL,
                resource_ref="rg/vm-01",
                title="two",
                detail="",
                occurred_at=_NOW - timedelta(minutes=5),
            ),
            ReportSignal(
                signal_id="s3",
                kind=SignalKind.SECURITY_ASSESSMENT,
                category=ReportCategory.SECURITY,
                severity=Severity.MEDIUM,
                resource_ref="rg/kv-01",
                title="three",
                detail="",
                occurred_at=_NOW - timedelta(minutes=15),
            ),
        ]
        return ReportFeed((StaticSignalSource("t", signals),))

    async def test_count_by_resource(self) -> None:
        ds = ReportFeedDataSource(feed=self._feed())
        result = await ds.query(
            QuerySpec(datasource="rf", parameters={"projection": "count_by_resource"}),
            since=_NOW - timedelta(hours=1),
            until=_NOW + timedelta(minutes=1),
            variables={},
        )
        by_res = {row["resource_ref"]: row["value"] for row in result.rows}
        assert by_res == {"rg/vm-01": 2, "rg/kv-01": 1}

    async def test_latest_per_resource(self) -> None:
        ds = ReportFeedDataSource(feed=self._feed())
        result = await ds.query(
            QuerySpec(datasource="rf", parameters={"projection": "latest_per_resource"}),
            since=_NOW - timedelta(hours=1),
            until=_NOW + timedelta(minutes=1),
            variables={},
        )
        # rg/vm-01 -> most recent is s2 (the CRITICAL one).
        by_res = {row["resource_ref"]: row["signal_id"] for row in result.rows}
        assert by_res == {"rg/vm-01": "s2", "rg/kv-01": "s3"}


class TestMetricPercentiles:
    async def test_percentiles_from_samples(self) -> None:
        samples = [
            MetricPoint(metric_name="lat", at=_NOW, value=float(v))
            for v in range(1, 101)  # 1..100
        ]
        ds = MetricDataSource(provider=StaticMetricProvider(samples))
        result = await ds.query(
            QuerySpec(
                datasource="metric",
                parameters={"metric_name": "lat", "projection": "percentiles"},
            ),
            since=_NOW - timedelta(hours=1),
            until=_NOW + timedelta(minutes=1),
            variables={},
        )
        by_pct = {row["percentile"]: row["value"] for row in result.rows}
        # Nearest-rank estimator on [1..100]: p50 is around the median,
        # p99 near the top. Loose bounds keep the test robust to the
        # exact rounding rule.
        assert 49 <= by_pct["p50"] <= 51
        assert by_pct["p99"] >= 98


class TestLogQueryProjectionsExtra:
    async def test_pattern_group(self) -> None:
        provider = StaticLogQueryProvider(
            (
                LogRecord(at=_NOW, body="error unable to connect", severity="error"),
                LogRecord(at=_NOW, body="error timeout waiting", severity="error"),
                LogRecord(at=_NOW, body="warn slow query 200ms", severity="warning"),
            )
        )
        ds = LogQueryDataSource(provider=provider)
        result = await ds.query(
            QuerySpec(
                datasource="log_query",
                parameters={"expression": "error", "projection": "pattern_group"},
            ),
            since=_NOW - timedelta(hours=1),
            until=_NOW + timedelta(minutes=1),
            variables={},
        )
        heads = {row["pattern"] for row in result.rows}
        # `error` records match the substring filter and cluster to
        # head 'error'; `warn` records are filtered out.
        assert "error" in heads

    async def test_series_hourly(self) -> None:
        provider = StaticLogQueryProvider(
            (
                LogRecord(at=_NOW, body="x", severity="info"),
                LogRecord(
                    at=_NOW - timedelta(hours=1),
                    body="x",
                    severity="info",
                ),
            )
        )
        ds = LogQueryDataSource(provider=provider)
        result = await ds.query(
            QuerySpec(
                datasource="log_query",
                parameters={"expression": "x", "projection": "series_hourly"},
            ),
            since=_NOW - timedelta(hours=2),
            until=_NOW + timedelta(minutes=1),
            variables={},
        )
        assert result.metadata["bucket"] == "hour"
        assert len(result.series[0].points) == 2


class TestCallableDataSource:
    async def test_sync_callable_ok(self) -> None:
        def _fn(spec, *, since, until, variables):
            return DataSet(scalar=variables.get("value", "unset"))

        ds = CallableDataSource(name="fn", fn=_fn)
        result = await ds.query(
            QuerySpec(datasource="fn"),
            since=_NOW,
            until=_NOW,
            variables={"value": "hi"},
        )
        assert result.scalar == "hi"

    async def test_async_callable_ok(self) -> None:
        async def _fn(spec, *, since, until, variables):
            return DataSet(scalar=42)

        ds = CallableDataSource(name="fn", fn=_fn)
        result = await ds.query(
            QuerySpec(datasource="fn"),
            since=_NOW,
            until=_NOW,
            variables={},
        )
        assert result.scalar == 42

    async def test_callable_must_return_dataset(self) -> None:
        ds = CallableDataSource(name="fn", fn=lambda *a, **kw: "nope")
        with pytest.raises(TypeError, match="expected DataSet"):
            await ds.query(
                QuerySpec(datasource="fn"),
                since=_NOW,
                until=_NOW,
                variables={},
            )


class TestFilesystemManifestDataSource:
    async def test_rows_projection_returns_files(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "b.txt").write_text("world", encoding="utf-8")
        ds = FilesystemManifestDataSource(root=tmp_path)
        result = await ds.query(
            QuerySpec(datasource="fs", parameters={"pattern": "**/*"}),
            since=_NOW,
            until=_NOW,
            variables={},
        )
        paths = {row["path"] for row in result.rows}
        assert paths == {"a.txt", "sub/b.txt"}

    async def test_traversal_pattern_rejected(self, tmp_path: Path) -> None:
        ds = FilesystemManifestDataSource(root=tmp_path)
        result = await ds.query(
            QuerySpec(datasource="fs", parameters={"pattern": "../*"}),
            since=_NOW,
            until=_NOW,
            variables={},
        )
        assert result.metadata.get("error") is not None

    async def test_count_total_projection(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("x", encoding="utf-8")
        ds = FilesystemManifestDataSource(root=tmp_path)
        result = await ds.query(
            QuerySpec(datasource="fs", parameters={"projection": "count_total"}),
            since=_NOW,
            until=_NOW,
            variables={},
        )
        assert result.scalar == 1
