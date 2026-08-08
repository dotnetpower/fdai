"""Deterministic operational-insight recipe evaluation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.detection.insights import (
    InsightObservation,
    InsightOperator,
    InsightRecipe,
    OperationalInsightEngine,
)
from fdai.core.event_ingest import EventIngest
from fdai.shared.contracts.models import Category, Mode, Severity
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.contracts.validation import JsonSchemaContractValidator, JsonSchemaEventValidator

_NOW = datetime(2026, 7, 18, 9, 0, tzinfo=UTC)


def _recipe(operator: InsightOperator, **overrides: object) -> InsightRecipe:
    values: dict[str, object] = {
        "recipe_id": f"test.{operator.value}",
        "title": operator.value,
        "category": Category.RELIABILITY,
        "severity": Severity.HIGH,
        "operator": operator,
        "metric": "primary",
        "threshold": 10.0,
        "comparison_metric": "secondary" if "ratio" in operator.value else None,
    }
    values.update(overrides)
    return InsightRecipe(**values)  # type: ignore[arg-type]


def _observation(**overrides: object) -> InsightObservation:
    values: dict[str, object] = {
        "resource_ref": "resource:example/service-a",
        "window_bucket": "2026-07-18T09:00Z",
        "values": {"primary": 20.0, "secondary": 2.0},
        "previous_values": {"primary": 5.0},
        "baseline_values": {"primary": 10.0},
        "sample_counts": {"primary": 30},
        "last_seen_at": {"primary": _NOW - timedelta(seconds=20)},
        "evaluated_at": _NOW,
    }
    values.update(overrides)
    return InsightObservation(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("recipe", "observation", "expected_score"),
    [
        (_recipe(InsightOperator.ABOVE), _observation(), 20.0),
        (_recipe(InsightOperator.BELOW, threshold=25.0), _observation(), 20.0),
        (_recipe(InsightOperator.DELTA_ABOVE), _observation(), 15.0),
        (_recipe(InsightOperator.DELTA_BELOW, threshold=20.0), _observation(), 15.0),
        (_recipe(InsightOperator.PERCENT_CHANGE_ABOVE, threshold=50.0), _observation(), 100.0),
        (_recipe(InsightOperator.PERCENT_CHANGE_BELOW, threshold=150.0), _observation(), 100.0),
        (_recipe(InsightOperator.RATIO_ABOVE, threshold=5.0), _observation(), 10.0),
        (_recipe(InsightOperator.RATIO_BELOW, threshold=15.0), _observation(), 10.0),
        (
            _recipe(InsightOperator.ABSENT),
            _observation(values={"secondary": 2.0}),
            1.0,
        ),
        (_recipe(InsightOperator.STALE, threshold=10.0), _observation(), 20.0),
    ],
)
def test_each_operator_fires(
    recipe: InsightRecipe,
    observation: InsightObservation,
    expected_score: float,
) -> None:
    findings = OperationalInsightEngine([recipe]).evaluate(observation)
    assert len(findings) == 1
    assert findings[0].score == pytest.approx(expected_score)


def test_incomplete_or_non_finite_telemetry_abstains() -> None:
    recipes = [
        _recipe(InsightOperator.DELTA_ABOVE),
        _recipe(InsightOperator.PERCENT_CHANGE_ABOVE),
        _recipe(InsightOperator.RATIO_ABOVE),
        _recipe(InsightOperator.ABOVE),
    ]
    observation = _observation(
        values={"primary": float("nan")},
        previous_values={},
        baseline_values={},
    )
    assert OperationalInsightEngine(recipes).evaluate(observation) == ()


def test_unavailable_metric_does_not_fire_absence_recipe() -> None:
    recipe = _recipe(InsightOperator.ABSENT)
    observation = _observation(
        values={},
        unavailable_metrics=frozenset({recipe.metric}),
    )
    assert OperationalInsightEngine([recipe]).evaluate(observation) == ()


def test_minimum_sample_gate_abstains() -> None:
    recipe = _recipe(InsightOperator.ABOVE, min_samples=10)
    observation = _observation(sample_counts={"primary": 9})
    assert OperationalInsightEngine([recipe]).evaluate(observation) == ()


def test_finding_re_enters_event_ingest_and_deduplicates() -> None:
    engine = OperationalInsightEngine([_recipe(InsightOperator.ABOVE)])
    finding = engine.evaluate(_observation())[0]
    event = engine.to_event(finding)
    assert event.event_type == "operational-insight.finding"
    assert event.mode is Mode.SHADOW
    assert event.payload["recipe_id"] == "test.above"

    validator = JsonSchemaEventValidator(
        JsonSchemaContractValidator(PackageResourceSchemaRegistry())
    )
    ingest = EventIngest(validator=validator)
    assert ingest.ingest(event) is not None
    assert ingest.ingest(engine.to_event(finding)) is None


def test_catalog_rejects_duplicate_ids() -> None:
    recipe = _recipe(InsightOperator.ABOVE)
    with pytest.raises(ValueError, match="unique"):
        OperationalInsightEngine([recipe, recipe])
