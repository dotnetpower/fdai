"""OTel Metric Exemplars, Continuous Profiling & Canary Delivery (Rounds 13-16, E037-E048).

Implements 2025-2026 OpenTelemetry Metric Exemplars, Prometheus 3.x UTF-8 conventions,
Continuous Profiling (eBPF / Pyroscope / PerfInsights), and Progressive Delivery:
- E037: OpenTelemetry Metric Exemplar contract (``OtelMetricExemplar``)
- E038: Prometheus 3.x UTF-8 identifier normalizer (``normalize_prometheus_v3_identifier``)
- E039: Exemplar-guided metric-spike bridge (``correlate_metric_spike_via_exemplars``)
- E040: Continuous profiling CPU/heap/mutex hotspot sample (``ContinuousProfileSample``)
- E041: Differential flamegraph regression comparator (``compare_profile_baselines``)
- E042: Monotonic memory-leak vs. transient spike discriminator (``detect_monotonic_memory_leak``)
- E043: Progressive delivery canary vs. baseline analyzer (``CanaryComparisonAssessment``)
- E044: Automated deployment rollback gate evaluator (``evaluate_deployment_rollback_gate``)
- E045: Azure Deployment Stacks & GitOps drift/deny verifier (``DeploymentStackDriftAssessment``)
- E046: Azure Monitor Data Collection Rule (DCR) & OTLP health (``DcrPipelineHealthAssessment``)
- E047: Synthetic monitoring & Real User Monitoring (RUM) correlator (``SyntheticRumCorrelation``)
- E048: Tail-based trace sampling retention policy evaluator (``evaluate_tail_sampling_policy``)
"""

from __future__ import annotations

import math
import re
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final

_HEX32_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-fA-F]{32}$")
_HEX16_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-fA-F]{16}$")


@dataclass(frozen=True, slots=True)
class OtelMetricExemplar:
    """E037: OpenTelemetry Metric Exemplar linking a metric bucket to an exact trace span."""

    metric_name: str
    value: float
    observed_at: datetime
    trace_id: str
    span_id: str
    resource_ref: str
    execution_authority: bool = False

    def __post_init__(self) -> None:
        if not self.metric_name.strip() or not self.resource_ref.strip():
            raise ValueError("metric_name and resource_ref MUST be non-empty")
        if type(self.value) is bool or not math.isfinite(self.value):
            raise ValueError("Exemplar value MUST be a finite number")
        if self.observed_at.tzinfo is None:
            raise ValueError("Exemplar observed_at MUST be timezone-aware")
        if _HEX32_RE.fullmatch(self.trace_id) is None or int(self.trace_id, 16) == 0:
            raise ValueError("trace_id MUST be a non-zero 32-char hex W3C TraceId")
        if _HEX16_RE.fullmatch(self.span_id) is None or int(self.span_id, 16) == 0:
            raise ValueError("span_id MUST be a non-zero 16-char hex W3C SpanId")
        if type(self.execution_authority) is not bool or self.execution_authority:
            raise ValueError("OtelMetricExemplar MUST have execution_authority=False")


def normalize_prometheus_v3_identifier(otel_name: str) -> dict[str, str]:
    """E038: Translate an OTel dotted name into Prometheus 3.x UTF-8 and legacy forms."""
    clean = otel_name.strip()
    if not clean or any(ch in clean for ch in ('"', "\\", "\n", "\r")):
        raise ValueError("Invalid OTel metric/attribute identifier")
    legacy = re.sub(r"[^A-Za-z0-9_:]", "_", clean)
    if legacy[0].isdigit():
        legacy = "_" + legacy
    return {
        "otel_original": clean,
        "prometheus_v3_utf8_selector": f'{{"{clean}"}}',
        "prometheus_legacy_underscore": legacy,
    }


def correlate_metric_spike_via_exemplars(
    exemplars: Sequence[OtelMetricExemplar],
    *,
    threshold: float,
) -> tuple[OtelMetricExemplar, ...]:
    """E039: Filter and rank exemplars exceeding ``threshold`` by descending value."""
    if type(threshold) is bool or not math.isfinite(threshold):
        raise ValueError("threshold MUST be a finite number")
    breached = [ex for ex in exemplars if ex.value >= threshold]
    breached.sort(key=lambda item: (-item.value, item.observed_at, item.trace_id))
    return tuple(breached)


@dataclass(frozen=True, slots=True)
class ContinuousProfileSample:
    """E040: Continuous profiling (eBPF / Pyroscope / PerfInsights) frame hotspot sample."""

    service_ref: str
    revision_id: str
    symbol_name: str
    cpu_self_percent: float
    heap_alloc_bytes_per_sec: float
    mutex_wait_ms_per_sec: float

    def __post_init__(self) -> None:
        if (
            not self.service_ref.strip()
            or not self.revision_id.strip()
            or not self.symbol_name.strip()
        ):
            raise ValueError("ContinuousProfileSample identifiers MUST be non-empty")
        for val in (
            self.cpu_self_percent,
            self.heap_alloc_bytes_per_sec,
            self.mutex_wait_ms_per_sec,
        ):
            if type(val) is bool or not math.isfinite(val) or val < 0:
                raise ValueError("ContinuousProfileSample metrics MUST be finite non-negative")


def compare_profile_baselines(
    baseline: Sequence[ContinuousProfileSample],
    candidate: Sequence[ContinuousProfileSample],
    *,
    cpu_regression_delta_percent: float = 10.0,
) -> tuple[dict[str, object], ...]:
    """E041: Differential flamegraph comparison between baseline and candidate revisions."""
    base_by_sym = {s.symbol_name: s for s in baseline}
    regressions: list[dict[str, object]] = []
    for cand in candidate:
        prev = base_by_sym.get(cand.symbol_name)
        prev_cpu = prev.cpu_self_percent if prev is not None else 0.0
        delta_cpu = round(cand.cpu_self_percent - prev_cpu, 4)
        if delta_cpu >= cpu_regression_delta_percent:
            regressions.append(
                {
                    "symbol_name": cand.symbol_name,
                    "baseline_revision": prev.revision_id if prev else "none",
                    "candidate_revision": cand.revision_id,
                    "delta_cpu_percent": delta_cpu,
                    "candidate_heap_bytes_per_sec": cand.heap_alloc_bytes_per_sec,
                }
            )
    regressions.sort(key=lambda item: -float(item["delta_cpu_percent"]))  # type: ignore[arg-type]
    return tuple(regressions)


def detect_monotonic_memory_leak(
    post_gc_heap_mib_series: Sequence[float],
    *,
    gc_pause_ratio: float,
) -> dict[str, object]:
    """E042: Discriminate a true monotonic post-GC memory leak from a transient traffic spike."""
    if len(post_gc_heap_mib_series) < 5:
        raise ValueError("post_gc_heap_mib_series requires at least 5 post-GC floor samples")
    if (
        type(gc_pause_ratio) is bool
        or not math.isfinite(gc_pause_ratio)
        or not 0.0 <= gc_pause_ratio <= 1.0
    ):
        raise ValueError("gc_pause_ratio MUST be in [0, 1]")
    for v in post_gc_heap_mib_series:
        if type(v) is bool or not math.isfinite(v) or v < 0:
            raise ValueError("Heap samples MUST be finite non-negative numbers")
    xs = [float(i) for i in range(len(post_gc_heap_mib_series))]
    ys = [float(v) for v in post_gc_heap_mib_series]
    slope, intercept = statistics.linear_regression(xs, ys)
    mean_y = statistics.fmean(ys)
    ss_tot = sum((y - mean_y) ** 2 for y in ys)
    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, ys, strict=True))
    r_squared = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0
    monotonic_pairs = sum(1 for left, right in zip(ys, ys[1:], strict=False) if right >= left)
    monotonic_ratio = monotonic_pairs / (len(ys) - 1)
    leak_confirmed = slope > 1.0 and r_squared >= 0.85 and monotonic_ratio >= 0.80
    return {
        "leak_confirmed": leak_confirmed,
        "slope_mib_per_interval": round(slope, 4),
        "r_squared": round(r_squared, 4),
        "monotonic_ratio": round(monotonic_ratio, 4),
        "gc_pause_ratio": round(gc_pause_ratio, 4),
        "classification": "monotonic_memory_leak" if leak_confirmed else "transient_or_stable",
        "execution_authority": False,
    }


@dataclass(frozen=True, slots=True)
class CanaryComparisonAssessment:
    """E043: Progressive delivery canary vs. stable baseline comparison."""

    canary_revision: str
    baseline_revision: str
    canary_error_rate: float
    baseline_error_rate: float
    canary_p99_latency_ms: float
    baseline_p99_latency_ms: float

    def __post_init__(self) -> None:
        if not self.canary_revision.strip() or not self.baseline_revision.strip():
            raise ValueError("canary_revision and baseline_revision MUST be non-empty")
        for val in (
            self.canary_error_rate,
            self.baseline_error_rate,
            self.canary_p99_latency_ms,
            self.baseline_p99_latency_ms,
        ):
            if type(val) is bool or not math.isfinite(val) or val < 0:
                raise ValueError("Canary comparison metrics MUST be finite non-negative")

    @property
    def error_rate_delta(self) -> float:
        return round(self.canary_error_rate - self.baseline_error_rate, 4)

    @property
    def latency_ratio(self) -> float:
        return (
            round(self.canary_p99_latency_ms / self.baseline_p99_latency_ms, 4)
            if self.baseline_p99_latency_ms > 0
            else 1.0
        )

    @property
    def canary_regressed(self) -> bool:
        return self.error_rate_delta >= 0.01 or self.latency_ratio >= 1.25


def evaluate_deployment_rollback_gate(
    *,
    canary: CanaryComparisonAssessment,
    slo_fast_burn_active: bool,
    new_exception_fingerprints: int,
) -> dict[str, object]:
    """E044: Proposal-only progressive delivery promotion/hold/rollback verdict."""
    if (
        type(slo_fast_burn_active) is not bool
        or type(new_exception_fingerprints) is not int
        or new_exception_fingerprints < 0
    ):
        raise ValueError("Invalid rollback gate inputs")
    if canary.canary_regressed or slo_fast_burn_active:
        verdict = "recommend_rollback"
    elif new_exception_fingerprints > 0:
        verdict = "hold_progression"
    else:
        verdict = "promote_eligible"
    return {
        "verdict": verdict,
        "canary_revision": canary.canary_revision,
        "error_rate_delta": canary.error_rate_delta,
        "latency_ratio": canary.latency_ratio,
        "slo_fast_burn_active": slo_fast_burn_active,
        "new_exception_fingerprints": new_exception_fingerprints,
        "execution_authority": False,
    }


@dataclass(frozen=True, slots=True)
class DeploymentStackDriftAssessment:
    """E045: Azure Deployment Stacks & GitOps out-of-band drift and deny-settings verifier."""

    stack_id: str
    provisioning_state: str
    deny_settings_mode: str
    detached_resources_count: int
    failed_resources_count: int
    out_of_band_drifted_count: int

    def __post_init__(self) -> None:
        if (
            not self.stack_id.strip()
            or not self.provisioning_state.strip()
            or not self.deny_settings_mode.strip()
        ):
            raise ValueError("DeploymentStackDriftAssessment text fields MUST be non-empty")
        for cnt in (
            self.detached_resources_count,
            self.failed_resources_count,
            self.out_of_band_drifted_count,
        ):
            if type(cnt) is not int or cnt < 0:
                raise ValueError("DeploymentStackDriftAssessment counts MUST be non-negative")

    @property
    def drift_or_failure_detected(self) -> bool:
        return (
            self.provisioning_state.lower() != "succeeded"
            or self.failed_resources_count > 0
            or self.out_of_band_drifted_count > 0
        )


@dataclass(frozen=True, slots=True)
class DcrPipelineHealthAssessment:
    """E046: Azure Monitor Data Collection Rule (DCR) and OTLP ingestion pipeline health."""

    dcr_id: str
    logs_dropped_per_min: float
    throttled_requests_per_min: float
    silent_agent_hosts_count: int

    def __post_init__(self) -> None:
        if not self.dcr_id.strip():
            raise ValueError("dcr_id MUST be non-empty")
        for val in (self.logs_dropped_per_min, self.throttled_requests_per_min):
            if type(val) is bool or not math.isfinite(val) or val < 0:
                raise ValueError("DCR rates MUST be finite non-negative")
        if type(self.silent_agent_hosts_count) is not int or self.silent_agent_hosts_count < 0:
            raise ValueError("silent_agent_hosts_count MUST be a non-negative integer")

    @property
    def telemetry_blindspot_risk(self) -> bool:
        return (
            self.logs_dropped_per_min > 0
            or self.throttled_requests_per_min > 0
            or self.silent_agent_hosts_count > 0
        )


@dataclass(frozen=True, slots=True)
class SyntheticRumCorrelation:
    """E047: Correlate Synthetic availability probes, RUM, and backend origin."""

    endpoint_ref: str
    failing_synthetic_regions: int
    total_synthetic_regions: int
    rum_client_error_rate: float
    backend_origin_5xx_rate: float

    def __post_init__(self) -> None:
        if not self.endpoint_ref.strip():
            raise ValueError("endpoint_ref MUST be non-empty")
        if (
            type(self.failing_synthetic_regions) is not int
            or type(self.total_synthetic_regions) is not int
            or self.failing_synthetic_regions < 0
            or self.total_synthetic_regions < 1
            or self.failing_synthetic_regions > self.total_synthetic_regions
        ):
            raise ValueError("Invalid synthetic region counts")
        for val in (self.rum_client_error_rate, self.backend_origin_5xx_rate):
            if type(val) is bool or not math.isfinite(val) or not 0.0 <= val <= 1.0:
                raise ValueError("Error rates MUST be in [0, 1]")

    @property
    def fault_domain(self) -> str:
        if self.backend_origin_5xx_rate >= 0.02:
            return "backend_origin_fault"
        if self.failing_synthetic_regions == self.total_synthetic_regions:
            return "global_edge_or_dns_fault"
        if self.failing_synthetic_regions > 0 or self.rum_client_error_rate >= 0.05:
            return "regional_isp_or_pop_degradation"
        return "healthy"


def evaluate_tail_sampling_policy(
    *,
    status_code: int,
    duration_ms: float,
    p99_threshold_ms: float,
    correlated_with_change: bool,
    baseline_sample_rate: float = 0.05,
) -> dict[str, object]:
    """E048: Tail-based trace sampling decision retaining 100% of error, slow, or change traces."""
    if type(status_code) is not int or type(correlated_with_change) is not bool:
        raise ValueError("Invalid status_code or correlated_with_change")
    if status_code >= 400 or duration_ms >= p99_threshold_ms or correlated_with_change:
        return {
            "retain_trace": True,
            "effective_sample_rate": 1.0,
            "reason": "high_value_anomaly_or_change_trace",
        }
    return {
        "retain_trace": False,
        "effective_sample_rate": baseline_sample_rate,
        "reason": "routine_head_sample_budget",
    }


__all__ = [
    "CanaryComparisonAssessment",
    "ContinuousProfileSample",
    "DcrPipelineHealthAssessment",
    "DeploymentStackDriftAssessment",
    "OtelMetricExemplar",
    "SyntheticRumCorrelation",
    "compare_profile_baselines",
    "correlate_metric_spike_via_exemplars",
    "detect_monotonic_memory_leak",
    "evaluate_deployment_rollback_gate",
    "evaluate_tail_sampling_policy",
    "normalize_prometheus_v3_identifier",
]
