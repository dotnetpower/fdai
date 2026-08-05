"""Evaluation adapter for shared Kubernetes dependency evidence semantics."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from fdai_evaluation_sdk import EvaluationTask

from fdai.delivery.evaluation.diagnostic_functions import DiagnosticFunctionExecutor


class KubernetesDependencyEvidenceClient(Protocol):
    async def inventory(self, task: EvaluationTask) -> Mapping[str, Any]: ...


@dataclass(frozen=True, slots=True)
class KubectlDependencyEvidenceProvider:
    client: KubernetesDependencyEvidenceClient
    executor: DiagnosticFunctionExecutor = field(default_factory=DiagnosticFunctionExecutor)

    async def collect(self, task: EvaluationTask) -> Mapping[str, Any]:
        inventory = await self.client.inventory(task)
        evidence_complete = inventory.get("truncated") is False
        resources = _mappings(inventory.get("resources"))
        execution = await self.executor.derive(
            "kubernetes_missing_dependency_reducer",
            {
                "resources": resources,
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


__all__ = ["KubectlDependencyEvidenceProvider", "KubernetesDependencyEvidenceClient"]
