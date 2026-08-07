"""Production composition for the independent Document Ingestion API."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping

import httpx
import psycopg
from azure.identity.aio import ManagedIdentityCredential
from azure.storage.filedatalake.aio import DataLakeServiceClient
from fdai_service_contracts import IngestionCapabilities, SourceStorageMode
from starlette.applications import Starlette

from fdai_ingestion_api_service.access import ClaimsDocumentAccessProvider
from fdai_ingestion_api_service.adapters.embedding import (
    AzureEmbeddingConfig,
    AzureEmbeddingModel,
)
from fdai_ingestion_api_service.adapters.event_bus import EventHubsKafkaPublisher
from fdai_ingestion_api_service.adapters.handover import PostgresHandoverDraftReader
from fdai_ingestion_api_service.adapters.postgres import (
    PostgresApiConfig,
    PostgresDocumentActivitySink,
    PostgresDocumentMetadataStore,
    PostgresDocumentSearch,
)
from fdai_ingestion_api_service.adapters.stewardship import (
    GitHubRepositoryHandoverIntake,
    GitHubRepositoryHandoverIntakeConfig,
    GitHubStewardshipWebhook,
    GitHubStewardshipWebhookConfig,
    PostgresRepositoryHandoverDraftRecorder,
    PostgresStewardshipMergeRecorder,
)
from fdai_ingestion_api_service.adapters.storage import (
    AzureDataLakeConfig,
    AzureDataLakeObjectStore,
)
from fdai_ingestion_api_service.auth import Authenticator, EntraJwtVerifier, GroupMapping
from fdai_ingestion_api_service.deletion import ApiDocumentDeletionService
from fdai_ingestion_api_service.http import IngestionGatewayConfig, build_app
from fdai_ingestion_api_service.ingestion import DocumentIngestionService

_REQUIRED_ENV = (
    "FDAI_DATABASE_URL",
    "FDAI_DATABASE_ROLE",
    "FDAI_INGESTION_DEPLOYMENT_ROLE",
    "FDAI_ADLS_ACCOUNT_URL",
    "FDAI_EMBEDDING_ENDPOINT",
    "FDAI_EMBEDDING_DEPLOYMENT",
    "FDAI_KAFKA_BOOTSTRAP_SERVERS",
    "FDAI_DOCUMENT_EVENT_TOPIC",
    "FDAI_ENTRA_TENANT_ID",
    "FDAI_API_AUDIENCE",
    "FDAI_RBAC_READERS_GROUP_ID",
    "FDAI_RBAC_CONTRIBUTORS_GROUP_ID",
    "FDAI_RBAC_APPROVERS_GROUP_ID",
    "FDAI_RBAC_OWNERS_GROUP_ID",
    "FDAI_RBAC_BREAK_GLASS_GROUP_ID",
    "FDAI_INGESTION_CORS_ALLOW_ORIGINS",
)


class ProductionConfigurationError(ValueError):
    """Production API environment is incomplete or grants the wrong role."""


def build_application(environ: Mapping[str, str]) -> Starlette:
    """Build the complete service-owned production ASGI application."""
    env = dict(environ)
    missing = [key for key in _REQUIRED_ENV if not env.get(key, "").strip()]
    if missing:
        raise ProductionConfigurationError(
            "production ingestion environment is missing: " + ", ".join(missing)
        )
    if env["FDAI_INGESTION_DEPLOYMENT_ROLE"].strip() != "api":
        raise ProductionConfigurationError("FDAI_INGESTION_DEPLOYMENT_ROLE MUST be api")
    if env["FDAI_DATABASE_ROLE"].strip() != "fdai_ingestion_api":
        raise ProductionConfigurationError("FDAI_DATABASE_ROLE MUST be fdai_ingestion_api")
    dsn = env["FDAI_DATABASE_URL"].strip()
    database = PostgresApiConfig(dsn=dsn)
    credential = ManagedIdentityCredential()
    http_client = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0))
    storage_config = AzureDataLakeConfig(
        account_url=env["FDAI_ADLS_ACCOUNT_URL"].strip(),
        source_file_system=env.get("FDAI_ADLS_SOURCE_FILE_SYSTEM", "documents").strip(),
        derived_file_system=env.get("FDAI_ADLS_DERIVED_FILE_SYSTEM", "derived").strip(),
    )
    storage = AzureDataLakeObjectStore(
        config=storage_config,
        service_client=DataLakeServiceClient(
            account_url=storage_config.account_url,
            credential=credential,
        ),
    )
    publisher = EventHubsKafkaPublisher(
        bootstrap_servers=env["FDAI_KAFKA_BOOTSTRAP_SERVERS"].strip(),
        credential=credential,
    )
    metadata = PostgresDocumentMetadataStore(config=database)
    activity = PostgresDocumentActivitySink(
        config=database,
        publisher=publisher,
        topic=env["FDAI_DOCUMENT_EVENT_TOPIC"].strip(),
        pantheon_topic=env.get("FDAI_PANTHEON_OBJECT_TOPIC", "aw.pantheon.objects").strip(),
    )
    access = ClaimsDocumentAccessProvider()
    service = DocumentIngestionService(
        access=access,
        metadata=metadata,
        objects=storage,
        activity=activity,
        capabilities=IngestionCapabilities(
            supported_formats=("text", "ooxml", "image-metadata", "pdf-text"),
            storage_modes=tuple(SourceStorageMode),
            max_file_size=_positive_int(env, "FDAI_DOCUMENT_MAX_FILE_SIZE", 25 * 1024 * 1024),
            max_batch_count=_positive_int(env, "FDAI_DOCUMENT_MAX_BATCH_COUNT", 10),
            archives_enabled=False,
            policy_versions=(env.get("FDAI_DOCUMENT_POLICY_VERSION", "prod-policy-v1"),),
        ),
    )

    async def verify_database_role() -> None:
        async with await psycopg.AsyncConnection.connect(dsn) as connection:
            row = await (await connection.execute("SELECT current_user")).fetchone()
        if row is None or str(row[0]) != "fdai_ingestion_api":
            raise ProductionConfigurationError("database session role is not fdai_ingestion_api")

    verifier = EntraJwtVerifier.from_env(env)
    authenticator = Authenticator(
        verifier=verifier,
        mapping=GroupMapping(
            reader_group_id=env["FDAI_RBAC_READERS_GROUP_ID"].strip(),
            contributor_group_id=env["FDAI_RBAC_CONTRIBUTORS_GROUP_ID"].strip(),
            approver_group_id=env["FDAI_RBAC_APPROVERS_GROUP_ID"].strip(),
            owner_group_id=env["FDAI_RBAC_OWNERS_GROUP_ID"].strip(),
            break_glass_group_id=env["FDAI_RBAC_BREAK_GLASS_GROUP_ID"].strip(),
        ),
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

    async def verify_adapters() -> None:
        results = await asyncio.gather(
            metadata.probe_readiness(),
            storage.probe_readiness(),
            publisher.probe_readiness(),
            embedding.probe_readiness(),
        )
        failures = tuple(
            f"{result.adapter}:{result.reason or 'unavailable'}"
            for result in results
            if not result.live_verified
        )
        if failures:
            raise ProductionConfigurationError(
                "ingestion API adapter readiness failed: " + ", ".join(failures)
            )

    stewardship_webhook = _build_stewardship_webhook(
        env=env,
        dsn=dsn,
        http_client=http_client,
    )
    repository_handover_intake = _build_repository_handover_intake(env=env, dsn=dsn)
    return build_app(
        authenticator=authenticator,
        service=service,
        deletion=ApiDocumentDeletionService(
            access=access,
            metadata=metadata,
            objects=storage,
            database=database,
            activity=activity,
        ),
        search_index=PostgresDocumentSearch(
            config=database,
            embedder=embedding,
            dimension=dimension,
        ),
        handover_drafts=PostgresHandoverDraftReader(dsn=dsn),
        stewardship_webhook=stewardship_webhook,
        repository_handover_intake=repository_handover_intake,
        config=IngestionGatewayConfig(
            proxy_upload=True,
            startup_checks=(verify_database_role, verify_adapters),
            cors_allow_origins=_origins(env["FDAI_INGESTION_CORS_ALLOW_ORIGINS"]),
            default_reader_groups=(env["FDAI_RBAC_READERS_GROUP_ID"].strip(),),
            allowed_collections=_collections(
                env.get("FDAI_DOCUMENT_COLLECTIONS", "shared-knowledge")
            ),
            shutdown_callbacks=(publisher.close, storage.close, http_client.aclose),
        ),
    )


def _positive_int(env: Mapping[str, str], key: str, default: int) -> int:
    value = int(env.get(key, str(default)))
    if value < 1:
        raise ProductionConfigurationError(f"{key} MUST be positive")
    return value


def _origins(raw: str) -> tuple[str, ...]:
    values = tuple(value.strip().rstrip("/") for value in raw.split(",") if value.strip())
    if not values or "*" in values:
        raise ProductionConfigurationError("ingestion CORS origins MUST be explicit")
    return values


def _collections(raw: str) -> tuple[str, ...]:
    values = tuple(value.strip() for value in raw.split(",") if value.strip())
    if not values:
        raise ProductionConfigurationError("at least one document collection is required")
    return values


def _build_stewardship_webhook(
    *, env: Mapping[str, str], dsn: str, http_client: httpx.AsyncClient
) -> GitHubStewardshipWebhook | None:
    enabled = env.get("FDAI_STEWARDSHIP_GITHUB_WEBHOOK_ENABLED", "").strip().casefold()
    if enabled not in {"1", "true", "yes", "on"}:
        return None
    required = (
        "FDAI_GITOPS_OWNER",
        "FDAI_GITOPS_REPO",
        "FDAI_GITOPS_TOKEN",
        "FDAI_GITHUB_WEBHOOK_SECRET",
    )
    missing = [key for key in required if not env.get(key, "").strip()]
    if missing:
        raise ProductionConfigurationError(
            "stewardship webhook environment is missing: " + ", ".join(missing)
        )
    return GitHubStewardshipWebhook(
        config=GitHubStewardshipWebhookConfig(
            repository=f"{env['FDAI_GITOPS_OWNER'].strip()}/{env['FDAI_GITOPS_REPO'].strip()}",
            webhook_secret=env["FDAI_GITHUB_WEBHOOK_SECRET"].strip(),
            token=env["FDAI_GITOPS_TOKEN"].strip(),
            api_base=env.get("FDAI_GITOPS_API_BASE", "https://api.github.com").strip(),
            timeout_seconds=float(env.get("FDAI_GITOPS_TIMEOUT_SECONDS", "15")),
        ),
        http_client=http_client,
        recorder=PostgresStewardshipMergeRecorder(dsn=dsn),
    )


def _build_repository_handover_intake(
    *, env: Mapping[str, str], dsn: str
) -> GitHubRepositoryHandoverIntake | None:
    enabled = env.get("FDAI_STEWARDSHIP_REPOSITORY_INTAKE_ENABLED", "").strip().casefold()
    if enabled not in {"1", "true", "yes", "on"}:
        return None
    required = ("FDAI_GITOPS_OWNER", "FDAI_GITOPS_REPO", "FDAI_GITHUB_WEBHOOK_SECRET")
    missing = [key for key in required if not env.get(key, "").strip()]
    if missing:
        raise ProductionConfigurationError(
            "repository handover intake environment is missing: " + ", ".join(missing)
        )
    return GitHubRepositoryHandoverIntake(
        config=GitHubRepositoryHandoverIntakeConfig(
            repository=f"{env['FDAI_GITOPS_OWNER'].strip()}/{env['FDAI_GITOPS_REPO'].strip()}",
            webhook_secret=env["FDAI_GITHUB_WEBHOOK_SECRET"].strip(),
        ),
        recorder=PostgresRepositoryHandoverDraftRecorder(dsn=dsn),
    )
