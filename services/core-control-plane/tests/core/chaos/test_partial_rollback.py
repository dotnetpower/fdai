"""Regression: a partial fault injection must still roll back what it injected."""

from __future__ import annotations

from collections.abc import Mapping

import pytest
from fdai.core.chaos import ExperimentOutcome, FaultInjectionHarness
from fdai.core.chaos.contract import FaultScenario
from fdai.shared.contracts.models import Mode


class _PartialInjector:
    """Injects fine until it hits ``fail_on``, then raises.

    Records every inject + stop so a test can prove the already-injected
    targets are rolled back even though a later inject failed.
    """

    def __init__(self, *, fail_on: str) -> None:
        self._fail_on = fail_on
        self.injected: list[str] = []
        self.stopped: list[str] = []

    @property
    def fault_type(self) -> str:
        return "cpu_stress"

    async def inject(self, *, target: str, params: Mapping[str, str]) -> None:  # noqa: ARG002
        if target == self._fail_on:
            raise RuntimeError(f"inject failed on {target}")
        self.injected.append(target)

    async def stop(self, *, target: str) -> None:
        self.stopped.append(target)


async def _noop_sleep(_seconds: float) -> None:
    return None


def _scenario() -> FaultScenario:
    return FaultScenario(
        scenario_id="multi",
        fault_type="cpu_stress",
        description="d",
        target_selector="sel",
        expected_signal="node_cpu",
        blast_radius_cap=5,
        duration_seconds=1.0,
    )


@pytest.mark.asyncio
async def test_partial_injection_rolls_back_injected_targets() -> None:
    injector = _PartialInjector(fail_on="b")
    harness = FaultInjectionHarness(injectors=(injector,), sleeper=_noop_sleep)

    result = await harness.run(_scenario(), approved_targets=("a", "b", "c"), mode=Mode.ENFORCE)

    # 'a' was injected before 'b' failed; both MUST be rolled back because the
    # failed call on 'b' may still have applied the fault.
    assert injector.injected == ["a"]
    assert injector.stopped == ["a", "b"]
    assert result.outcome is ExperimentOutcome.ABORTED
    assert result.injected is True
    assert result.reverted is True  # the live fault was undone


@pytest.mark.asyncio
async def test_first_target_failure_still_rolls_back_the_attempted_target() -> None:
    injector = _PartialInjector(fail_on="a")
    harness = FaultInjectionHarness(injectors=(injector,), sleeper=_noop_sleep)

    result = await harness.run(_scenario(), approved_targets=("a", "b"), mode=Mode.ENFORCE)

    # The raised call may have applied the fault (for example a client timeout
    # after the provider accepted it), so it is treated as injected.
    assert injector.injected == []
    assert injector.stopped == ["a"]
    assert result.outcome is ExperimentOutcome.ABORTED
    assert result.injected is True
    assert result.reverted is True


class _AppliedThenTimeoutInjector:
    """Applies the fault, then raises as a client-side timeout would."""

    def __init__(self) -> None:
        self.applied: list[str] = []
        self.stopped: list[str] = []

    @property
    def fault_type(self) -> str:
        return "cpu_stress"

    async def inject(self, *, target: str, params: Mapping[str, str]) -> None:  # noqa: ARG002
        self.applied.append(target)
        raise TimeoutError("provider accepted the change but the client timed out")

    async def stop(self, *, target: str) -> None:
        self.stopped.append(target)


@pytest.mark.asyncio
async def test_applied_then_timeout_injection_is_rolled_back_and_reported_injected() -> None:
    injector = _AppliedThenTimeoutInjector()
    harness = FaultInjectionHarness(injectors=(injector,), sleeper=_noop_sleep)

    result = await harness.run(_scenario(), approved_targets=("a",), mode=Mode.ENFORCE)

    assert injector.applied == ["a"]
    assert injector.stopped == ["a"]
    assert result.outcome is ExperimentOutcome.ABORTED
    assert result.injected is True
    assert result.error is not None and result.error.startswith("TimeoutError")
