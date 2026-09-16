"""Read-only telemetry recipe catalog facts for Forseti introspection."""

from __future__ import annotations

from fdai.core.rca.telemetry_recipes import DEFAULT_TELEMETRY_RECIPE_CATALOG


def telemetry_recipe_facts() -> dict[str, object]:
    """Return reviewed recipe identities without query or execution authority."""

    catalog = DEFAULT_TELEMETRY_RECIPE_CATALOG
    return {
        "telemetry_recipe_catalog_version": catalog.version,
        "telemetry_recipe_catalog_digest": catalog.catalog_digest,
        "telemetry_recipe_ids": [item.recipe_id for item in catalog.recipes],
        "raw_kql_available": False,
        "query_execution_authority": False,
    }


__all__ = ["telemetry_recipe_facts"]
