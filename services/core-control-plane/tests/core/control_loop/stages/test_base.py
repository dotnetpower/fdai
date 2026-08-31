"""Coverage for the dormant ControlLoop stage Protocol."""

from __future__ import annotations

from fdai.core.control_loop.stages.base import Stage


class _Stage:
    name = "example"

    async def handle(self, ctx: object) -> object:
        return ctx


async def test_stage_protocol_accepts_async_structural_implementation() -> None:
    stage = _Stage()

    assert isinstance(stage, Stage)
    marker = object()
    assert await stage.handle(marker) is marker
