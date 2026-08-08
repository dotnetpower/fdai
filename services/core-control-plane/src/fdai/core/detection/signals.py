"""Canonical detection-signal registry - the shared vocabulary that the
detection layer, the trust router, the investigation analyzers, and the
chaos harness use to refer to one observable condition.

A ``signal`` is a **CSP-neutral string handle** for a detection outcome
(e.g. ``"node_cpu"``, ``"rate_limit"``, ``"pod_restart"``). It is not a
metric, an event, or an alert - it is the normalized name the pipeline
agrees on so that:

- an analyzer / anomaly detector can emit it as the observation label,
- the harness can assert VALIDATED when a chaos experiment expects it,
- the router / RCA can look up its tier and analyzer preference, and
- the coverage matrix in
  ``docs/internals/sre-demo-scenarios-08-fdai-coverage.md`` can name it
  once and mean the same thing everywhere.

This module deliberately holds **string constants and a small registry
mapping**, not runtime behavior. Every scenario in the SRE demo pack
(S1-S14 + C1-C4) maps to at least one of these signals; adding a new
signal here is the single source of truth for "the detection layer knows
about this observable condition".
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

# --- Canonical signal names (CSP-neutral vocabulary) -----------------------

# Compute / workload
SIGNAL_NODE_CPU = "node_cpu"
"""AKS / Kubernetes node or pod CPU is high (T0+T1). Emitted by
``aks_analyzer`` and by ``detection/anomaly`` over Prometheus / KQL."""

SIGNAL_POD_RESTART = "pod_restart"
"""One or more pods restarted in a short window - crash-loop-adjacent
(T0). Fires on ``event_ingest`` (KubeEvents) for scenarios S1 / C2."""

SIGNAL_ROLLOUT_STALL = "rollout_stall"
"""A Kubernetes deployment rollout is stuck (ImagePullBackOff, unavailable
replicas) past its progress deadline (T0 + change correlation). Scenario
S12."""

SIGNAL_MEMBER_HOTSPOT = "member_hotspot"
"""One member of a pool (one pod, one instance) is significantly hotter
than its peers - the ``cloud_RoleInstance`` split of an otherwise
aggregate CPU/latency series (T0+T2 via ``rca/causal_chain``).

This signal is intentionally **RCA-only** and has no dedicated
``FaultScenario``: scenarios C3 / C4 inject an ordinary node/pod CPU or
memory stress (:data:`~fdai.core.chaos.AKS_POD_CPU_SPIKE` /
:data:`~fdai.core.chaos.VM_MEM_STRESS`), and the RCA layer emits
``member_hotspot`` when its causal chain identifies which one member is
responsible. Do not add a scenario with this ``expected_signal`` - if
you need one, author a distinct signal instead."""

# Host / IaaS
SIGNAL_HOST_CPU = "host_cpu"
"""Guest OS CPU sustained above threshold on a VM / VMSS instance (T0).
Distinct from ``node_cpu`` which is a Kubernetes-node measurement.
Scenario S5."""

SIGNAL_HOST_MEMORY = "host_memory"
"""Guest OS memory pressure (available memory low, swap thrash) on a VM
(T0). Scenarios S6 / C4."""

# Request / service level
SIGNAL_REQUEST_FAILURE = "request_failure"
"""HTTP request failure rate is elevated (server 5xx, HTTPChaos abort)
above the SLO burn threshold (T0). Scenario S4."""

SIGNAL_RATE_LIMIT = "rate_limit"
"""Upstream is returning HTTP 429 rate-limit errors (T0+T1). Scenario S9;
also emitted by ``azure_openai_analyzer``."""

# Network / gateway
SIGNAL_GATEWAY_LATENCY = "gateway_latency"
"""Backend first-byte latency at API Management or Application Gateway is
above bound (T0+T1). Scenarios S3 / S7 / S10; emitted by
``api_management_analyzer``."""

SIGNAL_BACKEND_HEALTH = "backend_health"
"""Application Gateway healthy-host count collapsed toward zero (T0 ->
T2 via reverse-RCA). Scenario S11; emitted by ``app_gateway_analyzer``."""

# Data / dependency
SIGNAL_DB_CPU = "db_cpu"
"""Database (MySQL / Postgres Flexible Server) CPU is saturated (T0 +
forecast band via ``detection/forecast``). Scenario S8; emitted by
``mysql_analyzer``."""

SIGNAL_CONFIG_DRIFT = "config_drift"
"""A governed configuration differs from its approved desired state. Scenario S13."""

SIGNAL_ALERT_TRIGGER = "alert_trigger"
"""An external alert entered the bounded investigation path. Scenario S14."""

# GPU / AI-serving (see docs/internals/sre-scenario-library-scaling.md
# "GPU / AI-serving domain"). None of these carry a shipped `FaultScenario`
# in the upstream `default_scenarios()` today - they are scenario-tied
# signals used by scenarios under `rule-catalog/chaos-scenarios/collected/gpu/`.
# Every one MUST be safe as an audit / log / Rego identifier (lowercase
# snake_case, ASCII).

SIGNAL_GPU_XID_EVENT = "gpu_xid_event"
"""NVIDIA GPU driver Xid diagnostic event fired (T0). Xid codes vary in
severity - the scenario or analyzer disambiguates by ``xid_code`` in
the event body."""

SIGNAL_GPU_ECC_UNCORRECTABLE = "gpu_ecc_uncorrectable"
"""GPU HBM uncorrectable ECC error observed (T0). Node drain candidate."""

SIGNAL_GPU_TEMP_THROTTLE = "gpu_temp_throttle"
"""GPU thermal throttle engaged; clock reduced below expected (T0+T1)."""

SIGNAL_GPU_POWER_THROTTLE = "gpu_power_throttle"
"""GPU power-cap throttle engaged; sustained SM clock reduction (T0+T1)."""

SIGNAL_GPU_PCIE_DEGRADATION = "gpu_pcie_degradation"
"""PCIe / NVLink negotiated bandwidth dropped below expected lane width
(T0+T1). All-reduce and host-to-device transfers suffer."""

SIGNAL_GPU_VRAM_OOM = "gpu_vram_oom"
"""CUDA out-of-memory (VRAM exhausted) observed on a training or
inference process (T0)."""

SIGNAL_GPU_UTIL_ZERO_WASTED = "gpu_util_zero_wasted"
"""A reserved / allocated GPU shows utilization at or near zero for a
sustained window (T0 + forecast). Advisory to Njord (cost)."""

SIGNAL_GPU_UTIL_SATURATED = "gpu_util_saturated"
"""GPU compute utilization sustained near 100% with queue backlog rising
(T0+T1). Capacity signal for Freyr."""

SIGNAL_NCCL_TIMEOUT = "nccl_timeout"
"""NCCL communicator timeout (all-reduce, broadcast, or send/recv hang)
observed in a distributed training or inference job (T0)."""

SIGNAL_DISTRIBUTED_STRAGGLER = "distributed_straggler"
"""One rank in a distributed job is significantly slower than its peers
per step, dragging global step time (T0+T2 via causal chain)."""

SIGNAL_INFERENCE_P99_SPIKE = "inference_p99_spike"
"""Model-serving p99 latency sustained above SLO band (T0+T1)."""

SIGNAL_KV_CACHE_PRESSURE = "kv_cache_pressure"
"""LLM inference KV-cache high-water mark near capacity; risk of eviction
storm or request drops (T0+T1)."""

SIGNAL_COLD_START_LATENCY_SPIKE = "cold_start_latency_spike"
"""First-token or first-response latency spiked after a model reload,
scale-out, or cold pod start (T0+T1)."""

SIGNAL_WEIGHTS_FETCH_STALL = "weights_fetch_stall"
"""Model-weights fetch from object storage (Blob / S3) stalled or below
expected throughput; blocks warmup (T0)."""

SIGNAL_SPOT_PREEMPT_CASCADE = "spot_preempt_cascade"
"""Spot / preemptible GPU reclaimed with subsequent restart failure
propagating across a distributed job (T0+T2)."""

SIGNAL_GPU_SKU_MISMATCH = "gpu_sku_mismatch"
"""A workload is running on a GPU SKU disproportionate to its profile
(e.g. H100 for an A100-class job). Advisory to Njord (cost)."""

SIGNAL_GPU_IDLE_HOURS_WASTED = "gpu_idle_hours_wasted"
"""Cumulative GPU-hours reserved and unused across a window exceeds
threshold. Advisory to Njord (cost)."""

SIGNAL_TOKEN_SPEND_SPIKE = "token_spend_spike"  # noqa: S105 - signal name, not a secret
"""LLM token spend (AOAI / Foundry / Bedrock) crossed a per-window
budget band (T0 + forecast). Advisory to Njord (cost)."""


# --- Signal descriptor + registry -----------------------------------------


class SignalRole(StrEnum):
    """How a signal enters the pipeline.

    ``SCENARIO`` signals are the ``expected_signal`` of at least one
    :class:`~fdai.core.chaos.FaultScenario` and fire from the analyzer /
    anomaly detector layer. ``RCA_ONLY`` signals are emitted by the RCA
    layer as a *drill-down* on an already-detected aggregate anomaly -
    no scenario declares them directly; naming one as ``expected_signal``
    would collapse the aggregate <-> member distinction the RCA layer
    depends on.
    """

    SCENARIO = "scenario"
    RCA_ONLY = "rca_only"


@dataclass(frozen=True, slots=True)
class SignalSpec:
    """Metadata for one canonical detection signal.

    ``tier_hint`` is a **routing hint**, not an enforcement gate: the
    trust router still computes per-event confidence, but a signal that
    is always deterministic (``pod_restart``) never needs to reach T2.
    ``rca_hint`` names the RCA analyzer typically used to explain the
    signal; a fork can override the actual binding. ``role`` names how
    the signal enters the pipeline (see :class:`SignalRole`).
    """

    signal: str
    """The canonical string (matches the ``SIGNAL_*`` constant value)."""

    description: str
    """One-line human-readable summary of what the signal observes."""

    tier_hint: str
    """Coarse routing hint: ``"T0"``, ``"T0+T1"``, ``"T0+T2"``, or
    ``"T0+forecast"``. Consumed by the trust router as a default."""

    rca_hint: str
    """Name of the RCA analyzer typically applied
    (``"failure_rate"``, ``"causal_chain"``, ``"change_evidence"``, ...).
    A fork may bind a different analyzer for the same signal."""

    role: SignalRole = SignalRole.SCENARIO
    """How the signal enters the pipeline. Defaults to
    :attr:`SignalRole.SCENARIO` so adding a new signal without thinking
    about it produces a scenario-tied signal (safest default); RCA-only
    signals opt in explicitly."""


_KNOWN_SIGNALS: Mapping[str, SignalSpec] = MappingProxyType(
    {
        spec.signal: spec
        for spec in (
            SignalSpec(
                signal=SIGNAL_NODE_CPU,
                description="Kubernetes node/pod CPU utilization elevated.",
                tier_hint="T0+T1",
                rca_hint="cpu_hotspot",
            ),
            SignalSpec(
                signal=SIGNAL_POD_RESTART,
                description="Pods restarted in a short window (crash-loop adjacent).",
                tier_hint="T0",
                rca_hint="member_source",
            ),
            SignalSpec(
                signal=SIGNAL_ROLLOUT_STALL,
                description="Deployment rollout past its progress deadline.",
                tier_hint="T0",
                rca_hint="change_evidence",
            ),
            SignalSpec(
                signal=SIGNAL_MEMBER_HOTSPOT,
                description="One pool member is significantly hotter than its peers.",
                tier_hint="T0+T2",
                rca_hint="causal_chain",
                role=SignalRole.RCA_ONLY,
            ),
            SignalSpec(
                signal=SIGNAL_HOST_CPU,
                description="VM guest OS CPU sustained above threshold.",
                tier_hint="T0",
                rca_hint="host_cpu",
            ),
            SignalSpec(
                signal=SIGNAL_HOST_MEMORY,
                description="VM guest OS memory pressure (low avail, swap).",
                tier_hint="T0",
                rca_hint="memory_vs_cpu",
            ),
            SignalSpec(
                signal=SIGNAL_REQUEST_FAILURE,
                description="Request failure (5xx / abort) rate elevated.",
                tier_hint="T0",
                rca_hint="failure_rate",
            ),
            SignalSpec(
                signal=SIGNAL_RATE_LIMIT,
                description="Upstream returning HTTP 429 rate-limit errors.",
                tier_hint="T0+T1",
                rca_hint="throttle",
            ),
            SignalSpec(
                signal=SIGNAL_GATEWAY_LATENCY,
                description="Gateway backend first-byte latency elevated.",
                tier_hint="T0+T1",
                rca_hint="dependency_latency",
            ),
            SignalSpec(
                signal=SIGNAL_BACKEND_HEALTH,
                description="Gateway healthy-host count collapsed.",
                tier_hint="T0+T2",
                rca_hint="causal_chain",
            ),
            SignalSpec(
                signal=SIGNAL_DB_CPU,
                description="Database CPU saturated (slow queries likely).",
                tier_hint="T0+forecast",
                rca_hint="slow_query",
            ),
            SignalSpec(
                signal=SIGNAL_CONFIG_DRIFT,
                description="Governed configuration differs from approved desired state.",
                tier_hint="T0",
                rca_hint="change_evidence",
            ),
            SignalSpec(
                signal=SIGNAL_ALERT_TRIGGER,
                description="External alert entered the bounded investigation path.",
                tier_hint="T0",
                rca_hint="causal_chain",
            ),
            # --- GPU / AI-serving --------------------------------------
            SignalSpec(
                signal=SIGNAL_GPU_XID_EVENT,
                description="NVIDIA GPU driver Xid diagnostic event fired.",
                tier_hint="T0",
                rca_hint="gpu_xid",
            ),
            SignalSpec(
                signal=SIGNAL_GPU_ECC_UNCORRECTABLE,
                description="GPU HBM uncorrectable ECC error observed.",
                tier_hint="T0",
                rca_hint="gpu_ecc",
            ),
            SignalSpec(
                signal=SIGNAL_GPU_TEMP_THROTTLE,
                description="GPU thermal throttle engaged; clock reduced.",
                tier_hint="T0+T1",
                rca_hint="gpu_thermal",
            ),
            SignalSpec(
                signal=SIGNAL_GPU_POWER_THROTTLE,
                description="GPU power-cap throttle engaged; clock reduced.",
                tier_hint="T0+T1",
                rca_hint="gpu_power",
            ),
            SignalSpec(
                signal=SIGNAL_GPU_PCIE_DEGRADATION,
                description="PCIe/NVLink negotiated bandwidth dropped below expected.",
                tier_hint="T0+T1",
                rca_hint="gpu_interconnect",
            ),
            SignalSpec(
                signal=SIGNAL_GPU_VRAM_OOM,
                description="CUDA out-of-memory on training or inference process.",
                tier_hint="T0",
                rca_hint="gpu_memory",
            ),
            SignalSpec(
                signal=SIGNAL_GPU_UTIL_ZERO_WASTED,
                description="Reserved GPU shows near-zero utilization sustained.",
                tier_hint="T0+forecast",
                rca_hint="gpu_idle",
            ),
            SignalSpec(
                signal=SIGNAL_GPU_UTIL_SATURATED,
                description="GPU util near 100% with queue backlog rising.",
                tier_hint="T0+T1",
                rca_hint="gpu_saturation",
            ),
            SignalSpec(
                signal=SIGNAL_NCCL_TIMEOUT,
                description="NCCL communicator timeout in distributed job.",
                tier_hint="T0",
                rca_hint="nccl_hang",
            ),
            SignalSpec(
                signal=SIGNAL_DISTRIBUTED_STRAGGLER,
                description="One rank slower than peers, drags step time.",
                tier_hint="T0+T2",
                rca_hint="causal_chain",
            ),
            SignalSpec(
                signal=SIGNAL_INFERENCE_P99_SPIKE,
                description="Model-serving p99 latency above SLO band.",
                tier_hint="T0+T1",
                rca_hint="latency_burn",
            ),
            SignalSpec(
                signal=SIGNAL_KV_CACHE_PRESSURE,
                description="LLM KV-cache near capacity; eviction storm risk.",
                tier_hint="T0+T1",
                rca_hint="kv_cache",
            ),
            SignalSpec(
                signal=SIGNAL_COLD_START_LATENCY_SPIKE,
                description="First-token latency spiked after model reload / scale-out.",
                tier_hint="T0+T1",
                rca_hint="cold_start",
            ),
            SignalSpec(
                signal=SIGNAL_WEIGHTS_FETCH_STALL,
                description="Model-weights fetch from object storage stalled.",
                tier_hint="T0",
                rca_hint="weights_stall",
            ),
            SignalSpec(
                signal=SIGNAL_SPOT_PREEMPT_CASCADE,
                description="Spot GPU reclaim cascaded into distributed job restart failure.",
                tier_hint="T0+T2",
                rca_hint="preempt_cascade",
            ),
            SignalSpec(
                signal=SIGNAL_GPU_SKU_MISMATCH,
                description="Workload running on a GPU SKU disproportionate to its profile.",
                tier_hint="T0",
                rca_hint="gpu_sizing",
            ),
            SignalSpec(
                signal=SIGNAL_GPU_IDLE_HOURS_WASTED,
                description="Cumulative reserved-but-unused GPU-hours over budget.",
                tier_hint="T0+forecast",
                rca_hint="gpu_waste",
            ),
            SignalSpec(
                signal=SIGNAL_TOKEN_SPEND_SPIKE,
                description="LLM token spend crossed per-window budget band.",
                tier_hint="T0+forecast",
                rca_hint="cost_burn",
            ),
        )
    }
)


def known_signals() -> Mapping[str, SignalSpec]:
    """Return the read-only signal registry.

    The returned mapping is immutable (a ``MappingProxyType``); callers
    that need to extend the registry in a fork MUST wrap this and pass
    their own dict, never mutate the returned view.
    """
    return _KNOWN_SIGNALS


def is_known_signal(signal: str) -> bool:
    """True iff ``signal`` is a registered canonical detection signal."""
    return signal in _KNOWN_SIGNALS


def signals_with_role(role: SignalRole) -> frozenset[str]:
    """Return the set of registered signal names that carry ``role``.

    Derived from the single source of truth (``_KNOWN_SIGNALS``); tests
    and consumers MUST NOT hard-code a parallel set - reading the role
    off the registry keeps the two from drifting.
    """
    return frozenset(name for name, spec in _KNOWN_SIGNALS.items() if spec.role is role)


__all__ = [
    "SIGNAL_ALERT_TRIGGER",
    "SIGNAL_BACKEND_HEALTH",
    "SIGNAL_COLD_START_LATENCY_SPIKE",
    "SIGNAL_CONFIG_DRIFT",
    "SIGNAL_DB_CPU",
    "SIGNAL_DISTRIBUTED_STRAGGLER",
    "SIGNAL_GATEWAY_LATENCY",
    "SIGNAL_GPU_ECC_UNCORRECTABLE",
    "SIGNAL_GPU_IDLE_HOURS_WASTED",
    "SIGNAL_GPU_PCIE_DEGRADATION",
    "SIGNAL_GPU_POWER_THROTTLE",
    "SIGNAL_GPU_SKU_MISMATCH",
    "SIGNAL_GPU_TEMP_THROTTLE",
    "SIGNAL_GPU_UTIL_SATURATED",
    "SIGNAL_GPU_UTIL_ZERO_WASTED",
    "SIGNAL_GPU_VRAM_OOM",
    "SIGNAL_GPU_XID_EVENT",
    "SIGNAL_HOST_CPU",
    "SIGNAL_HOST_MEMORY",
    "SIGNAL_INFERENCE_P99_SPIKE",
    "SIGNAL_KV_CACHE_PRESSURE",
    "SIGNAL_MEMBER_HOTSPOT",
    "SIGNAL_NCCL_TIMEOUT",
    "SIGNAL_NODE_CPU",
    "SIGNAL_POD_RESTART",
    "SIGNAL_RATE_LIMIT",
    "SIGNAL_REQUEST_FAILURE",
    "SIGNAL_ROLLOUT_STALL",
    "SIGNAL_SPOT_PREEMPT_CASCADE",
    "SIGNAL_TOKEN_SPEND_SPIKE",
    "SIGNAL_WEIGHTS_FETCH_STALL",
    "SignalRole",
    "SignalSpec",
    "is_known_signal",
    "known_signals",
    "signals_with_role",
]
