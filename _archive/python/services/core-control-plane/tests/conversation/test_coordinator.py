"""Coordinator: intent match, RBAC gate, session projection, abstain."""

from __future__ import annotations

import pytest
from fdai.core.conversation import (
    AbstainResult,
    ConversationCoordinator,
    ConversationSession,
    CoordinatorConfig,
    ExploreCatalogTool,
    Principal,
    Role,
    ToolResult,
)


def _fake_action_type(name: str) -> object:
    """Minimum shape ExploreCatalogTool needs for iteration."""

    from dataclasses import dataclass

    @dataclass(frozen=True)
    class _Enum:
        value: str

        def __str__(self) -> str:
            return self.value

    @dataclass(frozen=True)
    class _TriggerKind:
        kind: _Enum

    @dataclass(frozen=True)
    class _ActionType:
        name: str
        description: str
        operation: _Enum
        category: _Enum
        trigger_kind: _TriggerKind

    return _ActionType(
        name=name,
        description="synthetic tag add",
        operation=_Enum("tag"),
        category=_Enum("remediation"),
        trigger_kind=_TriggerKind(_Enum("rule_violation")),
    )


def _fake_rule(rid: str, resource_type: str, description: str) -> object:
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class _Sev:
        value: str

        def __str__(self) -> str:
            return self.value

    @dataclass(frozen=True)
    class _Rule:
        id: str
        resource_type: str
        category: str
        severity: _Sev
        description: str

    return _Rule(
        id=rid,
        resource_type=resource_type,
        category="security",
        severity=_Sev("high"),
        description=description,
    )


@pytest.fixture
def tool_fixture():
    rules = [_fake_rule("r.storage-public", "storage-account", "Deny public access on storage")]
    action_types = [_fake_action_type("remediate.tag-add")]
    return ExploreCatalogTool(rules=rules, action_types=action_types)


@pytest.fixture
def coordinator(tool_fixture):
    return ConversationCoordinator(tools=[tool_fixture])


@pytest.fixture
def reader_session():
    return ConversationSession(
        session_id="sess-reader",
        principal=Principal(id="alice", role=Role.READER),
        channel_id="cli",
    )


def test_coordinator_dispatches_explore_catalog(coordinator, reader_session):
    result = coordinator.handle_turn(session=reader_session, message="explore_catalog storage")
    assert isinstance(result, ToolResult)
    assert result.status == "ok"
    assert result.data["query"] == "storage"


def test_coordinator_abstains_on_unknown_verb(coordinator, reader_session):
    result = coordinator.handle_turn(session=reader_session, message="do the needful please")
    assert isinstance(result, AbstainResult)
    assert "explore_catalog" in result.tool_inventory


def test_coordinator_appends_full_turn_transcript(coordinator, reader_session):
    coordinator.handle_turn(session=reader_session, message="explore_catalog tag")
    directions = [t.direction for t in reader_session.turns]
    # inbound -> tool_call -> tool_result
    assert directions == ["inbound", "tool_call", "tool_result"]
    tool_names = [t.tool_name for t in reader_session.turns if t.tool_name]
    assert tool_names == ["explore_catalog", "explore_catalog"]


def test_coordinator_never_fabricates_a_call_on_low_confidence(coordinator, reader_session):
    # Empty argument -> confidence 0.85 (still above default 0.75); should call.
    result = coordinator.handle_turn(session=reader_session, message="explore_catalog")
    assert isinstance(result, ToolResult)
    # Bump threshold to force abstain, verify never fabricates.
    strict = ConversationCoordinator(
        tools=[
            ExploreCatalogTool(
                rules=[],
                action_types=[_fake_action_type("remediate.tag-add")],
            )
        ],
        config=CoordinatorConfig(chat_t0_confidence_threshold=0.95),
    )
    strict_session = ConversationSession(
        session_id="sess-strict", principal=reader_session.principal, channel_id="cli"
    )
    r2 = strict.handle_turn(session=strict_session, message="explore_catalog")
    assert isinstance(r2, AbstainResult)


def test_coordinator_rbac_gate_denies_below_floor():
    """A tool whose floor is Approver rejects a Reader-role principal."""

    from typing import Any

    from fdai.core.conversation.tools import ToolResult as _ToolResult

    calls = 0

    class _ApproverOnlyTool:
        name = "explore_catalog"
        description = "gated"
        rbac_floor = Role.APPROVER
        side_effect_class = "read"

        def call(self, *, arguments: dict[str, Any], principal: Principal) -> _ToolResult:
            nonlocal calls
            calls += 1
            return _ToolResult(status="ok", preview="should-not-fire")

    coord = ConversationCoordinator(tools=[_ApproverOnlyTool()])
    session = ConversationSession(
        session_id="s",
        principal=Principal(id="reader", role=Role.READER),
        channel_id="cli",
    )
    result = coord.handle_turn(session=session, message="explore_catalog tag")
    assert isinstance(result, ToolResult)
    assert result.status == "error"
    assert result.preview == (
        "Tool access denied: 'explore_catalog' requires role 'approver'; "
        "current role is 'reader'. No tool was called."
    )
    assert calls == 0
    assert [turn.direction for turn in session.turns] == ["inbound", "system"]


def test_list_tools_for_filters_by_rbac():
    class _ReaderTool:
        name = "explore_catalog"
        description = "reader"
        rbac_floor = Role.READER
        side_effect_class = "read"

        def call(self, *, arguments, principal):  # noqa: ARG002
            return ToolResult(status="ok")

    class _ApproverTool:
        name = "approve_hil"
        description = "approver"
        rbac_floor = Role.APPROVER
        side_effect_class = "approve"

        def call(self, *, arguments, principal):  # noqa: ARG002
            return ToolResult(status="ok")

    coord = ConversationCoordinator(tools=[_ReaderTool(), _ApproverTool()])
    reader = Principal(id="r", role=Role.READER)
    approver = Principal(id="a", role=Role.APPROVER)

    assert coord.list_tools_for(reader) == ("explore_catalog",)
    assert coord.list_tools_for(approver) == ("approve_hil", "explore_catalog")


def test_coordinator_rejects_empty_tool_set():
    with pytest.raises(ValueError, match="at least one tool"):
        ConversationCoordinator(tools=[])


def test_default_surface_rejects_alias_and_accepts_exact_command(coordinator, reader_session):
    ordinary = coordinator.handle_turn(session=reader_session, message="list rules")
    exact = coordinator.handle_turn(session=reader_session, message="explore_catalog storage")

    assert isinstance(ordinary, AbstainResult)
    assert "semantic conversation runtime" in ordinary.reason
    assert isinstance(exact, ToolResult)


def test_session_snapshot_is_immutable(coordinator, reader_session):
    coordinator.handle_turn(session=reader_session, message="explore_catalog tag")
    snapshot = reader_session.snapshot()
    coordinator.handle_turn(session=reader_session, message="explore_catalog stub")
    # Original snapshot unchanged - it's a tuple.
    assert len(snapshot) == 3
    assert len(reader_session.snapshot()) == 6
