"""Ingest Chaos Mesh CRD types into the FDAI chaos-scenarios catalog.

Chaos Mesh ships ~12 CRD kinds (PodChaos, NetworkChaos, HTTPChaos,
IOChaos, StressChaos, DNSChaos, KernelChaos, TimeChaos, BlockChaos,
JVMChaos, AWSChaos, GCPChaos, PhysicalMachineChaos). Each supports
several action modes (e.g. NetworkChaos: delay, loss, corrupt,
duplicate, partition, bandwidth). The seed generator in
`scripts/catalog/generate-scenarios.py` covers the demo-parity subset
(pod-kill, StressChaos cpu, NetworkChaos delay, HTTPChaos abort,
DNSChaos, IOChaos latency); this ingester adds the remaining common
action modes.

Source: https://chaos-mesh.org (CRD reference). Hand-curated - the
upstream docs are hand-maintained YAML examples, not a machine
schema, so a static list is honest and CSP-neutral. When Chaos Mesh
adds a new action, extend `_ENTRIES` and re-run.

Output: `rule-catalog/chaos-scenarios/collected/chaos-mesh/*.yaml`,
one file per scenario. Idempotent - rewrites on every run.

Each emitted scenario:
  - provenance.source: chaos-mesh, method: collected
  - injector: chaos-mesh:<Kind> (the delivery-layer ChaosMeshInjector
    already knows how to apply/delete a CRD-body scenario)
  - expected_signal: must map to a registered SIGNAL_* in
    `core/detection/signals.py`; the loader rejects anything else
  - gates: shadow_status=pending, enforce_status=null
"""

from __future__ import annotations

import pathlib
import re
from dataclasses import dataclass

import yaml
from fdai.core.detection.signals import SignalRole, known_signals

_HERE = pathlib.Path(__file__).resolve()
_REPO_ROOT = next(parent for parent in _HERE.parents if (parent / "pyproject.toml").is_file())
_OUT_DIR = _REPO_ROOT / "rule-catalog" / "chaos-scenarios" / "collected" / "chaos-mesh"
_ALERT_WINDOW_S = 360.0
_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_KIND_PATTERN = re.compile(r"^[A-Z][A-Za-z0-9]+Chaos$")
_ALLOWED_CATEGORIES = frozenset(
    {
        "compute",
        "network",
        "storage",
        "state",
        "dependency",
        "traffic",
        "time",
        "resource_saturation",
        "identity",
        "quota",
        "cost_governance",
    }
)
_ALLOWED_TARGET_TYPES = frozenset(
    {
        "pod",
        "node",
        "vm",
        "vmss",
        "db",
        "lb",
        "dns",
        "disk",
        "cache",
        "secret_store",
        "identity",
        "ingress",
        "egress",
        "quota",
        "llm_endpoint",
        "control_plane",
    }
)
_ALLOWED_FAULT_FAMILIES = frozenset(
    {
        "stop",
        "delay",
        "drop",
        "corrupt",
        "saturate",
        "throttle",
        "deny",
        "misroute",
        "expire",
        "quota_shrink",
        "oom",
        "hang",
        "preempt",
        "checkpoint_fail",
        "cache_overflow",
        "ramp",
    }
)
_ALLOWED_INTENSITIES = frozenset({"mild", "high", "extreme"})


@dataclass(frozen=True, slots=True)
class Entry:
    slug: str  # kebab; becomes the id suffix and the filename stem
    kind: str  # Chaos Mesh CRD kind (CamelCase)
    action: str  # spec.action value
    description: str
    category: str
    target_type: str
    fault_family: str
    intensity: str
    expected_signal: str
    params: dict[str, str]
    rollback_note: str
    blast_radius_cap: int = 2
    tags: tuple[str, ...] = ()


# Only actions that map cleanly to a registered SIGNAL_* and that the
# seed generator does not already cover. Every entry uses a real
# upstream Chaos Mesh action spelling.
_ENTRIES: tuple[Entry, ...] = (
    # -- PodChaos ---------------------------------------------------------
    Entry(
        slug="pod-failure",
        kind="PodChaos",
        action="pod-failure",
        description="Mark a pod as unavailable via Chaos Mesh PodChaos "
        "(pod-failure): the pod is not deleted, kubelet reports NotReady.",
        category="compute",
        target_type="pod",
        fault_family="stop",
        intensity="high",
        expected_signal="pod_restart",
        params={"action": "pod-failure", "mode": "one"},
        rollback_note="Delete the PodChaos CRD; Chaos Mesh clears the mark.",
        blast_radius_cap=2,
        tags=("chaos-mesh", "pod"),
    ),
    Entry(
        slug="container-kill",
        kind="PodChaos",
        action="container-kill",
        description="Kill a specific container inside a pod (PodChaos "
        "container-kill); the pod itself survives but the container restarts.",
        category="compute",
        target_type="pod",
        fault_family="stop",
        intensity="high",
        expected_signal="pod_restart",
        params={"action": "container-kill", "mode": "one"},
        rollback_note="Delete the PodChaos CRD; kubelet restarts the container back to Ready.",
        blast_radius_cap=2,
        tags=("chaos-mesh", "container"),
    ),
    # -- NetworkChaos (additions to the seed's `delay`) -------------------
    Entry(
        slug="network-loss",
        kind="NetworkChaos",
        action="loss",
        description="Drop a fraction of outbound packets (NetworkChaos loss).",
        category="network",
        target_type="pod",
        fault_family="drop",
        intensity="high",
        expected_signal="request_failure",
        params={"action": "loss", "loss_percent": "20", "correlation": "50"},
        rollback_note="Delete the NetworkChaos CRD; interface returns to normal.",
        blast_radius_cap=2,
        tags=("chaos-mesh", "network"),
    ),
    Entry(
        slug="network-corrupt",
        kind="NetworkChaos",
        action="corrupt",
        description="Corrupt a fraction of outbound packets (NetworkChaos "
        "corrupt); typically surfaces as protocol / TLS errors downstream.",
        category="network",
        target_type="pod",
        fault_family="corrupt",
        intensity="high",
        expected_signal="request_failure",
        params={"action": "corrupt", "corrupt_percent": "20", "correlation": "50"},
        rollback_note="Delete the NetworkChaos CRD.",
        blast_radius_cap=2,
        tags=("chaos-mesh", "network"),
    ),
    Entry(
        slug="network-duplicate",
        kind="NetworkChaos",
        action="duplicate",
        description="Duplicate a fraction of outbound packets (NetworkChaos "
        "duplicate); tail-latency and retry-storm behaviour downstream.",
        category="network",
        target_type="pod",
        fault_family="corrupt",
        intensity="mild",
        expected_signal="gateway_latency",
        params={"action": "duplicate", "duplicate_percent": "10", "correlation": "50"},
        rollback_note="Delete the NetworkChaos CRD.",
        blast_radius_cap=2,
        tags=("chaos-mesh", "network"),
    ),
    Entry(
        slug="network-partition",
        kind="NetworkChaos",
        action="partition",
        description="Fully partition a pod from an upstream target "
        "(NetworkChaos partition); endpoints for the target collapse.",
        category="network",
        target_type="pod",
        fault_family="deny",
        intensity="extreme",
        expected_signal="backend_health",
        params={"action": "partition", "direction": "both"},
        rollback_note="Delete the NetworkChaos CRD; connectivity restores.",
        blast_radius_cap=2,
        tags=("chaos-mesh", "network"),
    ),
    Entry(
        slug="network-bandwidth",
        kind="NetworkChaos",
        action="bandwidth",
        description="Throttle egress bandwidth on the pod interface "
        "(NetworkChaos bandwidth); inflates first-byte latency downstream.",
        category="network",
        target_type="pod",
        fault_family="throttle",
        intensity="high",
        expected_signal="gateway_latency",
        params={"action": "bandwidth", "rate": "1mbps", "buffer": "10000"},
        rollback_note="Delete the NetworkChaos CRD.",
        blast_radius_cap=2,
        tags=("chaos-mesh", "network"),
    ),
    # -- HTTPChaos (additions to the seed's `abort`) ----------------------
    Entry(
        slug="http-delay",
        kind="HTTPChaos",
        action="delay",
        description="Inject an HTTP-layer delay (HTTPChaos delay) on the "
        "pod's inbound requests, above the abort path.",
        category="traffic",
        target_type="pod",
        fault_family="delay",
        intensity="high",
        expected_signal="gateway_latency",
        params={"target": "Request", "delay": "2s", "port": "80"},
        rollback_note="Delete the HTTPChaos CRD.",
        blast_radius_cap=2,
        tags=("chaos-mesh", "http"),
    ),
    Entry(
        slug="http-replace",
        kind="HTTPChaos",
        action="replace",
        description="Replace inbound HTTP body / status via HTTPChaos "
        "(replace) - useful to emulate corrupted 5xx responses.",
        category="traffic",
        target_type="pod",
        fault_family="corrupt",
        intensity="high",
        expected_signal="request_failure",
        params={"target": "Response", "replace_code": "503", "port": "80"},
        rollback_note="Delete the HTTPChaos CRD.",
        blast_radius_cap=2,
        tags=("chaos-mesh", "http"),
    ),
    # -- StressChaos (memory addition; the seed has cpu) -----------------
    Entry(
        slug="stress-memory",
        kind="StressChaos",
        action="memory",
        description="Sustain memory pressure via StressChaos memory stressor.",
        category="resource_saturation",
        target_type="pod",
        fault_family="saturate",
        intensity="high",
        expected_signal="host_memory",
        params={"stressor": "memory", "workers": "1", "size": "256M"},
        rollback_note="Delete the StressChaos CRD.",
        blast_radius_cap=2,
        tags=("chaos-mesh", "memory"),
    ),
    # -- IOChaos (fault; the seed has latency) ---------------------------
    Entry(
        slug="io-fault",
        kind="IOChaos",
        action="fault",
        description="Return errno on I/O syscalls (IOChaos fault); the "
        "process observes EIO / ENOSPC and downstream requests fail.",
        category="storage",
        target_type="disk",
        fault_family="corrupt",
        intensity="high",
        expected_signal="request_failure",
        params={"action": "fault", "errno": "5", "percent": "50"},
        rollback_note="Delete the IOChaos CRD.",
        blast_radius_cap=1,
        tags=("chaos-mesh", "io"),
    ),
    # -- DNSChaos error (the seed has random) ----------------------------
    Entry(
        slug="dns-error",
        kind="DNSChaos",
        action="error",
        description="Return DNS resolution errors (DNSChaos error) for "
        "outbound lookups; upstream calls fail before they leave the pod.",
        category="network",
        target_type="dns",
        fault_family="deny",
        intensity="extreme",
        expected_signal="request_failure",
        params={"action": "error", "scope": "all", "patterns": "*.svc.cluster.local"},
        rollback_note="Delete the DNSChaos CRD; DNS resolves normally.",
        blast_radius_cap=2,
        tags=("chaos-mesh", "dns"),
    ),
    # -- BlockChaos ------------------------------------------------------
    Entry(
        slug="block-delay",
        kind="BlockChaos",
        action="delay",
        description="Add latency to block-device I/O (BlockChaos delay); "
        "the pod observes elevated iowait.",
        category="storage",
        target_type="disk",
        fault_family="delay",
        intensity="high",
        expected_signal="host_cpu",
        params={"action": "delay", "delay": "300ms", "volume": "data"},
        rollback_note="Delete the BlockChaos CRD.",
        blast_radius_cap=1,
        tags=("chaos-mesh", "block"),
    ),
    # -- KernelChaos -----------------------------------------------------
    Entry(
        slug="kernel-panic",
        kind="KernelChaos",
        action="fail-syscall",
        description="Force a syscall to fail with a chosen errno "
        "(KernelChaos); processes typically restart / crash the container.",
        category="state",
        target_type="pod",
        fault_family="corrupt",
        intensity="extreme",
        expected_signal="pod_restart",
        params={"action": "fail-syscall", "syscall": "write", "errno": "5"},
        rollback_note="Delete the KernelChaos CRD; kernel behaviour resets.",
        blast_radius_cap=1,
        tags=("chaos-mesh", "kernel"),
    ),
)


def _validate_entry(e: Entry) -> None:
    if not _SLUG_PATTERN.fullmatch(e.slug):
        raise ValueError("invalid_slug")
    if not _KIND_PATTERN.fullmatch(e.kind):
        raise ValueError("unsupported_kind")
    if not e.action.strip():
        raise ValueError("missing_action")
    if e.category not in _ALLOWED_CATEGORIES:
        raise ValueError("unsupported_category")
    if e.target_type not in _ALLOWED_TARGET_TYPES:
        raise ValueError("unsupported_target_type")
    if e.fault_family not in _ALLOWED_FAULT_FAMILIES:
        raise ValueError("unsupported_fault_family")
    if e.intensity not in _ALLOWED_INTENSITIES:
        raise ValueError("unsupported_intensity")
    if e.blast_radius_cap < 1:
        raise ValueError("invalid_blast_radius_cap")
    if not e.description.strip() or not e.rollback_note.strip():
        raise ValueError("missing_description_or_rollback_note")
    signal = known_signals().get(e.expected_signal)
    if signal is None:
        raise ValueError("unknown_expected_signal")
    if signal.role is SignalRole.RCA_ONLY:
        raise ValueError("rca_only_signal_not_scenario_eligible")


def _to_body(e: Entry) -> dict[str, object]:
    _validate_entry(e)
    return {
        "id": f"chaos.chaos-mesh.{e.slug}",
        "version": 1,
        "provenance": {
            "source": "chaos-mesh",
            "source_url": "https://chaos-mesh.org",
            "synthesis_method": "collected",
        },
        "category": e.category,
        "target_type": e.target_type,
        "fault_family": e.fault_family,
        "intensity": e.intensity,
        "duration_seconds": _ALERT_WINDOW_S if e.intensity != "extreme" else _ALERT_WINDOW_S * 2,
        "expected_signal": e.expected_signal,
        "injector": f"chaos-mesh:{e.kind}",
        "blast_radius_cap": e.blast_radius_cap,
        "rollback_note": e.rollback_note,
        "gates": {"shadow_status": "pending", "enforce_status": None},
        "requires_hardware": False,
        "description": e.description,
        "params": dict(e.params),
        "tags": list(e.tags),
    }


def main() -> int:
    slugs = [e.slug for e in _ENTRIES]
    if len(slugs) != len(set(slugs)):
        raise ValueError("duplicate_slug")
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    valid_names = {f"{e.slug}.yaml" for e in _ENTRIES}
    for existing in _OUT_DIR.glob("*.yaml"):
        if existing.name not in valid_names:
            existing.unlink()
    written = 0
    for e in _ENTRIES:
        path = _OUT_DIR / f"{e.slug}.yaml"
        with path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(_to_body(e), f, sort_keys=False, default_flow_style=False)
        written += 1
    print(f"wrote {written} Chaos Mesh scenarios -> {_OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
