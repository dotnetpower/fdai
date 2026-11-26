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
    # Even though the signal WAS detected, the live-fault state is the
    # headline outcome - not a misleading VALIDATED.
    assert result.detected is True
    assert result.outcome is ExperimentOutcome.ROLLBACK_FAILED


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


async def test_duplicate_targets_deduped_no_double_inject() -> None:  # H7
    inj = _Injector()
    harness = FaultInjectionHarness(injectors=(inj,), probe=_OkProbe(), sleeper=_noop_sleep)
    result = await harness.run(
        _scenario(cap=2), approved_targets=("a", "a", "b"), mode=Mode.ENFORCE
    )
    # 'a' injected + stopped exactly once despite appearing twice.
    assert inj.injected == ["a", "b"]
    assert inj.stopped == ["a", "b"]
    assert result.targets == ("a", "b")


async def test_duplicates_do_not_trip_blast_radius_cap() -> None:  # H7
    inj = _Injector()
    harness = FaultInjectionHarness(injectors=(inj,), probe=_OkProbe(), sleeper=_noop_sleep)
    # Three copies of one distinct target with cap=1 is ONE target, not three.
    result = await harness.run(
        _scenario(cap=1), approved_targets=("a", "a", "a"), mode=Mode.ENFORCE
    )
    assert result.outcome is not ExperimentOutcome.BLAST_RADIUS_EXCEEDED
    assert inj.injected == ["a"]


async def test_blank_targets_dropped() -> None:  # H7
    inj = _Injector()
    harness = FaultInjectionHarness(injectors=(inj,), probe=_OkProbe(), sleeper=_noop_sleep)
    result = await harness.run(
        _scenario(cap=3), approved_targets=("a", "  ", "", "b"), mode=Mode.ENFORCE
    )
    assert inj.injected == ["a", "b"]
    assert result.targets == ("a", "b")


async def test_all_blank_targets_refused_in_enforce() -> None:  # H7
    inj = _Injector()
    harness = FaultInjectionHarness(injectors=(inj,), sleeper=_noop_sleep)
    result = await harness.run(_scenario(), approved_targets=("  ", ""), mode=Mode.ENFORCE)
    assert result.outcome is ExperimentOutcome.ABORTED
    assert result.error == "no_approved_targets"
    assert inj.injected == []


class _FailStopInjector:
    """Injects fine but always raises on stop (rollback failure)."""

    def __init__(self) -> None:
        self.injected: list[str] = []

    @property
    def fault_type(self) -> str:
        return "cpu_stress"

    async def inject(self, *, target: str, params: Mapping[str, str]) -> None:  # noqa: ARG002
        self.injected.append(target)

    async def stop(self, *, target: str) -> None:  # noqa: ARG002
        raise RuntimeError("rollback boom")


async def test_rollback_failure_outcome_beats_detection() -> None:  # H8
    inj = _FailStopInjector()
    harness = FaultInjectionHarness(injectors=(inj,), probe=_OkProbe(), sleeper=_noop_sleep)
    result = await harness.run(_scenario(), approved_targets=("a",), mode=Mode.ENFORCE)
    # Signal detected, but rollback raised -> a live fault is the headline.
    assert result.detected is True
    assert result.stopped is False
    assert result.reverted is False
    assert result.outcome is ExperimentOutcome.ROLLBACK_FAILED


async def test_clean_run_with_successful_rollback_stays_validated() -> None:  # H8
    inj = _Injector()
    harness = FaultInjectionHarness(injectors=(inj,), probe=_OkProbe(), sleeper=_noop_sleep)
    result = await harness.run(_scenario(), approved_targets=("a",), mode=Mode.ENFORCE)
    assert result.stopped is True
    assert result.outcome is ExperimentOutcome.VALIDATED


async def test_cancellation_rolls_back_and_still_audits() -> None:  # H9
    from fdai.core.chaos.injector import InMemoryExperimentRecorder

    inj = _Injector()
    recorder = InMemoryExperimentRecorder()

    async def _cancelling_sleep(_seconds: float) -> None:
        raise asyncio.CancelledError

    harness = FaultInjectionHarness(injectors=(inj,), recorder=recorder, sleeper=_cancelling_sleep)

    with pytest.raises(asyncio.CancelledError):
        await harness.run(_scenario(), approved_targets=("a",), mode=Mode.ENFORCE)

    # The injected target was rolled back despite the cancellation...
    assert inj.injected == ["a"]
    assert inj.stopped == ["a"]
    # ...and the run still produced exactly one audit record (invariant).
    assert len(recorder.results) == 1
    rec = recorder.results[0]
    assert rec.outcome is ExperimentOutcome.ABORTED
    assert rec.error == "cancelled"
    assert rec.reverted is True
