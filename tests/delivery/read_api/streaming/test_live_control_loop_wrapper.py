"""Wrapper-seam test for the dev ControlLoop emitter (Phase 4C).

Verifies that ``stage_publisher_wrapper`` is applied to the ControlLoop's stage
publisher, which is how the dev harness tees real pipeline frames into the
agent-activity relay. Skips when the shipped rule catalog cannot be composed in
this environment (the emitter needs it on disk).
"""

from __future__ import annotations

import pytest

from fdai.delivery.read_api.streaming.live_control_loop import (
    ControlLoopEmitterUnavailable,
    build_control_loop_emitter,
)
from fdai.shared.providers.stage_publisher import StagePublisher
from fdai.shared.providers.testing.sse import InMemorySseSink


def test_stage_publisher_wrapper_is_applied_to_the_control_loop() -> None:
    seen: list[StagePublisher] = []

    def _wrapper(inner: StagePublisher) -> StagePublisher:
        seen.append(inner)
        return inner

    emitter = build_control_loop_emitter(
        InMemorySseSink(),
        "aw.pipeline.stages",
        events_per_second=3.0,
        stage_publisher_wrapper=_wrapper,
    )
    try:
        emitter._build_control_loop()
    except ControlLoopEmitterUnavailable:
        pytest.skip("rule catalog not composable in this environment")
    assert len(seen) == 1, "wrapper MUST be invoked once with the inner stage publisher"


def test_no_wrapper_leaves_the_stage_publisher_unwrapped() -> None:
    emitter = build_control_loop_emitter(
        InMemorySseSink(),
        "aw.pipeline.stages",
        events_per_second=3.0,
    )
    assert emitter.stage_publisher_wrapper is None
