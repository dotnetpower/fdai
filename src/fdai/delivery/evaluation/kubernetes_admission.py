"""Evaluation adapter for shared Kubernetes admission drift evidence semantics."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from fdai_evaluation_sdk import EvaluationTask

from fdai.delivery.kubernetes.admission import mutating_webhook_resource_drift_findings
from fdai.delivery.kubernetes.admission_conditions import admission_condition_findings
from fdai.delivery.kubernetes.webhook_findings import admission_webhook_failure_findings
from fdai.delivery.kubernetes.webhook_timeout import cumulative_webhook_timeout_findings


def _utc_now() -> datetime:
    return datetime.now(UTC)


class KubernetesAdmissionEvidenceClient(Protocol):
    async def inventory(self, task: EvaluationTask) -> Mapping[str, Any]: ...

    async def events(self, task: EvaluationTask) -> Mapping[str, Any]: ...

    async def admission_configurations(self, task: EvaluationTask) -> Mapping[str, Any]: ...


@dataclass(frozen=True, slots=True)
class KubectlAdmissionEvidenceProvider:
    client: KubernetesAdmissionEvidenceClient
    clock: Callable[[], datetime] = _utc_now

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
        return {
            "cluster": str(inventory.get("cluster") or "")[:253],
            "namespace": namespace,
            "evidence_complete": evidence_complete,
            "findings": [
                *admission_condition_findings(
                    resources,
                    evidence_complete=evidence_complete,
                ),
                *admission_webhook_failure_findings(
                    resources,
                    events,
                    namespace=namespace,
                    evidence_complete=evidence_complete,
                ),
                *cumulative_webhook_timeout_findings(
                    events,
                    namespace=namespace,
                    evidence_complete=evidence_complete,
                    evidence_cutoff=self.clock(),
                ),
                *mutating_webhook_resource_drift_findings(
                    resources,
                    evidence_complete=evidence_complete,
                ),
            ],
        }


def _mappings(value: Any) -> list[Mapping[str, Any]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


__all__ = ["KubectlAdmissionEvidenceProvider", "KubernetesAdmissionEvidenceClient"]
