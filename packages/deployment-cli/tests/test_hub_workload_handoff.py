from __future__ import annotations

import json
from pathlib import Path

import pytest

from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.hub_workload_handoff import (
    WorkloadStateObject,
    build_handoff_inventory,
    read_handoff_inventory,
    verify_handoff_plan,
    verify_handoff_plans,
    write_handoff_operator_inputs,
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


def plan(
    actions: dict[str, list[str]],
    *,
    importing: dict[str, str] | None = None,
) -> dict[str, object]:
    changes = []
    for address, change_actions in actions.items():
        before = None if importing is not None else {"id": address}
        after = None if change_actions == ["forget"] else {"id": address}
        change: dict[str, object] = {
            "actions": change_actions,
            "before": before,
            "after": after,
        }
        if importing is not None:
            change["importing"] = {"id": importing[address]}
        changes.append({"address": address, "change": change})
    return {
        "format_version": "1.2",
        "complete": True,
        "errored": False,
        "applyable": any(value != ["no-op"] for value in actions.values()) or importing is not None,
        "resource_changes": changes,
        "resource_drift": [],
        "deferred_changes": [],
        "output_changes": {},
        "checks": [{"status": "pass"}],
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


def rendered_manifests() -> list[dict[str, object]]:
    return [
        {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "core-control-plane", "namespace": "fdai-runtime"},
            "spec": {"template": {}},
        },
        {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": "core-control-plane", "namespace": "fdai-runtime"},
            "spec": {"ports": []},
        },
        {
            "apiVersion": "batch/v1",
            "kind": "CronJob",
            "metadata": {"name": "inventory", "namespace": "fdai-runtime"},
            "spec": {"schedule": "0 * * * *"},
        },
        {
            "apiVersion": "autoscaling/v2",
            "kind": "HorizontalPodAutoscaler",
            "metadata": {"name": "core-control-plane", "namespace": "fdai-runtime"},
            "spec": {"minReplicas": 1},
        },
    ]


def native_scope() -> dict[str, object]:
    return {
        "installation_id": "installation-alpha",
        "entity_id": "fdai-workloads",
        "product": "fdai",
        "namespace": "fdai-runtime",
        "components": ["core-control-plane"],
        "service_components": ["core-control-plane"],
        "scheduled_components": ["inventory"],
        "autoscaled_components": ["core-control-plane"],
    }


def test_builds_exact_inventory_and_private_operator_inputs(tmp_path: Path) -> None:
    inventory = build_handoff_inventory(native_scope(), rendered_manifests())

    assert len(read_handoff_inventory(inventory)) == 4
    variables = inventory["terraform_variables"]
    assert isinstance(variables, dict)
    assert variables["deployments"] == {"core-control-plane": "fdai-runtime/core-control-plane"}
    assert variables["horizontal_pod_autoscalers"] == {
        "core-control-plane": "fdai-runtime/core-control-plane"
    }

    paths = write_handoff_operator_inputs(tmp_path, native_scope(), rendered_manifests())
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in paths)
    commands = paths[2].read_text(encoding="utf-8")
    assert "hub-workload-state-handoff/release" in commands
    assert "<rollback-import-plan>" in commands
    assert "--phase zero-change" in commands


def test_inventory_rejects_scope_or_digest_drift() -> None:
    with pytest.raises(ValueError, match="differs from the native scope"):
        build_handoff_inventory(native_scope(), rendered_manifests()[:-1])

    inventory = build_handoff_inventory(native_scope(), rendered_manifests())
    inventory["namespace"] = "other"
    with pytest.raises(ValueError, match="inventory is invalid"):
        read_handoff_inventory(inventory)


def test_exact_import_release_and_zero_change_plan_phases() -> None:
    expected = objects()
    import_ids = {item.address: item.import_id for item in expected}
    import_receipt = verify_handoff_plan(
        plan(
            {item.address: ["no-op"] for item in expected},
            importing=import_ids,
        ),
        expected,
        phase="import",
        inventory_digest=DIGEST,
    )
    release_receipt = verify_handoff_plan(
        plan({item.address: ["forget"] for item in expected}),
        expected,
        phase="release",
        inventory_digest=DIGEST,
    )
    zero_receipt = verify_handoff_plan(
        plan({item.address: ["no-op"] for item in expected}),
        expected,
        phase="zero-change",
        inventory_digest=DIGEST,
    )

    assert import_receipt["state_effect"] == "import-only"
    assert release_receipt["state_effect"] == "forgotten-without-destroy"
    assert zero_receipt["state_effect"] == "zero-change"
    assert all(
        receipt["live_mutation_authorized"] is False
        for receipt in (import_receipt, release_receipt, zero_receipt)
    )


def test_import_accepts_terraform_1_9_existing_object_readback() -> None:
    expected = objects()
    imported = plan(
        {item.address: ["no-op"] for item in expected},
        importing={item.address: item.import_id for item in expected},
    )
    for resource in imported["resource_changes"]:
        resource["change"]["before"] = resource["change"]["after"]

    receipt = verify_handoff_plan(
        imported,
        expected,
        phase="import",
        inventory_digest=DIGEST,
    )

    assert receipt["state_effect"] == "import-only"


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
        (["forget"], ["update"], "metadata|zero-change"),
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

    with pytest.raises(ValueError, match="inventory differs"):
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


@pytest.mark.parametrize(
    ("phase", "damage", "message"),
    [
        ("import", "changed-id", "import-only"),
        ("release", "delete", "forget-only"),
        ("zero-change", "missing", "inventory differs"),
        ("zero-change", "drift", "metadata"),
        ("zero-change", "move", "resource change"),
    ],
)
def test_plan_verifier_rejects_unsafe_or_incomplete_plans(
    phase: str,
    damage: str,
    message: str,
) -> None:
    expected = objects()
    import_ids = {item.address: item.import_id for item in expected}
    if phase == "import":
        candidate = plan(
            {item.address: ["no-op"] for item in expected},
            importing=import_ids,
        )
    elif phase == "release":
        candidate = plan({item.address: ["forget"] for item in expected})
    else:
        candidate = plan({item.address: ["no-op"] for item in expected})
    if damage == "changed-id":
        candidate["resource_changes"][0]["change"]["importing"]["id"] = "other"
    elif damage == "delete":
        candidate["resource_changes"][0]["change"]["actions"] = ["delete"]
    elif damage == "missing":
        candidate["resource_changes"].pop()
    elif damage == "drift":
        candidate["resource_drift"] = [{"address": expected[0].address}]
    else:
        candidate["resource_changes"][0]["previous_address"] = "old.address"

    with pytest.raises(ValueError, match=message):
        verify_handoff_plan(
            candidate,
            expected,
            phase=phase,
            inventory_digest=DIGEST,
        )
