from __future__ import annotations

from pathlib import Path

import yaml

DEPLOY = Path(__file__).resolve().parents[1] / "deploy"


def test_rbac_is_only_the_adapters_namespace_operations() -> None:
    documents = list(yaml.safe_load_all((DEPLOY / "namespace-rbac.yaml").read_text()))
    assert {document["kind"] for document in documents} == {
        "Namespace",
        "ServiceAccount",
        "Role",
        "RoleBinding",
    }
    role = next(document for document in documents if document["kind"] == "Role")
    assert role["metadata"]["namespace"] == "fdai-nginx-dev"
    assert {(rule["apiGroups"][0], rule["resources"][0]) for rule in role["rules"]} == {
        ("apps", "deployments"),
        ("", "services"),
        ("batch", "jobs"),
    }
    assert all(set(rule["verbs"]) == {"get", "create", "patch", "delete"} for rule in role["rules"])
    binding = next(document for document in documents if document["kind"] == "RoleBinding")
    assert binding["metadata"]["namespace"] == role["metadata"]["namespace"]
    assert binding["roleRef"]["kind"] == "Role"
    assert binding["subjects"] == [
        {"kind": "ServiceAccount", "name": "fdai-lifecycle-agent", "namespace": "fdai-agent-system"}
    ]


def test_durable_journal_volume_is_outside_workload_namespace() -> None:
    volume = yaml.safe_load((DEPLOY / "state-volume.yaml").read_text())
    assert volume["kind"] == "PersistentVolumeClaim"
    assert volume["metadata"]["namespace"] == "fdai-agent-system"
    assert volume["spec"]["accessModes"] == ["ReadWriteOnce"]
    assert volume["spec"]["resources"]["requests"]["storage"] == "4Gi"


def test_scheduled_permissions_are_opt_in_namespace_only_and_existing_names_are_fenced() -> None:
    documents = list(yaml.safe_load_all((DEPLOY / "scheduled-runtime-rbac.yaml").read_text()))
    assert [document["kind"] for document in documents] == ["Role", "RoleBinding"]
    role, binding = documents
    assert role["metadata"]["namespace"] == binding["metadata"]["namespace"] == "example-test"
    assert binding["roleRef"]["kind"] == "Role"
    for rule in role["rules"]:
        assert rule["apiGroups"] == ["batch"]
        assert rule["resources"] == ["cronjobs"]
        assert not set(rule["verbs"]) - {"get", "create", "patch", "delete"}
        if "create" in rule["verbs"]:
            assert rule["verbs"] == ["create"]
        else:
            assert rule["resourceNames"] == ["analyzer", "inventory", "self-review"]
