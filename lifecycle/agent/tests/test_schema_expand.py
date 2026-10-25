from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fdai_deployment_cli.lifecycle_release import SchemaExpandMigration

from fdai_lifecycle_agent.schema_expand import render_schema_expand_job
from fdai_lifecycle_agent.workload import Workload, WorkloadError, render

if TYPE_CHECKING:
    from conftest import FakeCluster


def test_schema_expand_job_uses_core_image_and_reviewed_references() -> None:
    desired = render(
        "fdai-demo",
        {
            (
                "application",
                "core-control-plane",
            ): "example.azurecr.io/core@sha256:" + "a" * 64
        },
    )
    deployment = next(item for item in desired if item["kind"] == "Deployment")
    pod = deployment["spec"]["template"]["spec"]
    pod["containers"][0]["env"] = [
        {
            "name": "FDAI_DATABASE_URL",
            "valueFrom": {
                "secretKeyRef": {
                    "name": "fdai-schema-migration-database",
                    "key": "FDAI_DATABASE_URL",
                    "optional": False,
                }
            },
        }
    ]
    migration = SchemaExpandMigration({"revision_2": "expand"}, 1800)

    job = render_schema_expand_job(
        desired,
        migration,
        namespace="fdai-demo",
        plan_digest="b" * 64,
        release_digest="sha256:" + "c" * 64,
        schema_target=2,
    )

    assert job["kind"] == "Job"
    assert job["metadata"]["annotations"]["fdai.io/schema-target"] == "2"
    assert job["spec"]["activeDeadlineSeconds"] == 1800
    job_pod = job["spec"]["template"]["spec"]
    assert job_pod["serviceAccountName"] == "fdai-schema-migration"
    assert job_pod["automountServiceAccountToken"] is True
    container = job_pod["containers"][0]
    assert container["image"] == deployment["spec"]["template"]["spec"]["containers"][0]["image"]
    assert container["command"] == ["python", "-m", "fdai.delivery.lifecycle_schema_expand"]
    assert any(item["name"] == "FDAI_DATABASE_URL" for item in container["env"])
    assert any(item["name"] == "FDAI_MIGRATION_CLASSIFICATION" for item in container["env"])


def test_completed_schema_expand_job_is_retained_as_receipt_and_not_reversed(
    cluster: FakeCluster,
) -> None:
    desired = render(
        cluster.namespace,
        {
            (
                "application",
                "core-control-plane",
            ): "example.azurecr.io/core@sha256:" + "a" * 64
        },
    )
    deployment = next(item for item in desired if item["kind"] == "Deployment")
    deployment["spec"]["template"]["spec"]["containers"][0]["env"] = [
        {
            "name": "FDAI_DATABASE_URL",
            "valueFrom": {
                "secretKeyRef": {
                    "name": "fdai-schema-migration-database",
                    "key": "FDAI_DATABASE_URL",
                    "optional": False,
                }
            },
        }
    ]
    job = render_schema_expand_job(
        desired,
        SchemaExpandMigration({"revision_2": "expand"}, 1800),
        namespace=cluster.namespace,
        plan_digest="b" * 64,
        release_digest="sha256:" + "c" * 64,
        schema_target=2,
    )
    workload = Workload(
        cluster=cluster,
        namespace=cluster.namespace,
        health_timeout_seconds=1,
        poll_interval_seconds=0,
        sleep=lambda _: None,
    )

    assert workload.apply((job, *desired)) is True
    assert cluster.get("Job", job["metadata"]["name"]) is not None
    assert workload.completed_schema_revision((job, *desired)) == 2
    assert workload.roll_back((job, *desired), ()) is True
    assert cluster.get("Job", job["metadata"]["name"]) is not None
    assert cluster.get("Deployment", "core-control-plane") is None


def test_failed_schema_expand_job_blocks_workload_switch(cluster: FakeCluster) -> None:
    desired = render(
        cluster.namespace,
        {
            (
                "application",
                "core-control-plane",
            ): "example.azurecr.io/core@sha256:" + "a" * 64
        },
    )
    deployment = next(item for item in desired if item["kind"] == "Deployment")
    deployment["spec"]["template"]["spec"]["containers"][0]["env"] = [
        {
            "name": "FDAI_DATABASE_URL",
            "valueFrom": {
                "secretKeyRef": {
                    "name": "fdai-schema-migration-database",
                    "key": "FDAI_DATABASE_URL",
                    "optional": False,
                }
            },
        }
    ]
    job = render_schema_expand_job(
        desired,
        SchemaExpandMigration({"revision_2": "expand"}, 1800),
        namespace=cluster.namespace,
        plan_digest="b" * 64,
        release_digest="sha256:" + "c" * 64,
        schema_target=2,
    )
    cluster.schema_status = "Failed"
    workload = Workload(
        cluster=cluster,
        namespace=cluster.namespace,
        health_timeout_seconds=1,
        poll_interval_seconds=0,
        sleep=lambda _: None,
    )

    with pytest.raises(WorkloadError, match="schema_check_failed"):
        workload.apply((job, *desired))

    assert cluster.get("Job", job["metadata"]["name"]) is not None
    assert cluster.get("Deployment", "core-control-plane") is None
