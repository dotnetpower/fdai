"""Route ontology tool calls to adapters with per-ActionType enforce gates."""

from __future__ import annotations

from collections.abc import Mapping

from fdai.shared.contracts.models import Mode
from fdai.shared.providers.tool import (
    ToolCallReceipt,
    ToolCallRequest,
    ToolError,
    ToolExecutor,
    ToolPromotionError,
)


class RoutingToolExecutor(ToolExecutor):
    """Dispatch by ActionType while keeping enforce permission route-local."""

    def __init__(
        self,
        *,
        routes: Mapping[str, ToolExecutor],
        enforce_actions: frozenset[str] = frozenset(),
        fallback: ToolExecutor | None = None,
    ) -> None:
        self._routes = dict(routes)
        self._enforce_actions = enforce_actions
        self._fallback = fallback
        unknown = enforce_actions - self._routes.keys()
        if unknown:
            raise ValueError(f"enforce_actions have no registered route: {sorted(unknown)}")

    async def execute(self, request: ToolCallRequest) -> ToolCallReceipt:
        adapter = self._routes.get(request.action_type_name, self._fallback)
        if adapter is None:
            raise ToolError("unknown_tool", f"no adapter for {request.action_type_name!r}")
        if request.mode is Mode.ENFORCE and request.action_type_name not in self._enforce_actions:
            raise ToolPromotionError(
                f"tool {request.action_type_name!r} is not enabled for enforce dispatch"
            )
        return await adapter.execute(request)


__all__ = ["RoutingToolExecutor"]
