"""Namespace-scoped Kubernetes evidence for external evaluation tasks."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from fdai_evaluation_sdk import EvaluationTask

from fdai.delivery.evaluation.diagnostic_functions import DiagnosticFunctionExecutor
from fdai.delivery.evaluation.kubernetes_evidence_projection import (
    _add_admission_conditions as _add_admission_conditions,
)
from fdai.delivery.evaluation.kubernetes_evidence_projection import (
    _bounded_strings as _bounded_strings,
)
from fdai.delivery.evaluation.kubernetes_evidence_projection import (
    _count as _count,
)
from fdai.delivery.evaluation.kubernetes_evidence_projection import (
    _image_reference_sha256 as _image_reference_sha256,
)
from fdai.delivery.evaluation.kubernetes_evidence_projection import (
    _items as _items,
)
from fdai.delivery.evaluation.kubernetes_evidence_projection import (
    _list_size as _list_size,
)
from fdai.delivery.evaluation.kubernetes_evidence_projection import (
    _node_ready as _node_ready,
)
from fdai.delivery.evaluation.kubernetes_evidence_projection import (
    _project_admission_condition as _project_admission_condition,
)
from fdai.delivery.evaluation.kubernetes_evidence_projection import (
    _project_admission_rule as _project_admission_rule,
)
from fdai.delivery.evaluation.kubernetes_evidence_projection import (
    _project_container_metric as _project_container_metric,
)
from fdai.delivery.evaluation.kubernetes_evidence_projection import (
    _project_container_resources as _project_container_resources,
)
from fdai.delivery.evaluation.kubernetes_evidence_projection import (
    _project_container_status as _project_container_status,
)
from fdai.delivery.evaluation.kubernetes_evidence_projection import (
    _project_endpoint_env as _project_endpoint_env,
)
from fdai.delivery.evaluation.kubernetes_evidence_projection import (
    _project_event as _project_event,
)
from fdai.delivery.evaluation.kubernetes_evidence_projection import (
    _project_host_ports as _project_host_ports,
)
from fdai.delivery.evaluation.kubernetes_evidence_projection import (
    _project_label_selector as _project_label_selector,
)
from fdai.delivery.evaluation.kubernetes_evidence_projection import (
    _project_labels as _project_labels,
)
from fdai.delivery.evaluation.kubernetes_evidence_projection import (
    _project_namespace_selector as _project_namespace_selector,
)
from fdai.delivery.evaluation.kubernetes_evidence_projection import (
    _project_node as _project_node,
)
from fdai.delivery.evaluation.kubernetes_evidence_projection import (
    _project_owner_reference as _project_owner_reference,
)
from fdai.delivery.evaluation.kubernetes_evidence_projection import (
    _project_owner_references as _project_owner_references,
)
from fdai.delivery.evaluation.kubernetes_evidence_projection import (
    _project_pod_metric as _project_pod_metric,
)
from fdai.delivery.evaluation.kubernetes_evidence_projection import (
    _project_pod_resource_spec as _project_pod_resource_spec,
)
from fdai.delivery.evaluation.kubernetes_evidence_projection import (
    _project_pod_template as _project_pod_template,
)
from fdai.delivery.evaluation.kubernetes_evidence_projection import (
    _project_probe as _project_probe,
)
from fdai.delivery.evaluation.kubernetes_evidence_projection import (
    _project_resource as _project_resource,
)
from fdai.delivery.evaluation.kubernetes_evidence_projection import (
    _project_resource_container as _project_resource_container,
)
from fdai.delivery.evaluation.kubernetes_evidence_projection import (
    _project_selector_presence as _project_selector_presence,
)
from fdai.delivery.evaluation.kubernetes_evidence_projection import (
    _project_template_container as _project_template_container,
)
from fdai.delivery.evaluation.kubernetes_evidence_projection import (
    _project_webhook as _project_webhook,
)
from fdai.delivery.evaluation.kubernetes_evidence_projection import (
    _project_webhook_configuration as _project_webhook_configuration,
)
from fdai.delivery.evaluation.kubernetes_evidence_projection import (
    _project_webhook_service as _project_webhook_service,
)
from fdai.delivery.evaluation.kubernetes_evidence_projection import (
    _text as _text,
)
from fdai.delivery.evaluation.kubernetes_evidence_projection import (
    _valid_condition_shape as _valid_condition_shape,
)
from fdai.delivery.kubernetes.owners import CustomOwnerQuery, project_custom_owner
from fdai.evaluation.evidence import EvaluationEvidenceProvider

CommandRunner = Callable[[tuple[str, ...]], Awaitable[bytes]]


def _utc_now() -> datetime:
    return datetime.now(UTC)


_DNS_SUBDOMAIN: Final = re.compile(
    r"^[a-z0-9](?:[-a-z0-9]*[a-z0-9])?(?:\.[a-z0-9](?:[-a-z0-9]*[a-z0-9])?)*$"
)
_DNS_LABEL: Final = re.compile(r"^[a-z0-9](?:[-a-z0-9]*[a-z0-9])?$")
_INVENTORY_RESOURCES: Final = (
    "deployments,statefulsets,daemonsets,replicasets,pods,services,endpoints"
)


@dataclass(frozen=True, slots=True)
class KubectlEvidenceConfig:
    """Immutable connection and read ceilings for one Kubernetes context."""

    kubeconfig: Path
    context: str
    cluster_name: str
    cluster_identity: str
    allowed_namespaces: frozenset[str]
    timeout_seconds: float = 15.0
    max_output_bytes: int = 4_194_304
    max_items: int = 500

    def __post_init__(self) -> None:
        if not self.kubeconfig.is_file():
            raise ValueError("evaluation kubeconfig MUST reference an existing file")
        if not self.context.strip() or not self.cluster_name.strip():
            raise ValueError("evaluation Kubernetes context and cluster name MUST not be empty")
        if re.fullmatch(r"sha256:[0-9a-f]{64}", self.cluster_identity) is None:
            raise ValueError("evaluation Kubernetes cluster identity MUST be SHA-256")
        if not self.allowed_namespaces:
            raise ValueError("evaluation Kubernetes namespace scope MUST not be empty")
        if any(not _valid_namespace(item) for item in self.allowed_namespaces):
            raise ValueError("evaluation Kubernetes namespace scope is invalid")
        if not 1.0 <= self.timeout_seconds <= 30.0:
            raise ValueError("evaluation kubectl timeout MUST be between 1 and 30 seconds")
        if not 1_024 <= self.max_output_bytes <= 16_777_216:
            raise ValueError("evaluation kubectl output limit MUST be between 1 KiB and 16 MiB")
        if not 1 <= self.max_items <= 1_000:
            raise ValueError("evaluation kubectl item limit MUST be between 1 and 1000")


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
        resources = [
            projection
            for item in selected
            if isinstance(item, Mapping) and (projection := _project_resource(item)) is not None
        ]
        projection_complete = len(resources) == len(selected) and all(
            isinstance(resource.get("uid"), str) and bool(str(resource["uid"]).strip())
            for resource in resources
        )
        return {
            "cluster": self._config.cluster_identity,
            "namespace": namespace,
            "resources": resources,
            "projection_complete": projection_complete,
            "truncated": len(items) > len(selected) or not projection_complete,
        }

    async def events(self, task: EvaluationTask) -> Mapping[str, Any]:
        namespace = self._namespace(task)
        payload = await self._get_json(namespace, "events")
        items = _items(payload)
        selected = items[-self._config.max_items :]
        events = [
            projection
            for item in selected
            if isinstance(item, Mapping) and (projection := _project_event(item)) is not None
        ]
        projection_complete = len(events) == len(selected)
        return {
            "cluster": self._config.cluster_identity,
            "namespace": namespace,
            "events": events,
            "projection_complete": projection_complete,
            "truncated": len(items) > len(selected) or not projection_complete,
        }

    async def pod_metrics(self, task: EvaluationTask) -> Mapping[str, Any]:
        namespace = self._namespace(task)
        path = f"/apis/metrics.k8s.io/v1beta1/namespaces/{namespace}/pods"
        payload = await self._get_raw_json(namespace, path)
        items = _items(payload)
        selected = items[: self._config.max_items]
        pods = [
            projection
            for item in selected
            if isinstance(item, Mapping) and (projection := _project_pod_metric(item)) is not None
        ]
        projection_complete = len(pods) == len(selected)
        return {
            "cluster": self._config.cluster_identity,
            "namespace": namespace,
            "pods": pods,
            "projection_complete": projection_complete,
            "truncated": len(items) > len(selected) or not projection_complete,
        }

    async def nodes(self, task: EvaluationTask) -> Mapping[str, Any]:
        self._namespace(task)
        payload = await self._get_cluster_json("nodes")
        items = _items(payload)
        selected = items[: self._config.max_items]
        nodes = [
            projection
            for item in selected
            if isinstance(item, Mapping) and (projection := _project_node(item)) is not None
        ]
        projection_complete = len(nodes) == len(selected)
        return {
            "cluster": self._config.cluster_identity,
            "nodes": nodes,
            "projection_complete": projection_complete,
            "truncated": len(items) > len(selected) or not projection_complete,
        }

    async def admission_configurations(self, task: EvaluationTask) -> Mapping[str, Any]:
        self._namespace(task)
        payload = await self._get_cluster_json(
            "mutatingwebhookconfigurations,validatingwebhookconfigurations"
        )
        items = _items(payload)
        selected = items[: self._config.max_items]
        resources = [
            projection
            for item in selected
            if isinstance(item, Mapping)
            and (projection := _project_webhook_configuration(item)) is not None
        ]
        projection_complete = len(resources) == len(selected)
        return {
            "cluster": self._config.cluster_identity,
            "resources": resources,
            "projection_complete": projection_complete,
            "truncated": len(items) > len(selected) or not projection_complete,
        }

    async def webhook_service(
        self,
        task: EvaluationTask,
        *,
        namespace: str,
        name: str,
    ) -> Mapping[str, Any]:
        self._namespace(task)
        if namespace not in self._config.allowed_namespaces or not _DNS_SUBDOMAIN.fullmatch(name):
            raise RuntimeError("webhook Service is outside the configured scope")
        command = (
            "kubectl",
            "--kubeconfig",
            str(self._config.kubeconfig),
            "--context",
            self._config.context,
            "--namespace",
            namespace,
            "get",
            f"service/{name}",
            "--ignore-not-found",
            "--output",
            "json",
            f"--request-timeout={self._config.timeout_seconds:g}s",
        )
        raw = await self._run(command)
        if not raw:
            return {"namespace": namespace, "name": name, "status": "confirmed_absent"}
        payload = await self._decode_json(raw)
        metadata = payload.get("metadata")
        if (
            payload.get("kind") != "Service"
            or not isinstance(metadata, Mapping)
            or metadata.get("namespace") != namespace
            or metadata.get("name") != name
        ):
            raise RuntimeError("kubectl returned a mismatched webhook Service")
        return {"namespace": namespace, "name": name, "status": "present"}

    async def custom_owner(
        self,
        task: EvaluationTask,
        query: CustomOwnerQuery,
    ) -> Mapping[str, Any] | None:
        namespace = self._namespace(task)
        payload = await self._get_json(namespace, query.resource)
        return project_custom_owner(payload, namespace=namespace, query=query)

    async def capacity(self, task: EvaluationTask) -> Mapping[str, Any]:
        from fdai.delivery.evaluation.kubernetes_capacity import KubectlCapacityEvidenceProvider

        return await KubectlCapacityEvidenceProvider(self).collect(task)

    async def dependencies(self, task: EvaluationTask) -> Mapping[str, Any]:
        from fdai.delivery.evaluation.kubernetes_dependency import KubectlDependencyEvidenceProvider

        return await KubectlDependencyEvidenceProvider(self).collect(task)

    async def admission(self, task: EvaluationTask) -> Mapping[str, Any]:
        from fdai.delivery.evaluation.kubernetes_admission import KubectlAdmissionEvidenceProvider

        return await KubectlAdmissionEvidenceProvider(self).collect(task)

    async def owners(self, task: EvaluationTask) -> Mapping[str, Any]:
        from fdai.delivery.evaluation.kubernetes_owners import KubectlOwnerEvidenceProvider

        return await KubectlOwnerEvidenceProvider(self).collect(task)

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

    async def _get_cluster_json(self, resources: str) -> Mapping[str, Any]:
        command = (
            "kubectl",
            "--kubeconfig",
            str(self._config.kubeconfig),
            "--context",
            self._config.context,
            "get",
            resources,
            "--output",
            "json",
            f"--request-timeout={self._config.timeout_seconds:g}s",
        )
        return await self._run_json(command)

    async def _run_json(self, command: tuple[str, ...]) -> Mapping[str, Any]:
        raw = await self._run(command)
        return await self._decode_json(raw)

    async def _decode_json(self, raw: bytes) -> Mapping[str, Any]:
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
    executor: DiagnosticFunctionExecutor = field(default_factory=DiagnosticFunctionExecutor)

    async def collect(self, task: EvaluationTask) -> Mapping[str, Any]:
        inventory = dict(await self.client.inventory(task))
        resources = [item for item in inventory.get("resources", []) if isinstance(item, Mapping)]
        evidence_complete = inventory.get("truncated") is False
        inventory["evidence_complete"] = evidence_complete
        execution = await self.executor.derive(
            "kubernetes_image_pull_controller_template_drift_candidate",
            {"resources": resources, "evidence_complete": evidence_complete},
        )
        inventory["findings"] = list(execution.findings)
        inventory["function_receipts"] = [execution.receipt]
        inventory["function_inputs"] = [execution.input_binding]
        return inventory


@dataclass(frozen=True, slots=True)
class KubectlEventEvidenceProvider:
    client: KubectlEvidenceClient
    clock: Callable[[], datetime] = _utc_now
    executor: DiagnosticFunctionExecutor = field(default_factory=DiagnosticFunctionExecutor)

    async def collect(self, task: EvaluationTask) -> Mapping[str, Any]:
        event_receipt, inventory = await asyncio.gather(
            self.client.events(task),
            self.client.inventory(task),
        )
        evidence = dict(event_receipt)
        events = [item for item in evidence.get("events", []) if isinstance(item, Mapping)]
        resources = [item for item in inventory.get("resources", []) if isinstance(item, Mapping)]
        evidence_complete = (
            evidence.get("truncated") is False and inventory.get("truncated") is False
        )
        evidence["evidence_complete"] = evidence_complete
        cutoff = self.clock().isoformat()
        executions = tuple(
            [
                await self.executor.derive(
                    mechanism_id,
                    {
                        "resources": resources,
                        "events": events,
                        "evidence_complete": evidence_complete,
                        "evidence_cutoff": cutoff,
                    },
                )
                for mechanism_id in (
                    "kubernetes_pod_host_port_conflict_candidate",
                    "kubernetes_liveness_probe_failure_candidate",
                    "kubernetes_readiness_probe_failure_candidate",
                )
            ]
        )
        evidence["findings"] = [finding for item in executions for finding in item.findings]
        evidence["function_receipts"] = [item.receipt for item in executions]
        evidence["function_inputs"] = [item.input_binding for item in executions]
        return evidence


@dataclass(frozen=True, slots=True)
class KubectlPodMetricEvidenceProvider:
    client: KubectlEvidenceClient

    async def collect(self, task: EvaluationTask) -> Mapping[str, Any]:
        return await self.client.pod_metrics(task)


@dataclass(frozen=True, slots=True)
class KubectlNodeEvidenceProvider:
    client: KubectlEvidenceClient

    async def collect(self, task: EvaluationTask) -> Mapping[str, Any]:
        return await self.client.nodes(task)


def kubernetes_evidence_providers(
    client: KubectlEvidenceClient,
) -> Mapping[str, EvaluationEvidenceProvider]:
    """Return provider bindings for the supported semantic capabilities."""

    from fdai.delivery.evaluation.kubernetes_admission import KubectlAdmissionEvidenceProvider
    from fdai.delivery.evaluation.kubernetes_capacity import KubectlCapacityEvidenceProvider
    from fdai.delivery.evaluation.kubernetes_dependency import KubectlDependencyEvidenceProvider
    from fdai.delivery.evaluation.kubernetes_owners import KubectlOwnerEvidenceProvider

    executor = DiagnosticFunctionExecutor()
    return {
        "observe.kubernetes.admission": KubectlAdmissionEvidenceProvider(client, executor=executor),
        "observe.kubernetes.capacity": KubectlCapacityEvidenceProvider(client, executor=executor),
        "observe.kubernetes.dependencies": KubectlDependencyEvidenceProvider(
            client, executor=executor
        ),
        "observe.kubernetes.inventory": KubectlInventoryEvidenceProvider(client, executor=executor),
        "observe.kubernetes.events": KubectlEventEvidenceProvider(client, executor=executor),
        "observe.kubernetes.nodes": KubectlNodeEvidenceProvider(client),
        "observe.kubernetes.owners": KubectlOwnerEvidenceProvider(client, executor=executor),
        "observe.metrics.query": KubectlPodMetricEvidenceProvider(client),
    }


def _valid_namespace(value: str) -> bool:
    return 1 <= len(value) <= 63 and _DNS_LABEL.fullmatch(value) is not None


__all__ = [
    "KubectlEventEvidenceProvider",
    "KubectlEvidenceClient",
    "KubectlEvidenceConfig",
    "KubectlInventoryEvidenceProvider",
    "KubectlNodeEvidenceProvider",
    "KubectlPodMetricEvidenceProvider",
    "kubernetes_evidence_providers",
]
