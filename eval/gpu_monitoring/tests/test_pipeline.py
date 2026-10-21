"""Offline GPU monitoring evidence, with no cloud or model calls."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from eval.gpu_monitoring.models import Analysis, GpuSample, Policy
from eval.gpu_monitoring.pipeline import analyze, publish_findings
from eval.gpu_monitoring.providers import DCGM_METRICS, normalize_sample
from eval.gpu_monitoring.reporting import build_report, verify_followup
from fdai.shared.contracts.models import Event
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.contracts.validation import JsonSchemaContractValidator

NOW = datetime(2026, 10, 14, tzinfo=UTC)


def window(**changes: object) -> list[GpuSample]:
    values: dict[str, object] = {
        "source": "azure_monitor",
        "resource_ref": "resource:example-gpu-node",
        "gpu_id": "example-gpu-0",
        "model": "A10",
        "utilization_pct": 40.0,
        "memory_used_mib": 8_000.0,
        "memory_total_mib": 24_000.0,
        "temperature_c": 60.0,
        "allocated": True,
        "queue_depth": 0,
        "xid_code": 0,
        "ecc_uncorrectable_total": 0,
        "cuda_oom_total": 0,
        "thermal_throttled": False,
    }
    values.update(changes)
    return [
        GpuSample.model_validate({**values, "observed_at": NOW - timedelta(seconds=300 - i * 30)})
        for i in range(11)
    ]


@pytest.mark.parametrize("model", ["A10", "T4", "H100"])
@pytest.mark.parametrize("source", ["azure_monitor", "datadog"])
def test_healthy_windows_do_not_create_findings(model: str, source: str) -> None:
    result = analyze(window(model=model, source=source), now=NOW)
    assert result.status == "healthy"
    assert not result.events


def test_authenticated_live_origin_is_preserved_in_event_and_report() -> None:
    samples = window(
        source="azure_vm_run_command",
        model="NVIDIA H100 NVL",
        memory_used_mib=95_000.0,
        memory_total_mib=95_830.0,
    )

    result = analyze(
        samples,
        now=NOW,
        evidence_origin="authenticated_live_observation",
    )
    report = build_report(result)

    assert result.evidence_origin == "authenticated_live_observation"
    assert result.events[0].payload["evidence_origin"] == "authenticated_live_observation"
    assert result.events[0].idempotency_key.startswith("gpu-authenticated_live_observation:")
    assert report["evidence_origin"] == "authenticated_live_observation"
    after = analyze(
        [
            item.model_copy(
                update={
                    "observed_at": item.observed_at + timedelta(minutes=6),
                    "memory_used_mib": 1_000.0,
                }
            )
            for item in samples
        ],
        now=NOW + timedelta(minutes=6),
        evidence_origin="authenticated_live_observation",
    )
    assert verify_followup(result, after)["verification_status"] == (
        "condition_cleared_in_followup"
    )


def test_saturation_requires_sustained_utilization_and_rising_backlog() -> None:
    samples = [
        item.model_copy(update={"queue_depth": i})
        for i, item in enumerate(window(utilization_pct=98.0))
    ]
    result = analyze(samples, now=NOW)
    assert [event.payload["signal"] for event in result.events] == ["gpu_util_saturated"]
    assert result.status == "finding"
    assert analyze(window(utilization_pct=100.0), now=NOW).status == "healthy"


def test_short_utilization_spike_does_not_trigger() -> None:
    samples = window()
    samples[-1] = samples[-1].model_copy(update={"utilization_pct": 100.0, "queue_depth": 20})
    assert analyze(samples, now=NOW).status == "healthy"


def test_memory_pressure_is_not_claimed_to_be_oom() -> None:
    result = analyze(window(memory_used_mib=23_500.0), now=NOW)
    assert result.events[0].payload["signal"] == "alert_trigger"
    assert result.events[0].payload["finding_kind"] == "memory_pressure"
    samples = window()
    samples[-1] = samples[-1].model_copy(update={"cuda_oom_total": 1})
    assert analyze(samples, now=NOW).events[0].payload["signal"] == "gpu_vram_oom"


def test_temperature_alone_is_not_claimed_to_be_throttling() -> None:
    result = analyze(window(temperature_c=90.0), now=NOW)
    assert result.events[0].payload["signal"] == "alert_trigger"
    assert result.events[0].payload["finding_kind"] == "high_temperature"
    result = analyze(window(temperature_c=90.0, thermal_throttled=True), now=NOW)
    assert result.events[0].payload["signal"] == "gpu_temp_throttle"


def test_allocated_idle_gpu_is_advisory_not_shutdown_authority() -> None:
    result = analyze(window(utilization_pct=2.0), now=NOW)
    assert result.events[0].payload["signal"] == "gpu_util_zero_wasted"
    assert result.events[0].mode.value == "shadow"
    assert result.events[0].decision is None
    assert analyze(window(utilization_pct=2.0, allocated=False), now=NOW).status == "healthy"
    report = build_report(result)
    assert report["execution_status"] == "not_executed"
    assert report["external_effect_verified"] is False


def test_xid_change_not_sticky_code_is_a_new_event() -> None:
    assert analyze(window(xid_code=79), now=NOW).status == "healthy"
    samples = window()
    samples[-1] = samples[-1].model_copy(update={"xid_code": 79})
    assert analyze(samples, now=NOW).events[0].payload["signal"] == "gpu_xid_event"


def test_ecc_counter_requires_increase_and_reset_is_not_error() -> None:
    assert analyze(window(ecc_uncorrectable_total=3), now=NOW).status == "healthy"
    samples = window(ecc_uncorrectable_total=3)
    samples[-1] = samples[-1].model_copy(update={"ecc_uncorrectable_total": 4})
    assert analyze(samples, now=NOW).events[0].payload["signal"] == "gpu_ecc_uncorrectable"
    samples[-1] = samples[-1].model_copy(update={"ecc_uncorrectable_total": 0})
    assert analyze(samples, now=NOW).status == "healthy"


@pytest.mark.parametrize("field", ["utilization_pct", "memory_used_mib", "temperature_c"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, -1.0])
def test_invalid_numeric_values_are_rejected(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        window(**{field: value})


def test_memory_used_cannot_exceed_capacity() -> None:
    with pytest.raises(ValueError, match="capacity"):
        window(memory_used_mib=25_000.0)


@pytest.mark.parametrize("changes", [{"utilization_pct": 101.0}, {"queue_depth": True}])
def test_invalid_percent_or_boolean_counter_is_rejected(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        window(**changes)


def test_future_and_naive_timestamps_fail_closed() -> None:
    with pytest.raises(ValueError, match="timezone"):
        window()[0].model_copy(update={"observed_at": NOW.replace(tzinfo=None)})
        analyze(window(), now=NOW.replace(tzinfo=None))
    with pytest.raises(ValueError, match="future"):
        analyze(
            [window()[0].model_copy(update={"observed_at": NOW + timedelta(seconds=1)})], now=NOW
        )


def test_stale_missing_sparse_or_short_evidence_is_not_healthy() -> None:
    assert analyze(window(), now=NOW + timedelta(minutes=10)).status == "insufficient_evidence"
    assert analyze([], now=NOW).status == "insufficient_evidence"
    assert analyze(window()[::3], now=NOW).status == "insufficient_evidence"
    assert analyze(window()[-3:], now=NOW).status == "insufficient_evidence"
    assert analyze(window(utilization_pct=None), now=NOW).status == "insufficient_evidence"


def test_duplicate_samples_do_not_inflate_duration_and_reorder_is_stable() -> None:
    samples = window(utilization_pct=2.0)
    baseline = analyze(samples, now=NOW)
    replay = analyze(list(reversed(samples + samples)), now=NOW + timedelta(seconds=5))
    assert baseline.events[0].event_id == replay.events[0].event_id
    assert baseline.events[0].idempotency_key == replay.events[0].idempotency_key
    assert baseline.events[0].payload == replay.events[0].payload
    assert analyze([samples[-1]] * 11, now=NOW).status == "insufficient_evidence"


def test_conflicting_duplicates_and_cross_gpu_windows_are_rejected() -> None:
    samples = window()
    conflict = samples[-1].model_copy(update={"utilization_pct": 90.0})
    with pytest.raises(ValueError, match="conflicting"):
        analyze([*samples, conflict], now=NOW)
    with pytest.raises(ValueError, match="identity"):
        analyze([*samples, samples[-1].model_copy(update={"gpu_id": "example-gpu-1"})], now=NOW)
    with pytest.raises(ValueError, match="identity"):
        analyze([*samples, samples[-1].model_copy(update={"source": "datadog"})], now=NOW)


def test_event_identity_binds_policy_and_evidence() -> None:
    samples = window(utilization_pct=2.0)
    first = analyze(samples, now=NOW)
    second = analyze(samples, now=NOW, policy=replace(Policy(), idle_utilization_pct=3.0))
    assert first.events[0].idempotency_key != second.events[0].idempotency_key
    changed = [item.model_copy(update={"utilization_pct": 1.0}) for item in samples]
    assert first.events[0].idempotency_key != analyze(changed, now=NOW).events[0].idempotency_key


def test_dcgm_and_configured_datadog_snapshots_normalize_to_same_units() -> None:
    identity = {
        "resource_ref": "resource:example-gpu-node",
        "gpu_id": "example-gpu-0",
        "model": "T4",
        "observed_at": NOW,
    }
    azure = normalize_sample(
        source="azure_monitor",
        identity=identity,
        metrics={
            "DCGM_FI_DEV_GPU_UTIL": 70.0,
            "DCGM_FI_DEV_FB_USED": 12_000.0,
            "DCGM_FI_DEV_FB_FREE": 4_000.0,
            "DCGM_FI_DEV_GPU_TEMP": 65.0,
        },
        metric_names=DCGM_METRICS,
    )
    datadog = normalize_sample(
        source="datadog",
        identity=identity,
        metrics={"example.util": 70.0, "example.used": 12_000.0, "example.free": 4_000.0},
        metric_names={
            "utilization_pct": "example.util",
            "memory_used_mib": "example.used",
            "memory_free_mib": "example.free",
        },
    )
    assert azure.utilization_pct == datadog.utilization_pct == 70.0
    assert azure.memory_total_mib == datadog.memory_total_mib == 16_000.0


def test_unsupported_metric_is_missing_not_zero() -> None:
    sample = normalize_sample(
        source="azure_monitor",
        identity=window()[0].model_dump(include={"resource_ref", "gpu_id", "model", "observed_at"}),
        metrics={},
        metric_names=DCGM_METRICS,
    )
    assert sample.utilization_pct is None
    assert sample.memory_total_mib is None


def test_provider_identity_cannot_override_source_or_metric_values() -> None:
    with pytest.raises(ValueError, match="identity"):
        normalize_sample(
            source="azure_monitor",
            identity={"source": "datadog"},
            metrics={},
            metric_names=DCGM_METRICS,
        )


def test_policy_is_bounded_and_finite() -> None:
    for changes in (
        {"window_seconds": 0},
        {"max_gap_seconds": 0},
        {"max_age_seconds": -1},
        {"saturation_pct": float("nan")},
        {"memory_pressure_pct": 101.0},
        {"max_samples": 0},
    ):
        with pytest.raises(ValueError):
            replace(Policy(), **changes)
    with pytest.raises(ValueError, match="bound"):
        analyze(window(), now=NOW, policy=replace(Policy(), max_samples=10))


def test_findings_validate_and_publish_using_fdai_event_contract() -> None:
    result = analyze(window(utilization_pct=2.0), now=NOW)
    validator = JsonSchemaContractValidator(PackageResourceSchemaRegistry())
    for event in result.events:
        validator.validate("event", event.model_dump(mode="json"))
        assert event.incident_correlation.value == "correlate"

    class RecordingBus:
        def __init__(self) -> None:
            self.records: list[Mapping[str, Any]] = []

        async def publish(self, topic: str, key: str, payload: Mapping[str, Any]) -> None:
            assert topic == "example.gpu.findings"
            assert key == result.events[0].resource_ref
            self.records.append(payload)

    bus = RecordingBus()
    asyncio.run(
        publish_findings(result, bus=bus, topic="example.gpu.findings", validator=validator)
    )
    received = [Event.model_validate(payload) for payload in bus.records]
    assert received == list(result.events)
    assert received[0].decision is None


def test_report_separates_hypothesis_observation_and_authority() -> None:
    result = analyze(window(memory_used_mib=23_500.0), now=NOW)
    report = build_report(result)
    assert report["evidence_origin"] == "synthetic_replay"
    assert report["mode"] == "shadow"
    assert report["root_cause_status"] == "hypothesis_only"
    assert report["findings"]
    assert report["execution_status"] == "not_executed"
    assert report["external_effect_verified"] is False


def test_followup_must_be_later_fresh_complete_and_same_gpu() -> None:
    before = analyze(window(memory_used_mib=23_500.0), now=NOW)
    after_time = NOW + timedelta(minutes=6)
    after = analyze(
        [
            item.model_copy(update={"observed_at": item.observed_at + timedelta(minutes=6)})
            for item in window()
        ],
        now=after_time,
    )
    report = verify_followup(before, after)
    assert report["verification_status"] == "recovered_in_replay"
    assert report["external_effect_verified"] is False
    assert verify_followup(before, before)["verification_status"] == "unverified"
    wrong_gpu = analyze(window(gpu_id="example-gpu-1"), now=NOW)
    assert verify_followup(before, wrong_gpu)["verification_status"] == "unverified"
    insufficient = analyze([], now=after_time)
    assert verify_followup(before, insufficient)["verification_status"] == "unverified"


def test_ongoing_finding_is_not_recovery() -> None:
    before = analyze(window(memory_used_mib=23_500.0), now=NOW)
    after = analyze(
        [
            item.model_copy(update={"observed_at": item.observed_at + timedelta(minutes=6)})
            for item in window(memory_used_mib=23_500.0)
        ],
        now=NOW + timedelta(minutes=6),
    )
    assert verify_followup(before, after)["verification_status"] == "still_failing"


def test_demo_covers_both_sources_and_all_three_gpu_models() -> None:
    from eval.gpu_monitoring.demo import run_scenarios

    report = run_scenarios()
    assert report["evidence_origin"] == "synthetic_replay"
    assert report["scenario_count"] == 54
    assert report["finding_scenarios"] == 48
    assert report["healthy_scenarios"] == 6
    assert report["recovered_scenarios"] == 48
    assert report["external_effect_verified"] is False


async def _failed_publication(result: Analysis) -> None:
    class FailedBus:
        async def publish(self, topic: str, key: str, payload: Mapping[str, Any]) -> None:
            raise ConnectionError("example broker unavailable")

    validator = JsonSchemaContractValidator(PackageResourceSchemaRegistry())
    await publish_findings(
        result, bus=FailedBus(), topic="example.gpu.findings", validator=validator
    )


def test_publication_failure_is_not_reported_as_success() -> None:
    with pytest.raises(ConnectionError, match="broker unavailable"):
        asyncio.run(_failed_publication(analyze(window(utilization_pct=2.0), now=NOW)))


def test_demo_persists_machine_readable_evidence(tmp_path: Path) -> None:
    from eval.gpu_monitoring.demo import main

    output = tmp_path / "gpu-report.json"
    assert main(["--output", str(output)]) == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["scenario_count"] == 54
    assert all(item["report"]["execution_status"] == "not_executed" for item in report["scenarios"])


@pytest.mark.parametrize(
    ("changes", "signal"),
    [
        ({"xid_code": 79}, "gpu_xid_event"),
        ({"ecc_uncorrectable_total": 1}, "gpu_ecc_uncorrectable"),
        ({"cuda_oom_total": 1}, "gpu_vram_oom"),
        ({"thermal_throttled": True}, "gpu_temp_throttle"),
    ],
)
def test_direct_fault_evidence_does_not_wait_for_utilization_window(
    changes: dict[str, object], signal: str
) -> None:
    samples = window(utilization_pct=None)[-2:]
    samples[-1] = samples[-1].model_copy(update=changes)
    result = analyze(samples, now=NOW)
    assert result.status == "finding"
    assert result.events[0].payload["signal"] == signal
    assert "short_window" in result.reason


def test_dcgm_integer_gauges_accept_integral_numbers_but_not_fractional_codes() -> None:
    identity = window()[0].model_dump(include={"resource_ref", "gpu_id", "model", "observed_at"})
    sample = normalize_sample(
        source="azure_monitor",
        identity=identity,
        metrics={"DCGM_FI_DEV_XID_ERRORS": 79.0},
        metric_names=DCGM_METRICS,
    )
    assert sample.xid_code == 79
    with pytest.raises(ValueError, match="integer"):
        normalize_sample(
            source="azure_monitor",
            identity=identity,
            metrics={"DCGM_FI_DEV_XID_ERRORS": 79.5},
            metric_names=DCGM_METRICS,
        )


def test_dcgm_unsupported_sentinel_does_not_become_extreme_temperature() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        normalize_sample(
            source="azure_monitor",
            identity=window()[0].model_dump(
                include={"resource_ref", "gpu_id", "model", "observed_at"}
            ),
            metrics={"DCGM_FI_DEV_GPU_TEMP": 9_223_372_036_854_775_794},
            metric_names=DCGM_METRICS,
        )


def test_equivalent_timezone_offsets_have_the_same_replay_identity() -> None:
    samples = window(utilization_pct=2.0)
    converted = [
        item.model_copy(
            update={"observed_at": item.observed_at.astimezone(timezone(timedelta(hours=9)))}
        )
        for item in samples
    ]
    first, second = analyze(samples, now=NOW), analyze(converted, now=NOW)
    assert first.events[0].idempotency_key == second.events[0].idempotency_key


def test_followup_without_original_fault_telemetry_cannot_verify_recovery() -> None:
    samples = window()
    samples[-1] = samples[-1].model_copy(update={"ecc_uncorrectable_total": 1})
    before = analyze(samples, now=NOW)
    after = analyze(
        [
            item.model_copy(update={"observed_at": item.observed_at + timedelta(minutes=6)})
            for item in window(ecc_uncorrectable_total=None)
        ],
        now=NOW + timedelta(minutes=6),
    )
    assert after.status == "healthy"
    assert verify_followup(before, after)["verification_status"] == "unverified"


def test_naive_observation_is_rejected_even_when_analysis_time_is_aware() -> None:
    samples = window()
    samples[-1] = samples[-1].model_copy(update={"observed_at": NOW.replace(tzinfo=None)})
    with pytest.raises(ValueError, match="timezone"):
        analyze(samples, now=NOW)
