"""Ingest Litmus Chaos experiment hub into the FDAI catalog.

Litmus is a CNCF chaos engineering project with a public experiment hub
(hub.litmuschaos.io). Its experiments run on Kubernetes clusters and
inject faults through `ChaosEngine` + `ChaosExperiment` CRDs
(litmuschaos.io/v1alpha1). Each experiment has a fixed slug, a target
scope (pod, container, node), and a small parameter set.

This ingester is a hand-curated CSP-neutral projection of 16 widely
used generic experiments from the hub - the ones whose fault
semantics map cleanly onto a signal FDAI's detection layer already
knows. Every entry ships with a `litmus:<experiment>` injector backed by
the Litmus ChaosEngine adapter. The upstream experiment identity stays
in `provenance.source_ref` and is also the installed ChaosExperiment name.

Reasoning about the "why is Litmus separate from Chaos Mesh" question
mirrors the earlier Chaos Studio insight: Litmus is a *managed
orchestrator* that composes underlying kernel / kubectl / stress
primitives. FDAI keeps the vendor identity in `provenance.source_ref`
and dispatches the entries through the shipped `litmus:*` delivery
adapter so operators can cross-reference the Litmus hub definition.

Source: hub.litmuschaos.io (upstream experiment specs). Idempotent -
the runner rewrites the same files every run and prunes stale ones.
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass

import yaml

_HERE = pathlib.Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[1]
_OUT_DIR = _REPO_ROOT / "rule-catalog" / "chaos-scenarios" / "collected" / "litmus"
_ALERT_WINDOW_S = 360.0


@dataclass(frozen=True, slots=True)
class Entry:
    slug: str
    experiment_name: str  # Litmus hub identifier
    description: str
    category: str
    target_type: str
    fault_family: str
    intensity: str
    expected_signal: str
    params: dict[str, str]
    rollback_note: str
    blast_radius_cap: int = 2


# Curated subset of the Litmus hub. Every entry uses an upstream
# experiment_name verbatim; the fault_family / expected_signal fields
# map to registered FDAI vocabulary.
_ENTRIES: tuple[Entry, ...] = (
    Entry(
        slug="pod-delete",
        experiment_name="pod-delete",
        description="Kill a target pod at a fixed cadence for the duration; "
        "the workload controller reschedules.",
        category="compute",
        target_type="pod",
        fault_family="stop",
        intensity="high",
        expected_signal="pod_restart",
        params={"CHAOS_INTERVAL": "10", "FORCE": "true"},
        rollback_note="ChaosEngine deletion + ReplicaSet self-heal.",
    ),
    Entry(
        slug="container-kill",
        experiment_name="container-kill",
        description="Kill a specific container inside a pod; kubelet restarts it.",
        category="compute",
        target_type="pod",
        fault_family="stop",
        intensity="high",
        expected_signal="pod_restart",
        params={"CHAOS_INTERVAL": "10", "SIGNAL": "SIGKILL"},
        rollback_note="Delete the ChaosEngine; kubelet restarts the container.",
    ),
    Entry(
        slug="pod-cpu-hog",
        experiment_name="pod-cpu-hog",
        description="Spike CPU on target pods to trigger node/pod CPU alarms.",
        category="compute",
        target_type="pod",
        fault_family="saturate",
        intensity="high",
        expected_signal="node_cpu",
        params={"CPU_CORES": "1", "CPU_LOAD": "100"},
        rollback_note="Delete the ChaosEngine; the CPU stressor exits.",
        blast_radius_cap=3,
    ),
    Entry(
        slug="pod-memory-hog",
        experiment_name="pod-memory-hog",
        description="Consume memory on target pods until they OOM or throttle.",
        category="resource_saturation",
        target_type="pod",
        fault_family="saturate",
        intensity="high",
        expected_signal="host_memory",
        params={"MEMORY_CONSUMPTION": "500"},
        rollback_note="Delete the ChaosEngine; kernel reclaims on exit.",
    ),
    Entry(
        slug="pod-network-latency",
        experiment_name="pod-network-latency",
        description="Add outbound network latency on target pods (tc netem).",
        category="network",
        target_type="pod",
        fault_family="delay",
        intensity="high",
        expected_signal="gateway_latency",
        params={"NETWORK_LATENCY": "2000", "JITTER": "0"},
        rollback_note="Delete the ChaosEngine; tc qdisc del removes the rule.",
    ),
    Entry(
        slug="pod-network-loss",
        experiment_name="pod-network-loss",
        description="Drop a fraction of outbound packets on target pods.",
        category="network",
        target_type="pod",
        fault_family="drop",
        intensity="high",
        expected_signal="request_failure",
        params={"NETWORK_PACKET_LOSS_PERCENTAGE": "30"},
        rollback_note="Delete the ChaosEngine; tc qdisc del removes the rule.",
    ),
    Entry(
        slug="pod-network-corruption",
        experiment_name="pod-network-corruption",
        description="Corrupt outbound packets; downstream calls fail parse.",
        category="network",
        target_type="pod",
        fault_family="corrupt",
        intensity="high",
        expected_signal="request_failure",
        params={"NETWORK_PACKET_CORRUPTION_PERCENTAGE": "20"},
        rollback_note="Delete the ChaosEngine.",
    ),
    Entry(
        slug="pod-network-duplication",
        experiment_name="pod-network-duplication",
        description="Duplicate a fraction of outbound packets - retry storms.",
        category="network",
        target_type="pod",
        fault_family="corrupt",
        intensity="mild",
        expected_signal="gateway_latency",
        params={"NETWORK_PACKET_DUPLICATION_PERCENTAGE": "20"},
        rollback_note="Delete the ChaosEngine.",
    ),
    Entry(
        slug="pod-http-latency",
        experiment_name="pod-http-latency",
        description="Add HTTP-layer latency to inbound requests on the pod.",
        category="traffic",
        target_type="pod",
        fault_family="delay",
        intensity="high",
        expected_signal="gateway_latency",
        params={"LATENCY": "2000", "TARGET_SERVICE_PORT": "80"},
        rollback_note="Delete the ChaosEngine.",
    ),
    Entry(
        slug="pod-http-status-code",
        experiment_name="pod-http-status-code",
        description="Rewrite inbound HTTP responses to a chosen status code.",
        category="traffic",
        target_type="pod",
        fault_family="corrupt",
        intensity="high",
        expected_signal="request_failure",
        params={"STATUS_CODE": "503", "MODIFY_RESPONSE_BODY": "false"},
        rollback_note="Delete the ChaosEngine.",
    ),
    Entry(
        slug="pod-dns-error",
        experiment_name="pod-dns-error",
        description="Force DNS lookups to fail for target hostnames on the pod.",
        category="network",
        target_type="dns",
        fault_family="deny",
        intensity="extreme",
        expected_signal="request_failure",
        params={"TARGET_HOSTNAMES": "'[\"*.svc.cluster.local\"]'"},
        rollback_note="Delete the ChaosEngine.",
    ),
    Entry(
        slug="pod-io-stress",
        experiment_name="pod-io-stress",
        description="Sustained disk I/O pressure on the pod's filesystem.",
        category="storage",
        target_type="disk",
        fault_family="saturate",
        intensity="high",
        expected_signal="host_cpu",
        params={"IO_WORKERS": "4"},
        rollback_note="Delete the ChaosEngine.",
        blast_radius_cap=1,
    ),
    Entry(
        slug="node-cpu-hog",
        experiment_name="node-cpu-hog",
        description="CPU pressure on the target node (all pods share the impact).",
        category="compute",
        target_type="node",
        fault_family="saturate",
        intensity="extreme",
        expected_signal="host_cpu",
        params={"NODE_CPU_CORE": "0"},
        rollback_note="Delete the ChaosEngine; the CPU stressor exits.",
        blast_radius_cap=1,
    ),
    Entry(
        slug="node-memory-hog",
        experiment_name="node-memory-hog",
        description="Memory pressure on the target node.",
        category="resource_saturation",
        target_type="node",
        fault_family="saturate",
        intensity="extreme",
        expected_signal="host_memory",
        params={"MEMORY_CONSUMPTION_PERCENTAGE": "50"},
        rollback_note="Delete the ChaosEngine.",
        blast_radius_cap=1,
    ),
    Entry(
        slug="node-drain",
        experiment_name="node-drain",
        description="Drain a node (cordon + evict) - workloads reschedule elsewhere.",
        category="compute",
        target_type="node",
        fault_family="stop",
        intensity="extreme",
        expected_signal="pod_restart",
        params={"NODE_LABEL": "node-role.kubernetes.io/worker"},
        rollback_note="Uncordon the node on ChaosEngine deletion; pods reschedule.",
        blast_radius_cap=1,
    ),
    Entry(
        slug="disk-fill",
        experiment_name="disk-fill",
        description="Fill the pod ephemeral disk toward the limit.",
        category="storage",
        target_type="disk",
        fault_family="saturate",
        intensity="extreme",
        expected_signal="host_cpu",
        params={"FILL_PERCENTAGE": "95"},
        rollback_note="Delete the ChaosEngine.",
        blast_radius_cap=1,
    ),
)


def _to_body(e: Entry) -> dict:
    return {
        "id": f"chaos.litmus.{e.slug}",
        "version": 1,
        "provenance": {
            "source": "litmus",
            "source_url": "https://hub.litmuschaos.io",
            "source_ref": e.experiment_name,
            "synthesis_method": "collected",
        },
        "category": e.category,
        "target_type": e.target_type,
        "fault_family": e.fault_family,
        "intensity": e.intensity,
        "duration_seconds": _ALERT_WINDOW_S if e.intensity != "extreme" else _ALERT_WINDOW_S * 2,
        "expected_signal": e.expected_signal,
        "injector": f"litmus:{e.experiment_name}",
        "blast_radius_cap": e.blast_radius_cap,
        "rollback_note": e.rollback_note,
        "gates": {"shadow_status": "pending", "enforce_status": None},
        "requires_hardware": False,
        "description": e.description,
        "params": dict(e.params),
        "tags": ["litmus"],
    }


def main() -> int:
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
    print(f"wrote {written} Litmus scenarios -> {_OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
