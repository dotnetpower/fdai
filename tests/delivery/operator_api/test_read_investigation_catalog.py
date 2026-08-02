from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
import yaml

from fdai.delivery.operator_api.routes.read_investigation_catalog import (
    ReadInvestigationCatalogBindingError,
    load_bound_investigation_intents,
    validate_investigation_intent_bindings,
)
from fdai.rule_catalog.schema.investigation_intent import (
    load_investigation_intents_from_mapping,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
CATALOG = REPO_ROOT / "rule-catalog" / "vocabulary" / "investigation-intents.yaml"


def _raw() -> dict[str, Any]:
    return cast(dict[str, Any], yaml.safe_load(CATALOG.read_text(encoding="utf-8")))


def test_shipped_investigation_catalog_matches_runtime_bindings() -> None:
    registry = load_bound_investigation_intents(REPO_ROOT)

    assert len(registry.intents) == 7


def test_binding_rejects_missing_runtime_intent() -> None:
    raw = _raw()
    del raw["intents"]["resource_state"]
    registry = load_investigation_intents_from_mapping(raw)

    with pytest.raises(ReadInvestigationCatalogBindingError, match="missing=resource_state"):
        validate_investigation_intent_bindings(registry)


def test_binding_rejects_non_heimdall_read_owner() -> None:
    raw = _raw()
    raw["intents"]["resource_state"]["owner_agent"] = "Freyr"
    registry = load_investigation_intents_from_mapping(raw)

    with pytest.raises(ReadInvestigationCatalogBindingError, match="Heimdall read ownership"):
        validate_investigation_intent_bindings(registry)


def test_binding_rejects_duplicate_plan_ids() -> None:
    raw = _raw()
    raw["intents"]["resource_state"]["plan_id"] = raw["intents"]["platform_health"]["plan_id"]
    registry = load_investigation_intents_from_mapping(raw)

    with pytest.raises(ReadInvestigationCatalogBindingError, match="plan_id values MUST be unique"):
        validate_investigation_intent_bindings(registry)


def test_binding_rejects_catalog_plan_id_drift() -> None:
    raw = _raw()
    raw["intents"]["resource_state"]["plan_id"] = "read.resource-state.v2"
    registry = load_investigation_intents_from_mapping(raw)

    with pytest.raises(ReadInvestigationCatalogBindingError, match="does not match runtime spec"):
        validate_investigation_intent_bindings(registry)
