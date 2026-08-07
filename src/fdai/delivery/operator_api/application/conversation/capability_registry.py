"""Request-time capability visibility for hierarchical conversation planning."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from fdai.delivery.operator_api.application.conversation.turn_plan import TurnTool


@dataclass(frozen=True, slots=True)
class ConversationCapability:
    tool: TurnTool
    owner: str
    authority: str
    available: Callable[[], bool]
    enabled: Callable[[], bool] = lambda: True
    unavailable_reason: str | None = None


class ConversationCapabilityRegistry:
    """Project only enabled and currently available tools to the mini planner."""

    def __init__(self, capabilities: Sequence[ConversationCapability]) -> None:
        names = [capability.tool.name for capability in capabilities]
        if len(names) != len(set(names)):
            raise ValueError("conversation capability names must be unique")
        self._capabilities = tuple(capabilities)

    def visible_tools(self) -> tuple[TurnTool, ...]:
        return tuple(
            capability.tool
            for capability in self._capabilities
            if capability.enabled() and capability.available()
        )

    def registered_tools(self) -> tuple[TurnTool, ...]:
        """Return every declared tool regardless of request-time availability."""

        return tuple(capability.tool for capability in self._capabilities)

    def status(self) -> tuple[dict[str, object], ...]:
        return tuple(
            {
                "name": capability.tool.name,
                "owner": capability.owner,
                "authority": capability.authority,
                "enabled": capability.enabled(),
                "available": capability.available(),
                "unavailable_reason": capability.unavailable_reason,
            }
            for capability in self._capabilities
        )


def static_capabilities(
    tools: Sequence[TurnTool],
    *,
    owner: str,
    authority: str,
) -> tuple[ConversationCapability, ...]:
    return tuple(
        ConversationCapability(
            tool=tool,
            owner=owner,
            authority=authority,
            available=lambda: True,
        )
        for tool in tools
    )


def validate_panel_chat_bindings(
    panels: Sequence[object],
    tools: Sequence[TurnTool],
) -> None:
    """Fail when a panel declares a conversational companion that is absent."""

    tool_names = {tool.name for tool in tools}
    for panel in panels:
        tool_name = getattr(panel, "conversation_tool", None)
        if tool_name is None:
            continue
        panel_name = getattr(panel, "name", None)
        if not isinstance(panel_name, str) or not panel_name or not isinstance(tool_name, str):
            raise ValueError("panel conversation binding is invalid")
        if tool_name not in tool_names:
            raise ValueError(f"panel {panel_name!r} requires chat capability {tool_name!r}")


__all__ = [
    "ConversationCapability",
    "ConversationCapabilityRegistry",
    "static_capabilities",
    "validate_panel_chat_bindings",
]
