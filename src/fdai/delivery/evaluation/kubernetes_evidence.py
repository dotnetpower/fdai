"""Namespace-scoped Kubernetes evidence for external evaluation tasks."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from fdai_evaluation_sdk import EvaluationTask

from fdai.delivery.kubernetes.admission_events import classify_admission_failure
from fdai.delivery.kubernetes.capacity import project_pod_resource_requests
from fdai.delivery.kubernetes.owners import CustomOwnerQuery, project_custom_owner
from fdai.delivery.kubernetes.quantity import cpu_millicores, memory_bytes, parse_quantity
from fdai.evaluation.evidence import EvaluationEvidenceProvider

CommandRunner = Callable[[tuple[str, ...]], Awaitable[bytes]]
_DNS_SUBDOMAIN: Final = re.compile(
    r"^[a-z0-9](?:[-a-z0-9]*[a-z0-9])?(?:\.[a-z0-9](?:[-a-z0-9]*[a-z0-9])?)*$"
)
_INVENTORY_RESOURCES: Final = (
    "deployments,statefulsets,daemonsets,replicasets,pods,services,endpoints"
)


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

    async def nodes(self, task: EvaluationTask) -> Mapping[str, Any]:
        self._namespace(task)
        payload = await self._get_cluster_json("nodes")
        items = _items(payload)
        selected = items[: self._config.max_items]
        return {
            "cluster": self._config.cluster_name,
            "nodes": [
                projection
                for item in selected
                if isinstance(item, Mapping) and (projection := _project_node(item)) is not None
            ],
            "truncated": len(items) > len(selected),
        }

    async def admission_configurations(self, task: EvaluationTask) -> Mapping[str, Any]:
        self._namespace(task)
        payload = await self._get_cluster_json(
            "mutatingwebhookconfigurations,validatingwebhookconfigurations"
        )
        items = _items(payload)
        selected = items[: self._config.max_items]
        return {
            "cluster": self._config.cluster_name,
            "resources": [
                projection
                for item in selected
                if isinstance(item, Mapping)
                and (projection := _project_webhook_configuration(item)) is not None
            ],
            "truncated": len(items) > len(selected),
        }

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

    return {
        "observe.kubernetes.admission": KubectlAdmissionEvidenceProvider(client),
        "observe.kubernetes.capacity": KubectlCapacityEvidenceProvider(client),
        "observe.kubernetes.dependencies": KubectlDependencyEvidenceProvider(client),
        "observe.kubernetes.inventory": KubectlInventoryEvidenceProvider(client),
        "observe.kubernetes.events": KubectlEventEvidenceProvider(client),
        "observe.kubernetes.nodes": KubectlNodeEvidenceProvider(client),
        "observe.kubernetes.owners": KubectlOwnerEvidenceProvider(client),
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
    if "ownerReferences" in metadata:
        owner_references, owner_references_complete = _project_owner_references(
            metadata.get("ownerReferences")
        )
        projected["owner_reference_projection_complete"] = owner_references_complete
        projected["owner_references"] = owner_references
    spec = item.get("spec")
    status = item.get("status")
    spec_values = spec if isinstance(spec, Mapping) else {}
    status_values = status if isinstance(status, Mapping) else {}
    if kind in {"Deployment", "StatefulSet", "ReplicaSet"}:
        projected.update(
            desired=_count(spec_values.get("replicas")),
            ready=_count(status_values.get("readyReplicas")),
            available=_count(status_values.get("availableReplicas")),
            updated=_count(status_values.get("updatedReplicas")),
        )
        template = _project_pod_template(spec_values.get("template"))
        if template is not None:
            projected["pod_template"] = template
        selector = _project_label_selector(spec_values.get("selector"))
        if selector is not None:
            projected["selector"] = selector
        _add_admission_conditions(projected, status_values.get("conditions"))
    elif kind == "DaemonSet":
        projected.update(
            desired=_count(status_values.get("desiredNumberScheduled")),
            ready=_count(status_values.get("numberReady")),
            unavailable=_count(status_values.get("numberUnavailable")),
        )
        template = _project_pod_template(spec_values.get("template"))
        if template is not None:
            projected["pod_template"] = template
        selector = _project_label_selector(spec_values.get("selector"))
        if selector is not None:
            projected["selector"] = selector
        _add_admission_conditions(projected, status_values.get("conditions"))
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
        uid = metadata.get("uid")
        if isinstance(uid, str) and uid:
            projected["uid"] = uid[:128]
        resource_requests = project_pod_resource_requests(spec_values)
        if resource_requests is not None:
            projected["resource_requests"] = resource_requests
        pod_spec = _project_pod_resource_spec(spec_values)
        if pod_spec is not None:
            projected["pod_spec"] = pod_spec
            labels = _project_labels(metadata.get("labels"))
            if labels is not None:
                projected["labels"] = labels
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


def _add_admission_conditions(projected: dict[str, Any], value: object) -> None:
    if value is None:
        return
    if not isinstance(value, list) or len(value) > 32:
        projected["admission_condition_projection_complete"] = False
        projected["admission_conditions"] = []
        return
    conditions: list[dict[str, Any]] = []
    projection_complete = True
    for index, item in enumerate(value):
        if not isinstance(item, Mapping) or not _valid_condition_shape(item):
            projection_complete = False
            continue
        condition = _project_admission_condition(item, source_index=index)
        if condition is not None:
            conditions.append(condition)
    projected["admission_condition_projection_complete"] = projection_complete
    projected["admission_conditions"] = conditions


def _project_admission_condition(
    value: Mapping[str, Any],
    *,
    source_index: int,
) -> dict[str, Any] | None:
    condition_type = value.get("type")
    status = value.get("status")
    reason = value.get("reason")
    message = value.get("message") or ""
    if not all(isinstance(item, str) for item in (condition_type, status, reason, message)):
        return None
    if status != "True":
        return None
    failure = classify_admission_failure(reason=str(reason), message=str(message))
    if failure is None:
        return None
    condition: dict[str, Any] = {
        "type": str(condition_type)[:128],
        "status": str(status)[:32],
        "reason": str(reason)[:256],
        "code": failure.code,
        "source_index": source_index,
    }
    if failure.webhook_name:
        condition["webhook_name"] = failure.webhook_name
    if failure.pod_security_profile:
        condition["pod_security_profile"] = failure.pod_security_profile
        condition["pod_security_version"] = failure.pod_security_version
        condition["pod_security_violations"] = list(failure.pod_security_violations)
    return condition


def _valid_condition_shape(value: Mapping[str, Any]) -> bool:
    return all(isinstance(value.get(key), str) for key in ("type", "status", "reason")) and (
        value.get("message") is None or isinstance(value.get("message"), str)
    )


def _project_owner_references(value: object) -> tuple[list[dict[str, str]], bool]:
    if value is None:
        return [], True
    if not isinstance(value, list):
        return [], False
    selected = value[:8]
    references = [
        projection
        for reference in selected
        if isinstance(reference, Mapping)
        and (projection := _project_owner_reference(reference)) is not None
    ]
    return references, len(value) <= 8 and len(references) == len(value)


def _project_owner_reference(value: Mapping[str, Any]) -> dict[str, Any] | None:
    api_version = value.get("apiVersion")
    kind = value.get("kind")
    name = value.get("name")
    uid = value.get("uid")
    if not all(isinstance(item, str) and item for item in (api_version, kind, name, uid)):
        return None
    return {
        "api_version": str(api_version)[:128],
        "kind": str(kind)[:128],
        "name": str(name)[:253],
        "uid": str(uid)[:128],
        "controller": value.get("controller") is True,
    }


def _project_pod_template(value: object) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    spec = value.get("spec")
    if not isinstance(spec, Mapping):
        return None
    raw_containers = spec.get("containers")
    if not isinstance(raw_containers, list) or len(raw_containers) > 32:
        return {"projection_complete": False, "containers": []}
    containers = [
        _project_template_container(item) for item in raw_containers if isinstance(item, Mapping)
    ]
    return {
        "projection_complete": len(containers) == len(raw_containers),
        "containers": containers,
    }


def _project_template_container(value: Mapping[str, Any]) -> dict[str, Any]:
    raw_ports = value.get("ports")
    port_values = raw_ports if isinstance(raw_ports, list) else []
    ports = [
        {"port": port}
        for item in port_values[:32]
        if isinstance(item, Mapping)
        and isinstance((port := item.get("containerPort")), int)
        and not isinstance(port, bool)
        and 1 <= port <= 65_535
    ]
    raw_env = value.get("env")
    env_values = raw_env if isinstance(raw_env, list) else []
    env = [
        projection
        for item in env_values[:128]
        if isinstance(item, Mapping) and (projection := _project_endpoint_env(item)) is not None
    ]
    resources = _project_container_resources(value.get("resources"))
    return {
        "name": _text(value.get("name"), 253),
        "resource_projection_complete": resources is not None,
        "resources": resources or {},
        "port_projection_complete": isinstance(raw_ports, list)
        and len(raw_ports) <= 32
        and len(ports) == len(raw_ports),
        "ports": ports,
        "env_projection_complete": isinstance(raw_env, list) and len(raw_env) <= 128,
        "env": env,
    }


def _project_pod_resource_spec(value: Mapping[str, Any]) -> dict[str, Any] | None:
    raw_containers = value.get("containers")
    if not isinstance(raw_containers, list):
        return None
    selected = raw_containers[:32]
    containers = [
        projection
        for item in selected
        if isinstance(item, Mapping)
        and (projection := _project_resource_container(item)) is not None
    ]
    return {
        "projection_complete": len(raw_containers) <= 32 and len(containers) == len(raw_containers),
        "containers": containers,
    }


def _project_resource_container(value: Mapping[str, Any]) -> dict[str, Any] | None:
    name = value.get("name")
    resources = _project_container_resources(value.get("resources"))
    if not isinstance(name, str) or not name or resources is None:
        return None
    return {
        "name": name[:253],
        "resource_projection_complete": True,
        "resources": resources,
    }


def _project_container_resources(value: object) -> dict[str, dict[str, str]] | None:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        return None
    projected: dict[str, dict[str, str]] = {}
    for section in ("requests", "limits"):
        raw_section = value.get(section)
        if raw_section is None:
            continue
        if not isinstance(raw_section, Mapping):
            return None
        section_values: dict[str, str] = {}
        for resource_name in ("cpu", "memory"):
            raw_quantity = raw_section.get(resource_name)
            if raw_quantity is None:
                continue
            if (
                not isinstance(raw_quantity, str)
                or len(raw_quantity) > 64
                or (quantity := parse_quantity(raw_quantity)) is None
                or quantity < 0
            ):
                return None
            section_values[resource_name] = raw_quantity
        if section_values:
            projected[section] = section_values
    return projected


def _project_label_selector(value: object) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    raw_labels = value.get("matchLabels")
    labels = raw_labels if isinstance(raw_labels, Mapping) else {}
    expressions = value.get("matchExpressions")
    projection_complete = (
        (raw_labels is None or isinstance(raw_labels, Mapping))
        and len(labels) <= 64
        and all(
            isinstance(key, str)
            and isinstance(label_value, str)
            and len(key) <= 253
            and len(label_value) <= 63
            for key, label_value in labels.items()
        )
        and (expressions is None or expressions == [])
    )
    return {
        "projection_complete": projection_complete,
        "match_labels": dict(labels) if projection_complete else {},
    }


def _project_labels(value: object) -> dict[str, Any] | None:
    if value is None:
        return {"projection_complete": True, "values": {}}
    if not isinstance(value, Mapping):
        return None
    projection_complete = len(value) <= 64 and all(
        isinstance(key, str)
        and isinstance(label_value, str)
        and len(key) <= 253
        and len(label_value) <= 63
        for key, label_value in value.items()
    )
    return {
        "projection_complete": projection_complete,
        "values": dict(value) if projection_complete else {},
    }


def _project_webhook_configuration(
    item: Mapping[str, Any],
) -> dict[str, Any] | None:
    kind = item.get("kind")
    metadata = item.get("metadata")
    webhooks = item.get("webhooks")
    if (
        kind not in {"MutatingWebhookConfiguration", "ValidatingWebhookConfiguration"}
        or not isinstance(metadata, Mapping)
        or not isinstance(webhooks, list)
    ):
        return None
    name = metadata.get("name")
    if not isinstance(name, str) or not name:
        return None
    selected = webhooks[:32]
    projected_webhooks = [
        projection
        for webhook in selected
        if isinstance(webhook, Mapping) and (projection := _project_webhook(webhook)) is not None
    ]
    return {
        "kind": kind,
        "name": name[:253],
        "namespace": "",
        "projection_complete": len(webhooks) <= 32 and len(projected_webhooks) == len(webhooks),
        "webhooks": projected_webhooks,
    }


def _project_webhook(value: Mapping[str, Any]) -> dict[str, Any] | None:
    name = value.get("name")
    rules = value.get("rules")
    object_selector = _project_selector_presence(value.get("objectSelector"))
    namespace_selector = _project_selector_presence(value.get("namespaceSelector"))
    match_conditions = value.get("matchConditions")
    if (
        not isinstance(name, str)
        or not isinstance(rules, list)
        or object_selector is None
        or namespace_selector is None
        or (match_conditions is not None and not isinstance(match_conditions, list))
    ):
        return None
    selected_rules = rules[:32]
    projected_rules = [
        projection
        for rule in selected_rules
        if isinstance(rule, Mapping) and (projection := _project_admission_rule(rule)) is not None
    ]
    condition_values = match_conditions if isinstance(match_conditions, list) else []
    client_config = value.get("clientConfig")
    if not isinstance(client_config, Mapping):
        return None
    service = _project_webhook_service(client_config.get("service"))
    if client_config.get("service") is not None and service is None:
        return None
    return {
        "name": name[:253],
        "projection_complete": len(rules) <= 32
        and len(projected_rules) == len(rules)
        and len(condition_values) <= 32
        and all(isinstance(condition, Mapping) for condition in condition_values),
        "object_selector": object_selector,
        "namespace_selector": namespace_selector,
        "match_conditions": [{} for _ in condition_values[:32]],
        "failure_policy": _text(value.get("failurePolicy"), 32),
        "timeout_seconds": _count(value.get("timeoutSeconds")),
        "service": service or {},
        "rules": projected_rules,
    }


def _project_webhook_service(value: object) -> dict[str, str] | None:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        return None
    namespace = value.get("namespace")
    name = value.get("name")
    if not isinstance(namespace, str) or not isinstance(name, str):
        return None
    return {"namespace": namespace[:253], "name": name[:253]}


def _project_selector_presence(value: object) -> dict[str, bool] | None:
    if value is None or value == {}:
        return {}
    return {"present": True} if isinstance(value, Mapping) else None


def _project_admission_rule(value: Mapping[str, Any]) -> dict[str, Any] | None:
    operations = _bounded_strings(value.get("operations"), 16)
    api_groups = _bounded_strings(value.get("apiGroups"), 16)
    api_versions = _bounded_strings(value.get("apiVersions"), 16)
    resources = _bounded_strings(value.get("resources"), 32)
    scope = value.get("scope")
    if any(item is None for item in (operations, api_groups, api_versions, resources)) or not (
        scope is None or isinstance(scope, str)
    ):
        return None
    return {
        "projection_complete": True,
        "operations": operations,
        "api_groups": api_groups,
        "api_versions": api_versions,
        "resources": resources,
        "scope": scope or "",
    }


def _bounded_strings(value: object, limit: int) -> list[str] | None:
    if not isinstance(value, list) or len(value) > limit:
        return None
    return (
        [item for item in value if isinstance(item, str)]
        if all(isinstance(item, str) and len(item) <= 253 for item in value)
        else None
    )


def _project_endpoint_env(value: Mapping[str, Any]) -> dict[str, str] | None:
    name = value.get("name")
    literal = value.get("value")
    if not isinstance(name, str) or not isinstance(literal, str):
        return None
    host, separator, port = literal.rpartition(":")
    if (
        separator != ":"
        or not _DNS_SUBDOMAIN.fullmatch(host)
        or not port.isdigit()
        or not 1 <= int(port) <= 65_535
    ):
        return None
    return {
        "name": name[:253],
        "endpoint_host": host,
        "endpoint_port": port,
    }


def _project_event(item: Mapping[str, Any]) -> dict[str, Any] | None:
    metadata = item.get("metadata")
    involved = item.get("involvedObject")
    if not isinstance(metadata, Mapping) or not isinstance(involved, Mapping):
        return None
    name = metadata.get("name")
    namespace = metadata.get("namespace")
    if not isinstance(name, str) or not isinstance(namespace, str):
        return None
    regarding = {
        "kind": _text(involved.get("kind"), 128),
        "name": _text(involved.get("name"), 253),
    }
    involved_uid = involved.get("uid")
    if isinstance(involved_uid, str) and involved_uid:
        regarding["uid"] = involved_uid[:128]
    reason = _text(item.get("reason"), 256)
    message = _text(item.get("message"), 1_024)
    projection: dict[str, Any] = {
        "name": name,
        "namespace": namespace,
        "type": _text(item.get("type"), 64),
        "reason": reason,
        "count": _count(item.get("count")),
        "last_seen": _text(
            item.get("eventTime") or item.get("lastTimestamp") or metadata.get("creationTimestamp"),
            64,
        ),
        "regarding": regarding,
    }
    admission_failure = classify_admission_failure(reason=reason, message=message)
    if admission_failure is None:
        projection["message"] = message
        return projection
    projection["code"] = admission_failure.code
    if admission_failure.webhook_name:
        projection["webhook_name"] = admission_failure.webhook_name
    if admission_failure.pod_security_profile:
        projection["pod_security_profile"] = admission_failure.pod_security_profile
        projection["pod_security_version"] = admission_failure.pod_security_version
        projection["pod_security_violations"] = list(admission_failure.pod_security_violations)
    return projection


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
        "cpu_millicores": cpu_millicores(usage.get("cpu")),
        "memory_bytes": memory_bytes(usage.get("memory")),
    }


def _project_node(item: Mapping[str, Any]) -> dict[str, Any] | None:
    metadata = item.get("metadata")
    spec = item.get("spec")
    status = item.get("status")
    if not isinstance(metadata, Mapping) or not isinstance(status, Mapping):
        return None
    name = metadata.get("name")
    if not isinstance(name, str):
        return None
    allocatable = status.get("allocatable")
    allocatable_values = allocatable if isinstance(allocatable, Mapping) else {}
    projected_allocatable = {
        resource_name: raw_value[:64]
        for resource_name in ("cpu", "memory")
        if isinstance((raw_value := allocatable_values.get(resource_name)), str)
        and (quantity := parse_quantity(raw_value)) is not None
        and quantity >= 0
    }
    return {
        "name": name,
        "ready": _node_ready(status.get("conditions")),
        "unschedulable": isinstance(spec, Mapping) and spec.get("unschedulable") is True,
        "allocatable": projected_allocatable,
        "allocatable_projection_complete": set(projected_allocatable) == {"cpu", "memory"},
    }


def _node_ready(value: object) -> bool:
    if not isinstance(value, list):
        return False
    return any(
        isinstance(condition, Mapping)
        and condition.get("type") == "Ready"
        and condition.get("status") == "True"
        for condition in value
    )


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
    "KubectlNodeEvidenceProvider",
    "KubectlPodMetricEvidenceProvider",
    "kubernetes_evidence_providers",
]
