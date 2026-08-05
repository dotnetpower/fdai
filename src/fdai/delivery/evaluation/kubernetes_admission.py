"""Evaluation adapter for shared Kubernetes admission drift evidence semantics."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from fdai_evaluation_sdk import EvaluationTask

from fdai.delivery.evaluation.diagnostic_functions import DiagnosticFunctionExecutor

_MAX_WEBHOOK_SERVICES = 8


def _utc_now() -> datetime:
    return datetime.now(UTC)


class KubernetesAdmissionEvidenceClient(Protocol):
    async def inventory(self, task: EvaluationTask) -> Mapping[str, Any]: ...

    async def events(self, task: EvaluationTask) -> Mapping[str, Any]: ...

    async def admission_configurations(self, task: EvaluationTask) -> Mapping[str, Any]: ...

    async def webhook_service(
        self, task: EvaluationTask, *, namespace: str, name: str
    ) -> Mapping[str, Any]: ...


@dataclass(frozen=True, slots=True)
class KubectlAdmissionEvidenceProvider:
    client: KubernetesAdmissionEvidenceClient
    clock: Callable[[], datetime] = _utc_now
    executor: DiagnosticFunctionExecutor = field(default_factory=DiagnosticFunctionExecutor)

    async def collect(self, task: EvaluationTask) -> Mapping[str, Any]:
        inventory = await self.client.inventory(task)
        event_inventory = await self.client.events(task)
        configurations = await self.client.admission_configurations(task)
        evidence_complete = (
            inventory.get("truncated") is False
            and event_inventory.get("truncated") is False
            and configurations.get("truncated") is False
        )
        resources = [
            *_mappings(inventory.get("resources")),
            *_mappings(configurations.get("resources")),
        ]
        namespace = str(inventory.get("namespace") or "")[:253]
        events = _mappings(event_inventory.get("events"))
        service_references = _service_references(_mappings(configurations.get("resources")))
        selected_references = service_references[:_MAX_WEBHOOK_SERVICES]
        service_receipts = [
            receipt
            for service_namespace, service_name in selected_references
            if (
                receipt := await self._service_receipt(
                    task,
                    namespace=service_namespace,
                    name=service_name,
                )
            )
            is not None
        ]
        service_evidence_complete = (
            evidence_complete
            and len(service_references) <= _MAX_WEBHOOK_SERVICES
            and len(service_receipts) == len(selected_references)
        )
        cutoff = self.clock().isoformat()
        executions = (
            await self.executor.derive(
                "kubernetes_direct_admission_condition_evidence",
                {"resources": resources, "evidence_complete": evidence_complete},
            ),
            await self.executor.derive(
                "kubernetes_webhook_failure_source_candidate",
                {
                    "resources": resources,
                    "events": events,
                    "namespace": namespace,
                    "evidence_complete": evidence_complete,
                },
            ),
            await self.executor.derive(
                "kubernetes_cumulative_webhook_timeout_candidate",
                {
                    "events": events,
                    "namespace": namespace,
                    "evidence_complete": evidence_complete,
                    "evidence_cutoff": cutoff,
                },
            ),
            await self.executor.derive(
                "kubernetes_missing_webhook_backend_candidate",
                {
                    "configurations": _mappings(configurations.get("resources")),
                    "service_receipts": service_receipts,
                    "evidence_complete": service_evidence_complete,
                },
            ),
            await self.executor.derive(
                "kubernetes_pod_security_restricted_mismatch_candidate",
                {
                    "resources": resources,
                    "events": events,
                    "evidence_complete": evidence_complete,
                    "evidence_cutoff": cutoff,
                },
            ),
            await self.executor.derive(
                "kubernetes_admission_resource_drift_reducer",
                {"resources": resources, "evidence_complete": evidence_complete},
            ),
        )
        return {
            "cluster": str(inventory.get("cluster") or "")[:253],
            "namespace": namespace,
            "evidence_complete": evidence_complete,
            "webhook_service_evidence_complete": service_evidence_complete,
            "findings": [finding for item in executions for finding in item.findings],
            "function_receipts": [item.receipt for item in executions],
            "function_inputs": [item.input_binding for item in executions],
        }

    async def _service_receipt(
        self,
        task: EvaluationTask,
        *,
        namespace: str,
        name: str,
    ) -> Mapping[str, Any] | None:
        try:
            return await self.client.webhook_service(task, namespace=namespace, name=name)
        except RuntimeError:
            return None


def _mappings(value: Any) -> list[Mapping[str, Any]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _service_references(
    configurations: list[Mapping[str, Any]],
) -> list[tuple[str, str]]:
    references = {
        (str(service.get("namespace") or ""), str(service.get("name") or ""))
        for configuration in configurations
        for webhook in _mappings(configuration.get("webhooks"))
        if isinstance((service := webhook.get("service")), Mapping)
        and service.get("namespace")
        and service.get("name")
    }
    return sorted(references)


__all__ = ["KubectlAdmissionEvidenceProvider", "KubernetesAdmissionEvidenceClient"]
