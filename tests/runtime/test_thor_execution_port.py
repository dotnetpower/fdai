"""Focused runtime binding checks for the in-process Thor execution port."""

from __future__ import annotations

from inspect import signature
from unittest.mock import MagicMock

from fdai.core.executor import (
    DirectApiShadowExecutor,
    InProcessThorExecutionPort,
    ShadowExecutor,
    ToolCallShadowExecutor,
)
from fdai.runtime.control_loop import _build_control_loop, _legacy_executor_bindings


def test_runtime_accepts_one_thor_port_and_preserves_executor_identity() -> None:
    pr_native = MagicMock(spec=ShadowExecutor)
    direct_api = MagicMock(spec=DirectApiShadowExecutor)
    tool_call = MagicMock(spec=ToolCallShadowExecutor)
    port = InProcessThorExecutionPort(
        pr_native=pr_native,
        direct_api=direct_api,
        tool_call=tool_call,
    )

    bindings = _legacy_executor_bindings(port)

    assert "thor_execution_port" in signature(_build_control_loop).parameters
    assert bindings == (pr_native, direct_api, tool_call)
