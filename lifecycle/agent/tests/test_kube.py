from __future__ import annotations

from typing import Any
from unittest.mock import Mock

import pytest
from kubernetes import config, dynamic  # type: ignore[import-untyped]
from kubernetes.client.exceptions import ApiException  # type: ignore[import-untyped]

from fdai_lifecycle_agent import kube
from fdai_lifecycle_agent.workload import (
    CreationRejectedError,
    Manifest,
    MutationNotSubmittedError,
    WorkloadError,
    render,
)


def cluster(monkeypatch: pytest.MonkeyPatch) -> tuple[kube.KubernetesCluster, Any]:
    api = Mock()
    monkeypatch.setattr(config, "new_client_from_config", lambda **_kwargs: Mock())
    monkeypatch.setattr(dynamic, "DynamicClient", lambda _client: api)
    return kube.KubernetesCluster(context="kind-task-owned", namespace="fdai-test"), api


def deployment() -> Manifest:
    return render(
        "fdai-test", {("operator", "operator-service"): "example.test/operator@sha256:" + "a" * 64}
    )[0]


def test_server_side_apply_never_takes_another_writers_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, api = cluster(monkeypatch)
    client.apply(deployment(), dry_run=True)
    assert api.server_side_apply.call_args.kwargs["force_conflicts"] is False
    assert api.server_side_apply.call_args.kwargs["dry_run"] == "All"
    api.server_side_apply.side_effect = ApiException(status=409)
    with pytest.raises(WorkloadError, match="kubernetes_request_rejected"):
        client.apply(deployment())


def test_a_write_404_is_failure_but_a_missing_read_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, api = cluster(monkeypatch)
    api.server_side_apply.side_effect = ApiException(status=404)
    with pytest.raises(WorkloadError, match="kubernetes_request_rejected"):
        client.apply(deployment())
    api.get.side_effect = ApiException(status=404)
    assert client.get("Deployment", "operator-service") is None


def test_adapter_refuses_external_services(monkeypatch: pytest.MonkeyPatch) -> None:
    client, api = cluster(monkeypatch)
    service = render(
        "fdai-test", {("operator", "operator-service"): "example.test/operator@sha256:" + "a" * 64}
    )[1]
    service["spec"]["type"] = "LoadBalancer"
    with pytest.raises(WorkloadError, match="workload_outside_scope"):
        client.apply(service)
    api.server_side_apply.assert_not_called()


def test_in_cluster_uses_separate_configuration_without_kubeconfig(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load = Mock()
    client = Mock()
    kubeconfig = Mock(side_effect=AssertionError("unexpected kubeconfig fallback"))
    monkeypatch.setattr(config, "load_incluster_config", load)
    monkeypatch.setattr(config, "new_client_from_config", kubeconfig)
    monkeypatch.setattr(kube, "ApiClient", client)
    kube.KubernetesCluster(in_cluster=True, namespace="fdai-test")
    load.assert_called_once()
    assert client.call_args.kwargs["configuration"] is load.call_args.kwargs["client_configuration"]
    kubeconfig.assert_not_called()


@pytest.mark.parametrize("context,in_cluster", [(None, False), ("kind-test", True)])
def test_authentication_modes_are_exclusive(context: str | None, in_cluster: bool) -> None:
    with pytest.raises(ValueError, match="exactly one"):
        kube.KubernetesCluster(context=context, in_cluster=in_cluster, namespace="fdai-test")


def test_failed_in_cluster_authentication_does_not_fall_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fallback = Mock()
    monkeypatch.setattr(config, "new_client_from_config", fallback)
    monkeypatch.setattr(
        config, "load_incluster_config", Mock(side_effect=config.ConfigException("bad"))
    )
    with pytest.raises(ValueError, match="authentication is unusable"):
        kube.KubernetesCluster(in_cluster=True, namespace="fdai-test")
    fallback.assert_not_called()


def test_create_only_uses_post_and_propagates_name_conflict(monkeypatch):
    client, api = cluster(monkeypatch)
    api.create.return_value.to_dict.return_value = {"metadata": {"uid": "created"}}
    assert client.create(deployment(), dry_run=True)["metadata"]["uid"] == "created"
    assert api.create.call_args.kwargs["dry_run"] == "All"
    api.create.side_effect = ApiException(status=409)
    with pytest.raises(WorkloadError, match="kubernetes_request_rejected"):
        client.create(deployment())
    api.server_side_apply.assert_not_called()


@pytest.mark.parametrize("status", [400, 401, 403, 404, 405, 409, 413, 415, 422, 429])
def test_create_explicit_api_rejection_confirms_no_effect(monkeypatch, status):
    client, api = cluster(monkeypatch)
    api.create.side_effect = ApiException(status=status)
    with pytest.raises(CreationRejectedError, match="kubernetes_request_rejected"):
        client.create(deployment())


@pytest.mark.parametrize("status", [None, 408, 500, 503, 504])
def test_create_ambiguous_failure_never_confirms_no_effect(monkeypatch, status):
    client, api = cluster(monkeypatch)
    api.create.side_effect = ApiException(status=status)
    with pytest.raises(WorkloadError) as failure:
        client.create(deployment())
    assert not isinstance(failure.value, CreationRejectedError)


def test_replace_binds_uid_and_resource_version_and_conflict_never_falls_back(monkeypatch):
    client, api = cluster(monkeypatch)
    api.get.return_value.to_dict.return_value = {
        "metadata": {"uid": "owned", "resourceVersion": "7"}
    }
    client.replace_owned(deployment(), "owned", dry_run=True)
    request = api.patch.call_args.kwargs
    assert request["content_type"] == "application/json-patch+json"
    assert request["body"][:2] == [
        {"op": "test", "path": "/metadata/uid", "value": "owned"},
        {"op": "test", "path": "/metadata/resourceVersion", "value": "7"},
    ]
    assert request["dry_run"] == "All"
    api.patch.side_effect = ApiException(status=409)
    with pytest.raises(WorkloadError, match="kubernetes_request_rejected"):
        client.replace_owned(deployment(), "owned")
    api.create.assert_not_called()
    api.server_side_apply.assert_not_called()


def test_foreign_uid_prevents_replace_and_service_retains_assigned_defaults(monkeypatch):
    client, api = cluster(monkeypatch)
    api.get.return_value.to_dict.return_value = {
        "metadata": {"uid": "foreign", "resourceVersion": "7"}
    }
    with pytest.raises(WorkloadError, match="native_resource_identity_changed"):
        client.replace_owned(deployment(), "owned")
    api.patch.assert_not_called()
    service = render(
        "fdai-test", {("operator", "operator-service"): "example.test/operator@sha256:" + "a" * 64}
    )[1]
    defaults = {
        "clusterIP": "10.0.0.10",
        "clusterIPs": ["10.0.0.10"],
        "ipFamilies": ["IPv4"],
        "ipFamilyPolicy": "SingleStack",
    }
    api.get.return_value.to_dict.return_value = {
        "metadata": {"uid": "owned", "resourceVersion": "8"},
        "spec": defaults,
    }
    client.replace_owned(service, "owned")
    spec = api.patch.call_args.kwargs["body"][-1]
    assert spec["op"] == "replace" and spec["path"] == "/spec"
    assert spec["value"].items() >= defaults.items()


def test_native_delete_uses_api_server_uid_precondition(monkeypatch):
    client, api = cluster(monkeypatch)
    client.delete_owned("Deployment", "operator-service", "owned")
    assert api.delete.call_args.kwargs["body"] == {
        "apiVersion": "v1",
        "kind": "DeleteOptions",
        "preconditions": {"uid": "owned"},
    }
    api.delete.side_effect = ApiException(status=409)
    with pytest.raises(WorkloadError, match="kubernetes_request_rejected"):
        client.delete_owned("Deployment", "operator-service", "owned")


@pytest.mark.parametrize(
    ("operation", "pause"),
    [
        ("create", "discovery"),
        ("replace", "discovery"),
        ("replace", "owned-read"),
        ("delete", "discovery"),
    ],
)
def test_submission_guard_runs_after_blocking_provider_preparation(monkeypatch, operation, pause):
    client, api = cluster(monkeypatch)
    expired = [False]
    resource = Mock()
    live = Mock()
    live.to_dict.return_value = {"metadata": {"uid": "owned", "resourceVersion": "7"}}

    def discover(**kwargs):
        if pause == "discovery":
            expired[0] = True
        return resource

    def read(*args, **kwargs):
        if pause == "owned-read":
            expired[0] = True
        return live

    def require_current():
        if expired[0]:
            raise MutationNotSubmittedError("native_scope_approval_expired")

    api.resources.get.side_effect = discover
    api.get.side_effect = read
    with pytest.raises(MutationNotSubmittedError, match="native_scope_approval_expired"):
        if operation == "create":
            client.create(deployment(), before_submit=require_current)
        elif operation == "replace":
            client.replace_owned(deployment(), "owned", before_submit=require_current)
        else:
            client.delete_owned(
                "Deployment", "operator-service", "owned", before_submit=require_current
            )
    api.create.assert_not_called()
    api.patch.assert_not_called()
    api.delete.assert_not_called()
