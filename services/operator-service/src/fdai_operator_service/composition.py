"""Production composition boundary for the independent Operator service."""

from __future__ import annotations

import logging
import os
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Protocol

from fdai_service_contracts import (
    AgentActivityQuery,
    OperatorReadModel,
    OperatorTokenVerifier,
)
from fdai_service_contracts.venue import (
    bus_security_protocol,
    resolve_execution_venue,
    uses_workload_identity,
)
from psycopg import Error as PsycopgError

from fdai_operator_service.adapters import (
    LiveStageKafkaConfig,
    LiveStageKafkaRelay,
    OperatorSemanticKafkaBus,
    OperatorSemanticKafkaConfig,
    create_workload_credential,
)
from fdai_operator_service.adapters.narrator_periodic_scheduler import (
    PeriodicNarratorRefreshScheduler,
)
from fdai_operator_service.assessment_projections import (
    FrameworkAssessmentProjectionBridge,
    WaraAssessmentProjectionBridge,
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
from fdai_operator_service.composition_data_sources import _build_data_sources
from fdai_operator_service.composition_lifecycle import (
    CompositeLifecycle as _CompositeLifecycle,
)
from fdai_operator_service.composition_lifecycle import (
    OwnedHttpClient as _OwnedHttpClient,
)
from fdai_operator_service.composition_lifecycle import (
    application_lifecycle as _application_lifecycle,
)
from fdai_operator_service.composition_lifecycle import (
    compose_application_lifecycle,
)
from fdai_operator_service.composition_routes import (
    COST_PSEUDONYM_KEY_ENV,
    REFERENCE_PANEL_ROUTES,
    WEBHOOK_SIGNING_SECRET_ENV,
    _build_route_families,
)
from fdai_operator_service.context_selection import ContextSelectionRegistry
from fdai_operator_service.contracts import ReadinessProbe
from fdai_operator_service.environment import (
    OperatorEnvironment,
)
from fdai_operator_service.families.conversation.semantic_turn import SemanticTurnEnvelopeBuilder
from fdai_operator_service.families.conversation.semantic_turn_runtime import (
    SEMANTIC_REQUEST_TOPIC,
    SEMANTIC_RESULT_TOPIC,
    DialogueRelationshipResolver,
    RuntimeCallEndpointObserver,
    SemanticTurnBridge,
    SemanticTurnEventPublisher,
    SemanticTurnResultSource,
    runtime_call_endpoint_observer_from_config,
)
from fdai_operator_service.iam_composition import (
    HIL_SIGNING_SECRET_ENV,
    AssignmentNoticeBridge,
    HilDecisionOutboxBridge,
    build_adaptive_relationship_resolver,
    build_assignment_notice_bridge,
    build_hil_decision_outbox_bridge,
    build_teams_hil_http_client,
)
from fdai_operator_service.model_lifecycle_composition import (
    AsyncResolvedModelsSource,
    build_model_revision_owner,
)
from fdai_operator_service.observer_deployment_projection import (
    ObserverProposalBridge,
    ObserverProposalReader,
    PostgresObserverProjectionStore,
)
from fdai_operator_service.outbox_runtime import (
    ActionConfirmationBridge,
    AlertQualityBridge,
    IncidentInterventionBridge,
    TestContextBridge,
    build_alert_quality_bindings,
)
from fdai_operator_service.postgres import (
    PostgresOperatorReadModel,
    PostgresOperatorReadModelConfig,
)
from fdai_operator_service.postgres_background_task_projection import (
    PostgresBackgroundTaskProjectionConfig,
    PostgresBackgroundTaskProjectionRepository,
)
from fdai_operator_service.postgres_family_store import (
    PostgresFamilyStore,
    PostgresFamilyStoreConfig,
)
from fdai_operator_service.postgres_read_investigation_completion import (
    PostgresReadInvestigationCompletionConfig,
    PostgresReadInvestigationCompletionRepository,
)
from fdai_operator_service.projections import (
    ProjectionUnavailableError,
    UnavailableOperatorReadModel,
)
from fdai_operator_service.read_investigation_completion_runtime import (
    ReadInvestigationCompletionBridge,
)
from fdai_operator_service.read_investigation_runtime import ReadInvestigationBridge
from fdai_operator_service.runtime import OperatorRuntime
from fdai_operator_service.streaming import LiveStreamEvent, LiveStreamHub

_LOGGER = logging.getLogger(__name__)


def _agent_state_key(event: LiveStreamEvent) -> str | None:
    payload = event.payload
    agent = payload.get("agent")
    return agent if payload.get("type") == "agent.state" and isinstance(agent, str) else None


def _live_activity_key(event: LiveStreamEvent) -> str | None:
    if event.event_type == "activity-status":
        return "__activity_status__"
    if event.event_type != "activity":
        return None
    payload = event.payload
    instance_id = payload.get("activity_instance_id")
    if isinstance(instance_id, str) and instance_id:
        return instance_id
    activity_id = payload.get("activity_id")
    return activity_id if isinstance(activity_id, str) and activity_id else None


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
    adaptive_relationship_resolver: DialogueRelationshipResolver | None = None
    resolved_models_source: AsyncResolvedModelsSource | None = None
    local_cli_identity_factory: LocalCliIdentityFactory = resolve_azure_cli_identity
    local_cli_session_token_factory: LocalCliSessionTokenFactory = lambda: secrets.token_urlsafe(32)

    def build_runtime(self, environ: Mapping[str, str] | None = None) -> OperatorRuntime:
        """Bind a validated environment snapshot to service-owned HTTP dependencies."""
        environment = OperatorEnvironment.parse(os.environ if environ is None else environ)
        model_revision_owner = build_model_revision_owner(
            environment,
            source=self.resolved_models_source,
        )
        configured_read_model = self.read_model or _postgres_read_model(environment)
        family_store = _postgres_family_store(environment)
        context_selection_registry = ContextSelectionRegistry()
        semantic_bus: OperatorSemanticKafkaBus | None = None
        live_stream_hub = LiveStreamHub(
            latest_key=_live_activity_key,
            latest_capacity=64,
        )
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
            relationship_resolver=self.adaptive_relationship_resolver,
            runtime_call_observer=runtime_call_endpoint_observer_from_config(environment.values),
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
        framework_assessment_projection_bridge = (
            FrameworkAssessmentProjectionBridge(
                store=family_store,
                source=semantic_bus,
                publisher=semantic_bus,
            )
            if family_store is not None and semantic_bus is not None
            else None
        )
        observer_proposal_store = (
            PostgresObserverProjectionStore(environment.database_url)
            if environment.database_url is not None
            else None
        )
        observer_proposal_bridge = (
            ObserverProposalBridge(
                store=observer_proposal_store, source=semantic_bus, publisher=semantic_bus
            )
            if observer_proposal_store is not None and semantic_bus is not None
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
        incident_intervention_bridge = (
            IncidentInterventionBridge(
                store=family_store,
                publisher=semantic_bus,
            )
            if family_store is not None and semantic_bus is not None
            else None
        )
        assignment_notice_bridge = build_assignment_notice_bridge(environment, semantic_bus)
        azure_monitor_webhook_bridge = (
            AzureMonitorWebhookBridge(
                store=family_store,
                publisher=semantic_bus,
                topic=event_topic,
            )
            if family_store is not None and semantic_bus is not None and event_topic is not None
            else None
        )
        test_context_bridge = (
            TestContextBridge(
                store=family_store, publisher=semantic_bus, topic=event_topic, source=semantic_bus
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
            local_username=(
                local_cli_identity.username if local_cli_identity is not None else None
            ),
            local_session_token=local_cli_session_token,
        )
        teams_http_client = build_teams_hil_http_client(environment)
        route_families, local_narrator = _build_route_families(
            environment=environment,
            model_revision_owner=model_revision_owner,
            authenticator=authenticator,
            store=family_store,
            semantic_bridge=semantic_bridge,
            semantic_bus=semantic_bus,
            read_model=configured_read_model,
            webhook_enabled=azure_monitor_webhook_bridge is not None,
            context_selection_registry=context_selection_registry,
            teams_http_client=teams_http_client,
        )
        alert_quality, alert_quality_bridge = build_alert_quality_bindings(
            authenticator=authenticator,
            environ=environment.values,
            store=family_store,
            transport=semantic_bus,
            event_topic=event_topic,
            proposal_writer=route_families.operations_proposal_writer,
        )
        route_families = replace(route_families, alert_quality=alert_quality)
        if observer_proposal_store is not None:
            route_families = replace(
                route_families,
                operations_projection_reader=ObserverProposalReader(
                    observer_proposal_store, fallback=route_families.operations_projection_reader
                ),
            )
        if (
            semantic_bridge is not None
            and self.adaptive_relationship_resolver is None
            and route_families.iam.directory is not None
        ):
            semantic_bridge.bind_relationship_resolver(
                build_adaptive_relationship_resolver(
                    projection_reader=route_families.operations_projection_reader,
                    directory=route_families.iam.directory,
                    assignments=route_families.iam.assignments,
                )
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
        live_activity_snapshot_loader = _LiveActivitySnapshotLoader(
            configured_read_model,
            live_stream_hub,
        )
        return OperatorRuntime(
            environment=environment,
            authenticator=authenticator,
            read_model=configured_read_model or UnavailableOperatorReadModel(),
            data_sources=_build_data_sources(
                configured=configured_read_model is not None,
                inventory_configured=family_store is not None,
            ),
            route_families=route_families,
            readiness_probe=self.readiness_probe
            or _readiness_probe(
                family_store,
                semantic_bus,
                semantic_bridge,
                read_investigation_bridge,
                background_task_projection_bridge,
                wara_assessment_projection_bridge,
                framework_assessment_projection_bridge,
                read_investigation_completion_bridge,
                action_confirmation_bridge,
                incident_intervention_bridge,
                azure_monitor_webhook_bridge,
                live_stage_relay,
                hil_decision_outbox_bridge,
                alert_quality_bridge=alert_quality_bridge,
                assignment_notice_bridge=assignment_notice_bridge,
                test_context_bridge=test_context_bridge,
                observer_proposal_bridge=observer_proposal_bridge,
            ),
            live_stream_hub=live_stream_hub,
            agent_stream_hub=agent_stream_hub,
            local_cli_profile=(
                local_cli_identity.to_dict() if local_cli_identity is not None else None
            ),
            local_cli_session_token=local_cli_session_token,
            lifecycle=_application_lifecycle(
                model_revision_owner,
                local_narrator,
                semantic_bridge,
                read_investigation_bridge,
                background_task_projection_bridge,
                wara_assessment_projection_bridge,
                framework_assessment_projection_bridge,
                read_investigation_completion_bridge,
                action_confirmation_bridge,
                incident_intervention_bridge,
                azure_monitor_webhook_bridge,
                live_activity_snapshot_loader,
                semantic_bus,
                live_stage_relay,
                narrator_scheduler,
                hil_decision_outbox_bridge,
                teams_http_client,
                alert_quality_bridge=alert_quality_bridge,
                assignment_notice_bridge=assignment_notice_bridge,
                test_context_bridge=test_context_bridge,
                observer_proposal_bridge=observer_proposal_bridge,
            ),
        )


class _LiveActivitySnapshotLoader:
    """Seed current Live activity from the authoritative durable projection."""

    def __init__(
        self,
        read_model: OperatorReadModel | None,
        hub: LiveStreamHub,
    ) -> None:
        self._read_model = read_model
        self._hub = hub

    async def start(self) -> None:
        if self._read_model is None:
            await self._hub.seed_latest((_live_activity_status("unavailable"),))
            return
        try:
            projection = await self._read_model.list_agent_activity(AgentActivityQuery(limit=64))
        except (ProjectionUnavailableError, PsycopgError, TimeoutError) as exc:
            _LOGGER.warning(
                "live_activity_snapshot_unavailable",
                extra={"error_kind": type(exc).__name__},
            )
            await self._hub.seed_latest((_live_activity_status("unavailable"),))
            return
        items = projection.to_dict().get("items")
        if not isinstance(items, list) or len(items) > 64:
            raise ValueError("durable activity snapshot MUST contain a bounded items array")
        events: list[LiveStreamEvent] = []
        for item in reversed(items):
            activity_id = item.get("activity_id") if isinstance(item, Mapping) else None
            if (
                not isinstance(item, Mapping)
                or item.get("type") != "agent.operational-activity"
                or not isinstance(activity_id, str)
            ):
                raise ValueError("durable activity snapshot item is malformed")
            events.append(
                LiveStreamEvent(
                    event_id=activity_id,
                    payload=dict(item),
                    event_type="activity",
                )
            )
        events.append(_live_activity_status("ready"))
        await self._hub.seed_latest(tuple(events))

    async def aclose(self) -> None:
        """Own no resources after the one-time projection read."""


def _live_activity_status(status: str) -> LiveStreamEvent:
    if status not in {"ready", "unavailable"}:
        raise ValueError("Live activity status is unsupported")
    return LiveStreamEvent(
        event_id=f"activity-status:{status}",
        event_type="activity-status",
        payload={
            "type": "live.activity-status",
            "status": status,
            "reason": (None if status == "ready" else "durable_projection_unavailable"),
            "ts": datetime.now(tz=UTC).isoformat(),
        },
    )


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
    relationship_resolver: DialogueRelationshipResolver | None = None,
    runtime_call_observer: RuntimeCallEndpointObserver | None = None,
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
        relationship_resolver=relationship_resolver,
        runtime_call_observer=runtime_call_observer,
    )


def _build_semantic_bus(environment: OperatorEnvironment) -> OperatorSemanticKafkaBus:
    bootstrap_servers = environment.kafka_bootstrap_servers
    if bootstrap_servers is None:
        raise RuntimeError("validated semantic Kafka bootstrap servers are missing")
    execution_venue = resolve_execution_venue(environment.values)
    credential = None
    if uses_workload_identity(execution_venue):
        credential = create_workload_credential(
            environment=environment.values,
            client_id=environment.managed_identity_client_id,
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
        credential = create_workload_credential(
            environment=environment.values,
            client_id=environment.managed_identity_client_id,
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


def _readiness_probe(
    store: PostgresFamilyStore | None,
    bus: OperatorSemanticKafkaBus | None,
    bridge: SemanticTurnBridge | None,
    read_investigation_bridge: ReadInvestigationBridge | None,
    background_task_projection_bridge: BackgroundTaskProjectionBridge | None,
    wara_assessment_projection_bridge: WaraAssessmentProjectionBridge | None,
    framework_assessment_projection_bridge: FrameworkAssessmentProjectionBridge | None,
    read_investigation_completion_bridge: ReadInvestigationCompletionBridge | None,
    action_confirmation_bridge: ActionConfirmationBridge | None,
    incident_intervention_bridge: IncidentInterventionBridge | None,
    azure_monitor_webhook_bridge: AzureMonitorWebhookBridge | None,
    live_stage_relay: LiveStageKafkaRelay | None,
    hil_decision_outbox_bridge: HilDecisionOutboxBridge | None = None,
    assignment_notice_bridge: AssignmentNoticeBridge | None = None,
    alert_quality_bridge: AlertQualityBridge | None = None,
    test_context_bridge: TestContextBridge | None = None,
    observer_proposal_bridge: ObserverProposalBridge | None = None,
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
                framework_assessment_projection_bridge is None
                or framework_assessment_projection_bridge.workers_ready()
            )
            and (
                read_investigation_completion_bridge is None
                or read_investigation_completion_bridge.workers_ready()
            )
            and (action_confirmation_bridge is None or action_confirmation_bridge.workers_ready())
            and (
                incident_intervention_bridge is None or incident_intervention_bridge.workers_ready()
            )
            and (
                azure_monitor_webhook_bridge is None or azure_monitor_webhook_bridge.workers_ready()
            )
            and (live_stage_relay is None or live_stage_relay.readiness())
            and (hil_decision_outbox_bridge is None or hil_decision_outbox_bridge.workers_ready())
            and (alert_quality_bridge is None or alert_quality_bridge.workers_ready())
            and (test_context_bridge is None or test_context_bridge.workers_ready())
            and (assignment_notice_bridge is None or assignment_notice_bridge.workers_ready())
            and (observer_proposal_bridge is None or observer_proposal_bridge.workers_ready())
        )

    return probe


async def _unavailable() -> bool:
    return False


__all__ = [
    "COST_PSEUDONYM_KEY_ENV",
    "HIL_SIGNING_SECRET_ENV",
    "OperatorComposition",
    "ProductionOperatorComposition",
    "REFERENCE_PANEL_ROUTES",
    "TokenVerifierFactory",
    "WEBHOOK_SIGNING_SECRET_ENV",
    "_CompositeLifecycle",
    "_OwnedHttpClient",
    "_application_lifecycle",
    "compose_application_lifecycle",
]
