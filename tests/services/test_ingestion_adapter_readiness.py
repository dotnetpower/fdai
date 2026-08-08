"""Configuration-only readiness contracts for live ingestion adapters."""

from __future__ import annotations

import asyncio
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
    ClamAvMalwareScanner,
    ClamAvScannerConfig,
    UnavailableImageOcr,
)
from fdai_document_worker_service.adapters.storage import (
    AzureDataLakeArtifactStore,
    AzureDataLakeConfig,
    AzureDataLakeObjectStore,
)
from fdai_document_worker_service.production import ProductionConfigurationError
from fdai_document_worker_service.production import build_runtime as build_worker_runtime
from fdai_ingestion_api_service.adapters.event_bus import EventHubsKafkaPublisher
from fdai_ingestion_api_service.adapters.postgres import (
    PostgresApiConfig,
)
from fdai_ingestion_api_service.adapters.postgres import (
    PostgresDocumentMetadataStore as PostgresApiDocumentMetadataStore,
)
from fdai_service_contracts import (
    AdapterReadinessState,
    DocumentWorkerClaim,
    DocumentWorkerClaimConflictError,
    DocumentWorkerClaimStatus,
    DocumentWorkerStage,
    ProviderUnavailableError,
    live_readiness,
    live_unavailable_readiness,
)

_WORKER_ENV = {
    "FDAI_DATABASE_URL": "postgresql://example.invalid/fdai",
    "FDAI_DATABASE_ROLE": "fdai_ingestion_worker",
    "FDAI_INGESTION_DEPLOYMENT_ROLE": "worker",
    "FDAI_ADLS_ACCOUNT_URL": "https://example.invalid",
    "FDAI_EMBEDDING_ENDPOINT": "https://example.invalid",
    "FDAI_EMBEDDING_DEPLOYMENT": "embedding",
    "FDAI_KAFKA_BOOTSTRAP_SERVERS": "example.invalid:9093",
    "FDAI_DOCUMENT_EVENT_TOPIC": "aw.pipeline.stages",
    "FDAI_CLAMAV_HOST": "127.0.0.1",
    "FDAI_CLAMAV_PORT": "3310",
}


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

    def assignment(self) -> set[str]:
        return {"object.event:0"}

    async def stop(self) -> None:
        return None


class Connection:
    async def __aenter__(self) -> Connection:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def execute(self, _query: str) -> Cursor:
        return Cursor({"ready": True})


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


class SchemaProbeConnection(Connection):
    def __init__(self) -> None:
        self.queries: list[str] = []

    async def execute(self, query: str, _params: object = ()) -> Cursor:
        self.queries.append(query)
        return Cursor({"ready": True})


class KafkaMetadataClient:
    def __init__(self, *, failure: Exception | None = None) -> None:
        self.failure = failure
        self.calls = 0

    async def fetch_all_metadata(self) -> object:
        self.calls += 1
        if self.failure is not None:
            raise self.failure
        return object()


class CachedKafkaProducer:
    def __init__(self, *, metadata_failure: Exception | None = None) -> None:
        self.client = KafkaMetadataClient(failure=metadata_failure)
        self.stop_calls = 0

    async def send_and_wait(self, *_args: object, **_kwargs: object) -> object:
        raise RuntimeError("broker send failed")

    async def stop(self) -> None:
        self.stop_calls += 1


class ClamAvReader:
    def __init__(self, response: bytes) -> None:
        self._response = response

    async def readuntil(self, separator: bytes) -> bytes:
        assert separator == b"\0"
        return self._response


class ClamAvWriter:
    def __init__(self, commands: list[bytes]) -> None:
        self._commands = commands

    def write(self, data: bytes) -> None:
        self._commands.append(data)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        return None

    async def wait_closed(self) -> None:
        return None


async def test_clamav_live_probe_requires_ping_version_and_loaded_signatures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = iter(
        (
            b"PONG\0",
            b"ClamAV 1.4.2/27500/Fri Aug  8 00:00:00 2026\0",
        )
    )
    commands: list[bytes] = []

    async def open_connection(host: str, port: int) -> tuple[ClamAvReader, ClamAvWriter]:
        assert (host, port) == ("127.0.0.1", 3310)
        return ClamAvReader(next(responses)), ClamAvWriter(commands)

    monkeypatch.setattr(asyncio, "open_connection", open_connection)
    scanner = ClamAvMalwareScanner(config=ClamAvScannerConfig(host="127.0.0.1", port=3310))

    result = await scanner.probe_readiness()

    assert result.live_verified is True
    assert commands == [b"zPING\0", b"zVERSION\0"]


async def test_clamav_live_probe_rejects_missing_signature_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = iter((b"PONG\0", b"ClamAV 1.4.2/0/unknown\0"))

    async def open_connection(_host: str, _port: int) -> tuple[ClamAvReader, ClamAvWriter]:
        return ClamAvReader(next(responses)), ClamAvWriter([])

    monkeypatch.setattr(asyncio, "open_connection", open_connection)
    scanner = ClamAvMalwareScanner(config=ClamAvScannerConfig(host="127.0.0.1", port=3310))

    result = await scanner.probe_readiness()

    assert result.live_verified is False
    assert result.reason == "signature_database_unavailable"


async def test_worker_startup_adapter_gate_includes_clamav(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[str] = []

    async def probe(adapter: object) -> object:
        name = type(adapter).__name__
        observed.append(name)
        return live_readiness(name)

    for adapter_type in (
        PostgresDocumentMetadataStore,
        AzureDataLakeObjectStore,
        AzureDataLakeArtifactStore,
        EventHubsKafkaBus,
        AzureEmbeddingModel,
        ClamAvMalwareScanner,
    ):
        monkeypatch.setattr(adapter_type, "probe_readiness", probe)

    runtime = build_worker_runtime(_WORKER_ENV)
    await runtime.startup_checks[1]()
    await asyncio.gather(*(callback() for callback in runtime.shutdown_callbacks))

    assert "ClamAvMalwareScanner" in observed


async def test_clamav_probe_failure_blocks_worker_startup_adapter_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def probe(adapter: object) -> object:
        name = type(adapter).__name__
        if isinstance(adapter, ClamAvMalwareScanner):
            return live_unavailable_readiness("clamav", "probe_failed:ConnectionRefusedError")
        return live_readiness(name)

    for adapter_type in (
        PostgresDocumentMetadataStore,
        AzureDataLakeObjectStore,
        AzureDataLakeArtifactStore,
        EventHubsKafkaBus,
        AzureEmbeddingModel,
        ClamAvMalwareScanner,
    ):
        monkeypatch.setattr(adapter_type, "probe_readiness", probe)

    runtime = build_worker_runtime(_WORKER_ENV)
    with pytest.raises(ProductionConfigurationError, match="clamav:probe_failed"):
        await runtime.startup_checks[1]()
    await asyncio.gather(*(callback() for callback in runtime.shutdown_callbacks))


async def test_ingestion_api_postgres_probe_references_required_owned_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = PostgresApiDocumentMetadataStore(
        config=PostgresApiConfig(dsn="postgresql://example.invalid/fdai")
    )
    connection = SchemaProbeConnection()

    async def connect() -> SchemaProbeConnection:
        return connection

    monkeypatch.setattr(store, "_connect", connect)

    result = await store.probe_readiness()

    assert result.live_verified is True
    statement = connection.queries[-1]
    for fragment in (
        "FROM document_upload_session",
        "FROM document_version",
        "FROM document_api_outbox",
        "FROM knowledge_chunk",
        "FROM state_kv",
    ):
        assert fragment in statement


async def test_ingestion_worker_postgres_probe_requires_owned_schema_and_grants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = PostgresDocumentMetadataStore(
        config=PostgresWorkerConfig(dsn="postgresql://example.invalid/fdai")
    )
    connection = SchemaProbeConnection()

    async def connect() -> SchemaProbeConnection:
        return connection

    monkeypatch.setattr(store, "_connect", connect)

    result = await store.probe_readiness()

    assert result.live_verified is True
    statement = connection.queries[-1]
    for fragment in (
        "FROM document_upload_session",
        "FROM document_version",
        "FROM document_worker_claim",
        "FROM document_worker_outbox",
        "FROM document_worker_effect",
        "FROM knowledge_chunk",
        "FROM state_kv",
        "has_table_privilege(current_user, 'document_upload_session', 'SELECT, UPDATE')",
        "has_table_privilege(current_user, 'document_worker_claim', 'SELECT, INSERT, UPDATE')",
        "has_table_privilege(current_user, 'knowledge_chunk', 'SELECT, INSERT, UPDATE, DELETE')",
    ):
        assert fragment in statement


async def test_ingestion_api_kafka_probe_refreshes_metadata_and_discards_stale_producer() -> None:
    publisher = EventHubsKafkaPublisher(
        bootstrap_servers="example.invalid:9093",
        credential=LiveCredential(),  # type: ignore[arg-type]
    )
    producer = CachedKafkaProducer(metadata_failure=RuntimeError("broker unavailable"))
    publisher._producer = producer  # type: ignore[assignment]

    result = await publisher.probe_readiness()

    assert result.live_verified is False
    assert producer.client.calls == 1
    assert producer.stop_calls == 1
    assert publisher._producer is None


async def test_ingestion_api_kafka_send_failure_discards_cached_producer() -> None:
    publisher = EventHubsKafkaPublisher(
        bootstrap_servers="example.invalid:9093",
        credential=LiveCredential(),  # type: ignore[arg-type]
    )
    producer = CachedKafkaProducer()
    publisher._producer = producer  # type: ignore[assignment]

    with pytest.raises(RuntimeError, match="broker send failed"):
        await publisher.publish("events", "key", {"value": "payload"})

    assert producer.stop_calls == 1
    assert publisher._producer is None


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


async def test_kafka_consumer_readiness_requires_current_group_ownership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(event_bus_module, "AIOKafkaConsumer", FakeKafkaConsumer)
    now = 10.0
    bus = EventHubsKafkaBus(
        config=EventHubsKafkaConfig(bootstrap_servers="example.com:9093"),
        credential=OffsetCredential(),  # type: ignore[arg-type]
        monotonic=lambda: now,
    )

    async def dead_letter(
        _topic: str,
        _key: str,
        _payload: dict[str, object],
        _reason: str,
    ) -> None:
        return None

    monkeypatch.setattr(bus, "dead_letter", dead_letter)
    events = bus.subscribe("object.event", "document-worker")

    await anext(events)

    assert bus.consumer_group_ready("object.event", "document-worker", freshness_seconds=5.0)
    now = 16.0
    assert not bus.consumer_group_ready("object.event", "document-worker", freshness_seconds=5.0)
    await events.aclose()
    assert not bus.consumer_group_ready("object.event", "document-worker", freshness_seconds=5.0)


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
