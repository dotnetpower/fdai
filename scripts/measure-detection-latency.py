"""Measure real detection latency per chaos scenario.

Companion to `scripts/run-enforce-scenarios.py`. That runner proves
`Mode.ENFORCE` VALIDATES with the full 5-minute analyzer window; its
`elapsed_seconds` is dominated by the harness `max_hold_seconds=180`
overhead, so it does NOT reflect how fast FDAI actually notices.

This driver reuses the same live injectors and probes, but instead of
waiting a fixed hold and probing once, it:

  1. Injects the fault.
  2. Polls the probe at the configured interval (per scenario) until
     it first returns True or the deadline is reached.
  3. Records `time_to_first_observed_seconds` from just after inject.
  4. Always stops / rolls back in a finally block.

The number is the latency for THIS probe. Metric-backed probes
(Azure Monitor `Percentage CPU`, MySQL `cpu_percent`) are naturally
gated by the platform's 1-minute aggregation window; event / status
probes (KubeEvents, Chaos Mesh CRD status, HTTP 429 sample, endpoint
count) fire within seconds. The doc breaks the two classes out.

Env vars: same set as scripts/run-enforce-scenarios.py
(`FDAI_ENFORCE_*`). Reports land under
`logs/detection-latency/<timestamp>/`.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sys
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from azure.identity import DefaultAzureCredential

from fdai.core.chaos.contract import FaultScenario
from fdai.core.chaos.injector import FaultInjector, SignalProbe
from fdai.core.chaos.scenarios import (
    AKS_BAD_DEPLOY,
    AKS_HTTP_ABORT,
    AKS_POD_CPU_SPIKE,
    AKS_POD_KILL,
    AOAI_TPM_THROTTLE,
    APPGW_BACKEND_FAILURE,
    MYSQL_CPU_PRESSURE,
    NETWORK_RTT_DELAY,
    VM_CPU_STRESS,
    VM_MEM_STRESS,
)
from fdai.delivery.chaos.aoai_ratelimit import (
    AoaiRateLimitInjector,
    AoaiRateLimitProbe,
    build_aoai_request_fn,
)
from fdai.delivery.chaos.chaos_mesh import (
    ChaosMeshInjectedProbe,
    ChaosMeshInjector,
)
from fdai.delivery.chaos.live_injectors import (
    AzureMonitorCpuProbe,
    AzVmCpuStressInjector,
    AzVmMemProbe,
    AzVmMemStressInjector,
    KubeBackendHealthProbe,
    KubectlBackendDownInjector,
    KubectlBadDeployInjector,
    KubectlPodKillInjector,
    KubeEventPodRestartProbe,
    KubeRolloutStallProbe,
)
from fdai.delivery.chaos.mysql_load import (
    AzMysqlQueryLoadInjector,
    AzureMonitorDbCpuProbe,
)


def _env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise SystemExit(f"required env var not set: {name}")
    return v


SUB_ID = _env("FDAI_ENFORCE_SUB_ID")
RG = _env("FDAI_ENFORCE_RG")
CTX = _env("FDAI_ENFORCE_AKS_CONTEXT")
NS = _env("FDAI_ENFORCE_NS")
CHAOS_NS = _env("FDAI_ENFORCE_CHAOS_NS")
BACKEND_DEPLOY = _env("FDAI_ENFORCE_BACKEND_DEPLOY")
BACKEND_SVC = _env("FDAI_ENFORCE_BACKEND_SVC")
BACKEND_LABEL = _env("FDAI_ENFORCE_BACKEND_LABEL")
VM_NAME = _env("FDAI_ENFORCE_VM")
VM_ID = (
    f"/subscriptions/{SUB_ID}/resourceGroups/{RG}"
    f"/providers/Microsoft.Compute/virtualMachines/{VM_NAME}"
)
MYSQL_HOST = _env("FDAI_ENFORCE_MYSQL_HOST")
MYSQL_USER = _env("FDAI_ENFORCE_MYSQL_USER")
MYSQL_SERVER = _env("FDAI_ENFORCE_MYSQL_SERVER")
MYSQL_ID = (
    f"/subscriptions/{SUB_ID}/resourceGroups/{RG}"
    f"/providers/Microsoft.DBforMySQL/flexibleServers/{MYSQL_SERVER}"
)
MYSQL_PW_FILE = _env("FDAI_ENFORCE_MYSQL_PW_FILE")
AOAI_ENDPOINT = _env("FDAI_ENFORCE_AOAI_ENDPOINT")
AOAI_DEPLOYMENT = _env("FDAI_ENFORCE_AOAI_DEPLOYMENT")

REPORT_ROOT = (
    Path("logs/detection-latency") / datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
)
REPORT_ROOT.mkdir(parents=True, exist_ok=True)

# Two probe classes. Event / status probes can be polled at 1 s and reflect
# the true edge; metric-backed probes are gated by a platform 60-second
# aggregation window, so a sub-minute poll adds only wall-clock cost.
POLL_FAST = 1.0
POLL_METRIC = 15.0

# Overall deadline. Long enough to give metric-based probes ~3 aggregation
# windows to surface; anything longer is a real detection gap, not noise.
MAX_WAIT_SECONDS = 240.0


def _mysql_password() -> str:
    return Path(MYSQL_PW_FILE).read_text().strip()


def _mysql_connect_factory():
    import pymysql

    pw = _mysql_password()

    def _connect():
        return pymysql.connect(
            host=MYSQL_HOST,
            user=MYSQL_USER,
            password=pw,
            ssl={"ssl": {}},
            connect_timeout=15,
        )

    return _connect


def _aoai_token_provider():
    cred = DefaultAzureCredential()
    scope = "https://cognitiveservices.azure.com/.default"

    def _tok() -> str:
        return cred.get_token(scope).token

    return _tok


def _stress_chaos_crd(name: str) -> str:
    return f"""
apiVersion: chaos-mesh.org/v1alpha1
kind: StressChaos
metadata:
  name: {name}
  namespace: {CHAOS_NS}
spec:
  mode: one
  selector:
    namespaces: [{NS}]
    labelSelectors:
      app: {BACKEND_DEPLOY}
  stressors:
    cpu:
      workers: 2
      load: 90
  duration: 5m
"""


def _network_delay_crd(name: str) -> str:
    return f"""
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: {name}
  namespace: {CHAOS_NS}
spec:
  action: delay
  mode: one
  selector:
    namespaces: [{NS}]
    labelSelectors:
      app: {BACKEND_DEPLOY}
  delay:
    latency: "250ms"
    jitter: "20ms"
    correlation: "50"
  duration: 5m
"""


def _http_abort_crd(name: str) -> str:
    return f"""
apiVersion: chaos-mesh.org/v1alpha1
kind: HTTPChaos
metadata:
  name: {name}
  namespace: {CHAOS_NS}
spec:
  mode: one
  selector:
    namespaces: [{NS}]
    labelSelectors:
      app: {BACKEND_DEPLOY}
  target: Request
  port: 80
  abort: true
  duration: 5m
"""


def _runs() -> list[tuple[FaultScenario, FaultInjector, SignalProbe, list[str], float, str]]:
    """Return (scenario, injector, probe, targets, poll_interval, probe_class)."""
    return [
        (
            AKS_POD_KILL,
            KubectlPodKillInjector(context=CTX, namespace=NS),
            KubeEventPodRestartProbe(context=CTX, namespace=NS),
            [BACKEND_LABEL],
            POLL_FAST,
            "kube_event",
        ),
        (
            AKS_POD_CPU_SPIKE,
            ChaosMeshInjector(
                fault_type=AKS_POD_CPU_SPIKE.fault_type,
                context=CTX,
                kind="StressChaos",
                name="fdai-s2-cpu",
                namespace=CHAOS_NS,
                crd_yaml=_stress_chaos_crd("fdai-s2-cpu"),
            ),
            ChaosMeshInjectedProbe(
                context=CTX, kind="StressChaos", name="fdai-s2-cpu", namespace=CHAOS_NS
            ),
            [BACKEND_LABEL],
            POLL_FAST,
            "chaos_mesh_status",
        ),
        (
            NETWORK_RTT_DELAY,
            ChaosMeshInjector(
                fault_type=NETWORK_RTT_DELAY.fault_type,
                context=CTX,
                kind="NetworkChaos",
                name="fdai-s3-netdelay",
                namespace=CHAOS_NS,
                crd_yaml=_network_delay_crd("fdai-s3-netdelay"),
            ),
            ChaosMeshInjectedProbe(
                context=CTX, kind="NetworkChaos", name="fdai-s3-netdelay", namespace=CHAOS_NS
            ),
            [BACKEND_LABEL],
            POLL_FAST,
            "chaos_mesh_status",
        ),
        (
            AKS_HTTP_ABORT,
            ChaosMeshInjector(
                fault_type=AKS_HTTP_ABORT.fault_type,
                context=CTX,
                kind="HTTPChaos",
                name="fdai-s4-httpabort",
                namespace=CHAOS_NS,
                crd_yaml=_http_abort_crd("fdai-s4-httpabort"),
            ),
            ChaosMeshInjectedProbe(
                context=CTX, kind="HTTPChaos", name="fdai-s4-httpabort", namespace=CHAOS_NS
            ),
            [BACKEND_LABEL],
            POLL_FAST,
            "chaos_mesh_status",
        ),
        (
            VM_CPU_STRESS,
            AzVmCpuStressInjector(resource_group=RG, vm_name=VM_NAME, duration_seconds=600),
            AzureMonitorCpuProbe(vm_resource_id=VM_ID, threshold_pct=40.0),
            [VM_NAME],
            POLL_METRIC,
            "azure_monitor_metric",
        ),
        (
            VM_MEM_STRESS,
            AzVmMemStressInjector(
                resource_group=RG, vm_name=VM_NAME, vm_bytes="250M", duration_seconds=600
            ),
            AzVmMemProbe(resource_group=RG, vm_name=VM_NAME, min_available_mb=350),
            [VM_NAME],
            POLL_METRIC,
            "run_command_free_m",
        ),
        (
            MYSQL_CPU_PRESSURE,
            AzMysqlQueryLoadInjector(
                connect_factory=_mysql_connect_factory(), concurrent_queries=4
            ),
            AzureMonitorDbCpuProbe(server_resource_id=MYSQL_ID, threshold_pct=25.0),
            ["orders"],
            POLL_METRIC,
            "azure_monitor_metric",
        ),
        (
            AOAI_TPM_THROTTLE,
            AoaiRateLimitInjector(
                request_fn=build_aoai_request_fn(
                    endpoint=AOAI_ENDPOINT,
                    deployment=AOAI_DEPLOYMENT,
                    token_provider=_aoai_token_provider(),
                    prompt="Reply with a long lorem ipsum paragraph.",
                    max_tokens=400,
                ),
                concurrency=8,
            ),
            AoaiRateLimitProbe(
                request_fn=build_aoai_request_fn(
                    endpoint=AOAI_ENDPOINT,
                    deployment=AOAI_DEPLOYMENT,
                    token_provider=_aoai_token_provider(),
                    prompt="one word please",
                    max_tokens=8,
                ),
                samples=5,
            ),
            [AOAI_DEPLOYMENT],
            POLL_FAST,
            "http_429_sample",
        ),
        (
            APPGW_BACKEND_FAILURE,
            KubectlBackendDownInjector(
                context=CTX,
                namespace=NS,
                deployment=BACKEND_DEPLOY,
                restore_replicas=3,
            ),
            KubeBackendHealthProbe(context=CTX, namespace=NS, service=BACKEND_SVC),
            [BACKEND_DEPLOY],
            POLL_FAST,
            "kube_endpoints",
        ),
        (
            AKS_BAD_DEPLOY,
            KubectlBadDeployInjector(
                context=CTX,
                namespace=NS,
                deployment=BACKEND_DEPLOY,
                container="web",
                bad_image="nginx:does-not-exist-latency-run",
            ),
            KubeRolloutStallProbe(context=CTX, namespace=NS, selector=BACKEND_LABEL),
            [BACKEND_LABEL],
            POLL_FAST,
            "kube_pod_status",
        ),
    ]


async def _measure(
    scenario: FaultScenario,
    injector: FaultInjector,
    probe: SignalProbe,
    targets: Sequence[str],
    poll_interval: float,
    probe_class: str,
) -> dict[str, Any]:
    started = datetime.now(tz=UTC)
    inject_start = time.monotonic()
    inject_end = inject_start
    inject_error: str | None = None
    first_observed: float | None = None
    poll_count = 0
    reverted = False
    try:
        for target in targets:
            await injector.inject(target=target, params=scenario.params)
        inject_end = time.monotonic()
        deadline = inject_end + MAX_WAIT_SECONDS
        while time.monotonic() < deadline:
            poll_count += 1
            try:
                observed = await probe.observed(
                    signal=scenario.expected_signal, targets=tuple(targets)
                )
            except Exception as exc:  # noqa: BLE001 - keep polling on transient probe errors
                observed = False
                inject_error = f"{type(exc).__name__}:{exc}"
            if observed:
                first_observed = time.monotonic() - inject_end
                break
            await asyncio.sleep(poll_interval)
    except Exception as exc:  # noqa: BLE001 - report driver errors
        inject_error = f"{type(exc).__name__}:{exc}"
    finally:
        for target in targets:
            with contextlib.suppress(Exception):
                await injector.stop(target=target)
        reverted = True
    total = time.monotonic() - inject_start
    payload = {
        "scenario_id": scenario.scenario_id,
        "expected_signal": scenario.expected_signal,
        "probe_class": probe_class,
        "poll_interval_seconds": poll_interval,
        "inject_seconds": round(inject_end - inject_start, 2),
        "time_to_first_observed_seconds": (
            round(first_observed, 2) if first_observed is not None else None
        ),
        "poll_count": poll_count,
        "observed": first_observed is not None,
        "reverted": reverted,
        "error": inject_error,
        "started_at": started.isoformat(),
        "ended_at": datetime.now(tz=UTC).isoformat(),
        "total_elapsed_seconds": round(total, 2),
    }
    out = REPORT_ROOT / f"{scenario.scenario_id}.json"
    out.write_text(json.dumps(payload, indent=2, sort_keys=True))
    ttfo = payload["time_to_first_observed_seconds"]
    print(
        f"[{'observed' if payload['observed'] else 'timeout '}] "
        f"{scenario.scenario_id:24s} inject={payload['inject_seconds']:>6.2f}s "
        f"ttfo={ttfo if ttfo is not None else 'N/A':>6}s "
        f"polls={poll_count} probe_class={probe_class}",
        flush=True,
    )
    return payload


async def main() -> int:
    print(f"report root: {REPORT_ROOT}", flush=True)
    runs = _runs()
    only = set(sys.argv[1:])
    if only:
        runs = [r for r in runs if r[0].scenario_id in only]
    reports: list[dict[str, Any]] = []
    for scenario, injector, probe, targets, poll_interval, probe_class in runs:
        r = await _measure(scenario, injector, probe, list(targets), poll_interval, probe_class)
        reports.append(r)
        await asyncio.sleep(10)

    (REPORT_ROOT / "report.json").write_text(
        json.dumps({"runs": reports}, indent=2, sort_keys=True)
    )
    md = [
        "# Detection latency measurements",
        "",
        f"Report root: `{REPORT_ROOT}`",
        "",
        f"`MAX_WAIT_SECONDS={MAX_WAIT_SECONDS}`, "
        f"`POLL_FAST={POLL_FAST}s`, `POLL_METRIC={POLL_METRIC}s`.",
        "",
        "| Scenario | Probe class | Inject (s) | Time to first observed (s) | Polls | Observed |",
        "|----------|-------------|-----------:|---------------------------:|------:|----------|",
    ]
    for r in reports:
        ttfo = r["time_to_first_observed_seconds"]
        md.append(
            f"| `{r['scenario_id']}` | `{r['probe_class']}` | {r['inject_seconds']} | "
            f"{ttfo if ttfo is not None else 'not observed'} | {r['poll_count']} | "
            f"{r['observed']} |"
        )
    (REPORT_ROOT / "summary.md").write_text("\n".join(md) + "\n")
    print(f"\nsummary written: {REPORT_ROOT / 'summary.md'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
