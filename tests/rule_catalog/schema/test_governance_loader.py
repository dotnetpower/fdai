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
from fdai.rule_catalog.schema.scope import ResourceContext, ScopeBinding, ScopeLevel


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


# ---- rule-set binding (assignment references a rule-set) -----------------


def _binding(**overrides: Any) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "schema_version": "1.0.0",
        "id": "assign-baseline",
        "rule_set": "security-baseline",
        "scope": {"level": "resource-group", "id": "rg-a"},
    }
    raw.update(overrides)
    return raw


def test_assignment_binds_rule_set() -> None:
    rs = load_rule_set_from_mapping(_minimal_rule_set())
    a = load_assignment_from_mapping(_binding(), rule_sets={rs.id: rs})
    # every rule-set member becomes a target rule
    assert a.target_rule_ids == frozenset({"r.encryption", "r.tagging"})
    # the rule-set's per-rule default_effect becomes the assignment override
    assert a.effect_for("r.encryption") is Effect.DENY
    assert a.effect_for("r.tagging") is Effect.AUDIT
    assert a.scope.id == "rg-a"
    # top-level defaults stay shadow
    assert a.effect is Effect.AUDIT
    assert a.enforcement is Enforcement.DO_NOT_ENFORCE


def test_assignment_binding_effect_overrides_tune_rule_set_defaults() -> None:
    rs = load_rule_set_from_mapping(_minimal_rule_set())
    a = load_assignment_from_mapping(
        _binding(effect_overrides={"r.encryption": "audit"}, enforcement="enforce"),
        rule_sets={rs.id: rs},
    )
    # the assignment-level override wins over the rule-set default (deny -> audit)
    assert a.effect_for("r.encryption") is Effect.AUDIT
    assert a.enforcement is Enforcement.ENFORCE


def test_assignment_unknown_rule_set_rejected() -> None:
    with pytest.raises(GovernanceLoadError) as ei:
        load_assignment_from_mapping(_binding(), rule_sets={})
    assert any("unknown rule-set" in i.message for i in ei.value.issues)


def test_assignment_rule_set_without_map_rejected() -> None:
    with pytest.raises(GovernanceLoadError):
        load_assignment_from_mapping(_binding())


def test_assignment_both_rule_set_and_target_rule_ids_rejected() -> None:
    raw = _binding(target_rule_ids=["r.x"])
    with pytest.raises(GovernanceLoadError):
        load_assignment_from_mapping(raw, rule_sets={})


def test_assignment_neither_rule_set_nor_target_rule_ids_rejected() -> None:
    raw = _binding()
    del raw["rule_set"]
    with pytest.raises(GovernanceLoadError):
        load_assignment_from_mapping(raw, rule_sets={})


# ---- provenance -----------------------------------------------------------


def test_assignment_loads_provenance() -> None:
    raw = _minimal()
    raw["provenance"] = {"created_at": "2026-07-03T00:00:00Z", "created_by": "governance-team"}
    a = load_assignment_from_mapping(raw)
    assert a.provenance is not None
    assert a.provenance.created_by == "governance-team"


def test_assignment_without_provenance_is_none() -> None:
    assert load_assignment_from_mapping(_minimal()).provenance is None


def test_assignment_bad_provenance_timestamp_rejected() -> None:
    raw = _minimal()
    raw["provenance"] = {"created_at": "not-a-date", "created_by": "team"}
    with pytest.raises(GovernanceLoadError) as ei:
        load_assignment_from_mapping(raw)
    assert any(i.key == "provenance" for i in ei.value.issues)


def test_assignment_naive_provenance_timestamp_rejected() -> None:
    raw = _minimal()
    raw["provenance"] = {"created_at": "2026-07-03T00:00:00", "created_by": "team"}
    with pytest.raises(GovernanceLoadError) as ei:
        load_assignment_from_mapping(raw)
    assert any("timezone-aware" in i.message for i in ei.value.issues)


def test_assignment_provenance_unknown_field_rejected() -> None:
    raw = _minimal()
    raw["provenance"] = {"created_at": "2026-07-03T00:00:00Z", "created_by": "t", "bogus": 1}
    with pytest.raises(GovernanceLoadError):
        load_assignment_from_mapping(raw)


def test_rule_set_loads_provenance() -> None:
    raw = _minimal_rule_set()
    raw["provenance"] = {"created_at": "2026-07-03T00:00:00Z", "created_by": "governance-team"}
    rs = load_rule_set_from_mapping(raw)
    assert rs.provenance is not None
    assert rs.provenance.created_by == "governance-team"


# ---- kind + version envelope ----------------------------------------------


def test_assignment_loads_kind_and_version() -> None:
    raw = _minimal()
    raw["kind"] = "assignment"
    raw["version"] = "1.2.0"
    a = load_assignment_from_mapping(raw)
    assert a.version == "1.2.0"


def test_assignment_wrong_kind_rejected() -> None:
    raw = _minimal()
    raw["kind"] = "rule-set"  # wrong kind for an assignment file
    with pytest.raises(GovernanceLoadError):
        load_assignment_from_mapping(raw)


def test_assignment_bad_version_rejected() -> None:
    raw = _minimal()
    raw["version"] = "v1"  # not semver
    with pytest.raises(GovernanceLoadError):
        load_assignment_from_mapping(raw)


def test_assignment_version_default_none() -> None:
    assert load_assignment_from_mapping(_minimal()).version is None


def test_rule_set_loads_kind() -> None:
    raw = _minimal_rule_set()
    raw["kind"] = "rule-set"
    rs = load_rule_set_from_mapping(raw)
    assert rs.id == "security-baseline"


def test_rule_set_wrong_kind_rejected() -> None:
    raw = _minimal_rule_set()
    raw["kind"] = "assignment"
    with pytest.raises(GovernanceLoadError):
        load_rule_set_from_mapping(raw)


# ---- include/exclude scope form (ScopeBinding) ----------------------------


def test_assignment_loads_scope_binding() -> None:
    raw = _minimal()
    raw["scope"] = {
        "include": ["scope://org-1/sub-1/prod"],
        "exclude": ["scope://org-1/sub-1/prod/sandbox"],
        "selector": {"resource_types": ["sql-database"]},
    }
    a = load_assignment_from_mapping(raw)
    assert isinstance(a.scope, ScopeBinding)
    ctx = ResourceContext(
        organization="org-1",
        account="sub-1",
        resource_group="prod",
        resource_id="db-1",
        resource_type="sql-database",
    )
    assert a.applies_to("r.encryption", ctx)
    # excluded child scope is not covered
    sandbox = ResourceContext(
        organization="org-1",
        account="sub-1",
        resource_group="sandbox",
        resource_id="db-2",
        resource_type="sql-database",
    )
    assert not a.applies_to("r.encryption", sandbox)


def test_assignment_scope_binding_bad_uri_rejected() -> None:
    raw = _minimal()
    raw["scope"] = {"include": ["not-a-scope-uri"]}
    with pytest.raises(GovernanceLoadError):
        load_assignment_from_mapping(raw)


def test_assignment_scope_binding_too_many_segments_rejected() -> None:
    raw = _minimal()
    raw["scope"] = {"include": ["scope://a/b/c/d/e"]}
    with pytest.raises(GovernanceLoadError):
        load_assignment_from_mapping(raw)


def test_assignment_scope_binding_blank_segment_rejected_at_domain() -> None:
    # a whitespace-only segment passes the schema URI pattern but ScopeRef
    # rejects it - the loader wraps that ValueError into a scope-keyed issue
    raw = _minimal()
    raw["scope"] = {"include": ["scope://   "]}
    with pytest.raises(GovernanceLoadError) as ei:
        load_assignment_from_mapping(raw)
    assert any(i.key == "scope" for i in ei.value.issues)


def test_assignment_scope_both_forms_rejected() -> None:
    raw = _minimal()
    raw["scope"] = {"level": "resource-group", "id": "rg-a", "include": ["scope://org-1"]}
    with pytest.raises(GovernanceLoadError):
        load_assignment_from_mapping(raw)


# ---- per-rule parameter_overrides -----------------------------------------


def test_assignment_loads_parameter_overrides() -> None:
    raw = _minimal()
    raw["parameters"] = {"k": "base"}
    raw["parameter_overrides"] = {"r.encryption": {"k": "specific", "extra": "e"}}
    a = load_assignment_from_mapping(raw)
    assert a.parameters_for("r.encryption") == {"k": "specific", "extra": "e"}


def test_assignment_parameter_overrides_bad_value_rejected() -> None:
    raw = _minimal()
    raw["parameter_overrides"] = {"r.encryption": {"k": 5}}  # value must be a string
    with pytest.raises(GovernanceLoadError):
        load_assignment_from_mapping(raw)
