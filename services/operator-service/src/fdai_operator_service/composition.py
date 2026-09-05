"""Production composition boundary for the independent Operator service."""

from __future__ import annotations

import os
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, cast

import httpx
from azure.identity.aio import ManagedIdentityCredential
from fdai_service_contracts import OperatorReadModel, OperatorTokenVerifier, ReadDataSource
from fdai_service_contracts.venue import (
    bus_security_protocol,
    resolve_execution_venue,
    uses_workload_identity,
)

from fdai_operator_service.action_confirmation_runtime import ActionConfirmationBridge
from fdai_operator_service.adapters import (
    LiveStageKafkaConfig,
    LiveStageKafkaRelay,
    LocalAzureNarratorAdapters,
    OperatorSemanticKafkaBus,
    OperatorSemanticKafkaConfig,
)
from fdai_operator_service.adapters.narrator_periodic_scheduler import (
    PeriodicNarratorRefreshScheduler,
)
from fdai_operator_service.adapters.resolved_models_key_vault import (
    KeyVaultResolvedModelsConfig,
    KeyVaultResolvedModelsSource,
)
from fdai_operator_service.auth import (
    EntraJwtVerifier,
    LocalAzureCliIdentity,
    OperatorAuthenticator,
    resolve_azure_cli_identity,
)
from fdai_operator_service.azure_monitor_webhook_runtime import AzureMonitorWebhookBridge
from fdai_operator_service.background_task_projection_runtime import (
    BackgroundTaskProjectionBridge,
)
from fdai_operator_service.context_selection import ContextSelectionRegistry
from fdai_operator_service.contracts import ApplicationLifecycle, ReadinessProbe
from fdai_operator_service.conversation_assurance_reader import (
    ConversationAssuranceReader,
    ConversationAssuranceReaderConfig,
)
from fdai_operator_service.environment import (
    OperatorEnvironment,
)
from fdai_operator_service.families.conversation import ConversationFamilyDependencies
from fdai_operator_service.families.conversation.document_export import (
    ConversationDocumentExporter,
)
from fdai_operator_service.families.conversation.semantic_turn import SemanticTurnEnvelopeBuilder
from fdai_operator_service.families.conversation.semantic_turn_runtime import (
    SEMANTIC_REQUEST_TOPIC,
    SEMANTIC_RESULT_TOPIC,
    SemanticTurnBridge,
    SemanticTurnConversationAdapters,
    SemanticTurnEventPublisher,
    SemanticTurnResultSource,
)
from fdai_operator_service.families.cost_governance import CostGovernanceFamilyDependencies
from fdai_operator_service.families.operations import PanelRoute
from fdai_operator_service.families.operations.contracts import ProjectionReader
from fdai_operator_service.family_adapters import (
    PostgresConversationAdapters,
    PostgresOperationsAdapters,
    PostgresWorkflowAdapters,
    UnavailableConversationAdapters,
    UnavailableOperationsAdapters,
    UnavailableWorkflowAdapters,
)
from fdai_operator_service.family_authorization import OperatorFamilyAuthorizer
from fdai_operator_service.iam_composition import (
    HIL_SIGNING_SECRET_ENV,
    HilDecisionOutboxBridge,
    build_hil_decision_outbox_bridge,
    build_postgres_iam_bindings,
    build_teams_hil_http_client,
    build_unavailable_iam_bindings,
)
from fdai_operator_service.model_lifecycle_startup import (
    AsyncResolvedModelsSource,
    ConfiguredResolvedModelsSource,
    OperatorResolvedModelsRevisionOwner,
)
from fdai_operator_service.postgres import (
    PostgresOperatorReadModel,
    PostgresOperatorReadModelConfig,
)
from fdai_operator_service.postgres_background_task_projection import (
    PostgresBackgroundTaskProjectionConfig,
    PostgresBackgroundTaskProjectionRepository,
)
from fdai_operator_service.postgres_cost_governance import (
    PostgresCostGovernanceConfig,
    PostgresCostGovernanceReader,
    UnavailableCostGovernanceReader,
)
from fdai_operator_service.postgres_family_store import (
    PostgresFamilyStore,
    PostgresFamilyStoreConfig,
)
from fdai_operator_service.postgres_read_investigation_completion import (
    PostgresReadInvestigationCompletionConfig,
    PostgresReadInvestigationCompletionRepository,
)
from fdai_operator_service.postgres_read_investigation_replay import (
    PostgresReadInvestigationReplayConfig,
    PostgresReadInvestigationReplayStore,
)
from fdai_operator_service.projections import UnavailableOperatorReadModel
from fdai_operator_service.read_investigation_completion_runtime import (
    ReadInvestigationCompletionBridge,
)
from fdai_operator_service.read_investigation_runtime import ReadInvestigationBridge
from fdai_operator_service.reporting import optional_pdf_report_encoder
from fdai_operator_service.reporting.incident_rca_projection import (
    IncidentRcaReportingProjectionReader,
)
from fdai_operator_service.routes import OperatorRouteFamilies
from fdai_operator_service.runtime import OperatorRuntime
from fdai_operator_service.runtime_projection_reader import (
    RuntimeProjectionReader,
    RuntimeProjectionReaderConfig,
)
from fdai_operator_service.streaming import LiveStreamEvent, LiveStreamHub
from fdai_operator_service.wara_projection import WaraAssessmentProjectionBridge

WEBHOOK_SIGNING_SECRET_ENV = "FDAI_OPERATOR_WEBHOOK_SECRET"  # noqa: S105
COST_PSEUDONYM_KEY_ENV = "FDAI_COST_PSEUDONYM_KEY"  # noqa: S105
REFERENCE_PANEL_ROUTES = (
    PanelRoute("/kpi/autonomy", "autonomy", "autonomy"),
    PanelRoute("/capabilities", "capabilities", "capabilities"),
    PanelRoute(
        "/configuration-baselines",
        "configuration-baselines",
        "configuration-baselines",
    ),
    PanelRoute(
        "/conversation-delivery",
        "conversation-delivery",
        "conversation-delivery",
    ),
    PanelRoute("/forecast-learning", "forecast-learning", "forecast-learning"),
    PanelRoute("/onboarding", "onboarding", "onboarding"),
    PanelRoute("/operator-memory", "operator-memory", "operator-memory"),
    PanelRoute("/skills", "skills", "skills"),
)


def _agent_state_key(event: LiveStreamEvent) -> str | None:
    payload = event.payload
    agent = payload.get("agent")
    return agent if payload.get("type") == "agent.state" and isinstance(agent, str) else None


class OperatorComposition(Protocol):
    """Build the complete service-owned runtime from explicit provider seams."""

    def build_runtime(self, environ: Mapping[str, str] | None = None) -> OperatorRuntime: ...


class TokenVerifierFactory(Protocol):
    """Build the process-local token verifier from validated environment state."""

    def __call__(self, environment: OperatorEnvironment) -> OperatorTokenVerifier: ...


LocalCliIdentityFactory = Callable[[], LocalAzureCliIdentity]
LocalCliSessionTokenFactory = Callable[[], str]


def _build_entra_verifier(environment: OperatorEnvironment) -> OperatorTokenVerifier:
    return EntraJwtVerifier.from_environment(environment)


@dataclass(frozen=True, slots=True)
class ProductionOperatorComposition:
    """Bind production identity and read providers without implementation imports."""

    verifier_factory: TokenVerifierFactory = _build_entra_verifier
    read_model: OperatorReadModel | None = None
    readiness_probe: ReadinessProbe | None = None
    semantic_event_publisher: SemanticTurnEventPublisher | None = None
    semantic_result_source: SemanticTurnResultSource | None = None
    resolved_models_source: AsyncResolvedModelsSource | None = None
    local_cli_identity_factory: LocalCliIdentityFactory = resolve_azure_cli_identity
    local_cli_session_token_factory: LocalCliSessionTokenFactory = lambda: secrets.token_urlsafe(32)

    def build_runtime(self, environ: Mapping[str, str] | None = None) -> OperatorRuntime:
        """Bind a validated environment snapshot to service-owned HTTP dependencies."""
        environment = OperatorEnvironment.parse(os.environ if environ is None else environ)
        model_revision_owner = _model_revision_owner(
            environment,
            source=self.resolved_models_source,
        )
        configured_read_model = self.read_model or _postgres_read_model(environment)
        family_store = _postgres_family_store(environment)
        context_selection_registry = ContextSelectionRegistry()
        semantic_bus: OperatorSemanticKafkaBus | None = None
        live_stream_hub = LiveStreamHub()
        agent_stream_hub = LiveStreamHub(latest_key=_agent_state_key)
        live_stage_relay: LiveStageKafkaRelay | None = None
        publisher = self.semantic_event_publisher
        result_source = self.semantic_result_source
        if publisher is None and result_source is None and environment.kafka_bootstrap_servers:
            if family_store is None:
                raise RuntimeError("semantic transport requires the authoritative PostgreSQL store")
            semantic_bus = _build_semantic_bus(environment)
            publisher = semantic_bus
            result_source = semantic_bus
            live_stage_relay = _build_live_stage_relay(
                environment, live_stream_hub, agent_stream_hub
            )
        semantic_bridge = _semantic_bridge(
            family_store,
            publisher=publisher,
            result_source=result_source,
            request_topic=environment.semantic_request_topic or SEMANTIC_REQUEST_TOPIC,
            result_topic=environment.semantic_projection_topic or SEMANTIC_RESULT_TOPIC,
            result_group=environment.semantic_consumer_group_id,
            context_selection_registry=context_selection_registry,
        )
        read_investigation_bridge = (
            ReadInvestigationBridge(
                store=family_store,
                publisher=semantic_bus,
                topic=environment.read_investigation_request_topic,
            )
            if family_store is not None
            and semantic_bus is not None
            and environment.read_investigation_request_topic is not None
            else None
        )
        background_task_projection_bridge = (
            BackgroundTaskProjectionBridge(
                store=PostgresBackgroundTaskProjectionRepository(
                    config=PostgresBackgroundTaskProjectionConfig(
                        dsn=environment.database_url,
                        statement_timeout_ms=environment.database_statement_timeout_ms,
                        connect_timeout_s=environment.database_connect_timeout_s,
                    )
                ),
                source=semantic_bus,
                publisher=semantic_bus,
                topic=environment.background_task_projection_topic,
                group_id=environment.background_task_projection_consumer_group_id,
            )
            if environment.database_url is not None
            and semantic_bus is not None
            and environment.background_task_projection_topic is not None
            and environment.background_task_projection_consumer_group_id is not None
            else None
        )
        wara_assessment_projection_bridge = (
            WaraAssessmentProjectionBridge(
                store=family_store,
                source=semantic_bus,
                publisher=semantic_bus,
            )
            if family_store is not None and semantic_bus is not None
            else None
        )
        read_investigation_completion_bridge = (
            ReadInvestigationCompletionBridge(
                store=PostgresReadInvestigationCompletionRepository(
                    config=PostgresReadInvestigationCompletionConfig(
                        dsn=environment.database_url,
                        statement_timeout_ms=environment.database_statement_timeout_ms,
                        connect_timeout_s=environment.database_connect_timeout_s,
                    )
                ),
                source=semantic_bus,
                publisher=semantic_bus,
                topic=environment.read_investigation_completion_topic,
                group_id=environment.read_investigation_completion_consumer_group_id,
            )
            if environment.database_url is not None
            and semantic_bus is not None
            and environment.read_investigation_completion_topic is not None
            and environment.read_investigation_completion_consumer_group_id is not None
            else None
        )
        event_topic = environment.values.get("KAFKA_TOPIC_EVENTS", "").strip() or None
        action_confirmation_bridge = (
            ActionConfirmationBridge(
                store=family_store,
                publisher=semantic_bus,
                topic=event_topic,
            )
            if family_store is not None and semantic_bus is not None and event_topic is not None
            else None
        )
        azure_monitor_webhook_bridge = (
            AzureMonitorWebhookBridge(
                store=family_store,
                publisher=semantic_bus,
                topic=event_topic,
            )
            if family_store is not None and semantic_bus is not None and event_topic is not None
            else None
        )
        local_cli_identity = (
            self.local_cli_identity_factory() if environment.local_azure_cli_auth else None
        )
        local_cli_session_token = (
            self.local_cli_session_token_factory() if local_cli_identity is not None else None
        )
        if local_cli_identity is not None and not local_cli_session_token:
            raise RuntimeError("local Azure CLI session token MUST NOT be empty")
        authenticator = OperatorAuthenticator(
            verifier=self.verifier_factory(environment),
            group_ids=environment.group_ids,
            local_principal=(
                local_cli_identity.principal if local_cli_identity is not None else None
            ),
            local_session_token=local_cli_session_token,
        )
        teams_http_client = build_teams_hil_http_client(environment)
        route_families, local_narrator = _build_route_families(
            environment=environment,
            authenticator=authenticator,
            store=family_store,
            semantic_bridge=semantic_bridge,
            semantic_bus=semantic_bus,
            read_model=configured_read_model,
            webhook_enabled=azure_monitor_webhook_bridge is not None,
            context_selection_registry=context_selection_registry,
            teams_http_client=teams_http_client,
        )
        hil_decision_outbox_bridge = build_hil_decision_outbox_bridge(
            environment=environment,
            store=family_store,
            semantic_bus=semantic_bus,
        )
        narrator_scheduler = (
            PeriodicNarratorRefreshScheduler(
                local_narrator,
                interval_seconds=environment.narrator_probe_interval_seconds,
            )
            if local_narrator is not None
            else None
        )
        return OperatorRuntime(
            environment=environment,
            authenticator=authenticator,
            read_model=configured_read_model or UnavailableOperatorReadModel(),
            data_sources=_build_data_sources(configured=configured_read_model is not None),
            route_families=route_families,
            readiness_probe=self.readiness_probe
            or _readiness_probe(
                family_store,
                semantic_bus,
                semantic_bridge,
                read_investigation_bridge,
                background_task_projection_bridge,
                wara_assessment_projection_bridge,
                read_investigation_completion_bridge,
                action_confirmation_bridge,
                azure_monitor_webhook_bridge,
                live_stage_relay,
                hil_decision_outbox_bridge,
            ),
            live_stream_hub=live_stream_hub,
            agent_stream_hub=agent_stream_hub,
            local_cli_profile=(
                local_cli_identity.to_dict() if local_cli_identity is not None else None
            ),
            local_cli_session_token=local_cli_session_token,
            lifecycle=_application_lifecycle(
                model_revision_owner,
                semantic_bridge,
                read_investigation_bridge,
                background_task_projection_bridge,
                wara_assessment_projection_bridge,
                read_investigation_completion_bridge,
                action_confirmation_bridge,
                azure_monitor_webhook_bridge,
                semantic_bus,
                live_stage_relay,
                narrator_scheduler,
                hil_decision_outbox_bridge,
                teams_http_client,
            ),
        )


class _OwnedHttpClient:
    """Close one composition-owned HTTP client with the application lifecycle."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def start(self) -> None:
        """Own no startup work; the client is ready when it is constructed."""

    async def aclose(self) -> None:
        """Close the owned client exactly once."""
        if not self._client.is_closed:
            await self._client.aclose()


def _postgres_read_model(environment: OperatorEnvironment) -> OperatorReadModel | None:
    if environment.database_url is None:
        return None
    return PostgresOperatorReadModel(
        PostgresOperatorReadModelConfig(
            dsn=environment.database_url,
            statement_timeout_ms=environment.database_statement_timeout_ms,
            connect_timeout_s=environment.database_connect_timeout_s,
        )
    )


def _build_route_families(
    *,
    environment: OperatorEnvironment,
    authenticator: OperatorAuthenticator,
    store: PostgresFamilyStore | None,
    semantic_bridge: SemanticTurnBridge | None,
    semantic_bus: OperatorSemanticKafkaBus | None,
    read_model: OperatorReadModel | None,
    webhook_enabled: bool,
    context_selection_registry: ContextSelectionRegistry,
    teams_http_client: httpx.AsyncClient | None = None,
) -> tuple[OperatorRouteFamilies, LocalAzureNarratorAdapters | None]:
    authorizer = OperatorFamilyAuthorizer(authenticator)
    report_pdf_encoder = optional_pdf_report_encoder()
    role_group_ids = {role.value: group_id for role, group_id in environment.group_ids.items()}
    if store is None:
        unavailable_conversation = UnavailableConversationAdapters()
        unavailable_workflow = UnavailableWorkflowAdapters()
        unavailable_operations = UnavailableOperationsAdapters()
        unavailable_cost = UnavailableCostGovernanceReader()
        routes = OperatorRouteFamilies(
            conversation=ConversationFamilyDependencies(
                authorizer=authorizer,
                projections=unavailable_conversation,
                outbox=unavailable_conversation,
                streams=unavailable_conversation,
            ),
            iam=build_unavailable_iam_bindings(
                authorizer=authorizer,
                role_group_ids=role_group_ids,
            ),
            workflow_authorize=authorizer.workflow,
            workflow_read_store=unavailable_workflow,
            workflow_proposal_writer=unavailable_workflow,
            operations_projection_reader=unavailable_operations,
            operations_proposal_writer=unavailable_operations,
            operations_replay_reader=unavailable_operations,
            operations_webhook_verifier=unavailable_operations,
            report_pdf_encoder=report_pdf_encoder,
            operation_panels=REFERENCE_PANEL_ROUTES,
            cost_governance=CostGovernanceFamilyDependencies(
                authenticator=authenticator,
                access=unavailable_cost,
                activation=unavailable_cost,
                projections=unavailable_cost,
            ),
        )
        return routes, None

    database_url = environment.database_url
    if database_url is None:  # pragma: no cover - store construction requires the same URL
        raise RuntimeError("validated Operator database URL is missing")
    postgres_adapters = PostgresConversationAdapters(store)
    postgres_conversation = ConversationAssuranceReader(
        ConversationAssuranceReaderConfig(
            dsn=database_url,
            statement_timeout_ms=environment.database_statement_timeout_ms,
            connect_timeout_s=environment.database_connect_timeout_s,
        ),
        fallback=postgres_adapters,
    )
    local_narrator = (
        LocalAzureNarratorAdapters.from_environment(
            environment.values,
            fallback_projections=postgres_conversation,
            fallback_streams=postgres_conversation,
        )
        if environment.local_azure_narrator
        else None
    )
    conversation = local_narrator or postgres_conversation
    semantic_adapters = (
        SemanticTurnConversationAdapters(
            bridge=semantic_bridge,
            fallback_projections=conversation,
            fallback_outbox=postgres_conversation,
            fallback_streams=postgres_conversation,
            document_exporter=ConversationDocumentExporter(
                store=store,
                pdf_encoder=report_pdf_encoder,
            ),
        )
        if semantic_bridge is not None
        else None
    )
    postgres_workflow = PostgresWorkflowAdapters(store)
    postgres_operations = PostgresOperationsAdapters(
        store,
        webhook_secret=environment.values.get(WEBHOOK_SIGNING_SECRET_ENV, "").strip() or None,
        read_investigation_replay=PostgresReadInvestigationReplayStore(
            config=PostgresReadInvestigationReplayConfig(dsn=database_url)
        ),
        context_selection_registry=context_selection_registry,
    )
    cost_reader = PostgresCostGovernanceReader(
        PostgresCostGovernanceConfig(
            dsn=database_url,
            statement_timeout_ms=environment.database_statement_timeout_ms,
            connect_timeout_s=environment.database_connect_timeout_s,
        )
    )
    operations_reader: ProjectionReader = (
        IncidentRcaReportingProjectionReader(postgres_operations, read_model)
        if read_model is not None
        else postgres_operations
    )
    operations_reader = RuntimeProjectionReader(
        RuntimeProjectionReaderConfig(
            dsn=database_url,
            statement_timeout_ms=environment.database_statement_timeout_ms,
            connect_timeout_s=environment.database_connect_timeout_s,
        ),
        fallback=operations_reader,
    )
    routes = OperatorRouteFamilies(
        conversation=ConversationFamilyDependencies(
            authorizer=authorizer,
            projections=semantic_adapters or conversation,
            outbox=semantic_adapters or postgres_conversation,
            streams=semantic_adapters or conversation,
        ),
        iam=build_postgres_iam_bindings(
            environment=environment,
            authenticator=authenticator,
            authorizer=authorizer,
            store=store,
            semantic_bus=semantic_bus,
            teams_http_client=teams_http_client,
            role_group_ids=role_group_ids,
        ),
        workflow_authorize=authorizer.workflow,
        workflow_read_store=postgres_workflow,
        workflow_proposal_writer=postgres_workflow,
        operations_projection_reader=operations_reader,
        operations_proposal_writer=postgres_operations,
        operations_replay_reader=postgres_operations,
        operations_webhook_verifier=(
            postgres_operations if webhook_enabled else UnavailableOperationsAdapters()
        ),
        report_pdf_encoder=report_pdf_encoder,
        operation_panels=REFERENCE_PANEL_ROUTES,
        cost_governance=CostGovernanceFamilyDependencies(
            authenticator=authenticator,
            access=cost_reader,
            activation=cost_reader,
            activation_writer=cost_reader,
            projections=cost_reader,
            analytics=cost_reader,
            pseudonym_key=(environment.values.get(COST_PSEUDONYM_KEY_ENV, "").encode() or None),
            authenticated_review_access=(
                environment.values.get(
                    "FDAI_COST_GOVERNANCE_AUTHENTICATED_REVIEW_ACCESS",
                    "",
                )
                .strip()
                .casefold()
                in {"1", "true", "yes", "on"}
            ),
        ),
    )
    return routes, local_narrator


def _postgres_family_store(environment: OperatorEnvironment) -> PostgresFamilyStore | None:
    if environment.database_url is None:
        return None
    if environment.database_role is None:
        raise RuntimeError("validated Operator database role is missing")
    return PostgresFamilyStore(
        PostgresFamilyStoreConfig(
            dsn=environment.database_url,
            role=environment.database_role,
            statement_timeout_ms=environment.database_statement_timeout_ms,
            connect_timeout_s=environment.database_connect_timeout_s,
            semantic_outbox_namespace=environment.semantic_outbox_namespace,
        )
    )


def _semantic_bridge(
    store: PostgresFamilyStore | None,
    *,
    publisher: SemanticTurnEventPublisher | None,
    result_source: SemanticTurnResultSource | None,
    request_topic: str,
    result_topic: str,
    result_group: str,
    context_selection_registry: ContextSelectionRegistry,
) -> SemanticTurnBridge | None:
    if publisher is None and result_source is None:
        return None
    if publisher is None or result_source is None:
        raise RuntimeError("semantic publisher and result source MUST be configured together")
    if store is None:
        raise RuntimeError("semantic transport requires the authoritative PostgreSQL store")
    return SemanticTurnBridge(
        store=store,
        publisher=publisher,
        result_source=result_source,
        request_topic=request_topic,
        result_topic=result_topic,
        result_group=result_group,
        builder=SemanticTurnEnvelopeBuilder(
            selection_registry=context_selection_registry,
        ),
    )


def _build_semantic_bus(environment: OperatorEnvironment) -> OperatorSemanticKafkaBus:
    bootstrap_servers = environment.kafka_bootstrap_servers
    if bootstrap_servers is None:
        raise RuntimeError("validated semantic Kafka bootstrap servers are missing")
    execution_venue = resolve_execution_venue(environment.values)
    credential = None
    if uses_workload_identity(execution_venue):
        credential = (
            ManagedIdentityCredential(client_id=environment.managed_identity_client_id)
            if environment.managed_identity_client_id is not None
            else ManagedIdentityCredential()
        )
    return OperatorSemanticKafkaBus(
        config=OperatorSemanticKafkaConfig(
            bootstrap_servers=bootstrap_servers,
            security_protocol=bus_security_protocol(execution_venue),
            request_topic=environment.semantic_request_topic or "operator.semantic-turn.requests",
            projection_topic=environment.semantic_projection_topic
            or "core.semantic-turn.projections",
            read_investigation_topic=environment.read_investigation_request_topic,
            read_investigation_completion_topic=(environment.read_investigation_completion_topic),
            background_task_projection_topic=environment.background_task_projection_topic,
            event_topic=environment.values.get("KAFKA_TOPIC_EVENTS", "").strip() or None,
            hil_decision_topic=environment.hil_decision_topic,
            notification_receipt_topic=environment.notification_receipt_topic,
            physical_topic=environment.semantic_physical_topic,
            client_id=environment.semantic_kafka_client_id,
        ),
        credential=credential,
    )


def _build_live_stage_relay(
    environment: OperatorEnvironment,
    hub: LiveStreamHub,
    agent_hub: LiveStreamHub,
) -> LiveStageKafkaRelay:
    bootstrap_servers = environment.kafka_bootstrap_servers
    if bootstrap_servers is None:
        raise RuntimeError("validated Kafka bootstrap servers are missing")
    execution_venue = resolve_execution_venue(environment.values)
    credential = None
    if uses_workload_identity(execution_venue):
        credential = (
            ManagedIdentityCredential(client_id=environment.managed_identity_client_id)
            if environment.managed_identity_client_id is not None
            else ManagedIdentityCredential()
        )
    return LiveStageKafkaRelay(
        config=LiveStageKafkaConfig(
            bootstrap_servers=bootstrap_servers,
            stage_topic=environment.stage_topic,
            group_id=environment.live_stage_consumer_group_id,
            security_protocol=bus_security_protocol(execution_venue),
        ),
        hub=hub,
        agent_hub=agent_hub,
        credential=credential,
    )


def _model_revision_owner(
    environment: OperatorEnvironment,
    *,
    source: AsyncResolvedModelsSource | None,
) -> OperatorResolvedModelsRevisionOwner | None:
    expected_digest = environment.values.get("LLM_RESOLVED_MODELS_SHA256", "").strip()
    configured_path = environment.values.get("LLM_RESOLVED_MODELS_PATH", "").strip()
    vault_url = environment.values.get(
        "FDAI_RESOLVED_MODELS_KEY_VAULT_URL",
        "",
    ).strip()
    secret_name = environment.values.get(
        "FDAI_RESOLVED_MODELS_KEY_VAULT_SECRET_NAME",
        "",
    ).strip()
    if source is None and not vault_url and not expected_digest:
        return None
    if len(expected_digest) != 64 or any(
        character not in "0123456789abcdef" for character in expected_digest
    ):
        raise RuntimeError("Operator requires LLM_RESOLVED_MODELS_SHA256")
    if source is not None:
        return OperatorResolvedModelsRevisionOwner(
            source=source,
            expected_digest=expected_digest,
        )
    if vault_url or secret_name:
        if not vault_url or not secret_name:
            raise RuntimeError(
                "Operator resolved-model Key Vault URL and secret name are both required"
            )
        credential = (
            ManagedIdentityCredential(client_id=environment.managed_identity_client_id)
            if environment.managed_identity_client_id is not None
            else ManagedIdentityCredential()
        )
        http_client = httpx.AsyncClient()

        async def token_provider(audience: str) -> str:
            return cast(str, (await credential.get_token(audience)).token)

        async def close() -> None:
            try:
                await http_client.aclose()
            finally:
                await credential.close()

        return OperatorResolvedModelsRevisionOwner(
            source=KeyVaultResolvedModelsSource(
                config=KeyVaultResolvedModelsConfig(
                    vault_url=vault_url,
                    secret_name=secret_name,
                    secret_version=environment.values.get(
                        "FDAI_RESOLVED_MODELS_KEY_VAULT_SECRET_VERSION",
                        "",
                    ).strip()
                    or None,
                ),
                token_provider=token_provider,
                http_client=_KeyVaultHttpClient(http_client),
            ),
            expected_digest=expected_digest,
            close=close,
        )
    if not configured_path:
        raise RuntimeError("Operator resolved-model source is not configured")
    return OperatorResolvedModelsRevisionOwner(
        source=ConfiguredResolvedModelsSource(configured_path),
        expected_digest=expected_digest,
    )


@dataclass(frozen=True, slots=True)
class _KeyVaultHttpClient:
    client: httpx.AsyncClient

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.client.get(url, **kwargs)


@dataclass(frozen=True, slots=True)
class _CompositeLifecycle:
    services: tuple[ApplicationLifecycle, ...]

    async def start(self) -> None:
        """Start dependencies in order and close every acquired resource on failure."""
        started: list[ApplicationLifecycle] = []
        for service in self.services:
            try:
                await service.start()
            except BaseException:
                await service.aclose()
                for prior in reversed(started):
                    await prior.aclose()
                raise
            started.append(service)

    async def aclose(self) -> None:
        """Close dependencies in reverse order so bridge consumers stop before Kafka."""
        first_error: BaseException | None = None
        for service in reversed(self.services):
            try:
                await service.aclose()
            except BaseException as exc:
                if first_error is None:
                    first_error = exc
        if first_error is not None:
            raise first_error


def _application_lifecycle(
    model_revision_owner: OperatorResolvedModelsRevisionOwner | None,
    bridge: SemanticTurnBridge | None,
    read_investigation_bridge: ReadInvestigationBridge | None,
    background_task_projection_bridge: BackgroundTaskProjectionBridge | None,
    wara_assessment_projection_bridge: WaraAssessmentProjectionBridge | None,
    read_investigation_completion_bridge: ReadInvestigationCompletionBridge | None,
    action_confirmation_bridge: ActionConfirmationBridge | None,
    azure_monitor_webhook_bridge: AzureMonitorWebhookBridge | None,
    bus: OperatorSemanticKafkaBus | None,
    live_stage_relay: LiveStageKafkaRelay | None,
    narrator_scheduler: PeriodicNarratorRefreshScheduler | None,
    hil_decision_outbox_bridge: HilDecisionOutboxBridge | None,
    teams_http_client: httpx.AsyncClient | None,
) -> ApplicationLifecycle | None:
    services = tuple(
        service
        for service in (
            model_revision_owner,
            bus,
            bridge,
            read_investigation_bridge,
            background_task_projection_bridge,
            wara_assessment_projection_bridge,
            read_investigation_completion_bridge,
            action_confirmation_bridge,
            azure_monitor_webhook_bridge,
            live_stage_relay,
            narrator_scheduler,
            hil_decision_outbox_bridge,
            _OwnedHttpClient(teams_http_client) if teams_http_client is not None else None,
        )
        if service is not None
    )
    if not services:
        return None
    if len(services) == 1:
        return services[0]
    return _CompositeLifecycle(services)


def _readiness_probe(
    store: PostgresFamilyStore | None,
    bus: OperatorSemanticKafkaBus | None,
    bridge: SemanticTurnBridge | None,
    read_investigation_bridge: ReadInvestigationBridge | None,
    background_task_projection_bridge: BackgroundTaskProjectionBridge | None,
    wara_assessment_projection_bridge: WaraAssessmentProjectionBridge | None,
    read_investigation_completion_bridge: ReadInvestigationCompletionBridge | None,
    action_confirmation_bridge: ActionConfirmationBridge | None,
    azure_monitor_webhook_bridge: AzureMonitorWebhookBridge | None,
    live_stage_relay: LiveStageKafkaRelay | None,
    hil_decision_outbox_bridge: HilDecisionOutboxBridge | None = None,
) -> ReadinessProbe:
    if store is None:
        return _unavailable
    if bus is None:
        return store.probe_readiness

    async def probe() -> bool:
        return (
            await store.probe_readiness()
            and await bus.probe_readiness()
            and (bridge is None or bridge.workers_ready())
            and (read_investigation_bridge is None or read_investigation_bridge.workers_ready())
            and (
                background_task_projection_bridge is None
                or background_task_projection_bridge.workers_ready()
            )
            and (
                wara_assessment_projection_bridge is None
                or wara_assessment_projection_bridge.workers_ready()
            )
            and (
                read_investigation_completion_bridge is None
                or read_investigation_completion_bridge.workers_ready()
            )
            and (action_confirmation_bridge is None or action_confirmation_bridge.workers_ready())
            and (
                azure_monitor_webhook_bridge is None or azure_monitor_webhook_bridge.workers_ready()
            )
            and (live_stage_relay is None or live_stage_relay.readiness())
            and (hil_decision_outbox_bridge is None or hil_decision_outbox_bridge.workers_ready())
        )

    return probe


def _build_data_sources(*, configured: bool) -> tuple[ReadDataSource, ...]:
    reason = None if configured else "Authoritative service-local projections are not configured."
    return (
        ReadDataSource(
            key="operational-state",
            source="service-local-projection" if configured else "not-configured",
            routes=(
                "/audit",
                "/audit/{correlation_id}/trace",
                "/browser-evidence",
                "/hil-queue",
                "/incidents",
                "/incidents/stream",
                "/kpi",
                "/kpi/llm-cost",
                "/rca",
            ),
            availability="unknown" if configured else "unavailable",
            configured=configured,
            reachable=None,
            authoritative=configured,
            durable=True if configured else None,
            reason=reason,
        ),
        ReadDataSource(
            key="cost-governance",
            source="retained-cost-observation" if configured else "not-configured",
            routes=(
                "/cost-governance/availability",
                "/cost-governance/settings",
                "/cost-governance/overview",
                "/cost-governance/resource-efficiency",
                "/cost-governance/optimization-cases",
                "/cost-governance/outcomes",
                "/finops",
            ),
            availability="unknown" if configured else "unavailable",
            configured=configured,
            reachable=None,
            authoritative=configured,
            durable=True if configured else None,
            reason=reason,
        ),
        ReadDataSource(
            key="overview-measurement",
            source="not-served-by-operator-service",
            routes=("/overview/measurement",),
            availability="unavailable",
            configured=False,
            reachable=False,
            authoritative=False,
            durable=None,
            reason="Overview measurement is owned by a separate projection service.",
        ),
        ReadDataSource(
            key="autonomy-measurement",
            source="service-local-audit" if configured else "not-configured",
            routes=("/kpi/autonomy",),
            availability="unknown" if configured else "unavailable",
            configured=configured,
            reachable=None,
            authoritative=configured,
            durable=True if configured else None,
            reason=reason,
        ),
        ReadDataSource(
            key="promotion-gate-evidence",
            source="repository-catalog-projection" if configured else "not-configured",
            routes=("/kpi/promotion-gates",),
            availability="unknown" if configured else "unavailable",
            configured=configured,
            reachable=None,
            authoritative=configured,
            durable=True if configured else None,
            reason=reason,
        ),
        ReadDataSource(
            key="onboarding-probe",
            source="repository-catalog-projection" if configured else "not-configured",
            routes=("/onboarding",),
            availability="unknown" if configured else "unavailable",
            configured=configured,
            reachable=None,
            authoritative=configured,
            durable=True if configured else None,
            reason=reason,
        ),
        ReadDataSource(
            key="detection-readiness",
            source="service-local-projection" if configured else "not-configured",
            routes=("/detection-readiness",),
            availability="unknown" if configured else "unavailable",
            configured=configured,
            reachable=None,
            authoritative=configured,
            durable=True if configured else None,
            reason=reason,
        ),
        ReadDataSource(
            key="workflow-app-catalog",
            source="repository-catalog-projection" if configured else "not-configured",
            routes=("/views/workflow-apps",),
            availability="unknown" if configured else "unavailable",
            configured=configured,
            reachable=None,
            authoritative=configured,
            durable=True if configured else None,
            reason=reason,
        ),
        ReadDataSource(
            key="configuration-baseline",
            source="service-local-projection" if configured else "not-configured",
            routes=("/configuration-baselines",),
            availability="unknown" if configured else "unavailable",
            configured=configured,
            reachable=None,
            authoritative=configured,
            durable=True if configured else None,
            reason=reason,
        ),
        ReadDataSource(
            key="conversation-delivery",
            source="operator-delivery-ledger" if configured else "not-configured",
            routes=("/conversation-delivery",),
            availability="unknown" if configured else "unavailable",
            configured=configured,
            reachable=None,
            authoritative=configured,
            durable=True if configured else None,
            reason=reason,
        ),
        ReadDataSource(
            key="capability-contract",
            source="repository-catalog-projection" if configured else "not-configured",
            routes=("/capabilities",),
            availability="unknown" if configured else "unavailable",
            configured=configured,
            reachable=None,
            authoritative=configured,
            durable=True if configured else None,
            reason=reason,
        ),
        ReadDataSource(
            key="runtime-skill",
            source="service-local-projection" if configured else "not-configured",
            routes=("/skills",),
            availability="unknown" if configured else "unavailable",
            configured=configured,
            reachable=None,
            authoritative=configured,
            durable=True if configured else None,
            reason=reason,
        ),
        ReadDataSource(
            key="forecast-learning",
            source="service-local-projection" if configured else "not-configured",
            routes=("/forecast-learning",),
            availability="unknown" if configured else "unavailable",
            configured=configured,
            reachable=None,
            authoritative=configured,
            durable=True if configured else None,
            reason=reason,
        ),
        ReadDataSource(
            key="operator-memory",
            source="service-local-projection" if configured else "not-configured",
            routes=("/operator-memory",),
            availability="unknown" if configured else "unavailable",
            configured=configured,
            reachable=None,
            authoritative=configured,
            durable=True if configured else None,
            reason=reason,
        ),
        ReadDataSource(
            key="notification-template",
            source="operator-service",
            routes=("/notification-templates/incident-opened",),
            availability="available",
            configured=True,
            reachable=True,
            authoritative=True,
            durable=False,
        ),
    )


async def _unavailable() -> bool:
    return False


__all__ = [
    "HIL_SIGNING_SECRET_ENV",
    "COST_PSEUDONYM_KEY_ENV",
    "OperatorComposition",
    "ProductionOperatorComposition",
    "TokenVerifierFactory",
    "WEBHOOK_SIGNING_SECRET_ENV",
]
