"""Configuration-only readiness contracts for live ingestion adapters."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import fdai_document_worker_service.adapters.event_bus as event_bus_module
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
from fdai_service_contracts import (
    AdapterReadinessState,
    DocumentWorkerClaim,
    DocumentWorkerClaimConflictError,
    DocumentWorkerClaimStatus,
    DocumentWorkerStage,
    ProviderUnavailableError,
)


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


class OffsetCredential:
    async def get_token(self, *_scopes: str) -> object:
        return SimpleNamespace(token="redacted-token", expires_on=4_000_000_000)

    async def close(self) -> None:
        return None


class FakeKafkaConsumer:
    latest: FakeKafkaConsumer | None = None

    def __init__(self, *_topics: str, **kwargs: object) -> None:
        self._token_provider = kwargs["sasl_oauth_token_provider"]
        self.messages = [
            SimpleNamespace(topic="object.event", key=b"document-1", value=b"{", offset=7),
            SimpleNamespace(
                topic="object.event",
                key=b"document-1",
                value=b'{"kind":"document_ingestion"}',
                offset=8,
            ),
        ]
        self.commits = 0
        FakeKafkaConsumer.latest = self

    async def start(self) -> None:
        await self._token_provider.token()

    async def getone(self) -> object:
        return self.messages.pop(0)

    async def commit(self) -> None:
        self.commits += 1

    async def stop(self) -> None:
        return None


class Connection:
    async def __aenter__(self) -> Connection:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def execute(self, _query: str) -> object:
        return object()


class Cursor:
    def __init__(self, row: object | None) -> None:
        self._row = row

    async def fetchone(self) -> object | None:
        return self._row


class Transaction:
    async def __aenter__(self) -> Transaction:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None


class StaleClaimConnection(Connection):
    def __init__(self) -> None:
        self.queries: list[str] = []

    def transaction(self) -> Transaction:
        return Transaction()

    async def execute(self, query: str, _params: object = ()) -> Cursor:
        self.queries.append(query)
        return Cursor(None)


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


async def test_postgres_worker_transition_rejects_stale_claim_before_lifecycle_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    postgres = PostgresDocumentMetadataStore(
        config=PostgresWorkerConfig(dsn="postgresql://example")
    )
    connection = StaleClaimConnection()

    async def connect() -> StaleClaimConnection:
        return connection

    monkeypatch.setattr(postgres, "_connect", connect)
    now = datetime.now(UTC)
    claim = DocumentWorkerClaim(
        upload_id=uuid4(),
        stage=DocumentWorkerStage.INDEXING,
        owner="stale-worker",
        attempt_id=uuid4(),
        revision=3,
        status=DocumentWorkerClaimStatus.ACTIVE,
        claimed_at=now - timedelta(seconds=30),
        lease_expires_at=now - timedelta(seconds=1),
    )
    session = SimpleNamespace(upload_id=claim.upload_id, revision=2)
    version = SimpleNamespace(revision=2)

    with pytest.raises(DocumentWorkerClaimConflictError, match="claim conflict"):
        await postgres.transition_worker_stage(
            session,  # type: ignore[arg-type]
            version,  # type: ignore[arg-type]
            claim=claim,
            expected_upload_state="indexing",
            expected_upload_revision=1,
            expected_version_state="indexing",
            expected_version_revision=1,
            event=object(),  # type: ignore[arg-type]
        )

    assert any("FROM document_worker_claim" in query for query in connection.queries)
    assert not any("UPDATE document_upload_session" in query for query in connection.queries)

    connection.queries.clear()
    with pytest.raises(DocumentWorkerClaimConflictError, match="claim conflict"):
        await postgres.enqueue_worker_event(object(), claim=claim)  # type: ignore[arg-type]
    assert any("FROM document_worker_claim" in query for query in connection.queries)
    assert not any("INSERT INTO document_worker_outbox" in query for query in connection.queries)


async def test_kafka_consumer_dead_letters_decode_error_before_committing_offset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(event_bus_module, "AIOKafkaConsumer", FakeKafkaConsumer)
    bus = EventHubsKafkaBus(
        config=EventHubsKafkaConfig(bootstrap_servers="example.com:9093"),
        credential=OffsetCredential(),  # type: ignore[arg-type]
    )
    dead_letters: list[tuple[str, str, dict[str, object], str]] = []

    async def dead_letter(
        topic: str,
        key: str,
        payload: dict[str, object],
        reason: str,
    ) -> None:
        dead_letters.append((topic, key, payload, reason))

    monkeypatch.setattr(bus, "dead_letter", dead_letter)
    events = bus.subscribe("object.event", "document-worker")

    event = await anext(events)
    await events.aclose()

    consumer = FakeKafkaConsumer.latest
    assert consumer is not None
    assert event.offset == 8
    assert event.payload == {"kind": "document_ingestion"}
    assert dead_letters == [
        (
            "object.event",
            "document-1",
            {"source_offset": 7},
            "invalid_event_payload",
        )
    ]
    assert consumer.commits == 1


async def test_kafka_consumer_does_not_commit_when_decode_dlq_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(event_bus_module, "AIOKafkaConsumer", FakeKafkaConsumer)
    bus = EventHubsKafkaBus(
        config=EventHubsKafkaConfig(bootstrap_servers="example.com:9093"),
        credential=OffsetCredential(),  # type: ignore[arg-type]
    )

    async def dead_letter(
        _topic: str,
        _key: str,
        _payload: dict[str, object],
        _reason: str,
    ) -> None:
        raise RuntimeError("DLQ unavailable")

    monkeypatch.setattr(bus, "dead_letter", dead_letter)
    events = bus.subscribe("object.event", "document-worker")

    with pytest.raises(RuntimeError, match="DLQ unavailable"):
        await anext(events)

    consumer = FakeKafkaConsumer.latest
    assert consumer is not None
    assert consumer.commits == 0


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
