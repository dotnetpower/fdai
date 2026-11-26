"""Runtime binding tests for collection Resource Health evidence."""

from __future__ import annotations

import pytest
from fdai.delivery.azure.resource_health_collection import (
    AzureResourceHealthCollectionReader,
)
from fdai.delivery.azure.service_health import AzureServiceHealthReader
from fdai.delivery.azure.subscription_scope import AzureSubscriptionScopeReader
from fdai.delivery.azure.vm_process_evidence import AzureVmProcessCpuReader
from fdai.delivery.kubernetes_resource_event_history import (
    KubernetesResourceEventHistoryReader,
)
from fdai.delivery.resource_event_history import CompositeResourceEventHistoryReader
from fdai.runtime.providers import (
    _build_resource_event_history_reader,
    _build_resource_health_collection_reader,
    _build_service_health_reader,
    _build_subscription_scope_reader,
    _build_vm_process_cpu_reader,
)
from fdai.runtime.resource_event_providers import (
    build_kubernetes_resource_event_history_reader,
)


def test_resource_health_reader_stays_unbound_without_server_scope(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("AZURE_SUBSCRIPTION_ID", raising=False)

    assert (
        _build_resource_health_collection_reader(
            identity=object(),
            http_client=object(),
        )
        is None
    )


def test_resource_health_reader_uses_server_scope_only(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv(
        "AZURE_SUBSCRIPTION_ID",
        "00000000-0000-0000-0000-000000000000",
    )

    reader = _build_resource_health_collection_reader(
        identity=object(),
        http_client=object(),
    )

    assert isinstance(reader, AzureResourceHealthCollectionReader)


def test_resource_event_reader_uses_the_same_server_scope(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv(
        "AZURE_SUBSCRIPTION_ID",
        "00000000-0000-0000-0000-000000000000",
    )

    reader = _build_resource_event_history_reader(
        identity=object(),
        http_client=object(),
    )

    assert isinstance(reader, CompositeResourceEventHistoryReader)


def test_kubernetes_event_reader_requires_complete_server_binding(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    environment = {
        "FDAI_KUBERNETES_API_SERVER": "https://cluster.example.com",
    }

    with pytest.raises(RuntimeError, match="requires API server, cluster ref, auth mode, and CA"):
        build_kubernetes_resource_event_history_reader(
            environment=environment,
            identity=object(),
        )


def test_kubernetes_event_reader_uses_workload_identity_binding() -> None:
    reader = build_kubernetes_resource_event_history_reader(
        environment={
            "FDAI_KUBERNETES_API_SERVER": "https://cluster.example.com",
            "FDAI_KUBERNETES_CLUSTER_REF": "cluster-example",
            "FDAI_KUBERNETES_CA_PEM": "test-ca-pem",
            "FDAI_KUBERNETES_AUTH_MODE": "workload-identity",
            "FDAI_KUBERNETES_AUDIENCE": "api://kubernetes",
        },
        identity=object(),
    )

    assert isinstance(reader, KubernetesResourceEventHistoryReader)


def test_service_health_reader_uses_the_same_server_scope(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv(
        "AZURE_SUBSCRIPTION_ID",
        "00000000-0000-0000-0000-000000000000",
    )

    reader = _build_service_health_reader(
        identity=object(),
        http_client=object(),
    )

    assert isinstance(reader, AzureServiceHealthReader)


def test_subscription_scope_reader_uses_the_same_server_scope(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv(
        "AZURE_SUBSCRIPTION_ID",
        "00000000-0000-0000-0000-000000000000",
    )

    reader = _build_subscription_scope_reader(
        identity=object(),
        http_client=object(),
    )

    assert isinstance(reader, AzureSubscriptionScopeReader)


def test_subscription_scope_reader_stays_unbound_without_server_scope(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("AZURE_SUBSCRIPTION_ID", raising=False)

    assert _build_subscription_scope_reader(identity=object(), http_client=object()) is None


def test_vm_process_reader_stays_unbound_without_monitor_workspace(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("FDAI_MONITOR_WORKSPACE_ID", raising=False)

    assert _build_vm_process_cpu_reader(identity=object(), http_client=object()) is None


def test_vm_process_reader_uses_server_owned_monitor_workspace(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv(
        "FDAI_MONITOR_WORKSPACE_ID",
        "00000000-0000-0000-0000-000000000000",
    )

    reader = _build_vm_process_cpu_reader(
        identity=object(),
        http_client=object(),
    )

    assert isinstance(reader, AzureVmProcessCpuReader)
