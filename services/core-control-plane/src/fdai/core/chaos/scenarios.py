"""Reference fault-injection scenarios (demo parity, CSP-neutral).

These mirror the injected faults in the Azure SRE Agent demo (session notes
slide 9), expressed with opaque, customer-agnostic ``target_selector``
handles. Each scenario names the ``expected_signal`` the control loop
SHOULD raise, so the harness can decide VALIDATED vs NOT_DETECTED.

The catalog covers every S/C scenario in
``docs/internals/sre-demo-scenarios-08-fdai-coverage.md``:

- S1  / C2 -> :data:`AKS_POD_KILL`               (``pod_restart``)
- S2  / C3 -> :data:`AKS_POD_CPU_SPIKE`          (``node_cpu``)
- S3  / S7 / S10 -> :data:`NETWORK_RTT_DELAY`    (``gateway_latency``)
- S4  -> :data:`AKS_HTTP_ABORT`                  (``request_failure``)
- S5  -> :data:`VM_CPU_STRESS`                   (``host_cpu``)
- S6  / C4 -> :data:`VM_MEM_STRESS`              (``host_memory``)
- S8  -> :data:`MYSQL_CPU_PRESSURE`              (``db_cpu``)
- S9  -> :data:`AOAI_TPM_THROTTLE`               (``rate_limit``)
- S11 -> :data:`APPGW_BACKEND_FAILURE`           (``backend_health``)
- S12 -> :data:`AKS_BAD_DEPLOY`                  (``rollout_stall``)

Every ``duration_seconds`` is at least 360s (the demo's 5-minute alert
window plus one probe cycle) so the harness will still see the expected
signal at the configured evaluation window. S13 (drift / knowledge) and
S14 (alert -> auto trigger) are not faults, so they do not appear here;
the coverage matrix marks them C separately.
"""

from __future__ import annotations

from fdai.core.chaos.contract import FaultScenario
from fdai.core.detection.signals import (
    SIGNAL_BACKEND_HEALTH,
    SIGNAL_DB_CPU,
    SIGNAL_GATEWAY_LATENCY,
    SIGNAL_HOST_CPU,
    SIGNAL_HOST_MEMORY,
    SIGNAL_NODE_CPU,
    SIGNAL_POD_RESTART,
    SIGNAL_RATE_LIMIT,
    SIGNAL_REQUEST_FAILURE,
    SIGNAL_ROLLOUT_STALL,
)

# Minimum hold every scenario is authored for. The demo's default alert
# evaluation window is 5 minutes; we add a 60-second buffer so the
# harness's post-inject probe cannot fire before the analyzer sees a
# full window of data. The harness's ``max_hold_seconds`` still bounds
# any authored value against runaway durations.
_ALERT_WINDOW_SECONDS = 300.0
_PROBE_BUFFER_SECONDS = 60.0
_MIN_HOLD_SECONDS = _ALERT_WINDOW_SECONDS + _PROBE_BUFFER_SECONDS  # 360.0

AKS_POD_KILL = FaultScenario(
    scenario_id="aks-pod-kill",
    fault_type="pod_kill",
    description=(
        "Kill an AKS pod (Chaos Mesh PodChaos pod-kill) to induce a "
        "restart the KubeEvents ingest MUST see."
    ),
    target_selector="workload:api-backend",
    expected_signal=SIGNAL_POD_RESTART,
    blast_radius_cap=2,
    duration_seconds=_MIN_HOLD_SECONDS,
    params={"grace_period_seconds": "0"},
    rollback_note=(
        "Kill is idempotent; the ReplicaSet reschedules the pod. The "
        "Chaos Mesh resource is removed on stop."
    ),
)

AKS_POD_CPU_SPIKE = FaultScenario(
    scenario_id="aks-pod-cpu-spike",
    fault_type="cpu_stress",
    description="Drive AKS pod CPU up to induce backend latency downstream.",
    target_selector="workload:api-backend",
    expected_signal=SIGNAL_NODE_CPU,
    blast_radius_cap=3,
    duration_seconds=_MIN_HOLD_SECONDS,
    params={"cpu_workers": "4"},
    rollback_note="Remove the Chaos Mesh StressChaos resource.",
)

AKS_HTTP_ABORT = FaultScenario(
    scenario_id="aks-http-abort",
    fault_type="http_abort",
    description=(
        "Abort a fraction of inbound HTTP requests at the pod "
        "(Chaos Mesh HTTPChaos, target=Request) to raise the failure "
        "rate above the SLO burn threshold."
    ),
    target_selector="workload:api-backend",
    expected_signal=SIGNAL_REQUEST_FAILURE,
    blast_radius_cap=2,
    duration_seconds=_MIN_HOLD_SECONDS,
    params={"abort_percent": "30", "target": "Request"},
    rollback_note="Remove the Chaos Mesh HTTPChaos resource.",
)

VM_CPU_STRESS = FaultScenario(
    scenario_id="vm-cpu-stress",
    fault_type="vm_cpu_stress",
    description=(
        "Sustain guest-OS CPU on a VM/VMSS instance (stress-ng) to "
        "trigger the host-CPU threshold analyzer."
    ),
    target_selector="host:linux-loadgen",
    expected_signal=SIGNAL_HOST_CPU,
    blast_radius_cap=1,
    duration_seconds=_MIN_HOLD_SECONDS,
    params={"cpu_workers": "0", "cpu_load_percent": "90"},
    rollback_note="Kill the stress-ng process; systemd unit is one-shot.",
)

VM_MEM_STRESS = FaultScenario(
    scenario_id="vm-mem-stress",
    fault_type="vm_mem_stress",
    description=(
        "Sustain guest-OS memory pressure on a VM (stress-ng --vm) to "
        "trigger the host-memory threshold analyzer; also covers the "
        "pod-memory variant used by C4."
    ),
    target_selector="host:linux-loadgen",
    expected_signal=SIGNAL_HOST_MEMORY,
    blast_radius_cap=1,
    duration_seconds=_MIN_HOLD_SECONDS,
    params={"vm_workers": "2", "vm_bytes": "1G"},
    rollback_note="Kill the stress-ng process; memory is released on exit.",
)

AKS_BAD_DEPLOY = FaultScenario(
    scenario_id="aks-bad-deploy",
    fault_type="bad_deploy",
    description=(
        "Roll out a Deployment revision that references a nonexistent "
        "image tag so pods stall in ImagePullBackOff past the progress "
        "deadline - RCA correlates this with the change feed."
    ),
    target_selector="workload:api-backend",
    expected_signal=SIGNAL_ROLLOUT_STALL,
    blast_radius_cap=1,
    duration_seconds=_MIN_HOLD_SECONDS,
    params={"image_tag": "does-not-exist", "progress_deadline_seconds": "300"},
    rollback_note=(
        "`kubectl rollout undo deployment/<name>` restores the prior "
        "revision; the executor runs it as the S12 remediation."
    ),
)

AOAI_TPM_THROTTLE = FaultScenario(
    scenario_id="aoai-tpm-throttle",
    fault_type="rate_limit",
    description="Shrink Azure OpenAI TPM to induce HTTP 429 rate-limit errors.",
    target_selector="model-deployment:chat",
    expected_signal=SIGNAL_RATE_LIMIT,
    blast_radius_cap=1,
    duration_seconds=_MIN_HOLD_SECONDS,
    params={"tpm_reduction_pct": "80"},
    rollback_note="Restore the prior TPM quota on the deployment.",
)

MYSQL_CPU_PRESSURE = FaultScenario(
    scenario_id="mysql-cpu-pressure",
    fault_type="query_load",
    description="Sustain MySQL CPU pressure to surface slow queries.",
    target_selector="db:orders",
    expected_signal=SIGNAL_DB_CPU,
    blast_radius_cap=1,
    duration_seconds=_MIN_HOLD_SECONDS,
    params={"concurrent_queries": "50"},
    rollback_note="Stop the load generator.",
)

APPGW_BACKEND_FAILURE = FaultScenario(
    scenario_id="appgw-backend-failure",
    fault_type="pod_kill",
    description="Fail a backend pool member to collapse healthy host count.",
    target_selector="workload:api-backend",
    expected_signal=SIGNAL_BACKEND_HEALTH,
    blast_radius_cap=2,
    duration_seconds=_MIN_HOLD_SECONDS,
    rollback_note="Allow the deployment to reschedule the pod.",
)

NETWORK_RTT_DELAY = FaultScenario(
    scenario_id="network-rtt-delay",
    fault_type="network_delay",
    description="Add outbound RTT to inflate dependency latency.",
    target_selector="workload:api-backend",
    expected_signal=SIGNAL_GATEWAY_LATENCY,
    blast_radius_cap=2,
    duration_seconds=_MIN_HOLD_SECONDS,
    params={"delay_ms": "250"},
    rollback_note="Remove the Chaos Mesh NetworkChaos resource.",
)


def default_scenarios() -> tuple[FaultScenario, ...]:
    """The reference chaos catalog matching every S/C demo fault.

    Order follows the demo pack (S1 -> S12; non-fault S13/S14 are covered
    by governance / trigger seams and do not appear here).
    """
    return (
        AKS_POD_KILL,
        AKS_POD_CPU_SPIKE,
        NETWORK_RTT_DELAY,
        AKS_HTTP_ABORT,
        VM_CPU_STRESS,
        VM_MEM_STRESS,
        MYSQL_CPU_PRESSURE,
        AOAI_TPM_THROTTLE,
        APPGW_BACKEND_FAILURE,
        AKS_BAD_DEPLOY,
    )


__all__ = [
    "AKS_BAD_DEPLOY",
    "AKS_HTTP_ABORT",
    "AKS_POD_CPU_SPIKE",
    "AKS_POD_KILL",
    "AOAI_TPM_THROTTLE",
    "APPGW_BACKEND_FAILURE",
    "MYSQL_CPU_PRESSURE",
    "NETWORK_RTT_DELAY",
    "VM_CPU_STRESS",
    "VM_MEM_STRESS",
    "default_scenarios",
]
