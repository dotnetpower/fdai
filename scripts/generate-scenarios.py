"""Deterministic combinatorial chaos-scenario generator.

Emits YAML scenarios into
`rule-catalog/chaos-scenarios/collected/synthesized/` and (for GPU)
`rule-catalog/chaos-scenarios/collected/gpu/`. No LLM; no external
        "probe-only:gpu-sku-mismatch",

Design intent (see docs/internals/sre-scenario-library-scaling.md):

    scenario = (target_type * fault_family * intensity * scope * duration)

The generator enumerates hand-curated valid tuples for each domain
axis (general server + GPU / AI-serving) so meaningless combinations
never get written. Every emitted scenario:

  - Uses a registered `expected_signal` from
    `fdai.core.detection.signals` (validated by the catalog loader).
    - Ships `injector: needs-injector` unless a mapping to a shipped
        delivery/chaos injector is known;
    the catalog loader keeps `needs-injector` scenarios out of
    `promoted/`.
  - Ships `gates.shadow_status: pending` and `enforce_status: null`.
    - Ships `requires_hardware: true` for GPU scenarios; they stay
        shadow-only until a suitable hardware substrate is available.

Idempotent: rewrites the same file names on every run. Safe to `git
diff` and commit.
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass

import yaml

_HERE = pathlib.Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[1]
_CATALOG_ROOT = _REPO_ROOT / "rule-catalog" / "chaos-scenarios"
_SYNTH_DIR = _CATALOG_ROOT / "collected" / "synthesized"
_GPU_DIR = _CATALOG_ROOT / "collected" / "gpu"

_ALERT_WINDOW_S = 360.0  # matches core/chaos/scenarios.py _MIN_HOLD_SECONDS


@dataclass(frozen=True, slots=True)
class Spec:
    id: str
    description: str
    provenance_source: str
    provenance_method: str
    category: str
    target_type: str
    fault_family: str
    intensity: str
    duration_seconds: float
    expected_signal: str
    injector: str
    blast_radius_cap: int
    rollback_note: str
    params: dict[str, str] | None = None
    gpu_domain: str | None = None
    requires_hardware: bool = False
    minimum_gpus: int = 0
    tags: tuple[str, ...] = ()

    def to_yaml_body(self) -> dict:
        body: dict = {
            "id": self.id,
            "version": 1,
            "provenance": {
                "source": self.provenance_source,
                "synthesis_method": self.provenance_method,
            },
            "category": self.category,
            "target_type": self.target_type,
            "fault_family": self.fault_family,
            "intensity": self.intensity,
            "duration_seconds": self.duration_seconds,
            "expected_signal": self.expected_signal,
            "injector": self.injector,
            "blast_radius_cap": self.blast_radius_cap,
            "rollback_note": self.rollback_note,
            "gates": {"shadow_status": "pending", "enforce_status": None},
            "requires_hardware": self.requires_hardware,
            "description": self.description,
        }
        if self.params:
            body["params"] = self.params
        if self.gpu_domain is not None:
            body["gpu_domain"] = self.gpu_domain
        if self.minimum_gpus:
            body["minimum_gpus"] = self.minimum_gpus
        if self.tags:
            body["tags"] = list(self.tags)
        return body


# ---------------------------------------------------------------------------
# General (non-GPU) tuples
# ---------------------------------------------------------------------------

# Each entry: (target_type, fault_family, expected_signal, injector, category,
# base blast_cap, params, description-suffix, rollback_note, tags).
_GENERAL_AXES: tuple[tuple, ...] = (
    (
        "pod",
        "stop",
        "pod_restart",
        "chaos-mesh:PodChaos",
        "compute",
        1,
        {"action": "pod-kill"},
        "kill one pod; ReplicaSet reschedules",
        "ReplicaSet reschedules the killed pod; CRD deletion removes the fault.",
        ("kubernetes", "self-heal"),
    ),
    (
        "pod",
        "saturate",
        "node_cpu",
        "chaos-mesh:StressChaos",
        "compute",
        3,
        {"stressor": "cpu", "workers": "2", "load_percent": "90"},
        "sustain pod CPU pressure",
        "Delete the Chaos Mesh StressChaos resource.",
        ("kubernetes", "cpu"),
    ),
    (
        "pod",
        "delay",
        "gateway_latency",
        "chaos-mesh:NetworkChaos",
        "network",
        2,
        {"action": "delay", "latency_ms": "250"},
        "inject outbound network delay on backend pods",
        "Delete the Chaos Mesh NetworkChaos resource.",
        ("kubernetes", "network"),
    ),
    (
        "pod",
        "drop",
        "request_failure",
        "chaos-mesh:HTTPChaos",
        "traffic",
        2,
        {"action": "abort", "abort_percent": "30"},
        "abort a fraction of inbound HTTP requests",
        "Delete the Chaos Mesh HTTPChaos resource.",
        ("kubernetes", "http"),
    ),
    (
        "vm",
        "saturate",
        "host_cpu",
        "az:vm-run-command",
        "compute",
        1,
        {"tool": "stress-ng", "cpu_workers": "0"},
        "sustain guest-OS CPU via stress-ng",
        "Run pkill -f stress-ng; systemd unit is one-shot.",
        ("vm", "iaas", "cpu"),
    ),
    (
        "vm",
        "saturate",
        "host_memory",
        "az:vm-run-command",
        "resource_saturation",
        1,
        {"tool": "stress-ng", "vm_bytes": "250M"},
        "sustain guest-OS memory pressure via stress-ng --vm",
        "Run pkill -f stress-ng; kernel reclaims on exit.",
        ("vm", "iaas", "memory"),
    ),
    (
        "db",
        "saturate",
        "db_cpu",
        "mysql:query-load",
        "resource_saturation",
        1,
        {"tool": "benchmark_load", "concurrent_queries": "4"},
        "drive MySQL/Postgres CPU via BENCHMARK-style workload",
        "Stop the load generator; server recovers on its own.",
        ("data", "database"),
    ),
    (
        "llm_endpoint",
        "throttle",
        "rate_limit",
        "aoai:rate-limit",
        "quota",
        1,
        {"target": "aoai", "concurrency": "8"},
        "drive LLM endpoint above per-window budget to induce 429",
        "Stop the load generator; TPM budget refills.",
        ("llm", "quota"),
    ),
    (
        "lb",
        "deny",
        "backend_health",
        "kubectl:scale",
        "traffic",
        1,
        {"scale_to": "0"},
        "scale backend deployment to 0 (endpoints collapse)",
        "Restore replicas via kubectl scale.",
        ("kubernetes", "endpoints"),
    ),
    (
        "pod",
        "corrupt",
        "rollout_stall",
        "kubectl:set-image",
        "state",
        1,
        {"bad_image_tag": "does-not-exist"},
        "roll out a deployment with a nonexistent image tag",
        "kubectl rollout undo restores the previous revision.",
        ("kubernetes", "change"),
    ),
    # -- second-tier / expansion combos (intensity variants) -----------
    (
        "vm",
        "saturate",
        "host_cpu",
        "az:vm-run-command",
        "compute",
        1,
        {"tool": "stress-ng", "cpu_workers": "0", "load_percent": "50"},
        "sustain guest-OS CPU at half saturation (borderline)",
        "Run pkill -f stress-ng.",
        ("vm", "iaas", "cpu", "borderline"),
    ),
    (
        "pod",
        "saturate",
        "node_cpu",
        "chaos-mesh:StressChaos",
        "compute",
        3,
        {"stressor": "cpu", "workers": "4", "load_percent": "100"},
        "extreme pod CPU (all cores saturated)",
        "Delete the Chaos Mesh StressChaos resource.",
        ("kubernetes", "cpu", "extreme"),
    ),
    (
        "pod",
        "delay",
        "gateway_latency",
        "chaos-mesh:NetworkChaos",
        "network",
        2,
        {"action": "delay", "latency_ms": "1000"},
        "inject 1s outbound network delay (extreme)",
        "Delete the Chaos Mesh NetworkChaos resource.",
        ("kubernetes", "network", "extreme"),
    ),
    (
        "pod",
        "drop",
        "request_failure",
        "chaos-mesh:HTTPChaos",
        "traffic",
        2,
        {"action": "abort", "abort_percent": "100"},
        "abort 100% of inbound HTTP requests (blackhole)",
        "Delete the Chaos Mesh HTTPChaos resource.",
        ("kubernetes", "http", "blackhole"),
    ),
    (
        "dns",
        "delay",
        "gateway_latency",
        "chaos-mesh:DNSChaos",
        "network",
        2,
        {"action": "random", "duration_multiplier": "5"},
        "randomize DNS answers on backend pods",
        "Delete the Chaos Mesh DNSChaos resource.",
        ("kubernetes", "network", "dns"),
    ),
    (
        "disk",
        "delay",
        "host_cpu",
        "chaos-mesh:IOChaos",
        "storage",
        1,
        {"action": "latency", "delay_ms": "500", "percent": "80"},
        "add I/O latency on the pod filesystem (dependency saturates CPU wait)",
        "Delete the Chaos Mesh IOChaos resource.",
        ("kubernetes", "io", "storage"),
    ),
)

# intensity for each general axis, and (intensity string, id suffix, blast_cap_delta,
# duration_seconds). We keep this small on purpose so the emitted set is
# audit-reviewable, not a wall of hundreds.
_GENERAL_INTENSITY_VARIANTS: tuple[tuple[str, str], ...] = (
    ("mild", "-mild"),
    ("high", "-high"),
    ("extreme", "-extreme"),
)


# ---------------------------------------------------------------------------
# GPU / AI-serving tuples (all shadow-only until a GPU substrate exists)
# ---------------------------------------------------------------------------

_GPU_AXES: tuple[tuple, ...] = (
    # driver
    (
        "gpu",
        "xid_event",
        "gpu_xid_event",
        "gpu_driver",
        "driver_xid",
        {"xid_code": "74", "severity": "critical"},
        "GPU fell off bus (Xid 74) - node drain candidate",
        "Node drain + hardware replacement (rollback = re-cordon).",
    ),
    (
        "gpu",
        "xid_event",
        "gpu_xid_event",
        "gpu_driver",
        "driver_xid",
        {"xid_code": "79", "severity": "critical"},
        "GPU fell off bus (Xid 79) - PCIe error",
        "Node drain + hardware replacement.",
    ),
    (
        "gpu",
        "ecc_error",
        "gpu_ecc_uncorrectable",
        "gpu_driver",
        "driver_xid",
        {"xid_code": "48"},
        "HBM uncorrectable ECC (Xid 48)",
        "Node drain; RMA the GPU.",
    ),
    (
        "gpu",
        "ecc_error",
        "gpu_ecc_uncorrectable",
        "gpu_driver",
        "driver_xid",
        {"xid_code": "63"},
        "Uncorrectable page fault (Xid 63)",
        "Restart the affected process; drain node if recurring.",
    ),
    (
        "gpu",
        "thermal_throttle",
        "gpu_temp_throttle",
        "gpu_driver",
        "driver_xid",
        {"threshold_c": "85"},
        "Thermal throttle at high junction temperature",
        "Reduce load; verify cooling; the throttle self-clears.",
    ),
    (
        "gpu",
        "throttle",
        "gpu_power_throttle",
        "gpu_driver",
        "driver_xid",
        {"power_cap_reduction_pct": "20"},
        "Sustained power-cap throttle (SM clock reduced 20%)",
        "Verify PSU / rack budget; the throttle clears when demand drops.",
    ),
    (
        "gpu",
        "delay",
        "gpu_pcie_degradation",
        "gpu_driver",
        "driver_xid",
        {"expected_lanes": "16", "observed_lanes": "8"},
        "PCIe lane count degraded from x16 to x8",
        "Reseat card or reboot node; if persistent, RMA.",
    ),
    # compute / memory
    (
        "gpu",
        "oom",
        "gpu_vram_oom",
        "gpu_compute",
        "memory_vram",
        {"process": "training", "batch_size_bump_pct": "20"},
        "CUDA OOM after batch-size bump",
        "Reduce batch size; restart the training process.",
    ),
    (
        "gpu",
        "oom",
        "gpu_vram_oom",
        "gpu_compute",
        "memory_vram",
        {"process": "inference", "concurrent_requests": "128"},
        "CUDA OOM under inference concurrency burst",
        "Shed load or shrink KV cache; process auto-restarts.",
    ),
    (
        "gpu",
        "hang",
        "gpu_util_zero_wasted",
        "gpu_compute",
        "memory_vram",
        {"symptom": "deadlocked_kernel", "duration_min": "30"},
        "GPU held by a deadlocked CUDA kernel (util 0%, VRAM held)",
        "SIGKILL the owning process; ideally cgroup-scoped restart.",
    ),
    (
        "gpu_cluster",
        "saturate",
        "gpu_util_saturated",
        "gpu_compute",
        "memory_vram",
        {"queue_depth": "sustained"},
        "GPU utilization pinned near 100% with queue backlog rising",
        "Scale out serving replicas or shed traffic.",
    ),
    # distributed
    (
        "training_job",
        "hang",
        "nccl_timeout",
        "gpu_distributed",
        "distributed",
        {"ring_size": "8", "op": "all_reduce"},
        "NCCL all-reduce hang - one rank stalled",
        "Kill the whole job (torchrun / mpirun); resume from last checkpoint.",
    ),
    (
        "training_job",
        "delay",
        "distributed_straggler",
        "gpu_distributed",
        "distributed",
        {"slow_rank_step_multiplier": "3"},
        "One rank is 3x slower than peers per training step",
        "Cordon the slow node; rerun after redistribution.",
    ),
    (
        "training_job",
        "preempt",
        "spot_preempt_cascade",
        "gpu_distributed",
        "distributed",
        {"preempt_percent": "25", "restart_failure_rate": "60"},
        "Spot GPU reclaim cascaded to distributed job restart failure",
        "Fall back to on-demand for the affected ranks; resume from checkpoint.",
    ),
    (
        "training_job",
        "checkpoint_fail",
        "spot_preempt_cascade",
        "gpu_distributed",
        "distributed",
        {"checkpoint_target": "blob_storage"},
        "Checkpoint save failed mid-preemption (no resume state)",
        "Restart from last successful checkpoint (may lose N steps).",
    ),
    # inference / serving
    (
        "inference_endpoint",
        "delay",
        "inference_p99_spike",
        "gpu_inference",
        "inference_serving",
        {"p99_multiplier": "5"},
        "Inference p99 latency spiked 5x above SLO band",
        "Scale out replicas; shed non-critical tenants.",
    ),
    (
        "inference_endpoint",
        "cache_overflow",
        "kv_cache_pressure",
        "gpu_inference",
        "inference_serving",
        {"cache_watermark_pct": "95"},
        "KV cache high-water at 95%; eviction storm imminent",
        "Cap max context length or scale out; auto-evictor drains cache.",
    ),
    (
        "inference_endpoint",
        "ramp",
        "cold_start_latency_spike",
        "gpu_inference",
        "inference_serving",
        {"model_size_gb": "40", "first_token_ms": "8000"},
        "Cold-start first-token latency 8s after model reload",
        "Pin at least one warm replica; predictive warmup on rollout.",
    ),
    # storage
    (
        "inference_endpoint",
        "delay",
        "weights_fetch_stall",
        "gpu_inference",
        "storage_dataflow",
        {"fetch_throughput_mb_s": "50"},
        "Model-weights fetch from object storage below expected throughput",
        "Failover to a mirrored region or retry with backoff.",
    ),
    # cost governance (advisory only; no injection, detection-side)
    (
        "gpu",
        "quota_shrink",
        "gpu_idle_hours_wasted",
        "gpu_cost",
        "cost_governance",
        {"idle_util_threshold_pct": "10", "window_hours": "24"},
        "Reserved GPU idle >90% of a 24h window (cost waste)",
        "Advisory: shrink reservation or move workload; no injection.",
    ),
    (
        "gpu",
        "quota_shrink",
        "gpu_sku_mismatch",
        "gpu_cost",
        "cost_governance",
        {"observed_sku": "H100", "recommended_sku": "A100"},
        "Workload profile indicates A100 may satisfy requirements at lower cost",
        "Advisory: re-SKU the deployment; no injection.",
    ),
    (
        "llm_endpoint",
        "quota_shrink",
        "token_spend_spike",
        "gpu_cost",
        "cost_governance",
        {"budget_multiplier": "3"},
        "LLM token spend crossed 3x normal per-window budget band",
        "Advisory: apply per-tenant token cap; no injection.",
    ),
)


def _general_specs() -> list[Spec]:
    out: list[Spec] = []
    seen: set[str] = set()
    for axis in _GENERAL_AXES:
        (
            target_type,
            fault_family,
            expected_signal,
            injector,
            category,
            blast_cap,
            base_params,
            desc_suffix,
            rollback_note,
            tags,
        ) = axis
        for intensity, id_suffix in _GENERAL_INTENSITY_VARIANTS:
            sid_base = (
                f"chaos.general.{target_type}-{fault_family}-{expected_signal.replace('_', '-')}"
                f"{id_suffix}"
            )
            sid = sid_base
            n = 2
            while sid in seen:
                sid = f"{sid_base}-v{n}"
                n += 1
            seen.add(sid)
            duration = _ALERT_WINDOW_S if intensity != "extreme" else _ALERT_WINDOW_S * 2
            out.append(
                Spec(
                    id=sid,
                    description=f"[{intensity}] {desc_suffix}",
                    provenance_source="synthesized",
                    provenance_method="deterministic",
                    category=category,
                    target_type=target_type,
                    fault_family=fault_family,
                    intensity=intensity,
                    duration_seconds=duration,
                    expected_signal=expected_signal,
                    injector=injector,
                    blast_radius_cap=blast_cap,
                    rollback_note=rollback_note,
                    params=dict(base_params) if base_params else None,
                    tags=tags,
                )
            )
    return out


def _gpu_specs() -> list[Spec]:
    out: list[Spec] = []
    for axis in _GPU_AXES:
        (
            target_type,
            fault_family,
            expected_signal,
            category,
            gpu_domain,
            params,
            description,
            rollback_note,
        ) = axis
        sid = f"chaos.gpu.{target_type}-{fault_family}-{expected_signal.replace('_', '-')}"
        # dedupe id if two axes emit the same sid by appending a numeric suffix.
        suffix = ""
        n = 2
        seen = {s.id for s in out}
        while sid + suffix in seen:
            suffix = f"-v{n}"
            n += 1
        # cost-governance is detection-only; the others need an injector we do
        # not ship yet.
        injector = "needs-injector"
        # GPU shadow-only: requires_hardware for anything that would actually
        # perturb a physical GPU; cost-governance scenarios are detection-only.
        requires_hw = category != "gpu_cost"
        minimum_gpus = 1 if target_type in {"gpu", "inference_endpoint"} else 0
        if target_type in {"gpu_cluster", "training_job"}:
            minimum_gpus = 2
        out.append(
            Spec(
                id=sid + suffix,
                description=description,
                provenance_source="synthesized",
                provenance_method="deterministic",
                category=category,
                target_type=target_type,
                fault_family=fault_family,
                intensity="high",
                duration_seconds=_ALERT_WINDOW_S,
                expected_signal=expected_signal,
                injector=injector,
                blast_radius_cap=1 if target_type == "gpu" else 2,
                rollback_note=rollback_note,
                params=dict(params) if params else None,
                gpu_domain=gpu_domain,
                requires_hardware=requires_hw,
                minimum_gpus=minimum_gpus,
                tags=("gpu", gpu_domain.replace("_", "-")),
            )
        )
    return out


def _write(spec: Spec, out_dir: pathlib.Path) -> pathlib.Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    body = spec.to_yaml_body()
    # filename = last segment of id, kebab-preserved
    fname = spec.id.split(".", 2)[-1] + ".yaml"
    path = out_dir / fname
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(body, f, sort_keys=False, default_flow_style=False)
    return path


def main() -> int:
    general = _general_specs()
    gpu = _gpu_specs()
    for s in general:
        _write(s, _SYNTH_DIR)
    for s in gpu:
        _write(s, _GPU_DIR)
    print(f"wrote {len(general)} general -> {_SYNTH_DIR}")
    print(f"wrote {len(gpu)} gpu     -> {_GPU_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
