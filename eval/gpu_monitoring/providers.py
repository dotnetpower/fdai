"""Metric-snapshot mapping; deliberately not a live collector or webhook parser."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Literal

from eval.gpu_monitoring.models import GpuSample

DCGM_METRICS = {
    "utilization_pct": "DCGM_FI_DEV_GPU_UTIL",
    "memory_used_mib": "DCGM_FI_DEV_FB_USED",
    "memory_free_mib": "DCGM_FI_DEV_FB_FREE",
    "temperature_c": "DCGM_FI_DEV_GPU_TEMP",
    "xid_code": "DCGM_FI_DEV_XID_ERRORS",
    "ecc_uncorrectable_total": "DCGM_FI_DEV_ECC_DBE_VOL_TOTAL",
}
_IDENTITY_FIELDS = frozenset({"resource_ref", "gpu_id", "model", "observed_at"})
_METRIC_FIELDS = frozenset(GpuSample.model_fields) - _IDENTITY_FIELDS - {"source"}
_INTEGER_FIELDS = frozenset(
    {"queue_depth", "xid_code", "ecc_uncorrectable_total", "cuda_oom_total"}
)


def normalize_sample(
    *,
    source: Literal["azure_monitor", "datadog"],
    identity: Mapping[str, object],
    metrics: Mapping[str, object],
    metric_names: Mapping[str, str],
) -> GpuSample:
    """Map already aligned points in percent/MiB/Celsius, preserving missing values.

    Datadog metric names and units must be confirmed for the installed integration.
    Workload allocation, queue depth, OOM counters and throttle evidence are not
    inferred from utilization, temperature, or framebuffer usage.
    """
    if set(identity) != _IDENTITY_FIELDS:
        raise ValueError("identity MUST contain exactly the four logical identity/time fields")
    if set(metric_names) - _METRIC_FIELDS - {"memory_free_mib"}:
        raise ValueError("metric mapping contains an unsupported canonical field")
    if any(not name.strip() for name in metric_names.values()):
        raise ValueError("metric mapping names MUST be non-empty")
    values = {canonical: metrics.get(raw_name) for canonical, raw_name in metric_names.items()}
    for field, value in values.items():
        if isinstance(value, int | float) and not isinstance(value, bool):
            if not math.isfinite(value) or value >= 2**63 - 1_024:
                raise ValueError("metric value is non-finite or an unsupported DCGM sentinel")
        if field in _INTEGER_FIELDS and isinstance(value, float):
            if not value.is_integer():
                raise ValueError("counter and diagnostic code metrics MUST be integer-valued")
            values[field] = int(value)
    free = values.pop("memory_free_mib", None)
    used = values.get("memory_used_mib")
    if free is not None:
        if isinstance(free, bool) or not isinstance(free, int | float):
            raise ValueError("memory_free_mib MUST be numeric")
        if isinstance(used, bool) or not isinstance(used, int | float):
            raise ValueError("free memory MUST be accompanied by numeric used memory")
        if free < 0:
            raise ValueError("memory_free_mib MUST be nonnegative")
        derived_total = used + free
        total = values.get("memory_total_mib")
        if total is not None and total != derived_total:
            raise ValueError("memory capacity metrics conflict")
        values["memory_total_mib"] = derived_total
    return GpuSample.model_validate({**identity, "source": source, **values})
