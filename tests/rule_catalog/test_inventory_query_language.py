from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from fdai.rule_catalog.schema.inventory_query_language import (
    InventoryQueryLanguageRegistryError,
    inventory_query_language_digest,
    load_inventory_query_language_from_mapping,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
CATALOG = REPO_ROOT / "rule-catalog" / "vocabulary" / "inventory-query-language.yaml"


def test_shipped_inventory_query_language_loads() -> None:
    registry = load_inventory_query_language_from_mapping(
        yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    )
    assert registry.schema_version == "1.1.0"
    assert registry.default_scope == "subscription"
    assert registry.current_requires_fresh is True
    assert {"stopped", "paused", "failed", "degraded", "unavailable"} <= set(registry.states)
    assert registry.states["degraded"].evidence_authority == "subscription_health"
    assert registry.states["unavailable"].evidence_authority == "subscription_health"
    assert registry.states["inactive"].suppresses == ("running",)
    assert all(
        entry.description for entry in (*registry.states.values(), *registry.operations.values())
    )
    assert all(
        entry.examples for entry in (*registry.states.values(), *registry.operations.values())
    )


def test_inventory_query_language_digest_is_replay_stable() -> None:
    raw = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    registry = load_inventory_query_language_from_mapping(raw)
    reordered = {key: raw[key] for key in reversed(tuple(raw))}

    assert inventory_query_language_digest(registry).startswith("sha256:")
    assert inventory_query_language_digest(
        load_inventory_query_language_from_mapping(reordered)
    ) == inventory_query_language_digest(registry)


def test_inventory_query_language_rejects_unknown_fields() -> None:
    raw = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    raw["question_specific_override"] = True
    with pytest.raises(InventoryQueryLanguageRegistryError):
        load_inventory_query_language_from_mapping(raw)


def test_inventory_query_language_rejects_unknown_state_suppression() -> None:
    raw = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    raw["states"]["inactive"]["suppresses"] = ["not-a-state"]
    with pytest.raises(InventoryQueryLanguageRegistryError):
        load_inventory_query_language_from_mapping(raw)


@pytest.mark.parametrize(
    "values",
    ([], ["   "], [f"state-{index}" for index in range(17)]),
)
def test_inventory_query_language_rejects_unbounded_state_values(values: list[str]) -> None:
    raw = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    raw["states"]["running"]["values"] = values

    with pytest.raises(InventoryQueryLanguageRegistryError):
        load_inventory_query_language_from_mapping(raw)
