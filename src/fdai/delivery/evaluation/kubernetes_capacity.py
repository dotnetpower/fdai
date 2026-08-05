"""Evaluation adapter for shared Kubernetes capacity evidence semantics."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from fdai_evaluation_sdk import EvaluationTask

from fdai.delivery.evaluation.diagnostic_functions import DiagnosticFunctionExecutor


class KubernetesCapacityEvidenceClient(Protocol):
    """Read surfaces required by the capacity evidence join."""

    async def inventory(self, task: EvaluationTask) -> Mapping[str, Any]: ...

    async def events(self, task: EvaluationTask) -> Mapping[str, Any]: ...

    async def nodes(self, task: EvaluationTask) -> Mapping[str, Any]: ...


@dataclass(frozen=True, slots=True)
class KubectlCapacityEvidenceProvider:
    """Join bounded reads through shared hold-only capacity semantics."""

    client: KubernetesCapacityEvidenceClient
    executor: DiagnosticFunctionExecutor = field(default_factory=DiagnosticFunctionExecutor)

    async def collect(self, task: EvaluationTask) -> Mapping[str, Any]:
        inventory, events, nodes = await asyncio.gather(
            self.client.inventory(task),
            self.client.events(task),
            self.client.nodes(task),
        )
        resources = _mappings(inventory.get("resources"))
        projected_events = _mappings(events.get("events"))
        projected_nodes = _mappings(nodes.get("nodes"))
        evidence_complete = all(
            payload.get("truncated") is False for payload in (inventory, events, nodes)
        )
        execution = await self.executor.derive(
            "kubernetes_capacity_reducer",
            {
                "resources": resources,
                "events": projected_events,
                "nodes": projected_nodes,
                "evidence_complete": evidence_complete,
            },
        )
        return {
            "cluster": str(inventory.get("cluster") or "")[:253],
            "namespace": str(inventory.get("namespace") or "")[:253],
            "evidence_complete": evidence_complete,
            "findings": list(execution.findings),
            "function_receipts": [execution.receipt],
            "function_inputs": [execution.input_binding],
        }


def _mappings(value: Any) -> list[Mapping[str, Any]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


__all__ = ["KubectlCapacityEvidenceProvider", "KubernetesCapacityEvidenceClient"]
