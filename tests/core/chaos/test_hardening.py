"""Chaos harness hardening: op/rollback timeouts, hold cap, empty-target guard.

Each test maps to a hardening item from the chaos/irp critique:

- H1 rollback timeout  -> a hung ``stop`` is flagged, never blocks the run.
- H2 inject timeout    -> a hung ``inject`` aborts (nothing left injected).
- H3 probe timeout     -> a hung probe aborts AND rolls back injected targets.
- H4 hold cap          -> an over-large authored duration is clamped.
- H6 empty targets     -> an enforce run over no targets is refused.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence

import pytest

from fdai.core.chaos import ExperimentOutcome, FaultInjectionHarness
from fdai.core.chaos.contract import FaultScenario
from fdai.shared.contracts.models import Mode


def _scenario(*, duration: float = 5.0, cap: int = 3) -> FaultScenario:
    return FaultScenario(
        scenario_id="s-test",
        fault_type="cpu_stress",
        description="test",
        target_selector="sel",
        expected_signal="cpu.throttle",
        blast_radius_cap=cap,
        duration_seconds=duration,
    )


class _Injector:
    def __init__(self, *, inject_hang: bool = False, stop_hang: bool = False) -> None:
        self._inject_hang = inject_hang
        self._stop_hang = stop_hang
        self.injected: list[str] = []
        self.stopped: list[str] = []

    @property
    def fault_type(self) -> str:
        return "cpu_stress"

    async def inject(self, *, target: str, params: Mapping[str, str]) -> None:  # noqa: ARG002
        if self._inject_hang:
            await asyncio.sleep(10)
        self.injected.append(target)

    async def stop(self, *, target: str) -> None:
        if self._stop_hang:
            await asyncio.sleep(10)
        self.stopped.append(target)


class _OkProbe:
    async def observed(self, *, signal: str, targets: Sequence[str]) -> bool:  # noqa: ARG002
        return True


class _HangProbe:
    async def observed(self, *, signal: str, targets: Sequence[str]) -> bool:  # noqa: ARG002
        await asyncio.sleep(10)
        return True  # pragma: no cover - cancelled by timeout


async def _noop_sleep(_seconds: float) -> None:
    return None


@pytest.mark.parametrize(
    "field",
    ["operation_timeout_seconds", "rollback_timeout_seconds", "max_hold_seconds"],
)
def test_ctor_rejects_nonpositive_bounds(field: str) -> None:
    with pytest.raises(ValueError, match=field):
        FaultInjectionHarness(**{field: 0.0})  # type: ignore[arg-type]


async def test_empty_targets_refused() -> None:  # H6
    inj = _Injector()
    harness = FaultInjectionHarness(injectors=(inj,), sleeper=_noop_sleep)
    result = await harness.run(_scenario(), approved_targets=(), mode=Mode.ENFORCE)
    assert result.outcome is ExperimentOutcome.ABORTED
    assert result.error == "no_approved_targets"
    assert inj.injected == []


async def test_inject_timeout_aborts_nothing_injected() -> None:  # H2
    inj = _Injector(inject_hang=True)
    harness = FaultInjectionHarness(
        injectors=(inj,), sleeper=_noop_sleep, operation_timeout_seconds=0.02
    )
    result = await harness.run(_scenario(), approved_targets=("a",), mode=Mode.ENFORCE)
    assert result.outcome is ExperimentOutcome.ABORTED
    assert result.error is not None and "TimeoutError" in result.error
    assert inj.injected == []


async def test_probe_timeout_aborts_and_rolls_back() -> None:  # H3
    inj = _Injector()
    harness = FaultInjectionHarness(
        injectors=(inj,),
        probe=_HangProbe(),
        sleeper=_noop_sleep,
        operation_timeout_seconds=0.02,
    )
    result = await harness.run(_scenario(), approved_targets=("a",), mode=Mode.ENFORCE)
    assert result.outcome is ExperimentOutcome.ABORTED
    assert inj.injected == ["a"]
    assert inj.stopped == ["a"]  # rolled back despite the probe hanging
    assert result.reverted is True


async def test_rollback_timeout_marks_not_reverted() -> None:  # H1
    inj = _Injector(stop_hang=True)
    harness = FaultInjectionHarness(
        injectors=(inj,),
        probe=_OkProbe(),
        sleeper=_noop_sleep,
        rollback_timeout_seconds=0.02,
    )
    result = await harness.run(_scenario(), approved_targets=("a",), mode=Mode.ENFORCE)
    assert inj.injected == ["a"]
    # A hung rollback is surfaced as a possibly-live fault, not a hang.
    assert result.stopped is False
    assert result.reverted is False


async def test_hold_capped_at_max_hold() -> None:  # H4
    holds: list[float] = []

    async def _recording_sleep(seconds: float) -> None:
        holds.append(seconds)

    harness = FaultInjectionHarness(
        injectors=(_Injector(),),
        probe=_OkProbe(),
        sleeper=_recording_sleep,
        max_hold_seconds=1.5,
    )
    await harness.run(_scenario(duration=1000.0), approved_targets=("a",), mode=Mode.ENFORCE)
    assert holds == [1.5]  # clamped to the harness ceiling


async def test_hold_uses_duration_when_below_cap() -> None:  # H4 lower branch
    holds: list[float] = []

    async def _recording_sleep(seconds: float) -> None:
        holds.append(seconds)

    harness = FaultInjectionHarness(
        injectors=(_Injector(),),
        probe=_OkProbe(),
        sleeper=_recording_sleep,
        max_hold_seconds=600.0,
    )
    await harness.run(_scenario(duration=2.0), approved_targets=("a",), mode=Mode.ENFORCE)
    assert holds == [2.0]
