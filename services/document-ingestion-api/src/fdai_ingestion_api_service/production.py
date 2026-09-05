"""Production composition for the independent Document Ingestion API."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from pathlib import Path

import httpx
import psycopg
from azure.identity.aio import ManagedIdentityCredential
from azure.storage.filedatalake.aio import DataLakeServiceClient
from fdai_service_contracts import (
    DocumentPurpose,
    IngestionCapabilities,
    SourceStorageMode,
    supported_document_format_ids,
)
from fdai_service_contracts.venue import (
    ExecutionVenue,
    ExecutionVenueError,
    resolve_execution_venue,
    uses_local_document_providers,
    uses_managed_identity,
    uses_workload_identity,
)
from starlette.applications import Starlette

from fdai_ingestion_api_service.access import ClaimsDocumentAccessProvider
from fdai_ingestion_api_service.adapters.embedding import (
    AzureEmbeddingConfig,
    AzureEmbeddingModel,
)
from fdai_ingestion_api_service.adapters.event_bus import EventHubsKafkaPublisher
from fdai_ingestion_api_service.adapters.handover import PostgresHandoverDraftReader
from fdai_ingestion_api_service.adapters.local import (
    DeterministicLocalEmbeddingModel,
    LocalDocumentObjectStore,
    PlaintextKafkaPublisher,
)
from fdai_ingestion_api_service.adapters.postgres import (
    PostgresApiConfig,
    PostgresDocumentActivitySink,
    PostgresDocumentMetadataStore,
    PostgresDocumentSearch,
)
from fdai_ingestion_api_service.adapters.protection import (
    PurviewRmsPreviewAuthorizer,
)
from fdai_ingestion_api_service.adapters.sharepoint import (
    MicrosoftGraphSharePointDeltaSource,
    SharePointDeltaConfig,
    SharePointDeltaSynchronizer,
)
from fdai_ingestion_api_service.adapters.sharepoint_identity import (
    FederatedManagedIdentityGraphCredential,
    SharePointFederatedCredentialConfig,
)
from fdai_ingestion_api_service.adapters.sharepoint_state import (
    PostgresSharePointDeltaStore,
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
from fdai_ingestion_api_service.auth import (
    Authenticator,
    EntraJwtVerifier,
    GroupMapping,
)
from fdai_ingestion_api_service.deletion import ApiDocumentDeletionService
from fdai_ingestion_api_service.download import GovernedDocumentDownload
from fdai_ingestion_api_service.http import IngestionGatewayConfig, build_app
from fdai_ingestion_api_service.ingestion import DocumentIngestionService
from fdai_ingestion_api_service.preview import (
    GovernedDocumentPreview,
    MetadataPreviewProtectionAuthorizer,
    PreviewProtectionAuthorizer,
)
from fdai_ingestion_api_service.sharepoint_connector import (
    NativeSharePointDeltaSink,
    SharePointConnectorConfig,
    SharePointConnectorIntake,
)

_COMMON_REQUIRED_ENV = (
    "FDAI_DATABASE_URL",
    "FDAI_DATABASE_ROLE",
    "FDAI_INGESTION_DEPLOYMENT_ROLE",
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
_DEPLOYED_REQUIRED_ENV = (
    "FDAI_MI_CLIENT_ID",
    "FDAI_ADLS_ACCOUNT_URL",
    "FDAI_EMBEDDING_ENDPOINT",
    "FDAI_EMBEDDING_DEPLOYMENT",
)
_LOGGER = logging.getLogger(__name__)


class ProductionConfigurationError(ValueError):
    """Production API environment is incomplete or grants the wrong role."""


def build_application(environ: Mapping[str, str]) -> Starlette:
    """Build the complete service-owned production ASGI application."""
    env = dict(environ)
    execution_venue = _execution_venue(env)
    required = _COMMON_REQUIRED_ENV + (
        _DEPLOYED_REQUIRED_ENV if execution_venue is ExecutionVenue.DEPLOYED else ()
    )
    missing = [key for key in required if not env.get(key, "").strip()]
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
    http_client = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0))
    credential = (
        _managed_identity_credential(env) if uses_managed_identity(execution_venue) else None
    )
    storage: AzureDataLakeObjectStore | LocalDocumentObjectStore
    if uses_local_document_providers(execution_venue):
        storage = LocalDocumentObjectStore(
            Path(env.get("FDAI_LOCAL_DOCUMENT_STORE_DIR", ".fdai/document-store"))
        )
    else:
        storage_config = AzureDataLakeConfig(
            account_url=env["FDAI_ADLS_ACCOUNT_URL"].strip(),
            source_file_system=env.get("FDAI_ADLS_SOURCE_FILE_SYSTEM", "documents").strip(),
            derived_file_system=env.get("FDAI_ADLS_DERIVED_FILE_SYSTEM", "derived").strip(),
        )
        storage = AzureDataLakeObjectStore(
            config=storage_config,
            service_client=DataLakeServiceClient(
                account_url=storage_config.account_url,
                credential=_azure_credential(credential),
            ),
        )
    publisher: EventHubsKafkaPublisher | PlaintextKafkaPublisher
    if uses_workload_identity(execution_venue):
        publisher = EventHubsKafkaPublisher(
            bootstrap_servers=env["FDAI_KAFKA_BOOTSTRAP_SERVERS"].strip(),
            credential=_azure_credential(credential),
        )
    else:
        publisher = PlaintextKafkaPublisher(
            bootstrap_servers=env["FDAI_KAFKA_BOOTSTRAP_SERVERS"].strip()
        )
    metadata = PostgresDocumentMetadataStore(config=database)
    activity = PostgresDocumentActivitySink(
        config=database,
        publisher=publisher,
        topic=env["FDAI_DOCUMENT_EVENT_TOPIC"].strip(),
        pantheon_topic=env.get("FDAI_PANTHEON_OBJECT_TOPIC", "fdai.pantheon.objects").strip(),
    )
    access = ClaimsDocumentAccessProvider()
    ocr_provider = env.get("FDAI_DOCUMENT_OCR_PROVIDER", "local_python").strip()
    if ocr_provider not in {"local_python", "azure_document_intelligence"}:
        raise ProductionConfigurationError(
            "FDAI_DOCUMENT_OCR_PROVIDER MUST be local_python or azure_document_intelligence"
        )
    ocr_available = ocr_provider == "local_python" or bool(env.get("FDAI_OCR_ENDPOINT", "").strip())
    service = DocumentIngestionService(
        access=access,
        metadata=metadata,
        objects=storage,
        capabilities=IngestionCapabilities(
            supported_formats=supported_document_format_ids(include_ocr=ocr_available),
            storage_modes=tuple(SourceStorageMode),
            max_file_size=_positive_int(env, "FDAI_DOCUMENT_MAX_FILE_SIZE", 25 * 1024 * 1024),
            max_batch_count=_positive_int(env, "FDAI_DOCUMENT_MAX_BATCH_COUNT", 10),
            archives_enabled=False,
            policy_versions=(env.get("FDAI_DOCUMENT_POLICY_VERSION", "prod-policy-v1"),),
            ocr_available=ocr_available,
        ),
    )
    deletion_service = ApiDocumentDeletionService(access=access, metadata=metadata)

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
    embedding = (
        DeterministicLocalEmbeddingModel(dimension=dimension)
        if uses_local_document_providers(execution_venue)
        else AzureEmbeddingModel(
            config=AzureEmbeddingConfig(
                endpoint=env["FDAI_EMBEDDING_ENDPOINT"].strip(),
                deployment=env["FDAI_EMBEDDING_DEPLOYMENT"].strip(),
                dimension=dimension,
            ),
            credential=_azure_credential(credential),
            client=http_client,
        )
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

    async def drain_api_outbox() -> None:
        while True:
            try:
                published = await activity.drain()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - durable rows remain retryable
                _LOGGER.error(
                    "document_api_outbox_drain_failed",
                    extra={"exception_type": type(exc).__name__},
                )
                published = 0
            await asyncio.sleep(0.1 if published else 2.0)

    connector_drainers = [drain_api_outbox]
    if _truthy(env.get("FDAI_SHAREPOINT_CONNECTOR_ENABLED", "")):
        if uses_local_document_providers(execution_venue):
            raise ProductionConfigurationError(
                "SharePoint connector requires the deployed execution venue"
            )
        connector_config = _sharepoint_connector_config(env)
        connector_state = PostgresSharePointDeltaStore(dsn=dsn)
        federated_config = SharePointFederatedCredentialConfig(
            target_tenant_id=connector_config.target_tenant_id,
            client_id=env["FDAI_SHAREPOINT_CLIENT_ID"].strip(),
        )
        graph_config = SharePointDeltaConfig(
            connector_id=connector_config.connector_id,
            site_id=env["FDAI_SHAREPOINT_SITE_ID"].strip(),
            drive_id=env["FDAI_SHAREPOINT_DRIVE_ID"].strip(),
            collection_id=connector_config.collection_id,
            access_descriptor_ref=connector_config.access_descriptor_ref,
            page_size=_positive_int(env, "FDAI_SHAREPOINT_DELTA_PAGE_SIZE", 100),
            max_pages_per_run=_positive_int(env, "FDAI_SHAREPOINT_DELTA_MAX_PAGES", 20),
            download_host_suffixes=tuple(
                value.strip()
                for value in env.get(
                    "FDAI_SHAREPOINT_DOWNLOAD_HOST_SUFFIXES", ".sharepoint.com"
                ).split(",")
                if value.strip()
            ),
            identity_binding=federated_config.binding_digest,
        )
        graph_credential = FederatedManagedIdentityGraphCredential(
            config=federated_config,
            managed_identity=_azure_credential(credential),
            client=http_client,
        )
        graph_source = MicrosoftGraphSharePointDeltaSource(
            config=graph_config,
            credential=graph_credential,
            client=http_client,
        )
        connector_intake = SharePointConnectorIntake(
            config=connector_config,
            service=service,
            state=connector_state,
            deletion=deletion_service,
        )
        synchronizer = SharePointDeltaSynchronizer(
            config=graph_config,
            source=graph_source,
            cursors=connector_state,
            sink=NativeSharePointDeltaSink(
                config=connector_config,
                source=graph_source,
                intake=connector_intake,
                max_file_size=service.capabilities.max_file_size,
            ),
        )

        async def reconcile_sharepoint_connector() -> None:
            while True:
                try:
                    applied = await synchronizer.synchronize()
                    await connector_state.reconcile_deletions(limit=100)
                    await connector_intake.reconcile_cancellations(
                        actor_id=(f"sharepoint-connector:{connector_config.binding_id}:reconciler"),
                        limit=100,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 - hold intent remains retryable
                    _LOGGER.error(
                        "sharepoint_connector_reconcile_failed",
                        extra={"exception_type": type(exc).__name__},
                    )
                    applied = 0
                await asyncio.sleep(
                    0.1
                    if applied
                    else _positive_int(env, "FDAI_SHAREPOINT_DELTA_INTERVAL_SECONDS", 60)
                )

        connector_drainers.append(reconcile_sharepoint_connector)

    stewardship_webhook = _build_stewardship_webhook(
        env=env,
        dsn=dsn,
        http_client=http_client,
    )
    repository_handover_intake = _build_repository_handover_intake(env=env, dsn=dsn)
    preview_protection: PreviewProtectionAuthorizer = MetadataPreviewProtectionAuthorizer()
    if env.get("FDAI_DOCUMENT_PROTECTION_PROVIDER", "signature").strip() == "purview_rms":
        protection_endpoint = env.get("FDAI_PROTECTION_ENDPOINT", "").strip()
        protection_audience = env.get("FDAI_PROTECTION_AUDIENCE", "").strip()
        if not protection_endpoint or not protection_audience:
            raise ProductionConfigurationError(
                "purview_rms preview requires FDAI_PROTECTION_ENDPOINT and FDAI_PROTECTION_AUDIENCE"
            )
        preview_protection = PurviewRmsPreviewAuthorizer(
            endpoint=protection_endpoint,
            audience=protection_audience,
            credential=_azure_credential(credential),
            client=http_client,
            timeout_seconds=float(env.get("FDAI_PROTECTION_TIMEOUT_SECONDS", "15")),
        )
    return build_app(
        authenticator=authenticator,
        service=service,
        deletion=deletion_service,
        download=GovernedDocumentDownload(access=access, metadata=metadata, objects=storage),
        preview=GovernedDocumentPreview(
            access=access,
            metadata=metadata,
            artifacts=storage,
            protection=preview_protection,
            max_units=_positive_int(env, "FDAI_DOCUMENT_PREVIEW_MAX_UNITS", 200),
            max_characters=_positive_int(env, "FDAI_DOCUMENT_PREVIEW_MAX_CHARACTERS", 100_000),
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
            readiness_checks=(verify_database_role, verify_adapters),
            api_outbox_drainers=tuple(connector_drainers),
            cors_allow_origins=_origins(env["FDAI_INGESTION_CORS_ALLOW_ORIGINS"]),
            default_reader_groups=(env["FDAI_RBAC_READERS_GROUP_ID"].strip(),),
            allowed_collections=_collections(
                env.get("FDAI_DOCUMENT_COLLECTIONS", "shared-knowledge")
            ),
            shutdown_callbacks=(publisher.close, storage.close, http_client.aclose),
        ),
    )


def _managed_identity_credential(env: Mapping[str, str]) -> ManagedIdentityCredential:
    """Select the exact user-assigned identity attached to the API Container App."""
    return ManagedIdentityCredential(client_id=env["FDAI_MI_CLIENT_ID"].strip())


def _azure_credential(
    credential: ManagedIdentityCredential | None,
) -> ManagedIdentityCredential:
    """Refuse to bind an Azure provider in a venue that declares no managed identity."""
    if credential is None:
        raise ProductionConfigurationError("an Azure-backed provider requires a managed identity")
    return credential


def _execution_venue(env: Mapping[str, str]) -> ExecutionVenue:
    """Resolve the venue through the shared contract, keeping this service's error type."""
    try:
        return resolve_execution_venue(env)
    except ExecutionVenueError as exc:
        raise ProductionConfigurationError(str(exc)) from exc


def _positive_int(env: Mapping[str, str], key: str, default: int) -> int:
    value = int(env.get(key, str(default)))
    if value < 1:
        raise ProductionConfigurationError(f"{key} MUST be positive")
    return value


def _truthy(value: str) -> bool:
    return value.strip().casefold() in {"1", "true", "yes", "on"}


def _sharepoint_connector_config(
    env: Mapping[str, str],
) -> SharePointConnectorConfig:
    required = (
        "FDAI_SHAREPOINT_CONNECTOR_ID",
        "FDAI_SHAREPOINT_TARGET_TENANT_ID",
        "FDAI_SHAREPOINT_CLIENT_ID",
        "FDAI_SHAREPOINT_SITE_ID",
        "FDAI_SHAREPOINT_DRIVE_ID",
        "FDAI_SHAREPOINT_COLLECTION_ID",
        "FDAI_SHAREPOINT_ACCESS_DESCRIPTOR_REF",
        "FDAI_SHAREPOINT_RETENTION_POLICY_VERSION",
    )
    missing = [key for key in required if not env.get(key, "").strip()]
    if missing:
        raise ProductionConfigurationError(
            "SharePoint connector environment is missing: " + ", ".join(missing)
        )
    purposes = tuple(
        DocumentPurpose(value.strip())
        for value in env.get("FDAI_SHAREPOINT_PURPOSES", "knowledge_base").split(",")
        if value.strip()
    )
    reader_groups = tuple(
        value.strip()
        for value in env.get("FDAI_SHAREPOINT_READER_GROUPS", "").split(",")
        if value.strip()
    )
    return SharePointConnectorConfig(
        connector_id=env["FDAI_SHAREPOINT_CONNECTOR_ID"].strip(),
        target_tenant_id=env["FDAI_SHAREPOINT_TARGET_TENANT_ID"].strip(),
        collection_id=env["FDAI_SHAREPOINT_COLLECTION_ID"].strip(),
        access_descriptor_ref=env["FDAI_SHAREPOINT_ACCESS_DESCRIPTOR_REF"].strip(),
        reader_groups=reader_groups,
        retention_policy_version=env["FDAI_SHAREPOINT_RETENTION_POLICY_VERSION"].strip(),
        purposes=purposes,
    )


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
