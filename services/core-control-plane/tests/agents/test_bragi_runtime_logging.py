"""Bragi split-module logging compatibility."""

from __future__ import annotations

from fdai.agents._framework import (
    bragi_ask_runtime,
    bragi_conversation_runtime,
    bragi_status_runtime,
)


def test_bragi_runtime_mixins_keep_member_logger_name() -> None:
    assert bragi_ask_runtime._LOG.name == "fdai.agents.bragi"
    assert bragi_conversation_runtime._LOG.name == "fdai.agents.bragi"
    assert bragi_status_runtime._LOG.name == "fdai.agents.bragi"
