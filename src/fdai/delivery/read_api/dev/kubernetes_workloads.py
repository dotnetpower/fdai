"""Explicitly scoped Kubernetes workload evidence for the local read API."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

KUBECONFIG_ENV: Final = "FDAI_LOCAL_KUBECONFIG"
KUBERNETES_CONTEXT_ENV: Final = "FDAI_LOCAL_KUBERNETES_CONTEXT"
KUBERNETES_CLUSTER_ENV: Final = "FDAI_LOCAL_KUBERNETES_CLUSTER_NAME"
_MAX_OUTPUT_BYTES: Final = 4 * 1024 * 1024
CommandRunner = Callable[[tuple[str, ...]], Awaitable[str]]


@dataclass(frozen=True, slots=True)
class KubectlWorkloadConfig:
    kubeconfig: Path
    context: str
    cluster_name: str
    timeout_seconds: float = 15.0
    max_items: int = 200

    def __post_init__(self) -> None:
        if not self.kubeconfig.is_file():
            raise ValueError("FDAI_LOCAL_KUBECONFIG MUST reference an existing file")
        if not self.context.strip():
            raise ValueError("FDAI_LOCAL_KUBERNETES_CONTEXT MUST not be empty")
        if not self.cluster_name.strip():
            raise ValueError("FDAI_LOCAL_KUBERNETES_CLUSTER_NAME MUST not be empty")
        if not 1.0 <= self.timeout_seconds <= 30.0:
            raise ValueError("kubectl workload timeout MUST be between 1 and 30 seconds")
        if not 1 <= self.max_items <= 500:
            raise ValueError("kubectl workload max_items MUST be between 1 and 500")


class KubectlWorkloadProvider:
    """Read bounded Deployment and Pod state from one configured context."""

    def __init__(self, *, config: KubectlWorkloadConfig, run: CommandRunner | None = None) -> None:
        self._config = config
        self._run = run or self._run_command

    async def __call__(self) -> Mapping[str, Any]:
        command = (
            "kubectl",
            "--kubeconfig",
            str(self._config.kubeconfig),
            "--context",
            self._config.context,
            "get",
            "deployments,pods",
            "--all-namespaces",
            "--output",
            "json",
        )
        raw = await self._run(command)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError("kubectl returned invalid workload JSON") from exc
        if not isinstance(payload, Mapping) or not isinstance(payload.get("items"), list):
            raise RuntimeError("kubectl returned an invalid workload payload")
        items = payload["items"]
        selected = items[: self._config.max_items]
        deployments = [
            projected
            for item in selected
            if isinstance(item, Mapping) and (projected := _project_deployment(item)) is not None
        ]
        pods = [
            projected
            for item in selected
            if isinstance(item, Mapping) and (projected := _project_pod(item)) is not None
        ]
        return {
            "status": "matched",
            "cluster_name": self._config.cluster_name,
            "source": "kubernetes_apiserver",
            "observed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "deployments": deployments,
            "pods": pods,
            "truncated": len(items) > len(selected),
        }

    async def _run_command(self, command: tuple[str, ...]) -> str:
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("kubectl executable is unavailable") from exc
        try:
            async with asyncio.timeout(self._config.timeout_seconds):
                stdout, _stderr = await process.communicate()
        except TimeoutError as exc:
            process.kill()
            await process.wait()
            raise RuntimeError("kubectl workload query timed out") from exc
        if process.returncode != 0:
            raise RuntimeError("kubectl workload query failed")
        if len(stdout) > _MAX_OUTPUT_BYTES:
            raise RuntimeError("kubectl workload response exceeded the size limit")
        return stdout.decode("utf-8")


def kubectl_workload_provider_from_env(
    environ: Mapping[str, str],
) -> KubectlWorkloadProvider | None:
    values = {
        KUBECONFIG_ENV: environ.get(KUBECONFIG_ENV, "").strip(),
        KUBERNETES_CONTEXT_ENV: environ.get(KUBERNETES_CONTEXT_ENV, "").strip(),
        KUBERNETES_CLUSTER_ENV: environ.get(KUBERNETES_CLUSTER_ENV, "").strip(),
    }
    if not any(values.values()):
        return None
    if not all(values.values()):
        raise ValueError(
            "FDAI_LOCAL_KUBECONFIG, FDAI_LOCAL_KUBERNETES_CONTEXT, and "
            "FDAI_LOCAL_KUBERNETES_CLUSTER_NAME must be configured together"
        )
    return KubectlWorkloadProvider(
        config=KubectlWorkloadConfig(
            kubeconfig=Path(values[KUBECONFIG_ENV]).expanduser().resolve(),
            context=values[KUBERNETES_CONTEXT_ENV],
            cluster_name=values[KUBERNETES_CLUSTER_ENV],
        )
    )


def _project_deployment(item: Mapping[str, Any]) -> dict[str, Any] | None:
    if item.get("kind") != "Deployment":
        return None
    metadata = item.get("metadata")
    spec = item.get("spec")
    status = item.get("status")
    if not isinstance(metadata, Mapping):
        return None
    name = metadata.get("name")
    namespace = metadata.get("namespace")
    if not isinstance(name, str) or not isinstance(namespace, str):
        return None
    spec_values = spec if isinstance(spec, Mapping) else {}
    status_values = status if isinstance(status, Mapping) else {}
    return {
        "namespace": namespace,
        "name": name,
        "desired": _nonnegative_int(spec_values.get("replicas")),
        "ready": _nonnegative_int(status_values.get("readyReplicas")),
        "available": _nonnegative_int(status_values.get("availableReplicas")),
    }


def _project_pod(item: Mapping[str, Any]) -> dict[str, Any] | None:
    if item.get("kind") != "Pod":
        return None
    metadata = item.get("metadata")
    status = item.get("status")
    if not isinstance(metadata, Mapping) or not isinstance(status, Mapping):
        return None
    name = metadata.get("name")
    namespace = metadata.get("namespace")
    if not isinstance(name, str) or not isinstance(namespace, str):
        return None
    raw_statuses = status.get("containerStatuses")
    container_statuses = raw_statuses if isinstance(raw_statuses, list) else []
    return {
        "namespace": namespace,
        "name": name,
        "phase": str(status.get("phase") or "Unknown"),
        "ready": sum(
            1
            for container_status in container_statuses
            if isinstance(container_status, Mapping) and container_status.get("ready") is True
        ),
        "containers": len(container_statuses),
    }


def _nonnegative_int(value: object) -> int:
    return value if isinstance(value, int) and value >= 0 else 0


__all__ = [
    "KUBECONFIG_ENV",
    "KUBERNETES_CLUSTER_ENV",
    "KUBERNETES_CONTEXT_ENV",
    "KubectlWorkloadConfig",
    "KubectlWorkloadProvider",
    "kubectl_workload_provider_from_env",
]
