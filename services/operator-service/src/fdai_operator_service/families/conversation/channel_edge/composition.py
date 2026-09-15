"""Compose the standalone channel edge from Operator-owned dependencies."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

import httpx
from azure.identity.aio import ClientSecretCredential, ManagedIdentityCredential
from fdai_operator_service.adapters.semantic_kafka import (
    OperatorSemanticKafkaBus,
    OperatorSemanticKafkaConfig,
)
from fdai_operator_service.families.conversation.channel_delivery_models import ChannelKind
from fdai_operator_service.families.conversation.channel_edge.attachment_handoff import (
    AzureAttachmentTokenProvider,
    BoundedAttachmentSpool,
    ChannelAttachmentFetcher,
    ChannelAttachmentIntakeClient,
    ConfiguredTeamsAttachmentEndpointResolver,
    SlackPrivateAttachmentFetcher,
    StaticSlackBotTokenProvider,
    TeamsPrivateAttachmentFetcher,
)
from fdai_operator_service.families.conversation.channel_edge.attachment_ingestion import (
    ChannelAttachmentIngestor,
)
from fdai_operator_service.families.conversation.channel_edge.environment import (
    ChannelEdgeConfigurationError,
    ChannelEdgeEnvironment,
    PrincipalScopeSettings,
)
from fdai_operator_service.families.conversation.channel_edge.pipeline import (
    ChannelDeliveryPipeline,
)
from fdai_operator_service.families.conversation.channel_edge.pipeline_contracts import (
    ChannelPrincipalContext,
    ChannelPublisher,
)
from fdai_operator_service.families.conversation.channel_edge.provider_adapters import (
    AzureChannelTokenProvider,
    RemoteJwksConfig,
    RemoteJwksProvider,
)
from fdai_operator_service.families.conversation.channel_edge.publishers import (
    SlackPublisherConfig,
    SlackResponsePublisher,
    TeamsResponsePublisher,
)
from fdai_operator_service.families.conversation.channel_edge.queues import (
    SlackIngressQueue,
    TeamsEndpointRegistry,
    TeamsIngressQueue,
)
from fdai_operator_service.families.conversation.channel_edge.runtime import (
    AsyncResource,
    ChannelEdgeRuntime,
)
from fdai_operator_service.families.conversation.channel_edge.slack_ingress import (
    SlackIngressConfig,
    SlackIngressVerifier,
)
from fdai_operator_service.families.conversation.channel_edge.teams_auth import (
    TeamsServiceTokenVerifier,
    TeamsTokenConfig,
)
from fdai_operator_service.families.conversation.channel_edge.teams_ingress import (
    TeamsIngressConfig,
    TeamsIngressVerifier,
)
from fdai_operator_service.families.conversation.channel_edge.worker import (
    ChannelDeliveryWorker,
    ChannelDeliveryWorkerConfig,
)
from fdai_operator_service.families.conversation.channel_message_ledger import (
    PostgresChannelMessageLedger,
    PostgresChannelMessageLedgerConfig,
)
from fdai_operator_service.families.conversation.contracts import PrincipalScope
from fdai_operator_service.families.conversation.postgres_channel_binding import (
    PostgresChannelBindingConfig,
    PostgresPrincipalChannelBindingStore,
)
from fdai_operator_service.families.conversation.postgres_channel_delivery import (
    PostgresChannelDeliveryConfig,
    PostgresChannelDeliveryStore,
)
from fdai_operator_service.families.conversation.semantic_turn_runtime import SemanticTurnBridge
from fdai_operator_service.postgres_family_store import (
    PostgresFamilyStore,
    PostgresFamilyStoreConfig,
)
from fdai_service_contracts.venue import ExecutionVenue, bus_security_protocol


@dataclass(frozen=True, slots=True)
class StaticChannelPrincipalResolver:
    """Resolve only startup-validated canonical principal scope records."""

    scopes: Mapping[str, PrincipalScopeSettings]

    async def resolve(self, principal_id: str) -> ChannelPrincipalContext:
        """Return one closed scope record or fail before semantic submission."""
        settings = self.scopes.get(principal_id)
        if settings is None:
            raise ValueError("authenticated channel principal has no configured scope")
        return ChannelPrincipalContext(
            scope=PrincipalScope(principal_id, settings.roles),
            scope_ref=settings.scope_ref,
            locale=settings.locale,
        )


@dataclass(frozen=True, slots=True)
class ProductionChannelEdgeComposition:
    """Build the production edge without Core imports or executor identity."""

    def build_runtime(self, environ: Mapping[str, str] | None = None) -> ChannelEdgeRuntime:
        """Bind one validated environment snapshot without starting network I/O."""
        environment = ChannelEdgeEnvironment.parse(os.environ if environ is None else environ)
        provider_http = httpx.AsyncClient(
            trust_env=False,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
        family_store = PostgresFamilyStore(
            PostgresFamilyStoreConfig(
                dsn=environment.database_url,
                role=environment.database_role,
            )
        )
        messages = PostgresChannelMessageLedger(
            config=PostgresChannelMessageLedgerConfig(dsn=environment.database_url)
        )
        bindings = PostgresPrincipalChannelBindingStore(
            config=PostgresChannelBindingConfig(dsn=environment.database_url)
        )
        deliveries = PostgresChannelDeliveryStore(
            config=PostgresChannelDeliveryConfig(dsn=environment.database_url)
        )
        semantic_credential = _semantic_credential(environment)
        semantic_bus = OperatorSemanticKafkaBus(
            config=OperatorSemanticKafkaConfig(
                bootstrap_servers=environment.kafka_bootstrap_servers,
                security_protocol=bus_security_protocol(environment.execution_venue),
                request_topic=environment.semantic_request_topic,
                projection_topic=environment.semantic_projection_topic,
                physical_topic=environment.semantic_physical_topic,
                client_id=environment.semantic_client_id,
            ),
            credential=semantic_credential,
        )
        semantic_bridge = SemanticTurnBridge(
            store=family_store,
            publisher=semantic_bus,
            result_source=semantic_bus,
            request_topic=environment.semantic_request_topic,
            result_topic=environment.semantic_projection_topic,
            result_group=environment.semantic_consumer_group,
        )
        publishers: dict[ChannelKind, ChannelPublisher] = {}
        resources: list[AsyncResource] = [provider_http]
        startup_checks = []
        attachment_readiness_checks = []
        slack_queue = None
        if environment.slack is not None:
            slack = environment.slack
            slack_queue = SlackIngressQueue(
                ingress=SlackIngressVerifier(
                    SlackIngressConfig(
                        signing_secret=slack.signing_secret,
                        team_id=slack.team_id,
                        principal_by_sender_id=slack.principal_by_sender_id,
                        attachments_enabled=environment.attachments_enabled,
                    )
                )
            )
            publishers[ChannelKind.SLACK] = SlackResponsePublisher(
                config=SlackPublisherConfig(bot_token=slack.bot_token),
                http_client=provider_http,
            )
        teams_queue = None
        if environment.teams is not None:
            teams = environment.teams
            jwks = RemoteJwksProvider(
                config=RemoteJwksConfig(url=teams.jwks_url),
                http_client=provider_http,
            )
            startup_checks.append(jwks.warm)
            endpoints = TeamsEndpointRegistry(allowed_service_urls=teams.allowed_service_urls)
            teams_queue = TeamsIngressQueue(
                ingress=TeamsIngressVerifier(
                    config=TeamsIngressConfig(
                        tenant_id=teams.tenant_id,
                        allowed_service_urls=teams.allowed_service_urls,
                        principal_by_aad_object_id=teams.principal_by_aad_object_id,
                        attachments_enabled=environment.attachments_enabled,
                    ),
                    tokens=TeamsServiceTokenVerifier(
                        config=TeamsTokenConfig(application_id=teams.application_id),
                        jwks=jwks,
                    ),
                ),
                endpoints=endpoints,
            )
            token_provider = AzureChannelTokenProvider(_teams_credential(environment))
            resources.append(token_provider)
            publishers[ChannelKind.TEAMS] = TeamsResponsePublisher(
                http_client=provider_http,
                identity=token_provider,
                endpoints=endpoints,
            )
        attachment_ingestor = None
        if environment.attachments is not None:
            attachment = environment.attachments
            attachment_http = httpx.AsyncClient(
                trust_env=False,
                follow_redirects=False,
                timeout=httpx.Timeout(30.0, connect=5.0),
                limits=httpx.Limits(max_connections=8, max_keepalive_connections=4),
            )
            intake_http = httpx.AsyncClient(
                trust_env=False,
                follow_redirects=False,
                timeout=httpx.Timeout(30.0, connect=5.0),
                limits=httpx.Limits(max_connections=8, max_keepalive_connections=4),
            )
            attachment_tokens = AzureAttachmentTokenProvider(_attachment_credential(environment))
            resources.extend((attachment_http, intake_http, attachment_tokens))
            spool = BoundedAttachmentSpool(scratch_directory=attachment.scratch_directory)
            fetchers: dict[ChannelKind, ChannelAttachmentFetcher] = {}
            if environment.slack is not None:
                if attachment.slack_files_info_url is None:
                    raise ChannelEdgeConfigurationError(
                        "Slack attachment metadata endpoint is unavailable"
                    )
                fetchers[ChannelKind.SLACK] = SlackPrivateAttachmentFetcher(
                    http_client=attachment_http,
                    tokens=StaticSlackBotTokenProvider(environment.slack.bot_token),
                    spool=spool,
                    files_info_url=attachment.slack_files_info_url,
                    metadata_hosts=attachment.slack_metadata_hosts,
                    download_hosts=attachment.slack_download_hosts,
                )
            if environment.teams is not None:
                if attachment.teams_url_template is None or attachment.teams_audience is None:
                    raise ChannelEdgeConfigurationError(
                        "Teams attachment endpoint resolver is unavailable"
                    )
                fetchers[ChannelKind.TEAMS] = TeamsPrivateAttachmentFetcher(
                    http_client=attachment_http,
                    tokens=attachment_tokens,
                    resolver=ConfiguredTeamsAttachmentEndpointResolver(
                        url_template=attachment.teams_url_template,
                        audience=attachment.teams_audience,
                    ),
                    spool=spool,
                    allowed_hosts=attachment.teams_hosts,
                    allowed_audiences=attachment.teams_audiences,
                )
            intake_client = ChannelAttachmentIntakeClient(
                http_client=intake_http,
                tokens=attachment_tokens,
                origin=attachment.intake_origin,
                audience=attachment.intake_audience,
                allow_loopback_http=(environment.execution_venue is ExecutionVenue.LOCAL),
            )
            attachment_readiness_checks.append(intake_client.probe_readiness)
            attachment_ingestor = ChannelAttachmentIngestor(
                intake=intake_client,
                fetchers=fetchers,
                principal_manifest_digest=attachment.principal_manifest_digest,
                max_content_bytes=attachment.max_content_bytes,
            )
        pipeline = ChannelDeliveryPipeline(
            messages=messages,
            principals=StaticChannelPrincipalResolver(environment.principal_scopes),
            bindings=bindings,
            deliveries=deliveries,
            semantic_outbox=semantic_bridge,
            semantic_streams=semantic_bridge,
            publishers=publishers,
            attachment_ingestor=attachment_ingestor,
        )
        worker = ChannelDeliveryWorker(
            store=deliveries,
            handler=pipeline,
            config=ChannelDeliveryWorkerConfig(
                channels=tuple(
                    channel
                    for channel in (ChannelKind.SLACK, ChannelKind.TEAMS)
                    if channel in environment.enabled_channels
                )
            ),
        )
        return ChannelEdgeRuntime(
            enabled_channels=environment.enabled_channels,
            pipeline=pipeline,
            worker=worker,
            semantic_transport=semantic_bus,
            semantic_bridge=semantic_bridge,
            slack_queue=slack_queue,
            teams_queue=teams_queue,
            readiness_checks=(
                family_store.probe_readiness,
                messages.probe_readiness,
                bindings.probe_readiness,
                deliveries.probe_readiness,
                semantic_bus.probe_readiness,
                *attachment_readiness_checks,
            ),
            startup_checks=tuple(startup_checks),
            resources=tuple(resources),
        )


def _semantic_credential(
    environment: ChannelEdgeEnvironment,
) -> ManagedIdentityCredential | None:
    if environment.execution_venue is ExecutionVenue.LOCAL:
        return None
    client_id = environment.managed_identity_client_id
    return (
        ManagedIdentityCredential(client_id=client_id) if client_id else ManagedIdentityCredential()
    )


def _teams_credential(
    environment: ChannelEdgeEnvironment,
) -> ClientSecretCredential | ManagedIdentityCredential:
    teams = environment.teams
    if teams is None:
        raise RuntimeError("Teams credential requested while Teams is disabled")
    if environment.execution_venue is ExecutionVenue.LOCAL:
        if teams.client_secret is None:
            raise RuntimeError("validated local Teams client secret is missing")
        return ClientSecretCredential(
            tenant_id=teams.tenant_id,
            client_id=teams.application_id,
            client_secret=teams.client_secret,
        )
    client_id = environment.managed_identity_client_id
    return (
        ManagedIdentityCredential(client_id=client_id) if client_id else ManagedIdentityCredential()
    )


def _attachment_credential(
    environment: ChannelEdgeEnvironment,
) -> ClientSecretCredential | ManagedIdentityCredential:
    settings = environment.attachments
    if settings is None:
        raise RuntimeError("attachment credential requested while attachments are disabled")
    if environment.execution_venue is ExecutionVenue.LOCAL:
        if settings.tenant_id is None or settings.client_secret is None:
            raise RuntimeError("validated local attachment identity is incomplete")
        return ClientSecretCredential(
            tenant_id=settings.tenant_id,
            client_id=settings.client_id,
            client_secret=settings.client_secret,
        )
    return ManagedIdentityCredential(client_id=settings.client_id)


__all__ = ["ProductionChannelEdgeComposition", "StaticChannelPrincipalResolver"]
