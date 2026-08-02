from __future__ import annotations

from fdai.delivery.operator_api.routes.chat_capability_registry import (
    ConversationCapability,
    ConversationCapabilityRegistry,
)
from fdai.delivery.operator_api.routes.chat_turn_plan import TurnTool


def _tool(name: str) -> TurnTool:
    return TurnTool(
        name=name,
        description="Read evidence.",
        side_effect_class="read_only",
        argument_schema={"type": "object", "properties": {}, "additionalProperties": False},
    )


def test_registry_projects_request_time_availability() -> None:
    ready = False
    registry = ConversationCapabilityRegistry(
        (
            ConversationCapability(
                tool=_tool("query_agent"),
                owner="agent_event_bus",
                authority="read",
                available=lambda: ready,
            ),
        )
    )

    assert registry.visible_tools() == ()
    ready = True
    assert [tool.name for tool in registry.visible_tools()] == ["query_agent"]


def test_registry_rejects_duplicate_capability_names() -> None:
    capability = ConversationCapability(
        tool=_tool("query_health"),
        owner="operator_api",
        authority="read",
        available=lambda: True,
    )

    try:
        ConversationCapabilityRegistry((capability, capability))
    except ValueError as exc:
        assert str(exc) == "conversation capability names must be unique"
    else:
        raise AssertionError("duplicate capability names must fail closed")
