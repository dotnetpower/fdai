"""MetricProvider bridge for operational insight evaluation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fdai.core.detection import (
    InsightOperator,
    InsightRecipe,
    OperationalInsightEngine,
    OperationalInsightSource,
)
from fdai.shared.contracts.models import Category, Severity
from fdai.shared.providers.metric import (
    MetricPoint,
    MetricProviderError,
    MetricQuery,
    StaticMetricProvider,
)

_NOW = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)
_RESOURCE = "resource:example/service-a"


def _recipe(
    recipe_id: str,
    operator: InsightOperator,
    metric: str,
    threshold: float,
    *,
    min_samples: int = 1,
) -> InsightRecipe:
    return InsightRecipe(
        recipe_id=recipe_id,
        title=recipe_id,
        category=Category.RELIABILITY,
        severity=Severity.HIGH,
        operator=operator,
        metric=metric,
        threshold=threshold,
        min_samples=min_samples,
    )


def _point(metric: str, minutes_ago: int, value: float) -> MetricPoint:
    return MetricPoint(
        metric_name=metric,
        at=_NOW - timedelta(minutes=minutes_ago),
        value=value,
        labels={"resource_id": _RESOURCE},
    )


async def test_source_builds_current_previous_and_baseline_values() -> None:
    recipes = [
        _recipe("cpu.high", InsightOperator.ABOVE, "cpu", 90, min_samples=3),
        _recipe("cpu.change", InsightOperator.PERCENT_CHANGE_ABOVE, "cpu", 50),
    ]
    provider = StaticMetricProvider(
        [_point("cpu", 3, 10), _point("cpu", 2, 10), _point("cpu", 1, 100)]
    )
    findings = await OperationalInsightSource(provider).evaluate(
        OperationalInsightEngine(recipes),
        resource_ref=_RESOURCE,
        since=_NOW - timedelta(minutes=5),
        until=_NOW,
        window_bucket="2026-07-18T12:00Z",
    )
    assert {finding.recipe_id for finding in findings} == {"cpu.high", "cpu.change"}
    change = next(finding for finding in findings if finding.recipe_id == "cpu.change")
    assert change.reference == 10
    assert change.score == 900


async def test_successful_empty_query_can_fire_absence() -> None:
    recipe = _recipe("process.missing", InsightOperator.ABSENT, "process.heartbeat", 1)
    findings = await OperationalInsightSource(StaticMetricProvider([])).evaluate(
        OperationalInsightEngine([recipe]),
        resource_ref=_RESOURCE,
        since=_NOW - timedelta(minutes=5),
        until=_NOW,
        window_bucket="window",
    )
    assert [finding.recipe_id for finding in findings] == ["process.missing"]


class _UnavailableProvider:
    async def query(self, query: MetricQuery):
        raise MetricProviderError(f"unavailable: {query.metric_name}")
        yield  # pragma: no cover - async generator marker


async def test_provider_failure_never_fires_absence() -> None:
    recipe = _recipe("process.missing", InsightOperator.ABSENT, "process.heartbeat", 1)
    findings = await OperationalInsightSource(_UnavailableProvider()).evaluate(
        OperationalInsightEngine([recipe]),
        resource_ref=_RESOURCE,
        since=_NOW - timedelta(minutes=5),
        until=_NOW,
        window_bucket="window",
    )
    assert findings == ()


async def test_stale_recipe_expands_its_query_window() -> None:
    recipe = _recipe("backup.stale", InsightOperator.STALE, "backup.last_success", 3600)
    provider = StaticMetricProvider([_point("backup.last_success", 90, 1)])
    findings = await OperationalInsightSource(provider).evaluate(
        OperationalInsightEngine([recipe]),
        resource_ref=_RESOURCE,
        since=_NOW - timedelta(minutes=5),
        until=_NOW,
        window_bucket="window",
    )
    assert [finding.recipe_id for finding in findings] == ["backup.stale"]
