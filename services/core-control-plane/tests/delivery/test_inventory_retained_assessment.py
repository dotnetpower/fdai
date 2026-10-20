"""Current-source concept evidence, not a provider incident or live qualification."""

from __future__ import annotations

import pytest
from fdai.delivery.azure import arg_transport


async def test_arg_cooldown_is_adapter_local_not_replayed_by_a_replacement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 0.0
    waits: list[float] = []

    async def sleep(delay: float) -> None:
        nonlocal now
        waits.append(delay)
        now += delay

    monkeypatch.setattr(arg_transport, "_monotonic", lambda: now)
    monkeypatch.setattr(arg_transport, "_sleep", sleep)
    original = arg_transport.ArgThrottleGate()
    await original.defer(20.0)
    replacement = arg_transport.ArgThrottleGate()
    await replacement.wait()
    assert waits == []
    assert now == 0.0
    await original.wait()
    assert waits == [20.0]
    assert now == 20.0
