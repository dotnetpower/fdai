"""Load configuration-defined operational insight recipes from YAML."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from fdai.core.detection.insights import InsightOperator, InsightRecipe
from fdai.shared.contracts.models import Category, Severity

_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_RATIO_OPERATORS = frozenset({InsightOperator.RATIO_ABOVE, InsightOperator.RATIO_BELOW})
_RECIPE_KEYS = frozenset(
    {
        "recipe_id",
        "title",
        "category",
        "severity",
        "operator",
        "metric",
        "threshold",
        "comparison_metric",
        "min_samples",
        "description",
    }
)


def load_operational_insight_recipes(path: str | Path) -> tuple[InsightRecipe, ...]:
    """Load and validate one versioned operational insight catalog."""
    catalog_path = Path(path)
    try:
        raw: Any = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"unable to load operational insight catalog: {catalog_path}") from exc
    root = _mapping(raw, field="catalog")
    unknown_root = set(root) - {"version", "recipes"}
    if unknown_root:
        raise ValueError(f"catalog has unknown fields: {sorted(unknown_root)}")
    if root.get("version") != 1:
        raise ValueError("catalog version MUST equal 1")
    raw_recipes = root.get("recipes")
    if not isinstance(raw_recipes, list) or not raw_recipes:
        raise ValueError("catalog recipes MUST be a non-empty list")

    recipes = tuple(_parse_recipe(item, index=index) for index, item in enumerate(raw_recipes))
    recipe_ids = [recipe.recipe_id for recipe in recipes]
    if len(recipe_ids) != len(set(recipe_ids)):
        raise ValueError("catalog recipe_id values MUST be unique")
    return recipes


def _parse_recipe(raw: object, *, index: int) -> InsightRecipe:
    item = _mapping(raw, field=f"recipes[{index}]")
    unknown = set(item) - _RECIPE_KEYS
    if unknown:
        raise ValueError(f"recipes[{index}] has unknown fields: {sorted(unknown)}")
    required = _RECIPE_KEYS - {"comparison_metric", "min_samples"}
    missing = required - set(item)
    if missing:
        raise ValueError(f"recipes[{index}] is missing fields: {sorted(missing)}")

    threshold = item["threshold"]
    min_samples = item.get("min_samples", 1)
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        raise ValueError(f"recipes[{index}].threshold MUST be numeric")
    threshold_value = float(threshold)
    if not math.isfinite(threshold_value):
        raise ValueError(f"recipes[{index}].threshold MUST be finite")
    if isinstance(min_samples, bool) or not isinstance(min_samples, int) or min_samples < 1:
        raise ValueError(f"recipes[{index}].min_samples MUST be an integer >= 1")
    try:
        operator = InsightOperator(_string(item["operator"], field=f"recipes[{index}].operator"))
        metric = _identifier(item["metric"], field=f"recipes[{index}].metric")
        comparison_metric = _optional_identifier(
            item.get("comparison_metric"),
            field=f"recipes[{index}].comparison_metric",
        )
        if operator in _RATIO_OPERATORS:
            if comparison_metric is None:
                raise ValueError("comparison_metric MUST be set for ratio operators")
            if comparison_metric == metric:
                raise ValueError("comparison_metric MUST differ from metric")
            if threshold_value < 0.0:
                raise ValueError("threshold MUST be >= 0 for ratio operators")
        elif comparison_metric is not None:
            raise ValueError("comparison_metric is only allowed for ratio operators")
        if operator is InsightOperator.STALE and threshold_value <= 0.0:
            raise ValueError("threshold MUST be > 0 for stale operator")

        return InsightRecipe(
            recipe_id=_identifier(item["recipe_id"], field=f"recipes[{index}].recipe_id"),
            title=_string(item["title"], field=f"recipes[{index}].title"),
            category=Category(_string(item["category"], field=f"recipes[{index}].category")),
            severity=Severity(_string(item["severity"], field=f"recipes[{index}].severity")),
            operator=operator,
            metric=metric,
            threshold=threshold_value,
            comparison_metric=comparison_metric,
            min_samples=min_samples,
            description=_string(item["description"], field=f"recipes[{index}].description"),
        )
    except ValueError as exc:
        raise ValueError(f"recipes[{index}] is invalid: {exc}") from exc


def _mapping(raw: object, *, field: str) -> Mapping[str, object]:
    if not isinstance(raw, Mapping) or not all(isinstance(key, str) for key in raw):
        raise ValueError(f"{field} MUST be a mapping with string keys")
    return raw


def _string(raw: object, *, field: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"{field} MUST be a non-empty string")
    return raw.strip()


def _identifier(raw: object, *, field: str) -> str:
    value = _string(raw, field=field)
    if not _ID_PATTERN.fullmatch(value):
        raise ValueError(
            f"{field} MUST use lowercase ASCII letters, digits, dot, dash, or underscore"
        )
    return value


def _optional_identifier(raw: object, *, field: str) -> str | None:
    if raw is None:
        return None
    return _identifier(raw, field=field)


__all__ = ["load_operational_insight_recipes"]
