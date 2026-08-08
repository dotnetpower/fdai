"""Deterministic operational-insight recipes over normalized telemetry.

The engine turns configuration-defined comparisons into evidence-backed,
shadow-first findings. It does not collect telemetry or execute actions. Each
finding re-enters event-ingest and follows the normal trust-router and risk-gate
path.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import NAMESPACE_URL, uuid4, uuid5

from fdai.shared.contracts.models import Category, Event, Mode, Severity

_INSIGHT_EVENT_TYPE = "operational-insight.finding"
_DEFAULT_SOURCE = "fdai.core.detection.insights"
_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


class InsightOperator(StrEnum):
    """Supported deterministic comparisons for an insight recipe."""

    ABOVE = "above"
    BELOW = "below"
    DELTA_ABOVE = "delta_above"
    DELTA_BELOW = "delta_below"
    PERCENT_CHANGE_ABOVE = "percent_change_above"
    PERCENT_CHANGE_BELOW = "percent_change_below"
    RATIO_ABOVE = "ratio_above"
    RATIO_BELOW = "ratio_below"
    ABSENT = "absent"
    STALE = "stale"


@dataclass(frozen=True, slots=True)
class InsightRecipe:
    """One configuration-defined operational condition."""

    recipe_id: str
    title: str
    category: Category
    severity: Severity
    operator: InsightOperator
    metric: str
    threshold: float
    comparison_metric: str | None = None
    min_samples: int = 1
    description: str = ""

    def __post_init__(self) -> None:
        if not _ID_PATTERN.fullmatch(self.recipe_id):
            raise ValueError(
                "recipe_id MUST use lowercase ASCII letters, digits, dot, dash, or underscore"
            )
        if not self.title:
            raise ValueError("title MUST be non-empty")
        if not self.metric:
            raise ValueError("metric MUST be non-empty")
        if not math.isfinite(self.threshold):
            raise ValueError("threshold MUST be finite")
        if self.min_samples < 1:
            raise ValueError("min_samples MUST be >= 1")
        if self.operator in {InsightOperator.RATIO_ABOVE, InsightOperator.RATIO_BELOW}:
            if not self.comparison_metric:
                raise ValueError("comparison_metric MUST be set for ratio operators")


@dataclass(frozen=True, slots=True)
class InsightObservation:
    """Normalized values available for one resource and evaluation window."""

    resource_ref: str
    window_bucket: str
    values: Mapping[str, float] = field(default_factory=dict)
    previous_values: Mapping[str, float] = field(default_factory=dict)
    baseline_values: Mapping[str, float] = field(default_factory=dict)
    sample_counts: Mapping[str, int] = field(default_factory=dict)
    last_seen_at: Mapping[str, datetime] = field(default_factory=dict)
    unavailable_metrics: frozenset[str] = frozenset()
    evaluated_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))

    def __post_init__(self) -> None:
        if not self.resource_ref:
            raise ValueError("resource_ref MUST be non-empty")
        if not self.window_bucket:
            raise ValueError("window_bucket MUST be non-empty")
        if self.evaluated_at.tzinfo is None:
            raise ValueError("evaluated_at MUST be timezone-aware")


@dataclass(frozen=True, slots=True)
class OperationalInsightFinding:
    """A fired recipe with enough evidence for deterministic replay."""

    recipe_id: str
    title: str
    category: Category
    severity: Severity
    operator: InsightOperator
    metric: str
    resource_ref: str
    window_bucket: str
    observed: float | None
    reference: float | None
    score: float
    threshold: float
    reason: str
    idempotency_key: str


class OperationalInsightEngine:
    """Evaluate a validated recipe catalog without side effects."""

    def __init__(
        self,
        recipes: Sequence[InsightRecipe],
        *,
        engine_id: str = "default",
        source: str = _DEFAULT_SOURCE,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not recipes:
            raise ValueError("recipes MUST be non-empty")
        if not engine_id:
            raise ValueError("engine_id MUST be non-empty")
        recipe_ids = [recipe.recipe_id for recipe in recipes]
        if len(recipe_ids) != len(set(recipe_ids)):
            raise ValueError("recipe_id values MUST be unique")
        self._recipes = tuple(recipes)
        self._engine_id = engine_id
        self._source = source
        self._clock = clock or (lambda: datetime.now(tz=UTC))

    @property
    def recipes(self) -> tuple[InsightRecipe, ...]:
        """Return the immutable recipe catalog in evaluation order."""
        return self._recipes

    def evaluate(self, observation: InsightObservation) -> tuple[OperationalInsightFinding, ...]:
        """Return every recipe that fires; invalid or incomplete telemetry abstains."""
        findings: list[OperationalInsightFinding] = []
        for recipe in self._recipes:
            finding = self._evaluate_recipe(recipe, observation)
            if finding is not None:
                findings.append(finding)
        return tuple(findings)

    def _evaluate_recipe(
        self,
        recipe: InsightRecipe,
        observation: InsightObservation,
    ) -> OperationalInsightFinding | None:
        result = _score(recipe, observation)
        if result is None:
            return None
        observed, reference, score = result
        return OperationalInsightFinding(
            recipe_id=recipe.recipe_id,
            title=recipe.title,
            category=recipe.category,
            severity=recipe.severity,
            operator=recipe.operator,
            metric=recipe.metric,
            resource_ref=observation.resource_ref,
            window_bucket=observation.window_bucket,
            observed=observed,
            reference=reference,
            score=score,
            threshold=recipe.threshold,
            reason=f"{recipe.operator.value} score {score:.4f} crossed {recipe.threshold:.4f}",
            idempotency_key=self._idempotency_key(recipe, observation),
        )

    def to_event(
        self,
        finding: OperationalInsightFinding,
        *,
        mode: Mode = Mode.SHADOW,
    ) -> Event:
        """Normalize a finding into an event that re-enters event-ingest."""
        now = self._clock()
        return Event(
            schema_version="1.0.0",
            event_id=uuid4(),
            idempotency_key=finding.idempotency_key,
            source=self._source,
            event_type=_INSIGHT_EVENT_TYPE,
            resource_ref=finding.resource_ref,
            payload={
                "kind": "operational_insight",
                "recipe_id": finding.recipe_id,
                "title": finding.title,
                "category": finding.category.value,
                "severity": finding.severity.value,
                "operator": finding.operator.value,
                "metric": finding.metric,
                "observed": finding.observed,
                "reference": finding.reference,
                "score": finding.score,
                "threshold": finding.threshold,
                "window_bucket": finding.window_bucket,
                "reason": finding.reason,
            },
            detected_at=now,
            ingested_at=now,
            mode=mode,
        )

    def _idempotency_key(
        self,
        recipe: InsightRecipe,
        observation: InsightObservation,
    ) -> str:
        return str(
            uuid5(
                NAMESPACE_URL,
                ":".join(
                    (
                        "fdai-operational-insight",
                        self._engine_id,
                        recipe.recipe_id,
                        observation.resource_ref,
                        observation.window_bucket,
                    )
                ),
            )
        )


def _score(
    recipe: InsightRecipe,
    observation: InsightObservation,
) -> tuple[float | None, float | None, float] | None:
    if recipe.metric in observation.unavailable_metrics:
        return None
    if (
        recipe.comparison_metric is not None
        and recipe.comparison_metric in observation.unavailable_metrics
    ):
        return None
    current = observation.values.get(recipe.metric)
    if recipe.operator is InsightOperator.ABSENT:
        return (None, None, 1.0) if current is None else None
    if recipe.operator is InsightOperator.STALE:
        last_seen = observation.last_seen_at.get(recipe.metric)
        if last_seen is None or last_seen.tzinfo is None:
            return None
        age_seconds = (observation.evaluated_at - last_seen).total_seconds()
        if age_seconds > recipe.threshold:
            return current, last_seen.timestamp(), age_seconds
        return None
    if current is None or not math.isfinite(current):
        return None
    if observation.sample_counts.get(recipe.metric, 0) < recipe.min_samples:
        return None

    reference: float | None = None
    if recipe.operator in {InsightOperator.ABOVE, InsightOperator.BELOW}:
        score = current
    elif recipe.operator in {InsightOperator.DELTA_ABOVE, InsightOperator.DELTA_BELOW}:
        reference = observation.previous_values.get(recipe.metric)
        if reference is None or not math.isfinite(reference):
            return None
        score = current - reference
    elif recipe.operator in {
        InsightOperator.PERCENT_CHANGE_ABOVE,
        InsightOperator.PERCENT_CHANGE_BELOW,
    }:
        reference = observation.baseline_values.get(recipe.metric)
        if reference is None or not math.isfinite(reference) or reference == 0.0:
            return None
        score = ((current - reference) / abs(reference)) * 100.0
    else:
        comparison_metric = recipe.comparison_metric
        if comparison_metric is None:
            return None
        reference = observation.values.get(comparison_metric)
        if reference is None or not math.isfinite(reference) or reference == 0.0:
            return None
        score = current / reference

    above = recipe.operator in {
        InsightOperator.ABOVE,
        InsightOperator.DELTA_ABOVE,
        InsightOperator.PERCENT_CHANGE_ABOVE,
        InsightOperator.RATIO_ABOVE,
    }
    fired = score > recipe.threshold if above else score < recipe.threshold
    return (current, reference, score) if fired else None


__all__ = [
    "InsightObservation",
    "InsightOperator",
    "InsightRecipe",
    "OperationalInsightEngine",
    "OperationalInsightFinding",
]
