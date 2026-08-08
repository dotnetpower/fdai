"""Operational insight catalog validation and executable coverage."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fdai.core.detection.insights import (
    InsightObservation,
    InsightOperator,
    InsightRecipe,
    OperationalInsightEngine,
)
from fdai.rule_catalog.schema.operational_insight import load_operational_insight_recipes

_ROOT = Path(__file__).parents[5]
_CATALOG = _ROOT / "rule-catalog" / "operational-insights" / "catalog.yaml"
_NOW = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)


def _firing_observation(recipe: InsightRecipe) -> InsightObservation:
    values: dict[str, float] = {}
    previous: dict[str, float] = {}
    baselines: dict[str, float] = {}
    last_seen: dict[str, datetime] = {}

    if recipe.operator is InsightOperator.ABOVE:
        values[recipe.metric] = recipe.threshold + 1.0
    elif recipe.operator is InsightOperator.BELOW:
        values[recipe.metric] = recipe.threshold - 1.0
    elif recipe.operator is InsightOperator.DELTA_ABOVE:
        previous[recipe.metric] = 100.0
        values[recipe.metric] = 101.0 + recipe.threshold
    elif recipe.operator is InsightOperator.DELTA_BELOW:
        previous[recipe.metric] = 100.0
        values[recipe.metric] = 99.0 + recipe.threshold
    elif recipe.operator is InsightOperator.PERCENT_CHANGE_ABOVE:
        baselines[recipe.metric] = 100.0
        values[recipe.metric] = 101.0 + recipe.threshold
    elif recipe.operator is InsightOperator.PERCENT_CHANGE_BELOW:
        baselines[recipe.metric] = 100.0
        values[recipe.metric] = 99.0 + recipe.threshold
    elif recipe.operator is InsightOperator.RATIO_ABOVE:
        assert recipe.comparison_metric is not None
        values[recipe.comparison_metric] = 10.0
        values[recipe.metric] = (recipe.threshold + 1.0) * 10.0
    elif recipe.operator is InsightOperator.RATIO_BELOW:
        assert recipe.comparison_metric is not None
        values[recipe.comparison_metric] = 10.0
        values[recipe.metric] = max(0.0, (recipe.threshold - 0.01) * 10.0)
    elif recipe.operator is InsightOperator.STALE:
        values[recipe.metric] = 1.0
        last_seen[recipe.metric] = _NOW - timedelta(seconds=recipe.threshold + 1.0)

    return InsightObservation(
        resource_ref="resource:example/operational-target",
        window_bucket="2026-07-18T12:00Z",
        values=values,
        previous_values=previous,
        baseline_values=baselines,
        sample_counts={recipe.metric: max(1, recipe.min_samples)},
        last_seen_at=last_seen,
        evaluated_at=_NOW,
    )


def test_catalog_contains_fifty_unique_executable_features() -> None:
    recipes = load_operational_insight_recipes(_CATALOG)
    assert len(recipes) == 50
    assert len({recipe.recipe_id for recipe in recipes}) == 50

    for recipe in recipes:
        findings = OperationalInsightEngine([recipe]).evaluate(_firing_observation(recipe))
        assert len(findings) == 1, recipe.recipe_id
        assert findings[0].recipe_id == recipe.recipe_id


def test_catalog_spans_required_operational_domains() -> None:
    recipe_ids = {recipe.recipe_id for recipe in load_operational_insight_recipes(_CATALOG)}
    prefixes = {recipe_id.split(".", maxsplit=1)[0] for recipe_id in recipe_ids}
    assert {
        "alert",
        "apm",
        "backup",
        "change",
        "cost",
        "database",
        "infrastructure",
        "log",
        "security",
        "slo",
        "stream",
        "synthetic",
        "telemetry",
    } <= prefixes


def test_loader_rejects_unknown_fields(tmp_path: Path) -> None:
    catalog = tmp_path / "bad.yaml"
    catalog.write_text("version: 1\nrecipes:\n  - recipe_id: bad\n    surprise: true\n")
    with pytest.raises(ValueError, match="unknown fields"):
        load_operational_insight_recipes(catalog)


def test_loader_rejects_duplicate_recipe_ids(tmp_path: Path) -> None:
    catalog = tmp_path / "duplicate.yaml"
    recipe = """
  - recipe_id: duplicate
    title: Duplicate
    category: reliability
    severity: medium
    operator: above
    metric: example.metric
    threshold: 1
    description: Duplicate recipe for validation.
"""
    catalog.write_text(f"version: 1\nrecipes:{recipe}{recipe}")
    with pytest.raises(ValueError, match="unique"):
        load_operational_insight_recipes(catalog)
