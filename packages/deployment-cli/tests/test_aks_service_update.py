"""AKS service updates remain digest-pinned, targeted, and peer preserving."""

from __future__ import annotations

import copy
import json

import pytest

from fdai_deployment_cli.aks_service_update import (
    deployment_snapshot,
    peers_unchanged,
    validate_plan_scope,
    validate_update_request,
)

SERVICE = "core-control-plane"
OLD_IMAGE = "example.com/fdai/core@sha256:" + "a" * 64
NEW_IMAGE = "example.com/fdai/core@sha256:" + "b" * 64
SOURCE = "c" * 40


def _deployments() -> dict[str, object]:
    items = []
    for index, name in enumerate((SERVICE, "operator-service"), start=1):
        items.append(
            {
                "metadata": {"name": name, "uid": f"uid-{name}", "generation": index},
                "spec": {
                    "template": {
                        "metadata": {"labels": {"fdai.io/source-commit": SOURCE}},
                        "spec": {
                            "containers": [
                                {
                                    "name": name,
                                    "image": (
                                        OLD_IMAGE
                                        if name == SERVICE
                                        else OLD_IMAGE.replace("/core@", f"/{name}@")
                                    ),
                                }
                            ]
                        },
                    }
                },
            }
        )
    return {"kind": "DeploymentList", "items": items}


def test_update_request_accepts_one_new_digest_in_the_same_repository() -> None:
    validate_update_request(
        service=SERVICE, image=NEW_IMAGE, source_commit=SOURCE, current_image=OLD_IMAGE
    )


@pytest.mark.parametrize(
    ("service", "image", "source_commit", "current_image"),
    [
        ("unknown", NEW_IMAGE, SOURCE, OLD_IMAGE),
        (SERVICE, "example.com/fdai/core:latest", SOURCE, OLD_IMAGE),
        (SERVICE, NEW_IMAGE, "main", OLD_IMAGE),
        (SERVICE, NEW_IMAGE.replace("/core@", "/other@"), SOURCE, OLD_IMAGE),
        (SERVICE, OLD_IMAGE, SOURCE, OLD_IMAGE),
    ],
)
def test_update_request_rejects_unbounded_inputs(
    service: str, image: str, source_commit: str, current_image: str
) -> None:
    with pytest.raises(ValueError):
        validate_update_request(
            service=service,
            image=image,
            source_commit=source_commit,
            current_image=current_image,
        )


def test_deployment_snapshot_binds_each_service_rollout() -> None:
    snapshot = deployment_snapshot(
        json.dumps(_deployments()), expected_services={SERVICE, "operator-service"}
    )

    assert snapshot[SERVICE] == {
        "uid": f"uid-{SERVICE}",
        "generation": 1,
        "image": OLD_IMAGE,
        "source_commit": SOURCE,
    }


def test_deployment_snapshot_accepts_kubectl_generic_deployment_list() -> None:
    deployments = _deployments()
    deployments.update({"apiVersion": "v1", "kind": "List"})
    for item in deployments["items"]:  # type: ignore[union-attr]
        item.update({"apiVersion": "apps/v1", "kind": "Deployment"})

    snapshot = deployment_snapshot(
        json.dumps(deployments), expected_services={SERVICE, "operator-service"}
    )

    assert set(snapshot) == {SERVICE, "operator-service"}


def test_deployment_snapshot_rejects_generic_list_with_non_deployment_item() -> None:
    deployments = _deployments()
    deployments.update({"apiVersion": "v1", "kind": "List"})
    for item in deployments["items"]:  # type: ignore[union-attr]
        item.update({"apiVersion": "apps/v1", "kind": "Deployment"})
    deployments["items"][0]["kind"] = "StatefulSet"  # type: ignore[index]

    with pytest.raises(ValueError, match="snapshot is invalid"):
        deployment_snapshot(
            json.dumps(deployments), expected_services={SERVICE, "operator-service"}
        )


def test_deployment_snapshot_rejects_missing_or_duplicate_services() -> None:
    deployments = _deployments()
    deployments["items"].pop()  # type: ignore[union-attr]
    with pytest.raises(ValueError, match="missing"):
        deployment_snapshot(
            json.dumps(deployments), expected_services={SERVICE, "operator-service"}
        )


def test_plan_scope_accepts_only_selected_deployment_update() -> None:
    validate_plan_scope(
        {
            "resource_changes": [
                {
                    "address": f'kubernetes_deployment_v1.workload["{SERVICE}"]',
                    "actions": ["update"],
                },
                {"address": "kubernetes_namespace_v1.runtime", "actions": ["no-op"]},
            ]
        },
        service=SERVICE,
    )


@pytest.mark.parametrize(
    "change",
    [
        {"address": "kubernetes_service_v1.workload", "actions": ["update"]},
        {
            "address": f'kubernetes_deployment_v1.workload["{SERVICE}"]',
            "actions": ["delete", "create"],
        },
    ],
)
def test_plan_scope_rejects_other_or_replacing_mutations(change: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="out-of-scope"):
        validate_plan_scope({"resource_changes": [change]}, service=SERVICE)


def test_peer_snapshot_must_remain_exact() -> None:
    before = deployment_snapshot(
        json.dumps(_deployments()), expected_services={SERVICE, "operator-service"}
    )
    after = copy.deepcopy(before)
    after[SERVICE]["generation"] = 2
    after[SERVICE]["image"] = NEW_IMAGE
    assert peers_unchanged(before=before, after=after, service=SERVICE)

    after["operator-service"]["generation"] = 3
    assert not peers_unchanged(before=before, after=after, service=SERVICE)
