"""Evaluation adapter tests for bounded Kubernetes custom owner evidence."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from fdai_evaluation_sdk import EvaluationTask

from fdai.delivery.evaluation.kubernetes_owners import KubectlOwnerEvidenceProvider
from fdai.delivery.kubernetes.owners import CustomOwnerQuery


class _Client:
    def __init__(
        self,
        *,
        truncated: bool = False,
        owner_count: int = 1,
        lookup_result: Mapping[str, Any] | None = None,
        fail_lookup: bool = False,
    ) -> None:
        self.truncated = truncated
        self.owner_count = owner_count
        self.lookup_result = lookup_result if lookup_result is not None else _owner()
        self.fail_lookup = fail_lookup

    async def inventory(self, task: EvaluationTask) -> Mapping[str, Any]:
        del task
        return {
            "cluster": "example-cluster",
            "namespace": "example-app",
            "resources": [
                {
                    "owner_reference_projection_complete": True,
                    "owner_references": [
                        {
                            "api_version": "database.example.io/v1",
                            "kind": "Database",
                            "name": f"database-{index}",
                            "uid": f"owner-{index}",
                        }
                        for index in range(self.owner_count)
                    ],
                }
            ],
            "truncated": self.truncated,
        }

    async def custom_owner(
        self,
        task: EvaluationTask,
        query: CustomOwnerQuery,
    ) -> Mapping[str, Any] | None:
        del task, query
        if self.fail_lookup:
            raise RuntimeError("synthetic owner lookup failure")
        return self.lookup_result


async def test_owner_provider_returns_uid_grounded_projection() -> None:
    evidence = await KubectlOwnerEvidenceProvider(_Client()).collect(None)  # type: ignore[arg-type]

    assert evidence["evidence_complete"] is True
    assert evidence["owners"] == [_owner()]


@pytest.mark.parametrize(
    "client_kwargs",
    [
        {"truncated": True},
        {"owner_count": 9},
        {"fail_lookup": True},
        {"lookup_result": {}},
    ],
)
async def test_owner_provider_abstains_on_incomplete_or_mismatched_evidence(
    client_kwargs: dict[str, object],
) -> None:
    client = _Client(**client_kwargs)  # type: ignore[arg-type]
    evidence = await KubectlOwnerEvidenceProvider(client).collect(None)  # type: ignore[arg-type]

    assert evidence["evidence_complete"] is False
    assert evidence["owners"] == []


def _owner() -> dict[str, object]:
    return {
        "api_version": "database.example.io/v1",
        "kind": "Database",
        "name": "database-0",
        "namespace": "example-app",
        "uid": "owner-0",
        "custom_resource": True,
        "resource_version": "7",
        "generation": 3,
        "deleting": False,
        "conditions": [],
    }
