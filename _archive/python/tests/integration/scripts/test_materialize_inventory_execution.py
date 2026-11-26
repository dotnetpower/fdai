from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

import pytest
from scripts.deployment.azure.materialize_inventory_execution import (
    materialize_inventory_execution,
)

_TARGET_IMAGE = f"example.azurecr.io/fdai@sha256:{'a' * 64}"


def _job() -> dict[str, Any]:
    return {
        "properties": {
            "template": {
                "containers": [
                    {
                        "name": "inventory",
                        "image": f"example.azurecr.io/fdai@sha256:{'b' * 64}",
                        "command": [
                            "python",
                            "-m",
                            "fdai.delivery.inventory_sync_cli",
                        ],
                        "args": [],
                        "cpu": 0.5,
                        "memory": "1Gi",
                        "volumeMounts": [{"volumeName": "scratch", "mountPath": "/scratch"}],
                        "env": [
                            {"name": "FDAI_INVENTORY_DSN", "secretRef": "inventory-dsn"},
                            {"name": "FDAI_INVENTORY_SOURCES", "value": "azure"},
                        ],
                    }
                ],
                "initContainers": [
                    {
                        "name": "init",
                        "image": "example.azurecr.io/init:1",
                        "command": ["/bin/true"],
                    }
                ],
                "volumes": [{"name": "scratch", "storageType": "EmptyDir"}],
            }
        }
    }


def test_preserves_supported_execution_fields_and_changes_image() -> None:
    job = _job()
    original = copy.deepcopy(job["properties"]["template"])

    execution = materialize_inventory_execution(job, image=_TARGET_IMAGE)

    expected = {
        "containers": copy.deepcopy(original["containers"]),
        "initContainers": copy.deepcopy(original["initContainers"]),
    }
    expected["containers"][0]["image"] = _TARGET_IMAGE
    assert execution == expected
    assert job["properties"]["template"] == original


def test_omits_job_owned_fields_that_the_start_api_inherits() -> None:
    execution = materialize_inventory_execution(_job(), image=_TARGET_IMAGE)

    assert "volumes" not in execution
    assert execution["containers"][0]["volumeMounts"] == [
        {"volumeName": "scratch", "mountPath": "/scratch"}
    ]


@pytest.mark.parametrize(
    "mutate",
    (
        lambda job: job["properties"]["template"].update(containers=[]),
        lambda job: job["properties"]["template"]["containers"][0].update(
            command=["python", "-m", "other"]
        ),
        lambda job: job["properties"]["template"]["containers"][0].update(env=[]),
    ),
)
def test_rejects_a_noncanonical_inventory_template(
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    job = _job()
    mutate(job)

    with pytest.raises(ValueError, match="inventory Job"):
        materialize_inventory_execution(job, image=_TARGET_IMAGE)


def test_rejects_a_non_digest_image() -> None:
    with pytest.raises(ValueError, match="digest-pinned"):
        materialize_inventory_execution(_job(), image="example.azurecr.io/fdai:latest")


def test_rejects_malformed_init_containers() -> None:
    job = _job()
    job["properties"]["template"]["initContainers"] = {}

    with pytest.raises(ValueError, match="init containers"):
        materialize_inventory_execution(job, image=_TARGET_IMAGE)
