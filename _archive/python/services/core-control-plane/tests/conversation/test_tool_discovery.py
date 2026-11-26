"""RBAC-filtered runtime tool search and description tests."""

from __future__ import annotations

import pytest
from fdai.core.conversation import (
    DescribeRuntimeTool,
    Principal,
    Role,
    RuntimeToolDiscovery,
    SearchRuntimeToolsTool,
    ToolDiscoveryError,
    default_tool_schemas,
)


def _discovery() -> RuntimeToolDiscovery:
    return RuntimeToolDiscovery(
        schemas=default_tool_schemas(),
        installed_tool_names=frozenset(
            {"query_inventory", "query_audit", "simulate_change", "approve_hil"}
        ),
    )


def test_search_returns_only_installed_and_principal_eligible_tools() -> None:
    reader = Principal(id="reader-1", role=Role.READER)

    results = _discovery().search("query", principal=reader)

    assert [descriptor.name for descriptor in results] == ["query_audit", "query_inventory"]


def test_reader_cannot_discover_or_describe_approval_tool() -> None:
    reader = Principal(id="reader-1", role=Role.READER)

    assert _discovery().search("approve", principal=reader) == ()
    with pytest.raises(ToolDiscoveryError, match="unavailable"):
        _discovery().describe("approve_hil", principal=reader)


def test_approver_sees_side_effect_metadata_without_invocation_handle() -> None:
    approver = Principal(id="approver-1", role=Role.APPROVER)

    descriptor = _discovery().describe("approve_hil", principal=approver)
    payload = descriptor.to_dict()

    assert payload["side_effect_class"] == "approve"
    assert payload["rbac_floor"] == "approver"
    assert "handler" not in payload
    assert "call" not in payload


def test_exact_name_is_ranked_before_description_match() -> None:
    reader = Principal(id="reader-1", role=Role.READER)
    results = _discovery().search("query_inventory", principal=reader)
    assert results[0].name == "query_inventory"


def test_uninstalled_schema_is_not_discoverable() -> None:
    owner = Principal(id="owner-1", role=Role.OWNER)
    with pytest.raises(ToolDiscoveryError, match="unavailable"):
        _discovery().describe("run_runbook", principal=owner)


def test_channel_tools_search_and_describe_without_invoking_target() -> None:
    principal = Principal(id="approver-1", role=Role.APPROVER)
    search = SearchRuntimeToolsTool(_discovery()).call(
        arguments={"query": "approve"},
        principal=principal,
    )
    describe = DescribeRuntimeTool(_discovery()).call(
        arguments={"tool_name": "approve_hil"},
        principal=principal,
    )

    assert search.data["tools"][0]["name"] == "approve_hil"
    assert describe.data["tool"]["side_effect_class"] == "approve"
    assert "handler" not in describe.data["tool"]
