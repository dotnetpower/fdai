"""Namespace-scoped Kubernetes evidence for external evaluation tasks."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Final

from fdai_evaluation_sdk import EvaluationTask

from fdai.evaluation.evidence import EvaluationEvidenceProvider

CommandRunner = Callable[[tuple[str, ...]], Awaitable[bytes]]
_DNS_SUBDOMAIN: Final = re.compile(
    r"^[a-z0-9](?:[-a-z0-9]*[a-z0-9])?(?:\.[a-z0-9](?:[-a-z0-9]*[a-z0-9])?)*$"
)
_INVENTORY_RESOURCES: Final = "deployments,statefulsets,daemonsets,pods,services,endpoints"
_CPU_QUANTITY: Final = re.compile(r"^(?P<value>[0-9]+(?:\.[0-9]+)?)(?P<unit>n|u|m)?$")
_MEMORY_QUANTITY: Final = re.compile(
    r"^(?P<value>[0-9]+(?:\.[0-9]+)?)(?P<unit>Ki|Mi|Gi|Ti|Pi|Ei)?$"
)
_CPU_TO_MILLICORES: Final = {
    "n": Decimal("0.000001"),
    "u": Decimal("0.001"),
    "m": Decimal("1"),
    "": Decimal("1000"),
}
_MEMORY_TO_BYTES: Final = {
    "Ki": 1_024,
    "Mi": 1_048_576,
    "Gi": 1_073_741_824,
    "Ti": 1_099_511_627_776,
    "Pi": 1_125_899_906_842_624,
    "Ei": 1_152_921_504_606_846_976,
    "": 1,
}


@dataclass(frozen=True, slots=True)
class KubectlEvidenceConfig:
    """Immutable connection and read ceilings for one Kubernetes context."""

    kubeconfig: Path
    context: str
    cluster_name: str
    allowed_namespaces: frozenset[str]
    timeout_seconds: float = 15.0
    max_output_bytes: int = 4_194_304
    max_items: int = 500

    def __post_init__(self) -> None:
        if not self.kubeconfig.is_file():
            raise ValueError("evaluation kubeconfig MUST reference an existing file")
        if not self.context.strip() or not self.cluster_name.strip():
            raise ValueError("evaluation Kubernetes context and cluster name MUST not be empty")
        if not self.allowed_namespaces:
            raise ValueError("evaluation Kubernetes namespace scope MUST not be empty")
        if any(not _valid_namespace(item) for item in self.allowed_namespaces):
            raise ValueError("evaluation Kubernetes namespace scope is invalid")
        if not 1.0 <= self.timeout_seconds <= 30.0:
            raise ValueError("evaluation kubectl timeout MUST be between 1 and 30 seconds")
        if not 1_024 <= self.max_output_bytes <= 16_777_216:
            raise ValueError("evaluation kubectl output limit MUST be between 1 KiB and 16 MiB")
        if not 1 <= self.max_items <= 2_000:
            raise ValueError("evaluation kubectl item limit MUST be between 1 and 2000")


class KubectlEvidenceClient:
    """Run fixed read-only kubectl queries against one explicit context."""

    def __init__(
        self,
        *,
        config: KubectlEvidenceConfig,
        run: CommandRunner | None = None,
    ) -> None:
        self._config = config
        self._run = run or self._run_command

    async def inventory(self, task: EvaluationTask) -> Mapping[str, Any]:
        namespace = self._namespace(task)
        payload = await self._get_json(namespace, _INVENTORY_RESOURCES)
        items = _items(payload)
        selected = items[: self._config.max_items]
        return {
            "cluster": self._config.cluster_name,
            "namespace": namespace,
            "resources": [
                projection
                for item in selected
                if isinstance(item, Mapping) and (projection := _project_resource(item)) is not None
            ],
            "truncated": len(items) > len(selected),
        }

    async def events(self, task: EvaluationTask) -> Mapping[str, Any]:
        namespace = self._namespace(task)
        payload = await self._get_json(namespace, "events")
        items = _items(payload)
        selected = items[-self._config.max_items :]
        return {
            "cluster": self._config.cluster_name,
            "namespace": namespace,
            "events": [
                projection
                for item in selected
                if isinstance(item, Mapping) and (projection := _project_event(item)) is not None
            ],
            "truncated": len(items) > len(selected),
        }

    async def pod_metrics(self, task: EvaluationTask) -> Mapping[str, Any]:
        namespace = self._namespace(task)
        path = f"/apis/metrics.k8s.io/v1beta1/namespaces/{namespace}/pods"
        payload = await self._get_raw_json(namespace, path)
        items = _items(payload)
        selected = items[: self._config.max_items]
        return {
            "cluster": self._config.cluster_name,
            "namespace": namespace,
            "pods": [
                projection
                for item in selected
                if isinstance(item, Mapping)
                and (projection := _project_pod_metric(item)) is not None
            ],
            "truncated": len(items) > len(selected),
        }

    def _namespace(self, task: EvaluationTask) -> str:
        if task.target.kind != "kubernetes.namespace":
            raise ValueError("kubectl evidence requires a kubernetes.namespace target")
        namespace = task.target.value
        if namespace not in self._config.allowed_namespaces:
            raise ValueError("evaluation task namespace is outside the configured scope")
        return namespace

    async def _get_json(self, namespace: str, resources: str) -> Mapping[str, Any]:
        command = (
            "kubectl",
            "--kubeconfig",
            str(self._config.kubeconfig),
            "--context",
            self._config.context,
            "--namespace",
            namespace,
            "get",
            resources,
            "--output",
            "json",
            f"--request-timeout={self._config.timeout_seconds:g}s",
        )
        return await self._run_json(command)

    async def _get_raw_json(self, namespace: str, path: str) -> Mapping[str, Any]:
        command = (
            "kubectl",
            "--kubeconfig",
            str(self._config.kubeconfig),
            "--context",
            self._config.context,
            "--namespace",
            namespace,
            "get",
            "--raw",
            path,
            f"--request-timeout={self._config.timeout_seconds:g}s",
        )
        return await self._run_json(command)

    async def _run_json(self, command: tuple[str, ...]) -> Mapping[str, Any]:
        raw = await self._run(command)
        if len(raw) > self._config.max_output_bytes:
            raise RuntimeError("kubectl evidence response exceeded the configured limit")
        try:
            payload = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("kubectl returned invalid evidence JSON") from exc
        if not isinstance(payload, Mapping):
            raise RuntimeError("kubectl returned an invalid evidence payload")
        return payload

    async def _run_command(self, command: tuple[str, ...]) -> bytes:
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("kubectl executable is unavailable") from exc
        if process.stdout is None:  # pragma: no cover - asyncio contract guard
            raise RuntimeError("kubectl stdout pipe is unavailable")
        output = bytearray()
        try:
            async with asyncio.timeout(self._config.timeout_seconds):
                while chunk := await process.stdout.read(65_536):
                    output.extend(chunk)
                    if len(output) > self._config.max_output_bytes:
                        process.kill()
                        await process.wait()
                        raise RuntimeError(
                            "kubectl evidence response exceeded the configured limit"
                        )
                return_code = await process.wait()
        except TimeoutError as exc:
            if process.returncode is None:
                process.kill()
                await process.wait()
            raise RuntimeError("kubectl evidence query timed out") from exc
        except BaseException:
            if process.returncode is None:
                process.kill()
                await process.wait()
            raise
        if return_code != 0:
            raise RuntimeError("kubectl evidence query failed")
        return bytes(output)


@dataclass(frozen=True, slots=True)
class KubectlInventoryEvidenceProvider:
    client: KubectlEvidenceClient

    async def collect(self, task: EvaluationTask) -> Mapping[str, Any]:
        return await self.client.inventory(task)


@dataclass(frozen=True, slots=True)
class KubectlEventEvidenceProvider:
    client: KubectlEvidenceClient

    async def collect(self, task: EvaluationTask) -> Mapping[str, Any]:
        return await self.client.events(task)


@dataclass(frozen=True, slots=True)
class KubectlPodMetricEvidenceProvider:
    client: KubectlEvidenceClient

    async def collect(self, task: EvaluationTask) -> Mapping[str, Any]:
        return await self.client.pod_metrics(task)


def kubernetes_evidence_providers(
    client: KubectlEvidenceClient,
) -> Mapping[str, EvaluationEvidenceProvider]:
    """Return provider bindings for the supported semantic capabilities."""

    return {
        "observe.kubernetes.inventory": KubectlInventoryEvidenceProvider(client),
        "observe.kubernetes.events": KubectlEventEvidenceProvider(client),
        "observe.metrics.query": KubectlPodMetricEvidenceProvider(client),
    }


def _items(payload: Mapping[str, Any]) -> list[Any]:
    items = payload.get("items")
    if not isinstance(items, list):
        raise RuntimeError("kubectl evidence payload has no item list")
    return items


def _project_resource(item: Mapping[str, Any]) -> dict[str, Any] | None:
    kind = item.get("kind")
    metadata = item.get("metadata")
    if not isinstance(kind, str) or not isinstance(metadata, Mapping):
        return None
    name = metadata.get("name")
    namespace = metadata.get("namespace")
    if not isinstance(name, str) or not isinstance(namespace, str):
        return None
    projected: dict[str, Any] = {"kind": kind, "name": name, "namespace": namespace}
    spec = item.get("spec")
    status = item.get("status")
    spec_values = spec if isinstance(spec, Mapping) else {}
    status_values = status if isinstance(status, Mapping) else {}
    if kind in {"Deployment", "StatefulSet"}:
        projected.update(
            desired=_count(spec_values.get("replicas")),
            ready=_count(status_values.get("readyReplicas")),
            available=_count(status_values.get("availableReplicas")),
            updated=_count(status_values.get("updatedReplicas")),
        )
    elif kind == "DaemonSet":
        projected.update(
            desired=_count(status_values.get("desiredNumberScheduled")),
            ready=_count(status_values.get("numberReady")),
            unavailable=_count(status_values.get("numberUnavailable")),
        )
    elif kind == "Pod":
        statuses = status_values.get("containerStatuses")
        container_statuses = statuses if isinstance(statuses, list) else []
        projected.update(
            phase=_text(status_values.get("phase"), 64),
            node=_text(spec_values.get("nodeName"), 253),
            deleting=metadata.get("deletionTimestamp") is not None,
            containers=[
                _project_container_status(value)
                for value in container_statuses
                if isinstance(value, Mapping)
            ],
        )
    elif kind == "Service":
        selector = spec_values.get("selector")
        projected.update(
            service_type=_text(spec_values.get("type"), 64),
            selector=dict(selector) if isinstance(selector, Mapping) else {},
        )
    elif kind == "Endpoints":
        subsets = item.get("subsets")
        subset_values = subsets if isinstance(subsets, list) else []
        projected.update(
            ready_addresses=sum(_list_size(value, "addresses") for value in subset_values),
            not_ready_addresses=sum(
                _list_size(value, "notReadyAddresses") for value in subset_values
            ),
        )
    else:
        return None
    return projected


def _project_container_status(value: Mapping[str, Any]) -> dict[str, Any]:
    state = value.get("state")
    state_values = state if isinstance(state, Mapping) else {}
    state_name = next(
        (name for name in ("waiting", "running", "terminated") if name in state_values),
        "unknown",
    )
    detail = state_values.get(state_name)
    detail_values = detail if isinstance(detail, Mapping) else {}
    projection: dict[str, Any] = {
        "name": _text(value.get("name"), 253),
        "ready": value.get("ready") is True,
        "restarts": _count(value.get("restartCount")),
        "state": state_name,
        "reason": _text(detail_values.get("reason"), 256),
    }
    last_state = value.get("lastState")
    last_state_values = last_state if isinstance(last_state, Mapping) else {}
    last_termination = last_state_values.get("terminated")
    if isinstance(last_termination, Mapping):
        projection["last_termination"] = {
            "reason": _text(last_termination.get("reason"), 256),
            "exit_code": _count(last_termination.get("exitCode")),
            "finished_at": _text(last_termination.get("finishedAt"), 64),
        }
    return projection


def _project_event(item: Mapping[str, Any]) -> dict[str, Any] | None:
    metadata = item.get("metadata")
    involved = item.get("involvedObject")
    if not isinstance(metadata, Mapping) or not isinstance(involved, Mapping):
        return None
    name = metadata.get("name")
    namespace = metadata.get("namespace")
    if not isinstance(name, str) or not isinstance(namespace, str):
        return None
    return {
        "name": name,
        "namespace": namespace,
        "type": _text(item.get("type"), 64),
        "reason": _text(item.get("reason"), 256),
        "message": _text(item.get("message"), 1_024),
        "count": _count(item.get("count")),
        "last_seen": _text(
            item.get("eventTime") or item.get("lastTimestamp") or metadata.get("creationTimestamp"),
            64,
        ),
        "regarding": {
            "kind": _text(involved.get("kind"), 128),
            "name": _text(involved.get("name"), 253),
        },
    }


def _project_pod_metric(item: Mapping[str, Any]) -> dict[str, Any] | None:
    metadata = item.get("metadata")
    containers = item.get("containers")
    if not isinstance(metadata, Mapping) or not isinstance(containers, list):
        return None
    name = metadata.get("name")
    namespace = metadata.get("namespace")
    if not isinstance(name, str) or not isinstance(namespace, str):
        return None
    return {
        "name": name,
        "namespace": namespace,
        "containers": [
            projection
            for value in containers
            if isinstance(value, Mapping)
            and (projection := _project_container_metric(value)) is not None
        ],
    }


def _project_container_metric(value: Mapping[str, Any]) -> dict[str, Any] | None:
    name = value.get("name")
    usage = value.get("usage")
    if not isinstance(name, str) or not isinstance(usage, Mapping):
        return None
    return {
        "name": name,
        "cpu_millicores": _cpu_millicores(usage.get("cpu")),
        "memory_bytes": _memory_bytes(usage.get("memory")),
    }


def _cpu_millicores(value: object) -> float:
    match = _CPU_QUANTITY.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        raise RuntimeError("kubectl returned an invalid Kubernetes CPU quantity")
    try:
        quantity = Decimal(match.group("value")) * _CPU_TO_MILLICORES[match.group("unit") or ""]
    except (InvalidOperation, KeyError) as exc:
        raise RuntimeError("kubectl returned an invalid Kubernetes CPU quantity") from exc
    return float(quantity)


def _memory_bytes(value: object) -> int:
    match = _MEMORY_QUANTITY.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        raise RuntimeError("kubectl returned an invalid Kubernetes memory quantity")
    try:
        quantity = Decimal(match.group("value")) * _MEMORY_TO_BYTES[match.group("unit") or ""]
    except (InvalidOperation, KeyError) as exc:
        raise RuntimeError("kubectl returned an invalid Kubernetes memory quantity") from exc
    return int(quantity)


def _valid_namespace(value: str) -> bool:
    return 1 <= len(value) <= 253 and _DNS_SUBDOMAIN.fullmatch(value) is not None


def _count(value: object) -> int:
    return value if isinstance(value, int) and value >= 0 else 0


def _text(value: object, limit: int) -> str:
    return value[:limit] if isinstance(value, str) else ""


def _list_size(value: object, key: str) -> int:
    if not isinstance(value, Mapping):
        return 0
    items = value.get(key)
    return len(items) if isinstance(items, list) else 0


__all__ = [
    "KubectlEventEvidenceProvider",
    "KubectlEvidenceClient",
    "KubectlEvidenceConfig",
    "KubectlInventoryEvidenceProvider",
    "KubectlPodMetricEvidenceProvider",
    "kubernetes_evidence_providers",
]
