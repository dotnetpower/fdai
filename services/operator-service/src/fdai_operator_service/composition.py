"""Production composition boundary for the independent Operator service."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from azure.identity.aio import ManagedIdentityCredential
from fdai_service_contracts import OperatorReadModel, OperatorTokenVerifier, ReadDataSource

from fdai_operator_service.adapters import (
    LiveStageKafkaConfig,
    LiveStageKafkaRelay,
    LocalAzureNarratorAdapters,
    OperatorSemanticKafkaBus,
    OperatorSemanticKafkaConfig,
)
from fdai_operator_service.auth import EntraJwtVerifier, OperatorAuthenticator
from fdai_operator_service.contracts import ApplicationLifecycle, ReadinessProbe
from fdai_operator_service.environment import OperatorEnvironment
from fdai_operator_service.families.conversation import ConversationFamilyDependencies
from fdai_operator_service.families.conversation.semantic_turn_runtime import (
    SEMANTIC_REQUEST_TOPIC,
    SEMANTIC_RESULT_TOPIC,
    SemanticTurnBridge,
    SemanticTurnConversationAdapters,
    SemanticTurnEventPublisher,
    SemanticTurnResultSource,
)
from fdai_operator_service.families.iam import HilCallbackConfig, IamFamilyBindings
from fdai_operator_service.family_adapters import (
    PostgresConversationAdapters,
    PostgresOperationsAdapters,
    PostgresWorkflowAdapters,
    UnavailableConversationAdapters,
    UnavailableOperationsAdapters,
    UnavailableWorkflowAdapters,
)
from fdai_operator_service.family_authorization import OperatorFamilyAuthorizer
from fdai_operator_service.postgres import (
    PostgresOperatorReadModel,
    PostgresOperatorReadModelConfig,
)
from fdai_operator_service.postgres_family_store import (
    PostgresFamilyStore,
    PostgresFamilyStoreConfig,
    UnavailablePostgresFamilyStore,
)
from fdai_operator_service.postgres_iam import PostgresIamAdapters
from fdai_operator_service.projections import UnavailableOperatorReadModel
from fdai_operator_service.reporting import optional_pdf_report_encoder
from fdai_operator_service.routes import OperatorRouteFamilies
from fdai_operator_service.runtime import OperatorRuntime
from fdai_operator_service.streaming import LiveStreamEvent, LiveStreamHub

HIL_SIGNING_SECRET_ENV = "FDAI_CHATOPS_WEBHOOK_SECRET"  # noqa: S105
WEBHOOK_SIGNING_SECRET_ENV = "FDAI_OPERATOR_WEBHOOK_SECRET"  # noqa: S105


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

    def build_runtime(self, environ: Mapping[str, str] | None = None) -> OperatorRuntime:
        """Bind a validated environment snapshot to service-owned HTTP dependencies."""
        environment = OperatorEnvironment.parse(os.environ if environ is None else environ)
        configured_read_model = self.read_model or _postgres_read_model(environment)
        family_store = _postgres_family_store(environment)
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
        )
        authenticator = OperatorAuthenticator(
            verifier=self.verifier_factory(environment),
            group_ids=environment.group_ids,
        )
        return OperatorRuntime(
            environment=environment,
            authenticator=authenticator,
            read_model=configured_read_model or UnavailableOperatorReadModel(),
            data_sources=_build_data_sources(configured=configured_read_model is not None),
            route_families=_build_route_families(
                environment=environment,
                authenticator=authenticator,
                store=family_store,
                semantic_bridge=semantic_bridge,
            ),
            readiness_probe=self.readiness_probe
            or _readiness_probe(family_store, semantic_bus, semantic_bridge, live_stage_relay),
            live_stream_hub=live_stream_hub,
            agent_stream_hub=agent_stream_hub,
            lifecycle=_application_lifecycle(semantic_bridge, semantic_bus, live_stage_relay),
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


def _build_route_families(
    *,
    environment: OperatorEnvironment,
    authenticator: OperatorAuthenticator,
    store: PostgresFamilyStore | None,
    semantic_bridge: SemanticTurnBridge | None,
) -> OperatorRouteFamilies:
    authorizer = OperatorFamilyAuthorizer(authenticator)
    report_pdf_encoder = optional_pdf_report_encoder()
    role_group_ids = {role.value: group_id for role, group_id in environment.group_ids.items()}
    if store is None:
        unavailable_conversation = UnavailableConversationAdapters()
        unavailable_workflow = UnavailableWorkflowAdapters()
        unavailable_operations = UnavailableOperationsAdapters()
        unavailable_iam = PostgresIamAdapters(UnavailablePostgresFamilyStore())
        return OperatorRouteFamilies(
            conversation=ConversationFamilyDependencies(
                authorizer=authorizer,
                projections=unavailable_conversation,
                outbox=unavailable_conversation,
                streams=unavailable_conversation,
            ),
            iam=IamFamilyBindings(
                authorize=authorizer.iam,
                authenticate=authorizer.iam,
                access_grants=unavailable_iam,
                human_access=unavailable_iam,
                directory=unavailable_iam,
                assignments=unavailable_iam,
                handover_goals=unavailable_iam,
                model_settings=unavailable_iam,
                runtime_settings=unavailable_iam,
                kill_switch=unavailable_iam,
                configuration_review=unavailable_iam,
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
        )

    postgres_conversation = PostgresConversationAdapters(store)
    conversation = (
        LocalAzureNarratorAdapters.from_environment(
            environment.values,
            fallback_projections=postgres_conversation,
            fallback_streams=postgres_conversation,
        )
        if environment.local_azure_narrator
        else postgres_conversation
    )
    semantic_adapters = (
        SemanticTurnConversationAdapters(
            bridge=semantic_bridge,
            fallback_projections=conversation,
            fallback_outbox=postgres_conversation,
            fallback_streams=postgres_conversation,
        )
        if semantic_bridge is not None
        else None
    )
    postgres_workflow = PostgresWorkflowAdapters(store)
    iam = PostgresIamAdapters(store)
    postgres_operations = PostgresOperationsAdapters(
        store,
        webhook_secret=environment.values.get(WEBHOOK_SIGNING_SECRET_ENV, "").strip() or None,
    )
    hil_secret = environment.values.get(HIL_SIGNING_SECRET_ENV, "").strip() or None
    return OperatorRouteFamilies(
        conversation=ConversationFamilyDependencies(
            authorizer=authorizer,
            projections=semantic_adapters or conversation,
            outbox=semantic_adapters or postgres_conversation,
            streams=semantic_adapters or conversation,
        ),
        iam=IamFamilyBindings(
            authorize=authorizer.iam,
            authenticate=authorizer.iam,
            access_grants=iam,
            human_access=iam,
            directory=iam,
            assignments=iam,
            handover_goals=iam,
            model_settings=iam,
            runtime_settings=iam,
            kill_switch=iam,
            configuration_review=iam,
            hil_registry=iam if hil_secret is not None else None,
            hil_outbox=iam if hil_secret is not None else None,
            hil_config=HilCallbackConfig(hil_secret) if hil_secret is not None else None,
            role_group_ids=role_group_ids,
        ),
        workflow_authorize=authorizer.workflow,
        workflow_read_store=postgres_workflow,
        workflow_proposal_writer=postgres_workflow,
        operations_projection_reader=postgres_operations,
        operations_proposal_writer=postgres_operations,
        operations_replay_reader=postgres_operations,
        operations_webhook_verifier=postgres_operations,
        report_pdf_encoder=report_pdf_encoder,
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
    )


def _build_semantic_bus(environment: OperatorEnvironment) -> OperatorSemanticKafkaBus:
    bootstrap_servers = environment.kafka_bootstrap_servers
    if bootstrap_servers is None:
        raise RuntimeError("validated semantic Kafka bootstrap servers are missing")
    execution_venue = environment.values.get("FDAI_EXECUTION_VENUE", "deployed").strip()
    if execution_venue not in {"local", "deployed"}:
        raise RuntimeError("FDAI_EXECUTION_VENUE MUST be local or deployed")
    credential = None
    if execution_venue == "deployed":
        credential = (
            ManagedIdentityCredential(client_id=environment.managed_identity_client_id)
            if environment.managed_identity_client_id is not None
            else ManagedIdentityCredential()
        )
    return OperatorSemanticKafkaBus(
        config=OperatorSemanticKafkaConfig(
            bootstrap_servers=bootstrap_servers,
            security_protocol="PLAINTEXT" if execution_venue == "local" else "SASL_SSL",
            request_topic=environment.semantic_request_topic or "operator.semantic-turn.requests",
            projection_topic=environment.semantic_projection_topic
            or "core.semantic-turn.projections",
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
    execution_venue = environment.values.get("FDAI_EXECUTION_VENUE", "deployed").strip()
    credential = None
    if execution_venue == "deployed":
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
            security_protocol="PLAINTEXT" if execution_venue == "local" else "SASL_SSL",
        ),
        hub=hub,
        agent_hub=agent_hub,
        credential=credential,
    )


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
    bridge: SemanticTurnBridge | None,
    bus: OperatorSemanticKafkaBus | None,
    live_stage_relay: LiveStageKafkaRelay | None,
) -> ApplicationLifecycle | None:
    services = tuple(service for service in (bus, bridge, live_stage_relay) if service is not None)
    if not services:
        return None
    if len(services) == 1:
        return services[0]
    return _CompositeLifecycle(services)


def _readiness_probe(
    store: PostgresFamilyStore | None,
    bus: OperatorSemanticKafkaBus | None,
    bridge: SemanticTurnBridge | None,
    live_stage_relay: LiveStageKafkaRelay | None,
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
            and (live_stage_relay is None or live_stage_relay.readiness())
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
    "OperatorComposition",
    "ProductionOperatorComposition",
    "TokenVerifierFactory",
    "WEBHOOK_SIGNING_SECRET_ENV",
]
