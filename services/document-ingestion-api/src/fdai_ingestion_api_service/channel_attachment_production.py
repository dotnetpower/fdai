"""Production composition for the internal channel attachment intake workload."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from datetime import timedelta
from pathlib import Path

import psycopg
from azure.identity.aio import ManagedIdentityCredential
from azure.storage.filedatalake.aio import DataLakeServiceClient
from fdai_service_contracts import IngestionCapabilities, SourceStorageMode
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
from fdai_ingestion_api_service.adapters.channel_attachment import (
    PostgresChannelAttachmentReservationStore,
)
from fdai_ingestion_api_service.adapters.event_bus import EventHubsKafkaPublisher
from fdai_ingestion_api_service.adapters.handover import PostgresHandoverDraftReader
from fdai_ingestion_api_service.adapters.local import (
    LocalDocumentObjectStore,
    PlaintextKafkaPublisher,
)
from fdai_ingestion_api_service.adapters.postgres import (
    PostgresApiConfig,
    PostgresDocumentActivitySink,
    PostgresDocumentMetadataStore,
)
from fdai_ingestion_api_service.adapters.storage import (
    AzureDataLakeConfig,
    AzureDataLakeObjectStore,
)
from fdai_ingestion_api_service.auth import (
    ChannelAttachmentWorkloadAuthenticator,
    EntraJwtVerifier,
)
from fdai_ingestion_api_service.channel_attachment import (
    ChannelAttachmentIntakeService,
    ChannelAttachmentPolicy,
    ChannelAttachmentPrincipalManifest,
)
from fdai_ingestion_api_service.channel_attachment_http import (
    ChannelAttachmentHttpConfig,
    build_channel_attachment_app,
)
from fdai_ingestion_api_service.ingestion import (
    DocumentIngestionService,
    DocumentLifecyclePolicy,
    TemporaryDocumentQuota,
)

_LOGGER = logging.getLogger(__name__)
_COMMON_REQUIRED = (
    "FDAI_DATABASE_URL",
    "FDAI_DATABASE_ROLE",
    "FDAI_INGESTION_DEPLOYMENT_ROLE",
    "FDAI_KAFKA_BOOTSTRAP_SERVERS",
    "FDAI_DOCUMENT_EVENT_TOPIC",
    "FDAI_ENTRA_TENANT_ID",
    "FDAI_CHANNEL_ATTACHMENT_API_AUDIENCE",
    "FDAI_CHANNEL_EDGE_CLIENT_ID",
    "FDAI_CHANNEL_ATTACHMENT_PRINCIPAL_SCOPES_JSON",
    "FDAI_CHANNEL_ATTACHMENT_COLLECTION_ID",
    "FDAI_CHANNEL_ATTACHMENT_ACCESS_DESCRIPTOR_REF",
    "FDAI_CHANNEL_ATTACHMENT_READER_GROUPS",
    "FDAI_CHANNEL_ATTACHMENT_RETENTION_POLICY_VERSION",
)
_DEPLOYED_REQUIRED = ("FDAI_MI_CLIENT_ID", "FDAI_ADLS_ACCOUNT_URL")


class ChannelAttachmentProductionConfigurationError(ValueError):
    """The internal intake workload is incomplete or has the wrong service role."""


def build_channel_attachment_application(environ: Mapping[str, str]) -> Starlette:
    """Compose the internal intake with the same document writer and event lifecycle."""

    env = dict(environ)
    venue = _execution_venue(env)
    required = _COMMON_REQUIRED + (_DEPLOYED_REQUIRED if venue is ExecutionVenue.DEPLOYED else ())
    missing = tuple(key for key in required if not env.get(key, "").strip())
    if missing:
        raise ChannelAttachmentProductionConfigurationError(
            "channel attachment intake environment is missing: " + ", ".join(missing)
        )
    if env["FDAI_INGESTION_DEPLOYMENT_ROLE"].strip() != "channel-intake":
        raise ChannelAttachmentProductionConfigurationError(
            "FDAI_INGESTION_DEPLOYMENT_ROLE MUST be channel-intake"
        )
    if env["FDAI_DATABASE_ROLE"].strip() != "fdai_ingestion_api":
        raise ChannelAttachmentProductionConfigurationError(
            "FDAI_DATABASE_ROLE MUST be fdai_ingestion_api"
        )

    dsn = env["FDAI_DATABASE_URL"].strip()
    database = PostgresApiConfig(dsn=dsn)
    credential = _managed_identity_credential(env) if uses_managed_identity(venue) else None
    storage: AzureDataLakeObjectStore | LocalDocumentObjectStore
    if uses_local_document_providers(venue):
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
                credential=_require_credential(credential),
            ),
        )
    publisher: EventHubsKafkaPublisher | PlaintextKafkaPublisher
    if uses_workload_identity(venue):
        publisher = EventHubsKafkaPublisher(
            bootstrap_servers=env["FDAI_KAFKA_BOOTSTRAP_SERVERS"].strip(),
            credential=_require_credential(credential),
            client_id="fdai-document-channel-intake",
        )
    else:
        publisher = PlaintextKafkaPublisher(
            bootstrap_servers=env["FDAI_KAFKA_BOOTSTRAP_SERVERS"].strip(),
            client_id="fdai-document-channel-intake-local",
        )
    metadata = PostgresDocumentMetadataStore(config=database)
    activity = PostgresDocumentActivitySink(
        config=database,
        publisher=publisher,
        topic=env["FDAI_DOCUMENT_EVENT_TOPIC"].strip(),
        pantheon_topic=env.get("FDAI_PANTHEON_OBJECT_TOPIC", "fdai.pantheon.objects").strip(),
    )
    access = ClaimsDocumentAccessProvider()
    policy_version = env["FDAI_CHANNEL_ATTACHMENT_RETENTION_POLICY_VERSION"].strip()
    max_file_size = _bounded_int(
        env,
        "FDAI_CHANNEL_ATTACHMENT_MAX_CONTENT_BYTES",
        25 * 1024 * 1024,
        maximum=1024 * 1024 * 1024,
    )
    ingestion = DocumentIngestionService(
        access=access,
        metadata=metadata,
        objects=storage,
        capabilities=IngestionCapabilities(
            supported_formats=("text", "ooxml", "image-metadata", "pdf-text"),
            storage_modes=(SourceStorageMode.MANAGED_COPY,),
            max_file_size=max_file_size,
            max_batch_count=8,
            archives_enabled=False,
            policy_versions=(policy_version,),
            ocr_available=False,
        ),
        lifecycle_policy=DocumentLifecyclePolicy(
            session_ephemeral_duration=timedelta(
                seconds=_bounded_int(
                    env,
                    "FDAI_DOCUMENT_SESSION_EPHEMERAL_DURATION_SECONDS",
                    24 * 60 * 60,
                    maximum=365 * 24 * 60 * 60,
                )
            )
        ),
        temporary_quota=TemporaryDocumentQuota(
            max_documents=_bounded_int(
                env,
                "FDAI_DOCUMENT_TEMPORARY_MAX_DOCUMENTS",
                100,
                maximum=100_000,
            ),
            max_bytes=_bounded_int(
                env,
                "FDAI_DOCUMENT_TEMPORARY_MAX_BYTES",
                256 * 1024 * 1024,
                maximum=10 * 1024 * 1024 * 1024 * 1024,
            ),
        ),
    )
    principals = ChannelAttachmentPrincipalManifest.parse(
        env["FDAI_CHANNEL_ATTACHMENT_PRINCIPAL_SCOPES_JSON"]
    )
    reader_groups = _csv(env["FDAI_CHANNEL_ATTACHMENT_READER_GROUPS"])
    policy = ChannelAttachmentPolicy(
        collection_id=env["FDAI_CHANNEL_ATTACHMENT_COLLECTION_ID"].strip(),
        access_descriptor_ref=env["FDAI_CHANNEL_ATTACHMENT_ACCESS_DESCRIPTOR_REF"].strip(),
        reader_groups=reader_groups,
        retention_policy_version=policy_version,
        max_content_bytes=max_file_size,
        require_handover_governance=venue is ExecutionVenue.DEPLOYED,
        admission_ttl=timedelta(
            seconds=_bounded_int(
                env,
                "FDAI_CHANNEL_ATTACHMENT_ADMISSION_TTL_SECONDS",
                15 * 60,
                maximum=60 * 60,
            )
        ),
    )
    handover_reader = PostgresHandoverDraftReader(dsn=dsn)
    intake = ChannelAttachmentIntakeService(
        ingestion=ingestion,
        metadata=metadata,
        access=access,
        reservations=PostgresChannelAttachmentReservationStore(dsn=dsn),
        principals=principals,
        policy=policy,
        handover_drafts=handover_reader,
        handover_governance=handover_reader,
    )
    verifier_env = {
        **env,
        "FDAI_API_AUDIENCE": env["FDAI_CHANNEL_ATTACHMENT_API_AUDIENCE"].strip(),
    }
    authenticator = ChannelAttachmentWorkloadAuthenticator(
        verifier=EntraJwtVerifier.from_env(verifier_env),
        allowed_client_id=env["FDAI_CHANNEL_EDGE_CLIENT_ID"].strip(),
    )

    async def verify_database_role() -> None:
        async with await psycopg.AsyncConnection.connect(dsn) as connection:
            row = await (await connection.execute("SELECT current_user")).fetchone()
        if row is None or str(row[0]) != "fdai_ingestion_api":
            raise ChannelAttachmentProductionConfigurationError(
                "database session role is not fdai_ingestion_api"
            )

    async def verify_adapters() -> None:
        results = await asyncio.gather(
            metadata.probe_readiness(),
            storage.probe_readiness(),
            publisher.probe_readiness(),
        )
        failures = tuple(
            f"{result.adapter}:{result.reason or 'unavailable'}"
            for result in results
            if not result.live_verified
        )
        if failures:
            raise ChannelAttachmentProductionConfigurationError(
                "channel attachment adapter readiness failed: " + ", ".join(failures)
            )

    async def drain_api_outbox() -> None:
        while True:
            try:
                published = await activity.drain()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - durable outbox remains retryable
                _LOGGER.error(
                    "channel_attachment_outbox_drain_failed",
                    extra={"exception_type": type(exc).__name__},
                )
                published = 0
            await asyncio.sleep(0.1 if published else 2.0)

    return build_channel_attachment_app(
        authenticator=authenticator,
        intake=intake,
        config=ChannelAttachmentHttpConfig(
            startup_checks=(verify_database_role, verify_adapters),
            readiness_checks=(verify_database_role, verify_adapters),
            background_tasks=(drain_api_outbox,),
            shutdown_callbacks=(publisher.close, storage.close),
        ),
    )


def _execution_venue(env: Mapping[str, str]) -> ExecutionVenue:
    try:
        return resolve_execution_venue(env)
    except ExecutionVenueError as exc:
        raise ChannelAttachmentProductionConfigurationError(str(exc)) from exc


def _managed_identity_credential(env: Mapping[str, str]) -> ManagedIdentityCredential:
    return ManagedIdentityCredential(client_id=env["FDAI_MI_CLIENT_ID"].strip())


def _require_credential(
    credential: ManagedIdentityCredential | None,
) -> ManagedIdentityCredential:
    if credential is None:
        raise ChannelAttachmentProductionConfigurationError(
            "deployed channel attachment intake requires managed identity"
        )
    return credential


def _bounded_int(
    env: Mapping[str, str],
    key: str,
    default: int,
    *,
    maximum: int,
) -> int:
    try:
        value = int(env.get(key, str(default)))
    except ValueError as exc:
        raise ChannelAttachmentProductionConfigurationError(f"{key} MUST be an integer") from exc
    if value < 1 or value > maximum:
        raise ChannelAttachmentProductionConfigurationError(f"{key} MUST be in [1, {maximum}]")
    return value


def _csv(value: str) -> tuple[str, ...]:
    items = tuple(item.strip() for item in value.split(",") if item.strip())
    if not items or len(items) != len(set(items)) or any(len(item) > 256 for item in items):
        raise ChannelAttachmentProductionConfigurationError(
            "channel attachment reader groups MUST be unique and bounded"
        )
    return items


__all__ = [
    "ChannelAttachmentProductionConfigurationError",
    "build_channel_attachment_application",
]
