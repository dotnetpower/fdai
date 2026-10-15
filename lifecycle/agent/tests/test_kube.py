from __future__ import annotations

from typing import Any
from unittest.mock import Mock

import pytest
from kubernetes.client.exceptions import ApiException  # type: ignore[import-untyped]

from fdai_lifecycle_agent import kube
from fdai_lifecycle_agent.workload import WorkloadError, render


def cluster(monkeypatch: pytest.MonkeyPatch) -> tuple[kube.KubernetesCluster, Any]:
    api = Mock()
    monkeypatch.setattr(kube.config, "new_client_from_config", lambda **_kwargs: Mock())
    monkeypatch.setattr(kube.dynamic, "DynamicClient", lambda _client: api)
    return kube.KubernetesCluster(context="kind-task-owned", namespace="fdai-test"), api


def deployment() -> kube.Manifest:
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
