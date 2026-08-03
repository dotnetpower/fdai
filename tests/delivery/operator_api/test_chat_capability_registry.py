from __future__ import annotations

from fdai.delivery.operator_api.routes.chat_capability_registry import (
    ConversationCapability,
    ConversationCapabilityRegistry,
    validate_panel_chat_bindings,
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


def test_registry_keeps_enabled_separate_from_available() -> None:
    enabled = False
    registry = ConversationCapabilityRegistry(
        (
            ConversationCapability(
                tool=_tool("web_search"),
                owner="approved_web_search",
                authority="read",
                available=lambda: True,
                enabled=lambda: enabled,
            ),
        )
    )

    assert registry.status()[0]["available"] is True
    assert registry.status()[0]["enabled"] is False
    assert registry.visible_tools() == ()
    enabled = True
    assert [tool.name for tool in registry.visible_tools()] == ["web_search"]


def test_declared_panel_chat_binding_requires_registered_tool() -> None:
    class Panel:
        name = "llm-cost"
        conversation_tool = "query_llm_usage"

    validate_panel_chat_bindings((Panel(), object()), (_tool("query_llm_usage"),))

    try:
        validate_panel_chat_bindings((Panel(),), (_tool("query_inventory"),))
    except ValueError as exc:
        assert str(exc) == "panel 'llm-cost' requires chat capability 'query_llm_usage'"
    else:
        raise AssertionError("missing declared panel chat capability must fail closed")
