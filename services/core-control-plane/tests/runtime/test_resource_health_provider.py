"""Runtime binding tests for collection Resource Health evidence."""

from __future__ import annotations

from fdai.delivery.azure.resource_event_history import AzureResourceEventHistoryReader
from fdai.delivery.azure.resource_health_collection import (
    AzureResourceHealthCollectionReader,
)
from fdai.delivery.azure.service_health import AzureServiceHealthReader
from fdai.runtime.providers import (
    _build_resource_event_history_reader,
    _build_resource_health_collection_reader,
    _build_service_health_reader,
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

    assert isinstance(reader, AzureResourceEventHistoryReader)


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
