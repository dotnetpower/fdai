"""Production composition for the dedicated document-ingestion gateway."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Final

import httpx
from starlette.applications import Starlette

from fdai.core.document_ingestion import DocumentIngestionService, DocumentIngestionWorker
from fdai.core.rbac.resolver import GroupMapping, RoleResolver
from fdai.core.stewardship.handover_bootstrap import HandoverBootstrapper
from fdai.delivery.azure.document_storage import (
    AzureDataLakeArtifactStore,
    AzureDataLakeConfig,
    AzureDataLakeObjectStore,
)
from fdai.delivery.azure.event_bus import EventHubsKafkaBus, EventHubsKafkaBusConfig
from fdai.delivery.azure.llm.embeddings import (
    AzureOpenAIEmbeddingModel,
    AzureOpenAIEmbeddingModelConfig,
)
from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity
from fdai.delivery.ingestion_gateway.access import ClaimsDocumentAccessProvider
from fdai.delivery.ingestion_gateway.activity import DurableDocumentActivitySink
from fdai.delivery.ingestion_gateway.handover import (
    HandoverBootstrapConsumer,
    StateStoreHandoverDraftStore,
)
from fdai.delivery.ingestion_gateway.main import IngestionGatewayConfig, build_app
from fdai.delivery.ingestion_gateway.worker_service import DocumentIngestionEventConsumer
from fdai.delivery.malware import ClamAvMalwareScanner, ClamAvScannerConfig
from fdai.delivery.persistence.postgres import PostgresStateStore, PostgresStateStoreConfig
from fdai.delivery.persistence.postgres_document_ingestion import (
    PostgresDocumentMetadataStore,
    PostgresDocumentMetadataStoreConfig,
)
from fdai.delivery.pgvector.document_index import (
    PgvectorDocumentIndex,
    PgvectorDocumentIndexConfig,
)
from fdai.delivery.read_api.auth import build_authenticator
from fdai.delivery.read_api.entra_verifier import EntraJwtVerifier
from fdai.delivery.stewardship import GraphPersonDirectory
from fdai.delivery.stewardship.production import (
    build_production_stewardship_governance,
)
from fdai.shared.contracts import IngestionCapabilities, SourceStorageMode
from fdai.shared.providers.local.document_ingestion import (
    SignatureProtectionInspector,
    StandardLibraryDocumentExtractor,
)
from fdai.shared.providers.local.secret import EnvSecretProvider

_REQUIRED_ENV: Final[tuple[str, ...]] = (
    "FDAI_DATABASE_URL",
    "FDAI_ENTRA_TENANT_ID",
    "FDAI_API_AUDIENCE",
    "FDAI_RBAC_READERS_GROUP_ID",
    "FDAI_RBAC_CONTRIBUTORS_GROUP_ID",
    "FDAI_RBAC_APPROVERS_GROUP_ID",
    "FDAI_RBAC_OWNERS_GROUP_ID",
    "FDAI_RBAC_BREAK_GLASS_GROUP_ID",
    "FDAI_ADLS_ACCOUNT_NAME",
    "FDAI_ADLS_ACCOUNT_URL",
    "FDAI_EMBEDDING_ENDPOINT",
    "FDAI_EMBEDDING_DEPLOYMENT",
    "FDAI_KAFKA_BOOTSTRAP_SERVERS",
    "FDAI_DOCUMENT_EVENT_TOPIC",
    "FDAI_INGESTION_CORS_ALLOW_ORIGINS",
)


class ProdIngestionConfigError(ValueError):
    """Raised when the production ingestion environment is incomplete."""


def build_prod_app(environ: Mapping[str, str] | None = None) -> Starlette:
    env = dict(environ if environ is not None else os.environ)
    missing = [key for key in _REQUIRED_ENV if not env.get(key, "").strip()]
    if missing:
        raise ProdIngestionConfigError(
            "production ingestion environment is missing: " + ", ".join(missing)
        )
    dsn = env["FDAI_DATABASE_URL"].strip()
    http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=10.0)
    )
    identity = ManagedIdentityWorkloadIdentity(http_client=http_client)

    async def graph_token() -> str:
        token = await identity.get_token("https://graph.microsoft.com/.default")
        return token.token

    person_directory = GraphPersonDirectory(
        client=http_client,
        token_provider=graph_token,
        base_url=env.get("FDAI_GRAPH_BASE_URL", "https://graph.microsoft.com/v1.0"),
    )
    storage_config = AzureDataLakeConfig(
        account_name=env["FDAI_ADLS_ACCOUNT_NAME"].strip(),
        account_url=env["FDAI_ADLS_ACCOUNT_URL"].strip(),
        source_file_system=env.get("FDAI_ADLS_SOURCE_FILE_SYSTEM", "documents").strip(),
        derived_file_system=env.get("FDAI_ADLS_DERIVED_FILE_SYSTEM", "derived").strip(),
    )
    object_store = AzureDataLakeObjectStore.from_identity(
        config=storage_config,
        identity=identity,
    )
    artifact_store = AzureDataLakeArtifactStore.from_identity(
        config=storage_config,
        identity=identity,
    )
    metadata = PostgresDocumentMetadataStore(config=PostgresDocumentMetadataStoreConfig(dsn=dsn))
    secrets = EnvSecretProvider(env={"document-index-dsn": dsn}, prefix="")
    embedder = AzureOpenAIEmbeddingModel(
        identity=identity,
        http_client=http_client,
        config=AzureOpenAIEmbeddingModelConfig(
            endpoint=env["FDAI_EMBEDDING_ENDPOINT"].strip(),
            deployment=env["FDAI_EMBEDDING_DEPLOYMENT"].strip(),
            dim=_positive_int(env, "FDAI_EMBEDDING_DIM", 384),
        ),
    )
    document_index = PgvectorDocumentIndex(
        config=PgvectorDocumentIndexConfig(
            dsn_secret="document-index-dsn",  # noqa: S106 - provider lookup key, not a secret
            embedding_dim=_positive_int(env, "FDAI_EMBEDDING_DIM", 384),
            max_chars=_positive_int(env, "FDAI_DOCUMENT_CHUNK_MAX_CHARS", 1200),
            overlap=_nonnegative_int(env, "FDAI_DOCUMENT_CHUNK_OVERLAP", 150),
        ),
        embedder=embedder,
        secrets=secrets,
    )
    event_bus = EventHubsKafkaBus(
        identity=identity,
        config=EventHubsKafkaBusConfig(
            bootstrap_servers=env["FDAI_KAFKA_BOOTSTRAP_SERVERS"].strip(),
            client_id="fdai-ingestion",
            auto_offset_reset="earliest",
        ),
    )
    state_store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=dsn))
    handover_drafts = StateStoreHandoverDraftStore(state_store=state_store)
    stewardship_governance = build_production_stewardship_governance(
        env=env,
        repo_root=Path(__file__).resolve().parents[4],
        http_client=http_client,
        state_store=state_store,
    )
    activity = DurableDocumentActivitySink(
        state_store=state_store,
        event_bus=event_bus,
        event_topic=env["FDAI_DOCUMENT_EVENT_TOPIC"].strip(),
    )
    access = ClaimsDocumentAccessProvider()
    capabilities = IngestionCapabilities(
        supported_formats=("text", "ooxml", "image-metadata", "pdf-detect-only"),
        storage_modes=tuple(SourceStorageMode),
        max_file_size=_positive_int(env, "FDAI_DOCUMENT_MAX_FILE_SIZE", 25 * 1024 * 1024),
        max_batch_count=_positive_int(env, "FDAI_DOCUMENT_MAX_BATCH_COUNT", 10),
        archives_enabled=False,
        policy_versions=(env.get("FDAI_DOCUMENT_POLICY_VERSION", "prod-policy-v1"),),
    )
    service = DocumentIngestionService(
        access=access,
        metadata=metadata,
        objects=object_store,
        activity=activity,
        capabilities=capabilities,
    )
    worker = DocumentIngestionWorker(
        access=access,
        metadata=metadata,
        objects=object_store,
        malware=ClamAvMalwareScanner(
            config=ClamAvScannerConfig(
                host=env.get("FDAI_CLAMAV_HOST", "127.0.0.1"),
                port=_positive_int(env, "FDAI_CLAMAV_PORT", 3310),
                max_stream_bytes=capabilities.max_file_size,
            )
        ),
        protection=SignatureProtectionInspector(),
        extractor=StandardLibraryDocumentExtractor(),
        artifacts=artifact_store,
        index=document_index,
        activity=activity,
        consumers=(
            HandoverBootstrapConsumer(
                bootstrapper=HandoverBootstrapper(directory=person_directory),
                store=handover_drafts,
                governance=(
                    stewardship_governance.service if stewardship_governance is not None else None
                ),
            ),
        ),
        indexing_stage_timeout_seconds=_positive_int(
            env, "FDAI_DOCUMENT_INDEXING_STAGE_TIMEOUT_SECONDS", 90
        ),
    )
    worker_service = DocumentIngestionEventConsumer(
        event_bus=event_bus,
        worker=worker,
        metadata=metadata,
        topic=env["FDAI_DOCUMENT_EVENT_TOPIC"].strip(),
    )
    verifier = EntraJwtVerifier.from_env(env)
    resolver = RoleResolver(group_mapping=_group_mapping(env))
    authenticator = build_authenticator(verifier=verifier, resolver=resolver)
    return build_app(
        authenticator=authenticator,
        service=service,
        worker=worker,
        search_index=document_index,
        handover_drafts=handover_drafts,
        stewardship_webhook=(
            stewardship_governance.webhook if stewardship_governance is not None else None
        ),
        config=IngestionGatewayConfig(
            proxy_upload=True,
            background_services=(worker_service.run, worker_service.reconcile),
            cors_allow_origins=_origins(env["FDAI_INGESTION_CORS_ALLOW_ORIGINS"]),
            default_reader_groups=(env["FDAI_RBAC_READERS_GROUP_ID"].strip(),),
            allowed_collections=_collections(
                env.get("FDAI_DOCUMENT_COLLECTIONS", "shared-knowledge")
            ),
            shutdown_callbacks=(
                event_bus.close,
                object_store.close,
                artifact_store.close,
                http_client.aclose,
            ),
        ),
    )


def app() -> Starlette:
    return build_prod_app()


def _group_mapping(env: Mapping[str, str]) -> GroupMapping:
    return GroupMapping(
        reader_group_id=env["FDAI_RBAC_READERS_GROUP_ID"].strip(),
        contributor_group_id=env["FDAI_RBAC_CONTRIBUTORS_GROUP_ID"].strip(),
        approver_group_id=env["FDAI_RBAC_APPROVERS_GROUP_ID"].strip(),
        owner_group_id=env["FDAI_RBAC_OWNERS_GROUP_ID"].strip(),
        break_glass_group_id=env["FDAI_RBAC_BREAK_GLASS_GROUP_ID"].strip(),
    )


def _origins(raw: str) -> tuple[str, ...]:
    origins = tuple(value.strip().rstrip("/") for value in raw.split(",") if value.strip())
    if not origins or "*" in origins:
        raise ProdIngestionConfigError("ingestion CORS origins MUST be explicit")
    return origins


def _collections(raw: str) -> tuple[str, ...]:
    collections = tuple(value.strip() for value in raw.split(",") if value.strip())
    if not collections:
        raise ProdIngestionConfigError("at least one document collection is required")
    return collections


def _positive_int(env: Mapping[str, str], key: str, default: int) -> int:
    value = int(env.get(key, str(default)))
    if value < 1:
        raise ProdIngestionConfigError(f"{key} MUST be positive")
    return value


def _nonnegative_int(env: Mapping[str, str], key: str, default: int) -> int:
    value = int(env.get(key, str(default)))
    if value < 0:
        raise ProdIngestionConfigError(f"{key} MUST be nonnegative")
    return value


__all__ = ["ProdIngestionConfigError", "app", "build_prod_app"]
