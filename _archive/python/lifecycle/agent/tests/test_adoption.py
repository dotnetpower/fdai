from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from fdai_lifecycle_agent.adoption import (
    AdoptionExpectation,
    adopt_runtime_objects,
    adoption_source_digest,
    release_adoption_reconciliation,
)
from fdai_lifecycle_agent.kube import KubernetesCluster
from fdai_lifecycle_agent.workload import FIELD_MANAGER, Manifest, WorkloadError


def _manifest(name: str) -> Manifest:
    labels = {
        "app.kubernetes.io/managed-by": FIELD_MANAGER,
        "fdai.io/entity": "application",
        "fdai.io/component": name,
    }
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": name,
            "namespace": "fdai-demo",
            "labels": labels,
        },
        "spec": {
            "replicas": 1,
            "selector": {"matchLabels": {"fdai.io/component": name}},
            "template": {
                "metadata": {"labels": labels},
                "spec": {"containers": [{"name": name, "image": "example.invalid/image"}]},
            },
        },
    }


class _Cluster:
    def __init__(self) -> None:
        self.objects = {
            ("Deployment", "first"): {"metadata": {"uid": "uid-first", "resourceVersion": "1"}},
            ("Deployment", "second"): {"metadata": {"uid": "uid-second", "resourceVersion": "1"}},
        }
        self.adopted: list[tuple[str, str]] = []
        self.adopted_versions: list[str] = []
        self.fail_name: str | None = None

    def get(self, kind: str, name: str) -> Manifest | None:
        return self.objects.get((kind, name))

    def adopt_terraform_owned(
        self,
        manifest: Manifest,
        *,
        uid: str,
        resource_version: str,
    ) -> Manifest:
        key = manifest["kind"], manifest["metadata"]["name"]
        if key[1] == self.fail_name:
            raise WorkloadError("injected")
        self.adopted.append(key)
        self.adopted_versions.append(resource_version)
        self.objects[key] = {"metadata": {"uid": uid, "resourceVersion": "2"}}
        return self.objects[key]


def _expectations() -> tuple[AdoptionExpectation, ...]:
    return (
        AdoptionExpectation("Deployment", "first", "uid-first", "1"),
        AdoptionExpectation("Deployment", "second", "uid-second", "1"),
    )


def test_adoption_records_exact_per_object_receipts(tmp_path: Path) -> None:
    cluster = _Cluster()
    destination = tmp_path / "adoption-receipt.json"

    receipt = adopt_runtime_objects(
        cluster,
        (_manifest("first"), _manifest("second")),
        _expectations(),
        installation_id="installation-alpha",
        release_id="release-1",
        destination=destination,
    )

    assert receipt["complete"] is True
    assert [item["uid"] for item in receipt["objects"]] == ["uid-first", "uid-second"]
    assert all(str(item["render_digest"]).startswith("sha256:") for item in receipt["objects"])
    assert all(item["resource_version"] == "2" for item in receipt["objects"])
    assert destination.stat().st_mode & 0o777 == 0o600


def test_status_only_resource_version_change_rebinds_before_adoption(tmp_path: Path) -> None:
    cluster = _Cluster()
    live = cluster.objects[("Deployment", "first")]
    expectation = AdoptionExpectation(
        "Deployment",
        "first",
        "uid-first",
        "1",
        adoption_source_digest(live),
    )
    live["metadata"]["resourceVersion"] = "2"

    adopt_runtime_objects(
        cluster,
        (_manifest("first"),),
        (expectation,),
        installation_id="installation-alpha",
        release_id="release-1",
        destination=tmp_path / "adoption-receipt.json",
    )

    assert cluster.adopted_versions == ["2"]


def test_interrupted_adoption_resumes_after_last_receipt(tmp_path: Path) -> None:
    cluster = _Cluster()
    cluster.fail_name = "second"
    destination = tmp_path / "adoption-receipt.json"

    with pytest.raises(WorkloadError, match="injected"):
        adopt_runtime_objects(
            cluster,
            (_manifest("first"), _manifest("second")),
            _expectations(),
            installation_id="installation-alpha",
            release_id="release-1",
            destination=destination,
        )

    partial = json.loads(destination.read_text())
    assert partial["complete"] is False
    assert [item["name"] for item in partial["objects"]] == ["first"]
    cluster.fail_name = None
    receipt = adopt_runtime_objects(
        cluster,
        (_manifest("first"), _manifest("second")),
        _expectations(),
        installation_id="installation-alpha",
        release_id="release-1",
        destination=destination,
    )
    assert receipt["complete"] is True
    assert cluster.adopted == [("Deployment", "first"), ("Deployment", "second")]


def test_resume_refuses_drift_after_a_retained_object_receipt(tmp_path: Path) -> None:
    cluster = _Cluster()
    cluster.fail_name = "second"
    destination = tmp_path / "adoption-receipt.json"
    with pytest.raises(WorkloadError, match="injected"):
        adopt_runtime_objects(
            cluster,
            (_manifest("first"), _manifest("second")),
            _expectations(),
            installation_id="installation-alpha",
            release_id="release-1",
            destination=destination,
        )
    cluster.fail_name = None
    cluster.objects[("Deployment", "first")]["metadata"]["resourceVersion"] = "3"
    cluster.objects[("Deployment", "first")]["spec"] = {"replicas": 2}

    with pytest.raises(WorkloadError, match="adoption_resource_drifted"):
        adopt_runtime_objects(
            cluster,
            (_manifest("first"), _manifest("second")),
            _expectations(),
            installation_id="installation-alpha",
            release_id="release-1",
            destination=destination,
        )

    assert cluster.adopted == [("Deployment", "first")]


def test_reconciliation_release_requires_complete_adoption_receipt(tmp_path: Path) -> None:
    cluster = _Cluster()
    adoption_path = tmp_path / "adoption-receipt.json"
    adopt_runtime_objects(
        cluster,
        (_manifest("first"), _manifest("second")),
        _expectations(),
        installation_id="installation-alpha",
        release_id="release-1",
        destination=adoption_path,
    )

    release = release_adoption_reconciliation(
        adoption_path,
        destination=tmp_path / "adoption-release.json",
    )

    assert release["reconciliation_released"] is True
    assert release["adoption_receipt_digest"].startswith("sha256:")


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("missing", "adoption_object_unknown"),
        ("drift", "adoption_resource_drifted"),
    ],
)
def test_adoption_refuses_unknown_or_drifted_objects(
    tmp_path: Path,
    mutation: str,
    reason: str,
) -> None:
    cluster = _Cluster()
    if mutation == "missing":
        cluster.objects.pop(("Deployment", "first"))
    else:
        cluster.objects[("Deployment", "first")]["metadata"]["resourceVersion"] = "9"

    with pytest.raises(WorkloadError, match=reason):
        adopt_runtime_objects(
            cluster,
            (_manifest("first"), _manifest("second")),
            _expectations(),
            installation_id="installation-alpha",
            release_id="release-1",
            destination=tmp_path / "adoption-receipt.json",
        )

    assert cluster.adopted == []


@pytest.mark.parametrize(
    "managed_fields",
    [[], [{"manager": "Terraform"}], [{"manager": "HashiCorp"}]],
    ids=["legacy-empty", "terraform", "hashicorp-provider"],
)
def test_kubernetes_adoption_forces_only_a_terraform_managed_object(
    managed_fields: list[dict[str, str]],
) -> None:
    cluster = object.__new__(KubernetesCluster)
    cluster._namespace = "fdai-demo"
    cluster._timeout = 10
    cluster.get = Mock(
        return_value={
            "metadata": {
                "uid": "uid-first",
                "resourceVersion": "1",
                "managedFields": managed_fields,
            }
        }
    )
    client = Mock()
    resource = Mock()
    adopted = Mock()
    adopted.to_dict.return_value = {"metadata": {"uid": "uid-first", "resourceVersion": "2"}}
    client.server_side_apply.return_value = adopted
    cluster._call = Mock(side_effect=lambda _kind, callback, **_kwargs: callback(client, resource))

    result = cluster.adopt_terraform_owned(
        _manifest("first"),
        uid="uid-first",
        resource_version="1",
    )

    assert result["metadata"]["resourceVersion"] == "2"
    assert client.server_side_apply.call_args.kwargs["force_conflicts"] is True
    assert (
        client.server_side_apply.call_args.kwargs["body"]["metadata"]["annotations"][
            "fdai.io/adopted-from"
        ]
        == "Terraform"
    )


def test_kubernetes_adoption_refuses_another_field_manager() -> None:
    cluster = object.__new__(KubernetesCluster)
    cluster._namespace = "fdai-demo"
    cluster._timeout = 10
    cluster.get = Mock(
        return_value={
            "metadata": {
                "uid": "uid-first",
                "resourceVersion": "1",
                "managedFields": [
                    {"manager": "Terraform"},
                    {"manager": "another-writer"},
                ],
            }
        }
    )
    cluster._call = Mock()

    with pytest.raises(WorkloadError, match="adoption_field_manager_conflict"):
        cluster.adopt_terraform_owned(
            _manifest("first"),
            uid="uid-first",
            resource_version="1",
        )

    cluster._call.assert_not_called()
