"""Evaluation adapter for bounded Kubernetes custom owner evidence."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from fdai_evaluation_sdk import EvaluationTask

from fdai.delivery.kubernetes.owners import CustomOwnerQuery, custom_owner_queries

_MAX_OWNERS = 8


class KubernetesOwnerEvidenceClient(Protocol):
    async def inventory(self, task: EvaluationTask) -> Mapping[str, Any]: ...

    async def custom_owner(
        self,
        task: EvaluationTask,
        query: CustomOwnerQuery,
    ) -> Mapping[str, Any] | None: ...


@dataclass(frozen=True, slots=True)
class KubectlOwnerEvidenceProvider:
    client: KubernetesOwnerEvidenceClient

    async def collect(self, task: EvaluationTask) -> Mapping[str, Any]:
        inventory = await self.client.inventory(task)
        resources = _mappings(inventory.get("resources"))
        queries, omitted = custom_owner_queries(resources, max_owners=_MAX_OWNERS)
        projected = await asyncio.gather(*(self._collect_owner(task, query) for query in queries))
        owners = [
            owner
            for query, owner in zip(queries, projected, strict=True)
            if owner is not None and owner.get("uid") == query.expected_uid
        ]
        evidence_complete = (
            inventory.get("truncated") is False and omitted == 0 and len(owners) == len(queries)
        )
        return {
            "cluster": str(inventory.get("cluster") or "")[:253],
            "namespace": str(inventory.get("namespace") or "")[:253],
            "evidence_complete": evidence_complete,
            "owners": owners if evidence_complete else [],
        }

    async def _collect_owner(
        self,
        task: EvaluationTask,
        query: CustomOwnerQuery,
    ) -> Mapping[str, Any] | None:
        try:
            return await self.client.custom_owner(task, query)
        except RuntimeError:
            return None


def _mappings(value: Any) -> list[Mapping[str, Any]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


__all__ = ["KubectlOwnerEvidenceProvider", "KubernetesOwnerEvidenceClient"]
