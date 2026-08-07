"""Configuration-only readiness contracts for live ingestion adapters."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from fdai_document_worker_service.adapters.event_bus import (
    EventHubsKafkaBus,
    EventHubsKafkaConfig,
)
from fdai_document_worker_service.adapters.postgres import (
    PostgresDocumentMetadataStore,
    PostgresWorkerConfig,
)
from fdai_document_worker_service.adapters.processing import (
    AzureDocumentIntelligenceOcr,
    AzureDocumentOcrConfig,
    AzureEmbeddingConfig,
    AzureEmbeddingModel,
    UnavailableImageOcr,
)
from fdai_document_worker_service.adapters.storage import (
    AzureDataLakeConfig,
    AzureDataLakeObjectStore,
)
from fdai_service_contracts import AdapterReadinessState, ProviderUnavailableError


class Credential:
    async def get_token(self, *_scopes: str) -> object:
        raise AssertionError("readiness MUST NOT request an Azure token")

    async def close(self) -> None:
        return None


class DataLakeClient:
    def __init__(self) -> None:
        self.file_system = FileSystem()

    def get_file_system_client(self, _name: str) -> object:
        return self.file_system

    async def close(self) -> None:
        return None


class FileSystem:
    async def get_file_system_properties(self, **_kwargs: object) -> object:
        return object()


class LiveCredential:
    async def get_token(self, *_scopes: str) -> object:
        return SimpleNamespace(token="redacted-token")

    async def close(self) -> None:
        return None


class Connection:
    async def __aenter__(self) -> Connection:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def execute(self, _query: str) -> object:
        return object()


def test_live_adapters_report_configuration_evidence_without_network_calls() -> None:
    credential = Credential()
    adls = AzureDataLakeObjectStore(
        config=AzureDataLakeConfig(account_url="https://example.com"),
        service_client=DataLakeClient(),  # type: ignore[arg-type]
    )
    event_hubs = EventHubsKafkaBus(
        config=EventHubsKafkaConfig(bootstrap_servers="example.com:9093"),
        credential=credential,  # type: ignore[arg-type]
    )
    postgres = PostgresDocumentMetadataStore(
        config=PostgresWorkerConfig(dsn="postgresql://example")
    )
    ocr = AzureDocumentIntelligenceOcr(
        config=AzureDocumentOcrConfig(endpoint="https://example.com"),
        credential=credential,  # type: ignore[arg-type]
        client=httpx.AsyncClient(transport=httpx.MockTransport(lambda _request: None)),
    )

    readiness = tuple(adapter.readiness() for adapter in (adls, event_hubs, postgres, ocr))

    assert {item.adapter for item in readiness} == {
        "adls-source",
        "event-hubs-kafka",
        "postgres-document-metadata",
        "document-intelligence-ocr",
    }
    assert all(item.state is AdapterReadinessState.READY for item in readiness)
    assert all(item.evidence == "configuration" for item in readiness)
    assert all(item.live_verified is False for item in readiness)


async def test_unconfigured_ocr_is_explicitly_unavailable_and_fails_closed() -> None:
    adapter = UnavailableImageOcr()

    readiness = adapter.readiness()

    assert readiness.state is AdapterReadinessState.UNAVAILABLE
    assert readiness.reason == "FDAI_OCR_ENDPOINT is not configured"
    with pytest.raises(ProviderUnavailableError, match="not configured"):
        await adapter.extract(version=object(), content=b"image")  # type: ignore[arg-type]


async def test_configured_adapters_perform_bounded_live_probes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    credential = LiveCredential()
    data_lake_client = DataLakeClient()
    adls = AzureDataLakeObjectStore(
        config=AzureDataLakeConfig(account_url="https://example.com"),
        service_client=data_lake_client,  # type: ignore[arg-type]
    )
    event_hubs = EventHubsKafkaBus(
        config=EventHubsKafkaConfig(bootstrap_servers="example.com:9093"),
        credential=credential,  # type: ignore[arg-type]
    )
    postgres = PostgresDocumentMetadataStore(
        config=PostgresWorkerConfig(dsn="postgresql://credential@example.com/database")
    )

    async def connect() -> Connection:
        return Connection()

    async def producer() -> object:
        return object()

    monkeypatch.setattr(postgres, "_connect", connect)
    monkeypatch.setattr(event_hubs, "_get_producer", producer)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer redacted-token"
        if request.method == "GET":
            return httpx.Response(200, json={"value": []})
        return httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2, 0.3]}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    ocr = AzureDocumentIntelligenceOcr(
        config=AzureDocumentOcrConfig(endpoint="https://example.com"),
        credential=credential,  # type: ignore[arg-type]
        client=client,
    )
    embedding = AzureEmbeddingModel(
        config=AzureEmbeddingConfig(
            endpoint="https://example.com", deployment="embedding", dimension=3
        ),
        credential=credential,  # type: ignore[arg-type]
        client=client,
    )

    results = (
        await postgres.probe_readiness(),
        await adls.probe_readiness(),
        await event_hubs.probe_readiness(),
        await ocr.probe_readiness(),
        await embedding.probe_readiness(),
    )

    assert {item.adapter for item in results} == {
        "postgres-document-metadata",
        "adls-source",
        "event-hubs-kafka",
        "document-intelligence-ocr",
        "azure-openai-embedding",
    }
    assert all(item.state is AdapterReadinessState.READY for item in results)
    assert all(item.evidence == "live" and item.live_verified for item in results)


async def test_live_probe_failure_reason_never_contains_connection_material(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_dsn = "postgresql://secret-user:secret-password@example.com/database"
    postgres = PostgresDocumentMetadataStore(config=PostgresWorkerConfig(dsn=secret_dsn))

    async def fail_connect() -> Connection:
        raise RuntimeError(secret_dsn)

    monkeypatch.setattr(postgres, "_connect", fail_connect)

    result = await postgres.probe_readiness()

    assert result.state is AdapterReadinessState.UNAVAILABLE
    assert result.reason == "probe_failed:RuntimeError"
    assert "secret" not in result.model_dump_json()
