"""Production composition for the independent Document Processing Worker."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

import httpx
import psycopg
from azure.identity.aio import ManagedIdentityCredential
from azure.storage.filedatalake.aio import DataLakeServiceClient
from fdai_service_contracts import AdapterLiveReadinessProvider

from fdai_document_worker_service.adapters.activity import PostgresDocumentActivitySink
from fdai_document_worker_service.adapters.event_bus import (
    EventHubsKafkaBus,
    EventHubsKafkaConfig,
    MultiplexedEventBus,
)
from fdai_document_worker_service.adapters.graph import GraphPersonDirectory
from fdai_document_worker_service.adapters.handover import PostgresHandoverDraftStore
from fdai_document_worker_service.adapters.ooxml import OoxmlParserBudget
from fdai_document_worker_service.adapters.postgres import (
    PostgresDocumentMetadataStore,
    PostgresWorkerConfig,
)
from fdai_document_worker_service.adapters.processing import (
    AzureDocumentIntelligenceOcr,
    AzureDocumentOcrConfig,
    AzureEmbeddingConfig,
    AzureEmbeddingModel,
    BoundedDocumentExtractor,
    ClamAvMalwareScanner,
    ClamAvScannerConfig,
    PgvectorDocumentIndex,
    SignatureProtectionInspector,
    UnavailableImageOcr,
)
from fdai_document_worker_service.adapters.storage import (
    AzureDataLakeArtifactStore,
    AzureDataLakeConfig,
    AzureDataLakeObjectStore,
)
from fdai_document_worker_service.consumer import DocumentIngestionEventConsumer
from fdai_document_worker_service.handover import (
    HandoverBootstrapConsumer,
    NullStewardPersonDirectory,
    stewardship_input_from_environment,
)
from fdai_document_worker_service.processing import DocumentIngestionWorker
from fdai_document_worker_service.supervisor import IngestionWorkerSupervisor

_REQUIRED_ENV = (
    "FDAI_DATABASE_URL",
    "FDAI_DATABASE_ROLE",
    "FDAI_INGESTION_DEPLOYMENT_ROLE",
    "FDAI_ADLS_ACCOUNT_URL",
    "FDAI_EMBEDDING_ENDPOINT",
    "FDAI_EMBEDDING_DEPLOYMENT",
    "FDAI_KAFKA_BOOTSTRAP_SERVERS",
    "FDAI_DOCUMENT_EVENT_TOPIC",
    "FDAI_CLAMAV_HOST",
    "FDAI_CLAMAV_PORT",
)
_CLAMAV_SIDECAR_HOST = "127.0.0.1"
_CLAMAV_SIDECAR_PORT = 3310


class ProductionConfigurationError(ValueError):
    """Production worker environment is incomplete or grants the wrong role."""


@dataclass(frozen=True, slots=True)
class ProductionWorkerRuntime:
    worker_service: DocumentIngestionEventConsumer
    startup_checks: tuple[Callable[[], Awaitable[None]], ...]
    shutdown_callbacks: tuple[Callable[[], Awaitable[None]], ...]


def build_runtime(environ: Mapping[str, str]) -> ProductionWorkerRuntime:
    """Build all worker providers without starting consumer loops."""
    env = dict(environ)
    missing = [key for key in _REQUIRED_ENV if not env.get(key, "").strip()]
    if missing:
        raise ProductionConfigurationError(
            "production ingestion environment is missing: " + ", ".join(missing)
        )
    if env["FDAI_INGESTION_DEPLOYMENT_ROLE"].strip() != "worker":
        raise ProductionConfigurationError("FDAI_INGESTION_DEPLOYMENT_ROLE MUST be worker")
    if env["FDAI_DATABASE_ROLE"].strip() != "fdai_ingestion_worker":
        raise ProductionConfigurationError("FDAI_DATABASE_ROLE MUST be fdai_ingestion_worker")
    clamav_host = env["FDAI_CLAMAV_HOST"].strip()
    if clamav_host != _CLAMAV_SIDECAR_HOST:
        raise ProductionConfigurationError(
            f"FDAI_CLAMAV_HOST MUST be {_CLAMAV_SIDECAR_HOST} for the replica-local sidecar"
        )
    clamav_port = _positive_int(env, "FDAI_CLAMAV_PORT", 0)
    if clamav_port != _CLAMAV_SIDECAR_PORT:
        raise ProductionConfigurationError(
            f"FDAI_CLAMAV_PORT MUST be {_CLAMAV_SIDECAR_PORT} for the replica-local sidecar"
        )
    dsn = env["FDAI_DATABASE_URL"].strip()
    credential = ManagedIdentityCredential()
    http_client = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0))
    storage_config = AzureDataLakeConfig(
        account_url=env["FDAI_ADLS_ACCOUNT_URL"].strip(),
        source_file_system=env.get("FDAI_ADLS_SOURCE_FILE_SYSTEM", "documents").strip(),
        derived_file_system=env.get("FDAI_ADLS_DERIVED_FILE_SYSTEM", "derived").strip(),
    )
    source_store = AzureDataLakeObjectStore(
        config=storage_config,
        service_client=DataLakeServiceClient(storage_config.account_url, credential=credential),
    )
    artifact_store = AzureDataLakeArtifactStore(
        config=storage_config,
        service_client=DataLakeServiceClient(storage_config.account_url, credential=credential),
    )
    raw_bus = EventHubsKafkaBus(
        config=EventHubsKafkaConfig(bootstrap_servers=env["FDAI_KAFKA_BOOTSTRAP_SERVERS"].strip()),
        credential=credential,
    )
    event_bus = MultiplexedEventBus(
        bus=raw_bus,
        logical_topics=frozenset({"object.event", "object.audit-entry", "object.context-index"}),
        physical_topic=env.get("FDAI_PANTHEON_OBJECT_TOPIC", "aw.pantheon.objects").strip(),
    )
    metadata = PostgresDocumentMetadataStore(config=PostgresWorkerConfig(dsn=dsn))
    ocr_endpoint = env.get("FDAI_OCR_ENDPOINT", "").strip()
    ocr = (
        AzureDocumentIntelligenceOcr(
            config=AzureDocumentOcrConfig(
                endpoint=ocr_endpoint,
                api_version=env.get("FDAI_OCR_API_VERSION", "2024-11-30").strip(),
                operation_timeout_seconds=_positive_int(
                    env, "FDAI_OCR_OPERATION_TIMEOUT_SECONDS", 180
                ),
                max_lines=_positive_int(env, "FDAI_OCR_MAX_LINES", 5000),
                max_characters=_positive_int(env, "FDAI_OCR_MAX_CHARACTERS", 1_000_000),
                max_response_bytes=_positive_int(env, "FDAI_OCR_MAX_RESPONSE_BYTES", 4_000_000),
            ),
            credential=credential,
            client=http_client,
        )
        if ocr_endpoint
        else UnavailableImageOcr()
    )
    dimension = _positive_int(env, "FDAI_EMBEDDING_DIM", 384)
    embedding = AzureEmbeddingModel(
        config=AzureEmbeddingConfig(
            endpoint=env["FDAI_EMBEDDING_ENDPOINT"].strip(),
            deployment=env["FDAI_EMBEDDING_DEPLOYMENT"].strip(),
            dimension=dimension,
        ),
        credential=credential,
        client=http_client,
    )
    document_index = PgvectorDocumentIndex(
        dsn=dsn,
        embedder=embedding,
        dimension=dimension,
        max_chars=_positive_int(env, "FDAI_DOCUMENT_CHUNK_MAX_CHARS", 1200),
        overlap=_nonnegative_int(env, "FDAI_DOCUMENT_CHUNK_OVERLAP", 150),
    )
    activity = PostgresDocumentActivitySink(
        dsn=dsn,
        event_bus=event_bus,
        event_topic=env["FDAI_DOCUMENT_EVENT_TOPIC"].strip(),
    )
    malware = ClamAvMalwareScanner(
        config=ClamAvScannerConfig(
            host=clamav_host,
            port=clamav_port,
            max_stream_bytes=_positive_int(env, "FDAI_DOCUMENT_MAX_FILE_SIZE", 25 * 1024 * 1024),
        )
    )
    worker = DocumentIngestionWorker(
        metadata=metadata,
        objects=source_store,
        malware=malware,
        protection=SignatureProtectionInspector(
            max_input_bytes=_positive_int(env, "FDAI_DOCUMENT_MAX_FILE_SIZE", 25 * 1024 * 1024)
        ),
        extractor=BoundedDocumentExtractor(
            image_ocr=ocr,
            max_input_bytes=_positive_int(env, "FDAI_DOCUMENT_MAX_FILE_SIZE", 25 * 1024 * 1024),
            max_characters=_positive_int(env, "FDAI_DOCUMENT_MAX_EXTRACTED_CHARACTERS", 1_000_000),
            ooxml_budget=OoxmlParserBudget(
                max_input_bytes=_positive_int(env, "FDAI_DOCUMENT_MAX_FILE_SIZE", 25 * 1024 * 1024),
                max_members=_positive_int(env, "FDAI_OOXML_MAX_MEMBERS", 10_000),
                max_expanded_bytes=_positive_int(
                    env, "FDAI_OOXML_MAX_EXPANDED_BYTES", 128 * 1024 * 1024
                ),
                max_compression_ratio=_bounded_float(
                    env,
                    "FDAI_OOXML_MAX_COMPRESSION_RATIO",
                    100.0,
                    minimum=1.0,
                    maximum=10_000.0,
                ),
                max_xml_member_bytes=_positive_int(
                    env, "FDAI_OOXML_MAX_XML_MEMBER_BYTES", 16 * 1024 * 1024
                ),
                max_xml_depth=_positive_int(env, "FDAI_OOXML_MAX_XML_DEPTH", 128),
                max_xml_nodes=_positive_int(env, "FDAI_OOXML_MAX_XML_NODES", 1_000_000),
                max_text_characters=_positive_int(env, "FDAI_OOXML_MAX_TEXT_CHARACTERS", 4_000_000),
                max_units=_positive_int(env, "FDAI_OOXML_MAX_UNITS", 100_000),
            ),
        ),
        artifacts=artifact_store,
        index=document_index,
        consumers=(
            HandoverBootstrapConsumer(
                directory=(
                    GraphPersonDirectory(
                        credential=credential,
                        client=http_client,
                        base_url=env.get(
                            "FDAI_GRAPH_BASE_URL", "https://graph.microsoft.com/v1.0"
                        ).strip(),
                    )
                    if _truthy(env.get("FDAI_GRAPH_STEWARDSHIP_ENABLED", ""))
                    else NullStewardPersonDirectory()
                ),
                store=PostgresHandoverDraftStore(dsn=dsn),
                stewardship=stewardship_input_from_environment(env),
                confidence_floor=_bounded_float(
                    env, "FDAI_HANDOVER_CONFIDENCE_FLOOR", 0.6, minimum=0.0, maximum=1.0
                ),
            ),
        ),
        indexing_stage_timeout_seconds=_positive_int(
            env, "FDAI_DOCUMENT_INDEXING_STAGE_TIMEOUT_SECONDS", 90
        ),
    )

    async def verify_database_role() -> None:
        async with await psycopg.AsyncConnection.connect(dsn) as connection:
            row = await (await connection.execute("SELECT current_user")).fetchone()
        if row is None or str(row[0]) != "fdai_ingestion_worker":
            raise ProductionConfigurationError("database session role is not fdai_ingestion_worker")

    async def verify_adapters() -> None:
        configured: list[AdapterLiveReadinessProvider] = [
            metadata,
            source_store,
            artifact_store,
            raw_bus,
            embedding,
            malware,
        ]
        if ocr_endpoint:
            configured.append(ocr)
        results = await asyncio.gather(*(adapter.probe_readiness() for adapter in configured))
        failures = tuple(
            f"{result.adapter}:{result.reason or 'unavailable'}"
            for result in results
            if not result.live_verified
        )
        if failures:
            raise ProductionConfigurationError(
                "ingestion worker adapter readiness failed: " + ", ".join(failures)
            )

    return ProductionWorkerRuntime(
        worker_service=DocumentIngestionEventConsumer(
            event_bus=event_bus,
            worker=worker,
            metadata=metadata,
            activity=activity,
            topic="object.audit-entry",
            worker_owner=env.get("FDAI_INGESTION_WORKER_OWNER", "").strip() or None,
            lease_seconds=_positive_int(env, "FDAI_INGESTION_WORKER_LEASE_SECONDS", 120),
        ),
        startup_checks=(verify_database_role, verify_adapters),
        shutdown_callbacks=(
            event_bus.close,
            source_store.close,
            artifact_store.close,
            http_client.aclose,
        ),
    )


def run_production_worker(environ: Mapping[str, str]) -> int:
    """Run the service-owned worker until a signal or required-loop failure."""
    runtime = build_runtime(environ)
    raw_port = environ.get("FDAI_INGESTION_WORKER_HEALTH_PORT", "8000").strip()
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise ProductionConfigurationError(
            "FDAI_INGESTION_WORKER_HEALTH_PORT MUST be an integer"
        ) from exc
    logging.basicConfig(level=logging.INFO)
    try:
        return asyncio.run(IngestionWorkerSupervisor(runtime=runtime, health_port=port).run())
    except KeyboardInterrupt:
        return 0


def _positive_int(env: Mapping[str, str], key: str, default: int) -> int:
    value = int(env.get(key, str(default)))
    if value < 1:
        raise ProductionConfigurationError(f"{key} MUST be positive")
    return value


def _nonnegative_int(env: Mapping[str, str], key: str, default: int) -> int:
    value = int(env.get(key, str(default)))
    if value < 0:
        raise ProductionConfigurationError(f"{key} MUST be nonnegative")
    return value


def _bounded_float(
    env: Mapping[str, str], key: str, default: float, *, minimum: float, maximum: float
) -> float:
    value = float(env.get(key, str(default)))
    if not minimum <= value <= maximum:
        raise ProductionConfigurationError(f"{key} MUST be in [{minimum}, {maximum}]")
    return value


def _truthy(value: str) -> bool:
    return value.strip().casefold() in {"1", "true", "yes", "on"}
