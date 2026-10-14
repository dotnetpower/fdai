"""Replay GPU anomalies and later observations without invoking a cloud, LLM or executor."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from eval.gpu_monitoring.models import GpuSample
from eval.gpu_monitoring.pipeline import analyze
from eval.gpu_monitoring.providers import DCGM_METRICS, normalize_sample
from eval.gpu_monitoring.reporting import build_report, verify_followup

_NOW = datetime(2026, 10, 14, tzinfo=UTC)
_SCENARIOS = (
    "healthy",
    "saturation",
    "memory_pressure",
    "high_temperature",
    "thermal_throttle",
    "cuda_oom",
    "xid",
    "ecc",
    "idle",
)
_CAPACITY_MIB = {"A10": 24_000.0, "T4": 16_000.0, "H100": 80_000.0}


def _samples(
    model: str, source: Literal["azure_monitor", "datadog"], scenario: str, now: datetime
) -> list[GpuSample]:
    total = _CAPACITY_MIB[model]
    samples: list[GpuSample] = []
    names = {
        **DCGM_METRICS,
        "allocated": "workload.allocated",
        "queue_depth": "workload.queue_depth",
        "cuda_oom_total": "workload.cuda_oom_total",
        "thermal_throttled": "driver.thermal_throttled",
    }
    if source == "datadog":
        # Synthetic aliases, intentionally not advertised as vendor metric names.
        names = {field: f"example.gpu.{field}" for field in names}
    for index in range(11):
        used = total * (0.98 if scenario == "memory_pressure" else 0.4)
        canonical: dict[str, object] = {
            "utilization_pct": (
                98.0 if scenario == "saturation" else 2.0 if scenario == "idle" else 40.0
            ),
            "memory_used_mib": used,
            "memory_free_mib": total - used,
            "temperature_c": 90.0 if scenario in {"high_temperature", "thermal_throttle"} else 60.0,
            "allocated": True,
            "queue_depth": index if scenario == "saturation" else 0,
            "xid_code": 79 if scenario == "xid" and index == 10 else 0,
            "ecc_uncorrectable_total": 1 if scenario == "ecc" and index == 10 else 0,
            "cuda_oom_total": 1 if scenario == "cuda_oom" and index == 10 else 0,
            "thermal_throttled": scenario == "thermal_throttle",
        }
        samples.append(
            normalize_sample(
                source=source,
                identity={
                    "resource_ref": "resource:example-gpu-node",
                    "gpu_id": "example-gpu-0",
                    "model": model,
                    "observed_at": now - timedelta(seconds=300 - index * 30),
                },
                metrics={names[field]: value for field, value in canonical.items()},
                metric_names=names,
            )
        )
    return samples


def run_scenarios() -> dict[str, object]:
    """Run 54 synthetic cases; clearing a replay threshold is not an executed fix."""
    scenarios: list[dict[str, object]] = []
    findings = healthy = recovered = 0
    sources: tuple[Literal["azure_monitor", "datadog"], ...] = ("azure_monitor", "datadog")
    for model in _CAPACITY_MIB:
        for source in sources:
            for scenario in _SCENARIOS:
                result = analyze(_samples(model, source, scenario, _NOW), now=_NOW)
                after_time = _NOW + timedelta(minutes=6)
                after = analyze(_samples(model, source, "healthy", after_time), now=after_time)
                followup = verify_followup(result, after)
                findings += result.status == "finding"
                healthy += result.status == "healthy"
                recovered += followup["verification_status"] == "recovered_in_replay"
                scenarios.append(
                    {
                        "gpu_model": model,
                        "source": source,
                        "scenario": scenario,
                        "report": build_report(result),
                        "followup": followup,
                    }
                )
    return {
        "schema_version": "1.0.0",
        "evidence_origin": "synthetic_replay",
        "external_effect_verified": False,
        "scenario_count": len(scenarios),
        "finding_scenarios": findings,
        "healthy_scenarios": healthy,
        "recovered_scenarios": recovered,
        "scenarios": scenarios,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Save synthetic JSON evidence to this file.")
    args = parser.parse_args(argv)
    encoded = json.dumps(run_scenarios(), indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.output is None:
        print(encoded, end="")
    else:
        args.output.write_text(encoded, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
