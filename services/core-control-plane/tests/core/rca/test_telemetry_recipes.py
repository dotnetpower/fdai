from __future__ import annotations

from dataclasses import replace

import pytest
from fdai.core.rca import (
    DEFAULT_TELEMETRY_RECIPE_CATALOG,
    TELEMETRY_RECIPE_OUTPUT_SCHEMA_DIGEST,
    TelemetryMechanism,
)


def test_default_catalog_covers_every_reviewed_mechanism_once() -> None:
    recipes = DEFAULT_TELEMETRY_RECIPE_CATALOG.recipes

    assert len(recipes) == len(TelemetryMechanism) == 8
    assert {item.mechanism for item in recipes} == set(TelemetryMechanism)
    assert all(
        item.output_schema_digest == TELEMETRY_RECIPE_OUTPUT_SCHEMA_DIGEST for item in recipes
    )
    assert all(item.query_execution_authority is False for item in recipes)


def test_lookup_requires_exact_reviewed_id_and_version() -> None:
    recipe = DEFAULT_TELEMETRY_RECIPE_CATALOG.get("requests.failed", "1.0.0")

    assert recipe.mechanism is TelemetryMechanism.FAILED_REQUESTS
    with pytest.raises(ValueError, match="reviewed catalog"):
        DEFAULT_TELEMETRY_RECIPE_CATALOG.get("requests.failed", "2.0.0")
    with pytest.raises(ValueError, match="reviewed catalog"):
        DEFAULT_TELEMETRY_RECIPE_CATALOG.get("caller.supplied", "1.0.0")


def test_catalog_digest_detects_recipe_substitution() -> None:
    recipes = DEFAULT_TELEMETRY_RECIPE_CATALOG.recipes
    changed = (replace(recipes[0], estimated_cost_units=11), *recipes[1:])

    with pytest.raises(ValueError, match="digest does not match"):
        replace(DEFAULT_TELEMETRY_RECIPE_CATALOG, recipes=changed)
