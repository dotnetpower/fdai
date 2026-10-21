from __future__ import annotations

from typing import Any
from unittest.mock import Mock

import pytest
from kubernetes import config, dynamic  # type: ignore[import-untyped]
from kubernetes.client.exceptions import ApiException  # type: ignore[import-untyped]

from fdai_lifecycle_agent import kube
from fdai_lifecycle_agent.workload import Manifest, WorkloadError, render


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
