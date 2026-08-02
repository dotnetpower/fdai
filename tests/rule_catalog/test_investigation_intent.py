from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from fdai.rule_catalog.schema.investigation_intent import (
    InvestigationIntentRegistryError,
    InvestigationOwner,
    InvestigationWorkClass,
    load_investigation_intents_from_mapping,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
CATALOG = REPO_ROOT / "rule-catalog" / "vocabulary" / "investigation-intents.yaml"


def _raw() -> dict[str, object]:
    return yaml.safe_load(CATALOG.read_text(encoding="utf-8"))


def test_shipped_investigation_intents_load_with_owner_and_evidence_contracts() -> None:
    registry = load_investigation_intents_from_mapping(_raw())

    assert registry.schema_version == "2.0.0"
    assert set(registry.intents) == {
        "resource_state",
        "change_attribution",
        "resource_change_history",
        "platform_health",
        "guest_shutdown",
        "network_security",
        "network_peering",
    }
    assert all(
        intent.work_class is InvestigationWorkClass.READ
        and intent.owner_agent is InvestigationOwner.HEIMDALL
        for intent in registry.intents.values()
    )
    assert registry.intents["resource_state"].evidence.max_age_seconds == 300


def test_investigation_intents_reject_unknown_owner() -> None:
    raw = _raw()
    raw["intents"]["resource_state"]["owner_agent"] = "Unknown"

    with pytest.raises(InvestigationIntentRegistryError):
        load_investigation_intents_from_mapping(raw)


def test_investigation_intents_reject_empty_matcher() -> None:
    raw = _raw()
    raw["intents"]["resource_state"]["required_any"] = []
    raw["intents"]["resource_state"]["required_all"] = []

    with pytest.raises(InvestigationIntentRegistryError, match="deterministic matcher"):
        load_investigation_intents_from_mapping(raw)


def test_investigation_intents_reject_response_mode_order_drift() -> None:
    raw = _raw()
    raw["intents"]["resource_state"]["response_modes"] = {"summary": {"terms": ["summary"]}}
    raw["intents"]["resource_state"]["response_mode_order"] = []

    with pytest.raises(InvestigationIntentRegistryError, match="response_mode_order"):
        load_investigation_intents_from_mapping(raw)


def test_investigation_intent_mapping_is_immutable() -> None:
    registry = load_investigation_intents_from_mapping(_raw())

    with pytest.raises(TypeError):
        registry.intents["new"] = registry.intents["resource_state"]  # type: ignore[index]
