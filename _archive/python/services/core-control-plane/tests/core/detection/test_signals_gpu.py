"""Sanity tests for GPU / AI-serving signals added to the registry.

These do not duplicate what `test_signals.py` already enforces
(name shape, description ASCII, tier hint whitelist, role partition);
they only assert the GPU family is present as scenario-tied signals so
a future refactor cannot silently drop a GPU signal from the registry.
"""

from __future__ import annotations

from fdai.core.detection.signals import (
    SIGNAL_COLD_START_LATENCY_SPIKE,
    SIGNAL_DISTRIBUTED_STRAGGLER,
    SIGNAL_GPU_ECC_UNCORRECTABLE,
    SIGNAL_GPU_IDLE_HOURS_WASTED,
    SIGNAL_GPU_PCIE_DEGRADATION,
    SIGNAL_GPU_POWER_THROTTLE,
    SIGNAL_GPU_SKU_MISMATCH,
    SIGNAL_GPU_TEMP_THROTTLE,
    SIGNAL_GPU_UTIL_SATURATED,
    SIGNAL_GPU_UTIL_ZERO_WASTED,
    SIGNAL_GPU_VRAM_OOM,
    SIGNAL_GPU_XID_EVENT,
    SIGNAL_INFERENCE_P99_SPIKE,
    SIGNAL_KV_CACHE_PRESSURE,
    SIGNAL_NCCL_TIMEOUT,
    SIGNAL_SPOT_PREEMPT_CASCADE,
    SIGNAL_TOKEN_SPEND_SPIKE,
    SIGNAL_WEIGHTS_FETCH_STALL,
    SignalRole,
    is_known_signal,
    known_signals,
    signals_with_role,
)

_GPU_SIGNALS = (
    SIGNAL_GPU_XID_EVENT,
    SIGNAL_GPU_ECC_UNCORRECTABLE,
    SIGNAL_GPU_TEMP_THROTTLE,
    SIGNAL_GPU_POWER_THROTTLE,
    SIGNAL_GPU_PCIE_DEGRADATION,
    SIGNAL_GPU_VRAM_OOM,
    SIGNAL_GPU_UTIL_ZERO_WASTED,
    SIGNAL_GPU_UTIL_SATURATED,
    SIGNAL_NCCL_TIMEOUT,
    SIGNAL_DISTRIBUTED_STRAGGLER,
    SIGNAL_INFERENCE_P99_SPIKE,
    SIGNAL_KV_CACHE_PRESSURE,
    SIGNAL_COLD_START_LATENCY_SPIKE,
    SIGNAL_WEIGHTS_FETCH_STALL,
    SIGNAL_SPOT_PREEMPT_CASCADE,
    SIGNAL_GPU_SKU_MISMATCH,
    SIGNAL_GPU_IDLE_HOURS_WASTED,
    SIGNAL_TOKEN_SPEND_SPIKE,
)


def test_all_gpu_signals_are_registered() -> None:
    for s in _GPU_SIGNALS:
        assert is_known_signal(s), f"GPU signal {s!r} missing from registry"


def test_gpu_signals_carry_scenario_role() -> None:
    scenario_role = signals_with_role(SignalRole.SCENARIO)
    for s in _GPU_SIGNALS:
        assert s in scenario_role, (
            f"GPU signal {s!r} must be scenario-tied "
            f"(RCA-only signals cannot be a scenario expected_signal)."
        )


def test_gpu_signal_descriptions_are_populated() -> None:
    for s in _GPU_SIGNALS:
        assert known_signals()[s].description.strip(), f"{s}: empty description"
