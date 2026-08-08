"""Per-ActionType tool routing and enforce isolation."""

from uuid import UUID

import pytest
from fdai.delivery.tool_router import RoutingToolExecutor
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.testing.tool import RecordingToolExecutor
from fdai.shared.providers.tool import ToolCallRequest, ToolPromotionError


def _request(action: str, *, mode: Mode) -> ToolCallRequest:
    return ToolCallRequest(
        action_id=UUID("00000000-0000-0000-0000-000000000001"),
        idempotency_key=f"{action}:{mode.value}",
        action_type_name=action,
        rule_ids=("operator.request",),
        tool_ref="target-1",
        labels=("enforce",) if mode is Mode.ENFORCE else ("shadow",),
        mode=mode,
    )


async def test_routes_by_action_type() -> None:
    vm = RecordingToolExecutor()
    jira = RecordingToolExecutor()
    router = RoutingToolExecutor(
        routes={"tool.run-python-on-vm": vm, "tool.open-ticket": jira},
    )

    await router.execute(_request("tool.run-python-on-vm", mode=Mode.SHADOW))
    await router.execute(_request("tool.open-ticket", mode=Mode.SHADOW))

    assert len(vm.records) == 1
    assert len(jira.records) == 1


async def test_enforce_permission_is_action_local() -> None:
    adapter = RecordingToolExecutor()
    router = RoutingToolExecutor(
        routes={"tool.run-python-on-vm": adapter, "tool.open-ticket": adapter},
        enforce_actions=frozenset({"tool.run-python-on-vm"}),
    )

    await router.execute(_request("tool.run-python-on-vm", mode=Mode.ENFORCE))
    with pytest.raises(ToolPromotionError, match="not enabled"):
        await router.execute(_request("tool.open-ticket", mode=Mode.ENFORCE))
