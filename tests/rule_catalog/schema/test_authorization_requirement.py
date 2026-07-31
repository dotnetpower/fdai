"""Strict loading for execution-authorization requirements."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest
import yaml

from fdai.rule_catalog.schema.authorization_requirement import (
    AuthorizationRequirementLoadError,
    load_authorization_requirement_catalog,
    load_authorization_requirement_from_mapping,
)


def _requirement() -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "kind": "authorization-requirement",
        "id": "object.write.target",
        "version": "1.0.0",
        "capability_id": "object.write",
        "action_type_ids": ["object.update"],
        "resource_types": ["object-storage"],
        "scope_expressions": ["target"],
        "execution_profile": "change-executor",
        "provenance": {
            "created_at": "2026-07-31T00:00:00Z",
            "created_by": "example-team",
        },
    }


def test_loads_provider_neutral_requirement() -> None:
    requirement = load_authorization_requirement_from_mapping(_requirement())
    assert requirement.requirement_id == "object.write.target"
    assert requirement.scope_expressions == ("target",)
    assert requirement.applies_to(
        action_type_id="object.update",
        resource_type="object-storage",
    )


def test_rejects_unknown_field_and_scope_expression() -> None:
    unknown_field = _requirement()
    unknown_field["provider_role"] = "example-role"
    with pytest.raises(AuthorizationRequirementLoadError):
        load_authorization_requirement_from_mapping(unknown_field)

    unknown_expression = _requirement()
    unknown_expression["scope_expressions"] = ["ancestor(tenant)"]
    with pytest.raises(AuthorizationRequirementLoadError):
        load_authorization_requirement_from_mapping(unknown_expression)


def test_catalog_rejects_duplicates_and_unknown_references(tmp_path: Any) -> None:
    first = _requirement()
    second = deepcopy(first)
    second["action_type_ids"] = ["unknown.action"]
    (tmp_path / "first.yaml").write_text(yaml.safe_dump(first), encoding="utf-8")
    (tmp_path / "second.yaml").write_text(yaml.safe_dump(second), encoding="utf-8")

    with pytest.raises(AuthorizationRequirementLoadError) as caught:
        load_authorization_requirement_catalog(
            tmp_path,
            known_action_type_ids=frozenset({"object.update"}),
            known_resource_types=frozenset({"object-storage"}),
            known_capability_ids=frozenset({"object.write"}),
            known_execution_profiles=frozenset({"change-executor"}),
        )
    assert any("duplicate" in item.message for item in caught.value.issues)


def test_catalog_accepts_complete_reference_set(tmp_path: Any) -> None:
    (tmp_path / "requirement.yaml").write_text(yaml.safe_dump(_requirement()), encoding="utf-8")
    loaded = load_authorization_requirement_catalog(
        tmp_path,
        known_action_type_ids=frozenset({"object.update"}),
        known_resource_types=frozenset({"object-storage"}),
        known_capability_ids=frozenset({"object.write"}),
        known_execution_profiles=frozenset({"change-executor"}),
    )
    assert [item.requirement_id for item in loaded] == ["object.write.target"]
