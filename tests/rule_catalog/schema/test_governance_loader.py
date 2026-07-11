"""Catalog-as-code loader for governance assignments."""

from __future__ import annotations

from typing import Any

import pytest

from fdai.rule_catalog.schema.effect import Effect, Enforcement
from fdai.rule_catalog.schema.governance_loader import (
    GovernanceLoadError,
    load_assignment_from_mapping,
    load_rule_set_from_mapping,
)
from fdai.rule_catalog.schema.scope import ResourceContext, ScopeLevel


def _minimal() -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "id": "assign-baseline-rg-a",
        "target_rule_ids": ["r.encryption"],
        "scope": {"level": "resource-group", "id": "rg-a"},
    }


def test_minimal_valid_load_defaults_to_shadow() -> None:
    a = load_assignment_from_mapping(_minimal())
    assert a.id == "assign-baseline-rg-a"
    assert a.target_rule_ids == frozenset({"r.encryption"})
    assert a.scope.level is ScopeLevel.RESOURCE_GROUP
    assert a.scope.id == "rg-a"
    assert a.effect is Effect.AUDIT
    assert a.enforcement is Enforcement.DO_NOT_ENFORCE


def test_full_valid_load() -> None:
    raw = {
        "schema_version": "1.0.0",
        "id": "assign-full",
        "target_rule_ids": ["r.encryption", "r.backup"],
        "scope": {
            "level": "account",
            "id": "sub-1",
            "selector": {
                "resource_types": ["compute"],
                "tags": {"env": "prod"},
                "resource_ids": ["vm-1"],
            },
            "excludes": ["rg-sandbox"],
        },
        "effect": "deny",
        "enforcement": "enforce",
        "parameters": {"max": "10"},
        "effect_overrides": {"r.backup": "remediate"},
    }
    a = load_assignment_from_mapping(raw)
    assert a.effect is Effect.DENY
    assert a.enforcement is Enforcement.ENFORCE
    assert a.effect_for("r.backup") is Effect.REMEDIATE
    assert a.parameters == {"max": "10"}
    assert a.scope.selector is not None
    assert a.scope.selector.resource_types == frozenset({"compute"})
    assert a.scope.excludes == frozenset({"rg-sandbox"})
    # the built Assignment behaves against a resource context
    ctx = ResourceContext(
        organization="org-1",
        account="sub-1",
        resource_group="rg-a",
        resource_id="vm-1",
        resource_type="compute",
        tags={"env": "prod"},
    )
    assert a.applies_to("r.encryption", ctx)


def test_missing_required_field_rejected() -> None:
    raw = _minimal()
    del raw["scope"]
    with pytest.raises(GovernanceLoadError) as ei:
        load_assignment_from_mapping(raw)
    assert ei.value.issues  # carries at least one issue


def test_unknown_field_rejected() -> None:
    raw = _minimal()
    raw["bogus"] = "x"
    with pytest.raises(GovernanceLoadError):
        load_assignment_from_mapping(raw)


def test_bad_effect_enum_rejected() -> None:
    raw = _minimal()
    raw["effect"] = "delete-everything"
    with pytest.raises(GovernanceLoadError):
        load_assignment_from_mapping(raw)


def test_bad_scope_level_rejected() -> None:
    raw = _minimal()
    raw["scope"] = {"level": "galaxy", "id": "x"}
    with pytest.raises(GovernanceLoadError):
        load_assignment_from_mapping(raw)


def test_empty_target_rule_ids_rejected() -> None:
    raw = _minimal()
    raw["target_rule_ids"] = []
    with pytest.raises(GovernanceLoadError):
        load_assignment_from_mapping(raw)


def test_bad_effect_override_value_rejected() -> None:
    raw = _minimal()
    raw["effect_overrides"] = {"r.encryption": "nope"}
    with pytest.raises(GovernanceLoadError):
        load_assignment_from_mapping(raw)


def _minimal_rule_set() -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "id": "security-baseline",
        "version": "1.0.0",
        "members": [
            {"rule_id": "r.encryption", "version": "1.0.0", "default_effect": "deny"},
            {"rule_id": "r.tagging", "version": "1.0.0"},
        ],
    }


def test_rule_set_valid_load() -> None:
    rs = load_rule_set_from_mapping(_minimal_rule_set())
    assert rs.id == "security-baseline"
    assert rs.rule_ids() == frozenset({"r.encryption", "r.tagging"})
    assert rs.default_effect_for("r.encryption") is Effect.DENY
    assert rs.default_effect_for("r.tagging") is Effect.AUDIT  # schema default
    assert rs.version_for("r.encryption") == "1.0.0"


def test_rule_set_missing_members_rejected() -> None:
    raw = _minimal_rule_set()
    raw["members"] = []
    with pytest.raises(GovernanceLoadError):
        load_rule_set_from_mapping(raw)


def test_rule_set_bad_member_default_effect_rejected() -> None:
    raw = _minimal_rule_set()
    raw["members"][0]["default_effect"] = "nuke"
    with pytest.raises(GovernanceLoadError):
        load_rule_set_from_mapping(raw)


def test_rule_set_unknown_field_rejected() -> None:
    raw = _minimal_rule_set()
    raw["surprise"] = 1
    with pytest.raises(GovernanceLoadError):
        load_rule_set_from_mapping(raw)
