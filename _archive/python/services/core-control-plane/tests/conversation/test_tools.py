"""Read-only invariants + RBAC matrix for the Day-1 console tools.

Every SystemConsoleTool shipped in Day 1 MUST satisfy:

- ``side_effect_class == 'read'`` - the shipped set is read-only.
- ``rbac_floor >= Role.READER`` - Reader is the lowest ordinary role.
- Calling the tool NEVER mutates the input rule/action_type sequences,
  NEVER touches an executor, NEVER writes to disk, NEVER opens a
  network connection.

These invariants are enforced by shape (Protocol + call surface) plus
behavioural tests below.
"""

from __future__ import annotations

import pytest
from fdai.core.conversation import (
    ExploreCatalogTool,
    Principal,
    Role,
    SystemConsoleTool,
    ToolResult,
)
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.rule_catalog.schema.resource_type import (
    load_resource_type_registry_from_mapping,
)
from fdai.rule_catalog.schema.rule import load_rule_catalog
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry


@pytest.fixture(scope="module")
def loaded_catalogs(tmp_path_factory):  # noqa: ARG001 - fixture protocol
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[4]
    registry = PackageResourceSchemaRegistry()
    catalog_root = repo_root / "rule-catalog"
    import yaml

    with (catalog_root / "vocabulary" / "resource-types.yaml").open() as f:
        rt = load_resource_type_registry_from_mapping(yaml.safe_load(f))
    action_types = load_action_type_catalog(catalog_root / "action-types", schema_registry=registry)
    rules = load_rule_catalog(
        catalog_root / "catalog",
        schema_registry=registry,
        resource_types=rt,
        action_types=action_types,
    )
    return list(rules), list(action_types)


def test_explore_catalog_is_a_system_console_tool(loaded_catalogs):
    rules, action_types = loaded_catalogs
    tool = ExploreCatalogTool(rules=rules, action_types=action_types)
    assert isinstance(tool, SystemConsoleTool)
    assert tool.side_effect_class == "read"
    assert tool.rbac_floor == Role.READER


def test_explore_catalog_finds_shipped_action_type(loaded_catalogs):
    rules, action_types = loaded_catalogs
    tool = ExploreCatalogTool(rules=rules, action_types=action_types)
    principal = Principal(id="test", role=Role.READER)

    result = tool.call(arguments={"query": "tag-add"}, principal=principal)

    assert result.status == "ok"
    assert result.data["query"] == "tag-add"
    ids = [a["id"] for a in result.data["action_types"]]
    assert "remediate.tag-add" in ids
    # evidence includes typed refs so audit callers can cite verbatim.
    assert any(ref.startswith("action_type:") for ref in result.evidence_refs)


def test_explore_catalog_abstains_when_no_match(loaded_catalogs):
    rules, action_types = loaded_catalogs
    tool = ExploreCatalogTool(rules=rules, action_types=action_types)
    principal = Principal(id="test", role=Role.READER)

    result = tool.call(arguments={"query": "definitely-no-such-thing-xyzzy"}, principal=principal)

    assert result.status == "abstain"
    assert result.data["rules"] == []
    assert result.data["action_types"] == []


def test_explore_catalog_rejects_bad_argument_shape(loaded_catalogs):
    rules, action_types = loaded_catalogs
    tool = ExploreCatalogTool(rules=rules, action_types=action_types)
    principal = Principal(id="test", role=Role.READER)

    with pytest.raises(TypeError):
        tool.call(arguments={"query": 123}, principal=principal)  # type: ignore[dict-item]

    with pytest.raises(ValueError):
        tool.call(
            arguments={"query": "tag", "limit": 999},
            principal=principal,
        )


def test_explore_catalog_never_mutates_inputs(loaded_catalogs):
    rules, action_types = loaded_catalogs
    tool = ExploreCatalogTool(rules=rules, action_types=action_types)
    principal = Principal(id="test", role=Role.READER)

    rules_snapshot = tuple(rules)
    actions_snapshot = tuple(action_types)

    for _ in range(5):
        tool.call(arguments={"query": "storage"}, principal=principal)

    assert tuple(rules) == rules_snapshot
    assert tuple(action_types) == actions_snapshot


def test_tool_result_is_immutable(loaded_catalogs):
    rules, action_types = loaded_catalogs
    tool = ExploreCatalogTool(rules=rules, action_types=action_types)
    principal = Principal(id="test", role=Role.READER)

    from dataclasses import FrozenInstanceError

    result = tool.call(arguments={"query": "tag"}, principal=principal)
    assert isinstance(result, ToolResult)
    with pytest.raises(FrozenInstanceError):
        result.status = "error"  # type: ignore[misc]
