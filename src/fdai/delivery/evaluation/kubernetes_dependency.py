"""Evaluation adapter for shared Kubernetes dependency evidence semantics."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from fdai_evaluation_sdk import EvaluationTask

from fdai.delivery.kubernetes.dependency import missing_service_dependency_findings


class KubernetesDependencyEvidenceClient(Protocol):
    async def inventory(self, task: EvaluationTask) -> Mapping[str, Any]: ...


@dataclass(frozen=True, slots=True)
class KubectlDependencyEvidenceProvider:
    client: KubernetesDependencyEvidenceClient

    async def collect(self, task: EvaluationTask) -> Mapping[str, Any]:
        inventory = await self.client.inventory(task)
        evidence_complete = inventory.get("truncated") is False
        resources = _mappings(inventory.get("resources"))
        return {
            "cluster": str(inventory.get("cluster") or "")[:253],
            "namespace": str(inventory.get("namespace") or "")[:253],
            "evidence_complete": evidence_complete,
            "findings": list(
                missing_service_dependency_findings(
                    resources,
                    evidence_complete=evidence_complete,
                )
            ),
        }


def _mappings(value: Any) -> list[Mapping[str, Any]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


__all__ = ["KubectlDependencyEvidenceProvider", "KubernetesDependencyEvidenceClient"]
