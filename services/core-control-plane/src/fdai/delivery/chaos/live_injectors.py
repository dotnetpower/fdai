"""Live (enforce) fault injectors + signal probes for the chaos harness.

These are the delivery-layer, **enforce-mode** counterparts of the upstream
shadow no-op :class:`~fdai.core.chaos.injector.ShadowFaultInjector`. Each
implements the core :class:`~fdai.core.chaos.injector.FaultInjector` /
:class:`~fdai.core.chaos.injector.SignalProbe` Protocol by shelling out to
``kubectl`` / ``az`` against an already-provisioned, already-approved test
substrate (e.g. ``rg-fdai-test``). ``core/`` never imports this module - it
is wired at a harness call site, exactly like any other delivery adapter.

Safety: every injector's ``stop`` is idempotent and reverses (or relies on
the ReplicaSet self-heal for) the perturbation, so the harness ``finally``
rollback holds. Targets are opaque label/selector handles the caller has
already scoped to the blast-radius-capped approved set.

This module is intentionally subprocess-based (not an SDK) so it stays a
thin, auditable shim over the exact commands an operator would run, and so
it carries no cloud SDK import into a hot path.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Mapping, Sequence
from typing import Final

_DEFAULT_TIMEOUT: Final[float] = 60.0


async def _run(
    cmd: Sequence[str],
    *,
    timeout: float = _DEFAULT_TIMEOUT,
    drop_azure_config_dir: bool = False,
) -> tuple[int, str, str]:
    """Run a subprocess, return (rc, stdout, stderr). Never shell=True."""

    env = None
    if drop_azure_config_dir:
        env = dict(os.environ)
        env.pop("AZURE_CONFIG_DIR", None)
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        raise
    return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")


# ---------------------------------------------------------------------------
# S1 - AKS pod kill  (fault_type="pod_kill", signal="pod_restart")
# ---------------------------------------------------------------------------


class KubectlPodKillInjector:
    """Delete one pod matching a label selector; the ReplicaSet self-heals."""

    fault_type = "pod_kill"

    def __init__(self, *, context: str, namespace: str, kubectl: str = "kubectl") -> None:
        self._ctx = context
        self._ns = namespace
        self._kubectl = kubectl

    def _base(self) -> list[str]:
        return [self._kubectl, "--context", self._ctx, "-n", self._ns]

    async def inject(self, *, target: str, params: Mapping[str, str]) -> None:
        rc, out, err = await _run(
            [*self._base(), "get", "pods", "-l", target, "-o", "jsonpath={.items[0].metadata.name}"]
        )
        pod = out.strip()
        if rc != 0 or not pod:
            raise RuntimeError(f"no pod for selector {target!r}: rc={rc} err={err.strip()}")
        grace = params.get("grace_period_seconds", "0")
        rc, _out, err = await _run([*self._base(), "delete", "pod", pod, f"--grace-period={grace}"])
        if rc != 0:
            raise RuntimeError(f"kubectl delete pod {pod} failed: {err.strip()}")

    async def stop(self, *, target: str) -> None:
        # The ReplicaSet reschedules the killed pod automatically; nothing to
        # undo. Idempotent by construction.
        return None


class KubeEventPodRestartProbe:
    """Observe a pod-restart signal from recent Kube events (Killing + create)."""

    def __init__(self, *, context: str, namespace: str, kubectl: str = "kubectl") -> None:
        self._ctx = context
        self._ns = namespace
        self._kubectl = kubectl

    async def observed(self, *, signal: str, targets: Sequence[str]) -> bool:
        rc, out, _err = await _run(
            [self._kubectl, "--context", self._ctx, "-n", self._ns, "get", "events", "-o", "json"]
        )
        if rc != 0:
            return False
        try:
            items = json.loads(out).get("items", [])
        except json.JSONDecodeError:
            return False
        reasons = {e.get("reason") for e in items}
        # A kill produces Killing on the old pod and SuccessfulCreate on the
        # ReplicaSet - the exact KubeEvents FDAI's event_ingest maps to
        # pod_restart.
        return "Killing" in reasons and "SuccessfulCreate" in reasons


# ---------------------------------------------------------------------------
# S12 - AKS bad deploy  (fault_type="bad_deploy", signal="rollout_stall")
# ---------------------------------------------------------------------------


class KubectlBadDeployInjector:
    """Set a deployment image to a non-existent tag; stop = rollout undo."""

    fault_type = "bad_deploy"

    def __init__(
        self,
        *,
        context: str,
        namespace: str,
        deployment: str,
        container: str,
        bad_image: str,
        kubectl: str = "kubectl",
    ) -> None:
        self._ctx = context
        self._ns = namespace
        self._deployment = deployment
        self._container = container
        self._bad_image = bad_image
        self._kubectl = kubectl

    def _base(self) -> list[str]:
        return [self._kubectl, "--context", self._ctx, "-n", self._ns]

    async def inject(self, *, target: str, params: Mapping[str, str]) -> None:
        rc, _out, err = await _run(
            [
                *self._base(),
                "set",
                "image",
                f"deployment/{self._deployment}",
                f"{self._container}={self._bad_image}",
            ]
        )
        if rc != 0:
            raise RuntimeError(f"kubectl set image failed: {err.strip()}")

    async def stop(self, *, target: str) -> None:
        # Reversible remediation: undo the rollout back to the last good spec.
        await _run([*self._base(), "rollout", "undo", f"deployment/{self._deployment}"])


class KubeRolloutStallProbe:
    """Observe a rollout-stall signal: an ImagePullBackOff/ErrImagePull pod."""

    def __init__(
        self,
        *,
        context: str,
        namespace: str,
        selector: str,
        kubectl: str = "kubectl",
    ) -> None:
        self._ctx = context
        self._ns = namespace
        self._selector = selector
        self._kubectl = kubectl

    async def observed(self, *, signal: str, targets: Sequence[str]) -> bool:
        rc, out, _err = await _run(
            [
                self._kubectl,
                "--context",
                self._ctx,
                "-n",
                self._ns,
                "get",
                "pods",
                "-l",
                self._selector,
                "-o",
                "json",
            ]
        )
        if rc != 0:
            return False
        try:
            items = json.loads(out).get("items", [])
        except json.JSONDecodeError:
            return False
        for pod in items:
            for cs in pod.get("status", {}).get("containerStatuses", []):
                waiting = cs.get("state", {}).get("waiting", {})
                if waiting.get("reason") in {"ImagePullBackOff", "ErrImagePull"}:
                    return True
        return False


# ---------------------------------------------------------------------------
# S5 - VM host CPU stress  (fault_type="host_cpu", signal="host_cpu")
# ---------------------------------------------------------------------------


class AzVmCpuStressInjector:
    """Run stress-ng on a VM via az run-command; stop = kill stress-ng."""

    fault_type = "vm_cpu_stress"

    def __init__(
        self,
        *,
        resource_group: str,
        vm_name: str,
        duration_seconds: int = 600,
        az: str = "az",
    ) -> None:
        self._rg = resource_group
        self._vm = vm_name
        self._duration = duration_seconds
        self._az = az

    async def _run_command(self, script: str) -> tuple[int, str, str]:
        return await _run(
            [
                self._az,
                "vm",
                "run-command",
                "invoke",
                "-g",
                self._rg,
                "-n",
                self._vm,
                "--command-id",
                "RunShellScript",
                "--scripts",
                script,
                "--query",
                "value[0].message",
                "-o",
                "tsv",
            ],
            timeout=180.0,
            drop_azure_config_dir=True,
        )

    async def inject(self, *, target: str, params: Mapping[str, str]) -> None:
        workers = params.get("cpu_workers", "0")  # 0 = all cores
        rc, _out, err = await self._run_command(
            "which stress-ng >/dev/null 2>&1 || (apt-get update -y -qq >/dev/null 2>&1 && "
            "apt-get install -y -qq stress-ng >/dev/null 2>&1); "
            f"setsid stress-ng --cpu {workers} --timeout {self._duration}s "
            ">/tmp/fdai-stress.log 2>&1 </dev/null & echo started; sleep 5"
        )
        if rc != 0:
            raise RuntimeError(f"az run-command stress inject failed: {err.strip()}")

    async def stop(self, *, target: str) -> None:
        await self._run_command("pkill -f stress-ng || true; echo stopped")


class AzureMonitorCpuProbe:
    """Observe host_cpu: VM Percentage CPU platform metric over a threshold."""

    def __init__(
        self,
        *,
        vm_resource_id: str,
        threshold_pct: float = 50.0,
        az: str = "az",
    ) -> None:
        self._vm_id = vm_resource_id
        self._threshold = threshold_pct
        self._az = az

    async def observed(self, *, signal: str, targets: Sequence[str]) -> bool:
        rc, out, _err = await _run(
            [
                self._az,
                "monitor",
                "metrics",
                "list",
                "--resource",
                self._vm_id,
                "--metric",
                "Percentage CPU",
                "--interval",
                "PT1M",
                "--aggregation",
                "Maximum",
                "--query",
                "value[0].timeseries[0].data[].maximum",
                "-o",
                "json",
            ],
            timeout=90.0,
            drop_azure_config_dir=True,
        )
        if rc != 0:
            return False
        try:
            values = [v for v in json.loads(out) if isinstance(v, (int, float))]
        except json.JSONDecodeError:
            return False
        return any(v >= self._threshold for v in values)


# ---------------------------------------------------------------------------
# S6 - VM memory stress  (fault_type="vm_mem_stress", signal="host_memory")
# ---------------------------------------------------------------------------


def _extract_int(message: str) -> int | None:
    """Pull the first integer out of an az run-command message body."""

    for token in message.replace("\n", " ").split():
        stripped = token.strip().strip(".,")
        if stripped.isdigit():
            return int(stripped)
    return None


class AzVmMemStressInjector:
    """Consume VM memory with stress-ng --vm; stop = kill stress-ng."""

    fault_type = "vm_mem_stress"

    def __init__(
        self,
        *,
        resource_group: str,
        vm_name: str,
        vm_bytes: str = "85%",
        duration_seconds: int = 300,
        az: str = "az",
    ) -> None:
        self._rg = resource_group
        self._vm = vm_name
        self._vm_bytes = vm_bytes
        self._duration = duration_seconds
        self._az = az

    async def _run_command(self, script: str) -> tuple[int, str, str]:
        return await _run(
            [
                self._az,
                "vm",
                "run-command",
                "invoke",
                "-g",
                self._rg,
                "-n",
                self._vm,
                "--command-id",
                "RunShellScript",
                "--scripts",
                script,
                "--query",
                "value[0].message",
                "-o",
                "tsv",
            ],
            timeout=180.0,
            drop_azure_config_dir=True,
        )

    async def inject(self, *, target: str, params: Mapping[str, str]) -> None:
        vm_bytes = params.get("vm_bytes", self._vm_bytes)
        rc, _out, err = await self._run_command(
            "which stress-ng >/dev/null 2>&1 || (apt-get update -y -qq >/dev/null 2>&1 && "
            "apt-get install -y -qq stress-ng >/dev/null 2>&1); "
            f"setsid stress-ng --vm 1 --vm-bytes {vm_bytes} --vm-keep --timeout "
            f"{self._duration}s >/tmp/fdai-memstress.log 2>&1 </dev/null & echo started; sleep 6"
        )
        if rc != 0:
            raise RuntimeError(f"az run-command mem-stress inject failed: {err.strip()}")

    async def stop(self, *, target: str) -> None:
        await self._run_command("pkill -f stress-ng || true; echo stopped")


class AzVmMemProbe:
    """Observe host_memory: available memory (MB) fell below a threshold."""

    def __init__(
        self,
        *,
        resource_group: str,
        vm_name: str,
        min_available_mb: int = 250,
        az: str = "az",
    ) -> None:
        self._rg = resource_group
        self._vm = vm_name
        self._min = min_available_mb
        self._az = az

    async def observed(self, *, signal: str, targets: Sequence[str]) -> bool:
        rc, out, _err = await _run(
            [
                self._az,
                "vm",
                "run-command",
                "invoke",
                "-g",
                self._rg,
                "-n",
                self._vm,
                "--command-id",
                "RunShellScript",
                "--scripts",
                "free -m | awk '/Mem:/ {print $7}'",
                "--query",
                "value[0].message",
                "-o",
                "tsv",
            ],
            timeout=120.0,
            drop_azure_config_dir=True,
        )
        if rc != 0:
            return False
        available = _extract_int(out)
        return available is not None and available < self._min


# ---------------------------------------------------------------------------
# S11 - backend failure  (fault_type="pod_kill", signal="backend_health")
# ---------------------------------------------------------------------------


class KubectlBackendDownInjector:
    """Scale a backend deployment to 0 (all endpoints down); stop = restore."""

    fault_type = "pod_kill"

    def __init__(
        self,
        *,
        context: str,
        namespace: str,
        deployment: str,
        restore_replicas: int,
        kubectl: str = "kubectl",
    ) -> None:
        self._ctx = context
        self._ns = namespace
        self._deployment = deployment
        self._restore = restore_replicas
        self._kubectl = kubectl

    def _base(self) -> list[str]:
        return [self._kubectl, "--context", self._ctx, "-n", self._ns]

    async def inject(self, *, target: str, params: Mapping[str, str]) -> None:
        rc, _out, err = await _run(
            [*self._base(), "scale", f"deployment/{self._deployment}", "--replicas=0"]
        )
        if rc != 0:
            raise RuntimeError(f"scale backend down failed: {err.strip()}")

    async def stop(self, *, target: str) -> None:
        await _run(
            [
                *self._base(),
                "scale",
                f"deployment/{self._deployment}",
                f"--replicas={self._restore}",
            ]
        )


class KubeBackendHealthProbe:
    """Observe backend_health: the service has zero ready endpoints."""

    def __init__(
        self,
        *,
        context: str,
        namespace: str,
        service: str,
        kubectl: str = "kubectl",
    ) -> None:
        self._ctx = context
        self._ns = namespace
        self._service = service
        self._kubectl = kubectl

    async def observed(self, *, signal: str, targets: Sequence[str]) -> bool:
        rc, out, _err = await _run(
            [
                self._kubectl,
                "--context",
                self._ctx,
                "-n",
                self._ns,
                "get",
                "endpoints",
                self._service,
                "-o",
                "json",
            ]
        )
        if rc != 0:
            return False
        try:
            subsets = json.loads(out).get("subsets") or []
        except json.JSONDecodeError:
            return False
        ready = sum(len(s.get("addresses") or []) for s in subsets)
        return ready == 0


__all__ = [
    "AzVmCpuStressInjector",
    "AzVmMemProbe",
    "AzVmMemStressInjector",
    "AzureMonitorCpuProbe",
    "KubeBackendHealthProbe",
    "KubeEventPodRestartProbe",
    "KubeRolloutStallProbe",
    "KubectlBackendDownInjector",
    "KubectlBadDeployInjector",
    "KubectlPodKillInjector",
]
