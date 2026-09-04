from __future__ import annotations

import asyncio

import pytest
from fdai.delivery.live_blast_probe import LiveBlastProbeAdapter
from fdai.shared.providers.blast_probe import ProbeQuery, ProbeResult, ProbeVerdict


class _Signal:
    def __init__(self, result: ProbeResult | None = None, error: Exception | None = None) -> None:
        self.result = result or ProbeResult(ProbeVerdict.QUIET)
        self.error = error

    async def read(self, query: ProbeQuery) -> ProbeResult:
        del query
        if self.error is not None:
            raise self.error
        return self.result


class _Streak:
    def __init__(self) -> None:
        self.value = 0

    async def get(self, query: ProbeQuery) -> int:
        del query
        return self.value

    async def record_failure(self, query: ProbeQuery) -> int:
        del query
        self.value += 1
        return self.value

    async def record_success(self, query: ProbeQuery) -> None:
        del query
        self.value = 0


def _query() -> ProbeQuery:
    return ProbeQuery("vm_traffic_last_5m", "opaque-target", 0.1)


@pytest.mark.asyncio
async def test_success_resets_streak_and_preserves_provider_result() -> None:
    streak = _Streak()
    streak.value = 2
    result = await LiveBlastProbeAdapter(
        signal_source=_Signal(ProbeResult(ProbeVerdict.QUIET)),
        failure_streak_source=streak,
    ).measure(_query())
    assert result.verdict is ProbeVerdict.QUIET
    assert streak.value == 0


@pytest.mark.asyncio
async def test_unavailable_source_fails_closed_and_escalates_after_streak() -> None:
    streak = _Streak()
    adapter = LiveBlastProbeAdapter(
        signal_source=_Signal(error=RuntimeError("unavailable")),
        failure_streak_source=streak,
    )
    assert (await adapter.measure(_query())).verdict is ProbeVerdict.ACTIVE
    assert (await adapter.measure(_query())).verdict is ProbeVerdict.ACTIVE
    assert (await adapter.measure(_query())).verdict is ProbeVerdict.OVERLOADED


@pytest.mark.asyncio
async def test_degraded_result_counts_as_failure_and_never_resets_streak() -> None:
    streak = _Streak()
    adapter = LiveBlastProbeAdapter(
        signal_source=_Signal(
            ProbeResult(
                ProbeVerdict.ACTIVE,
                reason="provider evidence unavailable",
                degraded=True,
            )
        ),
        failure_streak_source=streak,
    )

    assert (await adapter.measure(_query())).verdict is ProbeVerdict.ACTIVE
    assert streak.value == 1
    assert (await adapter.measure(_query())).verdict is ProbeVerdict.ACTIVE
    assert (await adapter.measure(_query())).verdict is ProbeVerdict.OVERLOADED


@pytest.mark.asyncio
async def test_degraded_overloaded_result_is_never_weakened_by_early_streak() -> None:
    streak = _Streak()
    original = ProbeResult(
        ProbeVerdict.OVERLOADED,
        reason="provider reports saturation",
        degraded=True,
        metrics={"requests": 100.0},
    )

    result = await LiveBlastProbeAdapter(
        signal_source=_Signal(original),
        failure_streak_source=streak,
    ).measure(_query())

    assert result == original
    assert streak.value == 1


@pytest.mark.asyncio
async def test_overloaded_result_survives_success_streak_reset_failure() -> None:
    class _ResetFailure(_Streak):
        async def record_success(self, query: ProbeQuery) -> None:
            del query
            raise RuntimeError("unavailable")

    result = await LiveBlastProbeAdapter(
        signal_source=_Signal(
            ProbeResult(
                ProbeVerdict.OVERLOADED,
                reason="provider reports saturation",
                metrics={"requests": 100.0},
            )
        ),
        failure_streak_source=_ResetFailure(),
    ).measure(_query())

    assert result.verdict is ProbeVerdict.OVERLOADED
    assert result.degraded is True
    assert result.metrics == {"requests": 100.0}


@pytest.mark.asyncio
async def test_missing_streak_source_evidence_fails_closed() -> None:
    class _BrokenStreak(_Streak):
        async def record_failure(self, query: ProbeQuery) -> int:
            del query
            raise RuntimeError("unavailable")

    result = await LiveBlastProbeAdapter(
        signal_source=_Signal(error=RuntimeError("unavailable")),
        failure_streak_source=_BrokenStreak(),
    ).measure(_query())
    assert result.verdict is ProbeVerdict.OVERLOADED


@pytest.mark.asyncio
async def test_initial_streak_read_failure_is_immediately_overloaded() -> None:
    class _UnreadableStreak(_Streak):
        async def get(self, query: ProbeQuery) -> int:
            del query
            raise RuntimeError("unavailable")

    streak = _UnreadableStreak()
    result = await LiveBlastProbeAdapter(
        signal_source=_Signal(error=RuntimeError("unavailable")),
        failure_streak_source=streak,
    ).measure(_query())

    assert result.verdict is ProbeVerdict.OVERLOADED
    assert result.degraded is True
    assert streak.value == 0


@pytest.mark.asyncio
async def test_one_deadline_bounds_streak_and_signal_operations_together() -> None:
    class _SlowStreak(_Streak):
        async def get(self, query: ProbeQuery) -> int:
            del query
            await asyncio.sleep(0.03)
            return self.value

    class _SlowSignal(_Signal):
        async def read(self, query: ProbeQuery) -> ProbeResult:
            del query
            await asyncio.sleep(0.03)
            return self.result

    loop = asyncio.get_running_loop()
    started = loop.time()
    result = await LiveBlastProbeAdapter(
        signal_source=_SlowSignal(ProbeResult(ProbeVerdict.QUIET)),
        failure_streak_source=_SlowStreak(),
    ).measure(ProbeQuery("vm_traffic_last_5m", "opaque-target", 0.04))

    assert result.verdict is ProbeVerdict.OVERLOADED
    assert loop.time() - started < 0.06


@pytest.mark.asyncio
async def test_non_boolean_degraded_flag_counts_as_failure() -> None:
    streak = _Streak()
    malformed = ProbeResult(
        ProbeVerdict.QUIET,
        degraded=0,  # type: ignore[arg-type]
    )

    result = await LiveBlastProbeAdapter(
        signal_source=_Signal(malformed),
        failure_streak_source=streak,
    ).measure(_query())

    assert result.verdict is ProbeVerdict.ACTIVE
    assert result.degraded is True
    assert streak.value == 1


@pytest.mark.parametrize("deadline", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_probe_deadline_is_rejected(deadline: float) -> None:
    with pytest.raises(ValueError, match="deadline_seconds"):
        ProbeQuery("vm_traffic_last_5m", "opaque-target", deadline)
