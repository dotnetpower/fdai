from __future__ import annotations

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
