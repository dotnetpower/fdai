"""Tests for the chaos / fault-injection harness."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import pytest

from fdai.core.chaos import (
    AKS_POD_CPU_SPIKE,
    ExperimentOutcome,
    FaultInjectionHarness,
    InMemoryExperimentRecorder,
    ShadowFaultInjector,
    default_scenarios,
)
from fdai.core.chaos.contract import FaultScenario
from fdai.core.chaos.injector import DetectionOnlyInjector
from fdai.shared.contracts.models import Mode


class _RecordingInjector:
    def __init__(self, *, fault_type: str, fail: bool = False) -> None:
        self._fault_type = fault_type
        self._fail = fail
        self.injected: list[str] = []
        self.stopped: list[str] = []

    @property
    def fault_type(self) -> str:
        return self._fault_type

    async def inject(self, *, target: str, params: Mapping[str, str]) -> None:  # noqa: ARG002
        if self._fail:
            raise RuntimeError("injection backend error")
        self.injected.append(target)

    async def stop(self, *, target: str) -> None:
        self.stopped.append(target)


class _AlwaysProbe:
    def __init__(self, *, result: bool) -> None:
        self._result = result

    async def observed(self, *, signal: str, targets: Sequence[str]) -> bool:  # noqa: ARG002
        return self._result


async def _noop_sleep(_seconds: float) -> None:
    return None


@pytest.mark.asyncio
async def test_shadow_never_touches_injector() -> None:
    injector = _RecordingInjector(fault_type="cpu_stress")
    recorder = InMemoryExperimentRecorder()
    harness = FaultInjectionHarness(injectors=(injector,), recorder=recorder, sleeper=_noop_sleep)

    result = await harness.run(AKS_POD_CPU_SPIKE, approved_targets=("pod-a",), mode=Mode.SHADOW)

    assert result.outcome is ExperimentOutcome.SHADOWED
    assert result.injected is False
    assert injector.injected == []  # provably no perturbation
    assert result.reverted is True
    assert recorder.results == [result]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "expected_outcome"),
    [
        (Mode.SHADOW, ExperimentOutcome.SHADOWED),
        (Mode.ENFORCE, ExperimentOutcome.VALIDATED),
    ],
)
async def test_detection_only_path_probes_without_injection_or_hold(
    mode: Mode,
    expected_outcome: ExperimentOutcome,
) -> None:
    scenario = FaultScenario(
        scenario_id="chaos.gpu.sku-mismatch",
        fault_type="quota_shrink",
        description="GPU SKU mismatch",
        target_selector="gpu:profile",
        expected_signal="gpu_sku_mismatch",
        blast_radius_cap=1,
        duration_seconds=360,
    )
    harness = FaultInjectionHarness(
        injectors=(DetectionOnlyInjector(fault_type="quota_shrink"),),
        probe=_AlwaysProbe(result=True),
        sleeper=lambda _: pytest.fail("detection-only path MUST NOT hold"),
    )

    result = await harness.run(scenario, approved_targets=("gpu-profile",), mode=mode)

    assert result.outcome is expected_outcome
    assert result.detected is True
    assert result.injected is False
    assert result.stopped is True


@pytest.mark.asyncio
async def test_enforce_validated_when_signal_detected() -> None:
    injector = _RecordingInjector(fault_type="cpu_stress")
    harness = FaultInjectionHarness(
        injectors=(injector,),
        probe=_AlwaysProbe(result=True),
        sleeper=_noop_sleep,
    )

    result = await harness.run(AKS_POD_CPU_SPIKE, approved_targets=("pod-a",), mode=Mode.ENFORCE)

    assert result.outcome is ExperimentOutcome.VALIDATED
    assert result.detected is True
    assert injector.injected == ["pod-a"]
    assert injector.stopped == ["pod-a"]  # always rolled back
    assert result.reverted is True


@pytest.mark.asyncio
async def test_enforce_not_detected_is_a_detection_gap() -> None:
    injector = _RecordingInjector(fault_type="cpu_stress")
    harness = FaultInjectionHarness(
        injectors=(injector,),
        probe=_AlwaysProbe(result=False),
        sleeper=_noop_sleep,
    )

    result = await harness.run(AKS_POD_CPU_SPIKE, approved_targets=("pod-a",), mode=Mode.ENFORCE)

    assert result.outcome is ExperimentOutcome.NOT_DETECTED
    assert injector.stopped == ["pod-a"]


@pytest.mark.asyncio
async def test_blast_radius_exceeded_refuses_injection() -> None:
    injector = _RecordingInjector(fault_type="cpu_stress")
    harness = FaultInjectionHarness(injectors=(injector,), sleeper=_noop_sleep)

    # AKS_POD_CPU_SPIKE cap is 3; request 4 targets.
    result = await harness.run(
        AKS_POD_CPU_SPIKE,
        approved_targets=("a", "b", "c", "d"),
        mode=Mode.ENFORCE,
    )

    assert result.outcome is ExperimentOutcome.BLAST_RADIUS_EXCEEDED
    assert injector.injected == []
    assert result.error is not None


@pytest.mark.asyncio
async def test_injection_failure_aborts_and_rolls_back() -> None:
    injector = _RecordingInjector(fault_type="cpu_stress", fail=True)
    harness = FaultInjectionHarness(injectors=(injector,), sleeper=_noop_sleep)

    result = await harness.run(AKS_POD_CPU_SPIKE, approved_targets=("pod-a",), mode=Mode.ENFORCE)

    assert result.outcome is ExperimentOutcome.ABORTED
    assert result.error is not None
    assert result.injected is False


@pytest.mark.asyncio
async def test_enforce_without_injector_aborts() -> None:
    harness = FaultInjectionHarness(injectors=(), sleeper=_noop_sleep)

    result = await harness.run(AKS_POD_CPU_SPIKE, approved_targets=("pod-a",), mode=Mode.ENFORCE)

    assert result.outcome is ExperimentOutcome.ABORTED
    assert "no_injector" in (result.error or "")


@pytest.mark.asyncio
async def test_wildcard_shadow_injector_covers_any_fault_type() -> None:
    harness = FaultInjectionHarness(
        injectors=(ShadowFaultInjector(),),
        probe=_AlwaysProbe(result=True),
        sleeper=_noop_sleep,
    )

    for scenario in default_scenarios():
        result = await harness.run(scenario, approved_targets=("t1",), mode=Mode.ENFORCE)
        assert result.outcome is ExperimentOutcome.VALIDATED
        assert result.reverted is True


def test_scenario_validation_rejects_bad_cap() -> None:
    with pytest.raises(ValueError, match="blast_radius_cap"):
        FaultScenario(
            scenario_id="x",
            fault_type="cpu_stress",
            description="d",
            target_selector="t",
            expected_signal="s",
            blast_radius_cap=0,
            duration_seconds=1.0,
        )
