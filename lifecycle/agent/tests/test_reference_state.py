from __future__ import annotations

import copy
import json
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
from fdai_deployment_cli.contracts import canonical_digest
from kubernetes import client as kubernetes_client  # type: ignore[import-untyped]
from kubernetes.client.exceptions import ApiException  # type: ignore[import-untyped]
from kubernetes.client.rest import RESTResponse  # type: ignore[import-untyped]
from urllib3.response import HTTPResponse

from fdai_lifecycle_agent import cli, kube
from fdai_lifecycle_agent.reference_state import (
    CSIReference,
    ReferenceReadBudget,
    observe_reference,
)
from fdai_lifecycle_agent.workload import WorkloadError

NOW = datetime(2026, 10, 21, tzinfo=UTC)
REFERENCE = CSIReference(
    entity_id="core",
    namespace="fdai-test",
    pod_name="core-pod",
    pod_uid="synthetic-pod-uid",
    class_name="core-secrets",
    status_name="core-status",
    object_id="secret/example-reference",
    object_version="synthetic-version",
    source_manager="secrets-store-csi-driver",
)


def documents() -> dict[str, dict[str, Any]]:
    return {
        "SecretProviderClassPodStatus": {
            "metadata": {
                "name": REFERENCE.status_name,
                "namespace": REFERENCE.namespace,
                "resourceVersion": "42",
                "ownerReferences": [{"kind": "Pod", "uid": REFERENCE.pod_uid}],
                "managedFields": [
                    {
                        "manager": REFERENCE.source_manager,
                        "time": NOW.isoformat(),
                    }
                ],
            },
            "status": {
                "mounted": True,
                "podName": REFERENCE.pod_name,
                "secretProviderClassName": REFERENCE.class_name,
                "objects": [{"id": REFERENCE.object_id, "version": REFERENCE.object_version}],
                "targetPath": "/never-read/mounted-secret",
            },
        },
        "Pod": {
            "metadata": {
                "name": REFERENCE.pod_name,
                "namespace": REFERENCE.namespace,
                "uid": REFERENCE.pod_uid,
                "labels": {"fdai.io/entity": REFERENCE.entity_id},
            },
            "spec": {
                "volumes": [
                    {
                        "csi": {
                            "driver": "secrets-store.csi.k8s.io",
                            "volumeAttributes": {"secretProviderClass": REFERENCE.class_name},
                        }
                    }
                ]
            },
        },
        "SecretProviderClass": {
            "metadata": {"name": REFERENCE.class_name, "namespace": REFERENCE.namespace},
            "spec": {"provider": "azure"},
        },
    }


def bind(
    monkeypatch: pytest.MonkeyPatch, docs: dict[str, dict[str, Any]]
) -> tuple[kube.KubernetesCluster, Mock]:
    api = Mock()
    monkeypatch.setattr(
        "fdai_lifecycle_agent.kube.config.new_client_from_config", lambda **_kwargs: api
    )

    def get(path: str, method: str, **kwargs: Any) -> dict[str, Any]:
        assert method == "GET"
        kinds = {
            "pods": "Pod",
            "secretproviderclasses": "SecretProviderClass",
            "secretproviderclasspodstatuses": "SecretProviderClassPodStatus",
        }
        plural = path.split("/")[-2]
        assert plural in kinds, "a Secret or value read was attempted"
        assert kwargs["path_params"]["namespace"] == REFERENCE.namespace
        return copy.deepcopy(docs[kinds[plural]])

    api.call_api.side_effect = get
    return kube.KubernetesCluster(context="synthetic-context", namespace=REFERENCE.namespace), api


def test_concrete_mechanical_adapter_reports_only_source_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cluster, api = bind(monkeypatch, documents())
    observation = observe_reference(REFERENCE, cluster, now=NOW)
    assert observation.state == "reported-mounted"
    assert observation.source_version == "42"
    assert observation.object_version == REFERENCE.object_version
    assert observation.pod_uid == REFERENCE.pod_uid
    assert observation.binding_digest == canonical_digest(asdict(REFERENCE))
    assert len(api.call_api.call_args_list) == 3
    assert {call.kwargs["path_params"]["name"] for call in api.call_api.call_args_list} == {
        REFERENCE.pod_name,
        REFERENCE.class_name,
        REFERENCE.status_name,
    }
    assert all(
        call.kwargs["path_params"]["namespace"] == REFERENCE.namespace
        for call in api.call_api.call_args_list
    )
    assert all(call.kwargs["_request_timeout"] == 10 for call in api.call_api.call_args_list)
    assert "targetPath" not in json.dumps(observation.to_json())
    assert REFERENCE.pod_name not in json.dumps(observation.to_json())
    api.server_side_apply.assert_not_called()
    api.delete.assert_not_called()
    with pytest.raises(WorkloadError, match="outside_scope"):
        cluster.read_csi_object("Secret", "example")


@pytest.mark.parametrize(
    ("fault", "expected"),
    [
        ("namespace", "conflict"),
        ("pod-uid", "conflict"),
        ("owner", "conflict"),
        ("entity", "conflict"),
        ("class", "conflict"),
        ("object-version", "conflict"),
        ("duplicate-object", "conflict"),
        ("provider", "conflict"),
        ("mount", "conflict"),
        ("stale", "stale"),
        ("future", "conflict"),
        ("no-time", "unknown"),
        ("bad-time", "unknown"),
        ("naive-time", "unknown"),
        ("no-rv", "unknown"),
        ("mounted-string", "unknown"),
        ("unmounted", "reported-unmounted"),
    ],
)
def test_negative_source_attribution_and_freshness(
    monkeypatch: pytest.MonkeyPatch, fault: str, expected: str
) -> None:
    docs = documents()
    status = docs["SecretProviderClassPodStatus"]
    if fault == "namespace":
        status["metadata"]["namespace"] = "another"
    elif fault == "pod-uid":
        docs["Pod"]["metadata"]["uid"] = "replacement"
    elif fault == "owner":
        status["metadata"]["ownerReferences"] = []
    elif fault == "entity":
        docs["Pod"]["metadata"]["labels"]["fdai.io/entity"] = "other"
    elif fault == "class":
        status["status"]["secretProviderClassName"] = "other"
    elif fault == "object-version":
        status["status"]["objects"][0]["version"] = "different"
    elif fault == "duplicate-object":
        status["status"]["objects"] *= 2
    elif fault == "provider":
        docs["SecretProviderClass"]["spec"]["provider"] = "unsupported"
    elif fault == "mount":
        docs["Pod"]["spec"]["volumes"] = []
    elif fault == "no-time":
        status["metadata"]["managedFields"] = []
    elif fault == "no-rv":
        status["metadata"].pop("resourceVersion")
    elif fault in {"mounted-string", "unmounted"}:
        status["status"]["mounted"] = "true" if fault == "mounted-string" else False
    else:
        stamp = {
            "stale": (NOW - timedelta(minutes=6)).isoformat(),
            "future": (NOW + timedelta(seconds=1)).isoformat(),
            "bad-time": "not-a-time",
            "naive-time": "2026-10-21T00:00:00",
        }[fault]
        status["metadata"]["managedFields"][0]["time"] = stamp
    source, _ = bind(monkeypatch, docs)
    assert observe_reference(REFERENCE, source, now=NOW).state == expected


@pytest.mark.parametrize("code", [403, 404, 500])
def test_missing_or_denied_source_is_unavailable(
    monkeypatch: pytest.MonkeyPatch, code: int
) -> None:
    source, api = bind(monkeypatch, documents())
    api.call_api.side_effect = ApiException(status=code)
    assert observe_reference(REFERENCE, source, now=NOW).state == "unavailable"
    assert observe_reference(REFERENCE, None, now=NOW).state == "unavailable"


def test_native_reference_command_uses_real_adapter_without_value_reads(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, api = bind(monkeypatch, documents())
    path = tmp_path / "references.json"
    path.write_text(json.dumps([asdict(REFERENCE)]))
    path.chmod(0o600)
    arguments = [
        "reference-status",
        "--references",
        str(path),
        "--kube-context",
        "synthetic-context",
        "--namespace",
        REFERENCE.namespace,
    ]
    assert cli.main(arguments, clock=lambda: NOW) == 0
    result = capsys.readouterr()
    assert json.loads(result.out)["references"][0]["state"] == "reported-mounted"
    assert "secret_value" not in result.out + result.err
    assert "/never-read" not in result.out + result.err
    assert len(api.call_api.call_args_list) == 3
    path.write_text(json.dumps([asdict(replace(REFERENCE, namespace="another"))]))
    api.reset_mock()
    assert cli.main(arguments, clock=lambda: NOW) == 2
    api.call_api.assert_not_called()


def test_exhausted_batch_budget_does_not_make_another_source_request() -> None:
    source = Mock()
    budget = ReferenceReadBudget(source, deadline=30.0, monotonic=lambda: 30.0)
    assert observe_reference(REFERENCE, budget, now=NOW).state == "unavailable"
    source.read_csi_object.assert_not_called()


def test_actual_sdk_serializes_fixed_read_path_and_returns_raw_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = kubernetes_client.ApiClient(kubernetes_client.Configuration())
    response = HTTPResponse(
        body=json.dumps(documents()["SecretProviderClassPodStatus"]).encode(),
        status=200,
        headers={"Content-Type": "application/json"},
    )
    transport = Mock(return_value=RESTResponse(response))
    monkeypatch.setattr(api, "request", transport)
    monkeypatch.setattr(
        "fdai_lifecycle_agent.kube.config.new_client_from_config", lambda **_kwargs: api
    )
    try:
        source = kube.KubernetesCluster(context="synthetic-context", namespace=REFERENCE.namespace)
        result = source.read_csi_object("SecretProviderClassPodStatus", REFERENCE.status_name)
        assert result is not None
        assert result["status"]["secretProviderClassName"] == REFERENCE.class_name
        method, url = transport.call_args.args
        assert method == "GET"
        assert url.endswith(
            "/apis/secrets-store.csi.x-k8s.io/v1/namespaces/fdai-test/"
            "secretproviderclasspodstatuses/core-status"
        )
        assert transport.call_args.kwargs["_request_timeout"] == 10.0
        assert transport.call_args.kwargs["body"] is None
    finally:
        api.close()


def test_generated_csi_status_name_is_not_mistaken_for_a_63_character_namespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference = replace(REFERENCE, status_name="core-pod-" + "a" * 80)
    docs = documents()
    docs["SecretProviderClassPodStatus"]["metadata"]["name"] = reference.status_name
    source, api = bind(monkeypatch, docs)
    assert observe_reference(reference, source, now=NOW).state == "reported-mounted"
    assert api.call_api.call_args_list[0].kwargs["path_params"]["name"] == reference.status_name
    api.reset_mock()
    with pytest.raises(WorkloadError, match="outside_scope"):
        source.read_csi_object("Pod", "../another")
    api.call_api.assert_not_called()
