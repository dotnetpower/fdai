from __future__ import annotations

import json
from pathlib import Path

import pytest

from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.hub_workload_handoff import (
    WorkloadStateObject,
    verify_handoff_plans,
    write_handoff_terraform_files,
)

DIGEST = "sha256:" + "a" * 64


def objects() -> tuple[WorkloadStateObject, ...]:
    return (
        WorkloadStateObject(
            'kubernetes_deployment_v1.workload["core-control-plane"]',
            "fdai-runtime/core-control-plane",
            DIGEST,
        ),
        WorkloadStateObject(
            'kubernetes_service_v1.workload["core-control-plane"]',
            "fdai-runtime/core-control-plane",
            DIGEST,
        ),
    )


def plan(actions: dict[str, list[str]]) -> dict[str, object]:
    return {
        "format_version": "1.2",
        "resource_changes": [
            {"address": address, "change": {"actions": change}}
            for address, change in actions.items()
        ],
    }


def adoption_release() -> dict[str, object]:
    body: dict[str, object] = {
        "schema_version": "fdai.runtime-adoption-release.v1",
        "installation_id": "installation-alpha",
        "release_id": "release-1",
        "adoption_receipt_digest": DIGEST,
        "reconciliation_released": True,
    }
    return body | {"receipt_digest": "sha256:" + canonical_digest(body)}


def test_handoff_files_use_destroy_false_and_exact_rollback_imports(tmp_path: Path) -> None:
    release_path, rollback_path = write_handoff_terraform_files(
        tmp_path / "handoff",
        objects(),
    )

    release = json.loads(release_path.read_text())
    rollback = json.loads(rollback_path.read_text())
    assert all(item["lifecycle"] == {"destroy": False} for item in release["removed"])
    assert [item["from"] for item in release["removed"]] == [
        '${kubernetes_deployment_v1.workload["core-control-plane"]}',
        '${kubernetes_service_v1.workload["core-control-plane"]}',
    ]
    assert [item["to"] for item in rollback["import"]] == [
        '${kubernetes_deployment_v1.workload["core-control-plane"]}',
        '${kubernetes_service_v1.workload["core-control-plane"]}',
    ]
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in (release_path, rollback_path))


def test_exact_forget_and_zero_change_plans_create_receipt() -> None:
    expected = objects()
    release = plan({item.address: ["forget"] for item in expected})
    rollback = plan({item.address: ["no-op"] for item in expected})

    receipt = verify_handoff_plans(
        release,
        rollback,
        expected,
        adoption_release=adoption_release(),
    )

    assert receipt["release_state"] == "forgotten-without-destroy"
    assert receipt["rollback_state"] == "zero-change"
    assert str(receipt["receipt_digest"]).startswith("sha256:")


@pytest.mark.parametrize(
    ("release_actions", "rollback_actions", "message"),
    [
        (["delete"], ["no-op"], "forget-only"),
        (["update"], ["no-op"], "forget-only"),
        (["forget"], ["update"], "zero-change"),
    ],
)
def test_handoff_plan_rejects_destroy_update_or_rollback_drift(
    release_actions: list[str],
    rollback_actions: list[str],
    message: str,
) -> None:
    expected = objects()

    with pytest.raises(ValueError, match=message):
        verify_handoff_plans(
            plan({item.address: release_actions for item in expected}),
            plan({item.address: rollback_actions for item in expected}),
            expected,
            adoption_release=adoption_release(),
        )


def test_handoff_plan_rejects_unknown_or_missing_object() -> None:
    expected = objects()
    release = plan({expected[0].address: ["forget"]})
    rollback = plan(
        {
            expected[0].address: ["no-op"],
            'kubernetes_deployment_v1.workload["unknown"]': ["no-op"],
        }
    )

    with pytest.raises(ValueError, match="forget-only"):
        verify_handoff_plans(
            release,
            rollback,
            expected,
            adoption_release=adoption_release(),
        )


def test_rollback_plan_requires_agent_reconciliation_release() -> None:
    expected = objects()
    release = plan({item.address: ["forget"] for item in expected})
    rollback = plan({item.address: ["no-op"] for item in expected})
    invalid = adoption_release()
    invalid["reconciliation_released"] = False

    with pytest.raises(ValueError, match="reconciliation release"):
        verify_handoff_plans(
            release,
            rollback,
            expected,
            adoption_release=invalid,
        )
