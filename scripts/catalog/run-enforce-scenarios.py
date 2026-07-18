"""Run all reference chaos scenarios in ENFORCE mode against a test substrate.

This is a dev-only harness driver, not shipped runtime code. It wires the
live delivery injectors + probes to their upstream `core.chaos` scenarios
and persists an audit-shaped JSON report per run under
`logs/enforce-runs/<timestamp>/`.

Substrate configuration is **entirely env-driven** (no hardcoded customer
identifiers), so any fork can point this at its own disposable test RG.
Required env vars:

    FDAI_ENFORCE_SUB_ID          Azure subscription id
    FDAI_ENFORCE_RG              resource group hosting the test substrate
    FDAI_ENFORCE_AKS_CONTEXT     kubectl context for the test AKS cluster
    FDAI_ENFORCE_NS              namespace for the demo backend
    FDAI_ENFORCE_CHAOS_NS        namespace where Chaos Mesh is installed
    FDAI_ENFORCE_BACKEND_DEPLOY  demo backend Deployment name
    FDAI_ENFORCE_BACKEND_SVC     demo backend Service name
    FDAI_ENFORCE_BACKEND_LABEL   label selector for the backend pods
    FDAI_ENFORCE_VM              VM name (for S5 / S6)
    FDAI_ENFORCE_MYSQL_HOST      MySQL Flexible Server FQDN (S8)
    FDAI_ENFORCE_MYSQL_USER      MySQL admin login (S8)
    FDAI_ENFORCE_MYSQL_SERVER    MySQL Flexible Server resource name (S8)
    FDAI_ENFORCE_MYSQL_PW_FILE   path to a file with the MySQL password (S8)
    FDAI_ENFORCE_AOAI_ENDPOINT   AOAI account endpoint URL (S9)
    FDAI_ENFORCE_AOAI_DEPLOYMENT AOAI chat deployment name (S9)

The runner uses `max_hold_seconds=180` at the harness level (probe-oriented
validation, not a full 5-minute production alert window). It writes
`report.json` + one `<scenario>.json` per run + a `summary.md` under
`logs/enforce-runs/<timestamp>/`.

Prerequisites (verified manually before running):
  - `az account show` matches `FDAI_ENFORCE_SUB_ID`.
  - `kubectl --context $FDAI_ENFORCE_AKS_CONTEXT get nodes` -> Ready.
  - Demo backend Deployment + Service exist in `$FDAI_ENFORCE_NS`.
  - Chaos Mesh is installed in `$FDAI_ENFORCE_CHAOS_NS`.
  - `FDAI_ENFORCE_MYSQL_PW_FILE` contains the current MySQL admin password
    and the caller's public IP is allowed by the server firewall.
  - The signed-in identity has "Cognitive Services OpenAI User" on the
    AOAI account.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from azure.identity import DefaultAzureCredential

from fdai.core.chaos.contract import ExperimentResult, FaultScenario
from fdai.core.chaos.harness import FaultInjectionHarness
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
from fdai.shared.contracts.models import Mode


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

REPORT_ROOT = Path("logs/enforce-runs") / datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
REPORT_ROOT.mkdir(parents=True, exist_ok=True)


def _mysql_password() -> str:
    return Path(MYSQL_PW_FILE).read_text().strip()


def _mysql_connect_factory():
    import pymysql  # local import - not a core dep

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


# --- Chaos Mesh CRD builders --------------------------------------------------
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


# --- Runs table ---------------------------------------------------------------
def _build_runs():
    """Return (scenario, injector, probe, approved_targets) tuples."""
    return [
        (
            AKS_POD_KILL,
            KubectlPodKillInjector(context=CTX, namespace=NS),
            KubeEventPodRestartProbe(context=CTX, namespace=NS),
            [BACKEND_LABEL],
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
        ),
        (
            VM_CPU_STRESS,
            AzVmCpuStressInjector(resource_group=RG, vm_name=VM_NAME, duration_seconds=600),
            AzureMonitorCpuProbe(vm_resource_id=VM_ID, threshold_pct=40.0),
            [VM_NAME],
        ),
        (
            VM_MEM_STRESS,
            # Fixed byte size; caller-owned test VM may have very little
            # commit budget (small SKU, no swap). Tune vm_bytes down until
            # stress-ng-vm can mmap without OOM-terminating mid-hold.
            AzVmMemStressInjector(
                resource_group=RG, vm_name=VM_NAME, vm_bytes="250M", duration_seconds=600
            ),
            AzVmMemProbe(resource_group=RG, vm_name=VM_NAME, min_available_mb=350),
            [VM_NAME],
        ),
        (
            MYSQL_CPU_PRESSURE,
            AzMysqlQueryLoadInjector(
                connect_factory=_mysql_connect_factory(), concurrent_queries=4
            ),
            AzureMonitorDbCpuProbe(server_resource_id=MYSQL_ID, threshold_pct=25.0),
            ["orders"],
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
        ),
        (
            AKS_BAD_DEPLOY,
            KubectlBadDeployInjector(
                context=CTX,
                namespace=NS,
                deployment=BACKEND_DEPLOY,
                container="web",
                bad_image="nginx:does-not-exist-enforce-run",
            ),
            KubeRolloutStallProbe(context=CTX, namespace=NS, selector=BACKEND_LABEL),
            [BACKEND_LABEL],
        ),
    ]


def _serialize(result: ExperimentResult) -> dict:
    d = dataclasses.asdict(result)
    d["mode"] = result.mode.value
    d["outcome"] = result.outcome.value
    d["started_at"] = result.started_at.isoformat()
    d["ended_at"] = result.ended_at.isoformat()
    d["targets"] = list(result.targets)
    d["reverted"] = result.reverted
    return d


async def _run_one(scenario: FaultScenario, injector, probe, targets: list[str]) -> dict:
    harness = FaultInjectionHarness(
        injectors=[injector],
        probe=probe,
        operation_timeout_seconds=120.0,
        rollback_timeout_seconds=120.0,
        max_hold_seconds=180.0,
    )
    t0 = time.monotonic()
    try:
        res = await harness.run(scenario, approved_targets=targets, mode=Mode.ENFORCE)
        elapsed = time.monotonic() - t0
        payload = _serialize(res)
        payload["elapsed_seconds"] = round(elapsed, 2)
    except Exception as exc:  # noqa: BLE001 - report driver errors instead of crashing
        payload = {
            "scenario_id": scenario.scenario_id,
            "outcome": "driver_error",
            "error": f"{type(exc).__name__}:{exc}",
            "elapsed_seconds": round(time.monotonic() - t0, 2),
        }
    out = REPORT_ROOT / f"{scenario.scenario_id}.json"
    out.write_text(json.dumps(payload, indent=2, sort_keys=True))
    print(
        f"[{payload.get('outcome', '?')}] {scenario.scenario_id} "
        f"detected={payload.get('detected')} reverted={payload.get('reverted')} "
        f"elapsed={payload.get('elapsed_seconds')}s",
        flush=True,
    )
    return payload


async def main() -> int:
    print(f"report root: {REPORT_ROOT}", flush=True)
    runs = _build_runs()
    only = set(sys.argv[1:])
    if only:
        runs = [r for r in runs if r[0].scenario_id in only]
    all_reports: list[dict] = []
    for scenario, injector, probe, targets in runs:
        r = await _run_one(scenario, injector, probe, targets)
        all_reports.append(r)
        # Small breather between AKS-based runs so the analyzer doesn't
        # confuse two overlapping perturbations if any linger.
        await asyncio.sleep(10)

    summary = REPORT_ROOT / "report.json"
    summary.write_text(json.dumps({"runs": all_reports}, indent=2, sort_keys=True))

    md = ["# Enforce run summary", "", f"Report root: `{REPORT_ROOT}`", ""]
    md.append("| Scenario | Outcome | Detected | Reverted | Elapsed (s) | Error |")
    md.append("|----------|---------|----------|----------|-------------|-------|")
    for r in all_reports:
        md.append(
            f"| `{r.get('scenario_id')}` | {r.get('outcome')} | "
            f"{r.get('detected')} | {r.get('reverted')} | "
            f"{r.get('elapsed_seconds')} | {r.get('error') or ''} |"
        )
    (REPORT_ROOT / "summary.md").write_text("\n".join(md) + "\n")
    print(f"\nsummary written: {summary}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
