"""Kubernetes custom owner relationship finding tests."""

from __future__ import annotations

from typing import cast

import pytest

from fdai.delivery.kubernetes.owner_findings import custom_owner_degradation_findings


@pytest.mark.parametrize("workload_name", ["database", "orders", "catalog-v2"])
def test_custom_owner_degradation_is_uid_grounded_and_metamorphic(
    workload_name: str,
) -> None:
    findings = custom_owner_degradation_findings(
        [_workload(workload_name)],
        [_owner()],
        evidence_complete=True,
    )

    assert findings == (
        {
            "reason": "custom_owner_has_degraded_workload",
            "resource": {
                "kind": "Database",
                "name": "primary",
                "namespace": "example-app",
                "uid": "owner-uid",
            },
            "degraded_workloads": [
                {
                    "kind": "StatefulSet",
                    "name": workload_name,
                    "namespace": "example-app",
                    "desired": 3,
                    "ready": 2,
                }
            ],
            "evidence_strength": "direct_owner_reference",
            "causality": "candidate_only",
            "decision": "hold",
        },
    )


@pytest.mark.parametrize("mutation", ["wrong_uid", "not_controller", "ready", "ambiguous"])
def test_custom_owner_degradation_abstains_without_unique_direct_relationship(
    mutation: str,
) -> None:
    workload = _workload("database")
    references = cast(list[dict[str, object]], workload["owner_references"])
    if mutation == "wrong_uid":
        references[0]["uid"] = "replacement-uid"
    elif mutation == "not_controller":
        references[0]["controller"] = False
    elif mutation == "ready":
        workload["ready"] = 3
    else:
        references.append({**references[0], "uid": "other-uid"})

    owners = [_owner(), {**_owner(), "uid": "other-uid", "name": "secondary"}]
    assert not custom_owner_degradation_findings(
        [workload],
        owners,
        evidence_complete=True,
    )


def test_custom_owner_degradation_abstains_on_incomplete_evidence() -> None:
    assert not custom_owner_degradation_findings(
        [_workload("database")],
        [_owner()],
        evidence_complete=False,
    )


def _owner() -> dict[str, object]:
    return {
        "api_version": "database.example.io/v1",
        "kind": "Database",
        "name": "primary",
        "namespace": "example-app",
        "uid": "owner-uid",
        "custom_resource": True,
    }


def _workload(name: str) -> dict[str, object]:
    return {
        "kind": "StatefulSet",
        "name": name,
        "namespace": "example-app",
        "desired": 3,
        "ready": 2,
        "owner_reference_projection_complete": True,
        "owner_references": [
            {
                "api_version": "database.example.io/v1",
                "kind": "Database",
                "name": "primary",
                "uid": "owner-uid",
                "controller": True,
            }
        ],
    }
