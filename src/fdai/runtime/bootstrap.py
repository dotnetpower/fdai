"""Headless control-plane process lifecycle and shutdown coordination."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, cast

import httpx

from fdai.agents import (
    OWNED_OBJECT_TOPICS,
    PantheonRuntime,
    ShadowDivergenceLedger,
)
from fdai.composition import (
    LlmBindings,
    default_container_from_env,
)
from fdai.core.chaos.coverage import ScenarioCoverageAggregator
from fdai.core.chaos.symptom_index import build_from_promoted
from fdai.core.control_loop import ControlLoop
from fdai.core.learning import PostTurnProposalModel, RuleHintSubmitter
from fdai.core.operational_context import OperationalContextMaterializer
from fdai.core.readiness import AuthorityCeiling
from fdai.core.readiness.coordinator import _TRANSITION_TOPIC
from fdai.delivery.agent_introspection_bus import AGENT_INTROSPECTION_TOPICS
from fdai.delivery.persistence.postgres_case_history import (
    PostgresCaseHistoryMetadataStore,
    PostgresCaseHistoryMetadataStoreConfig,
)
from fdai.delivery.read_api.streaming.agent_activity_stream import (
    runtime_agent_state_snapshot,
)
from fdai.delivery.read_api.streaming.agent_runtime_state_publisher import (
    AgentRuntimeStatePublisher,
    EventBusPantheonActivityObserver,
)
from fdai.delivery.startup_probe import OpaCompileStartupProbe
from fdai.runtime.bootstrap_bindings import (
    build_runtime_workload_identity as _build_runtime_workload_identity,
)
from fdai.runtime.bootstrap_bindings import (
    case_history_identity_client_id as _case_history_identity_client_id,
)
from fdai.runtime.bootstrap_bindings import (
    operational_event_bus as _operational_event_bus,
)
from fdai.runtime.bootstrap_lifecycle import (
    build_runtime_saga as _build_runtime_saga,
)
from fdai.runtime.bootstrap_lifecycle import (
    install_shutdown_signals as _install_shutdown_signals,
)
from fdai.runtime.bootstrap_lifecycle import (
    run_main as _run_main,
)
from fdai.runtime.bootstrap_lifecycle import (
    runtime_positive_integer as _runtime_positive_integer,
)
from fdai.runtime.bootstrap_lifecycle import (
    semantic_router_config_from_env as _semantic_router_config_from_env,
)
from fdai.runtime.bootstrap_lifecycle import (
    start_health_server as _start_health_server,
)
from fdai.runtime.bootstrap_lifecycle import (
    supervise_runtime_tasks as _supervise_runtime_tasks,
)
from fdai.runtime.case_history import (
    CaseHistoryRetentionTickPublisher,
    CaseHistoryRuntime,
    build_case_history_runtime,
)
from fdai.runtime.configuration import (
    _attach_runtime_github_change_feed,
    _attach_runtime_knowledge_source,
    _attach_runtime_metric_provider,
    _finalize_llm_bindings,
    _new_http_client,
    _resolve_catalog_root,
    _resolve_policies_root,
    _summarize_config,
)
from fdai.runtime.consumers import (
    _consume,
    _consume_canaries,
    _consume_hil_decisions,
    _consume_resource_changes,
    _log_pantheon_exit,
)
from fdai.runtime.control_loop import (
    _build_control_loop,
    _build_irp_event_handler,
    _load_resource_types,
)
from fdai.runtime.delivery import _build_incident_notifier
from fdai.runtime.forecast_learning import (
    ForecastLearningRuntime,
    build_forecast_learning_runtime,
)
from fdai.runtime.health import RuntimeHealthServer
from fdai.runtime.operating_model import project_operating_model_from_env
from fdai.runtime.post_turn_review import (
    build_azure_post_turn_models,
    build_post_turn_review_runtime,
    post_turn_review_dsn,
)
from fdai.runtime.providers import (
    _build_audit_store,
    _build_inventory_delta_projector,
    _build_operator_memory_store,
)
from fdai.runtime.readiness import (
    StartupReadinessRuntime,
    build_startup_readiness_runtime,
)
from fdai.shared.config.models import LlmMode
from fdai.shared.config.runtime_flags import pantheon_start_enabled
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.workload_identity import WorkloadIdentity

_LOGGER = logging.getLogger("fdai.startup")
_AUXILIARY_KAFKA_BOOTSTRAP_ENV = "FDAI_AUXILIARY_KAFKA_BOOTSTRAP_SERVERS"
_RUNTIME_LOGICAL_TOPICS = (
    OWNED_OBJECT_TOPICS | AGENT_INTROSPECTION_TOPICS | frozenset({_TRANSITION_TOPIC})
)


async def _run() -> int:
    container = default_container_from_env()
    summary = _summarize_config(container)
    _LOGGER.info("startup_ok", extra={"config": summary})

    http_client: httpx.AsyncClient | None = None
    identity: WorkloadIdentity | None = None
    bus: EventBus | None = None
    auxiliary_bus: EventBus | None = None
    pantheon_runtime: PantheonRuntime | None = None
    agent_introspection_server: Any = None
    runtime_state_publisher: AgentRuntimeStatePublisher | None = None
    pantheon_heartbeat: float | None = None
    divergence_ledger: ShadowDivergenceLedger | None = None
    health_server: RuntimeHealthServer | None = None
    case_history_runtime: CaseHistoryRuntime | None = None
    case_history_retention_publisher: CaseHistoryRetentionTickPublisher | None = None
    forecast_learning_runtime: ForecastLearningRuntime | None = None
    startup_readiness_runtime: StartupReadinessRuntime | None = None

    try:
        telemetry_requested = bool(
            os.environ.get("FDAI_MONITOR_WORKSPACE_ID", "").strip()
            or os.environ.get("FDAI_PROMETHEUS_ENDPOINT", "").strip()
        )
        gateway_requested = bool(os.environ.get("FDAI_DEV_OPERATIONS_GATEWAY_URL", "").strip())
        case_history_requested = bool(os.environ.get("FDAI_CASE_HISTORY_CONTAINER_URL", "").strip())
        if case_history_requested:
            _case_history_identity_client_id(os.environ)
        if (
            container.config.llm.mode == LlmMode.AZURE
            or telemetry_requested
            or gateway_requested
            or case_history_requested
        ):
            http_client = _new_http_client()
            identity = _build_runtime_workload_identity(http_client)

        if container.config.llm.mode == LlmMode.AZURE:
            if http_client is None or identity is None:
                raise RuntimeError("Azure LLM mode requires HTTP and workload identity bindings")
            container = await _finalize_llm_bindings(
                container, http_client=http_client, identity=identity
            )
            bindings: LlmBindings = container.require_llm_bindings()
            _LOGGER.info(
                "azure_llm_bindings_attached",
                extra={"cross_check_models": len(bindings.cross_check_models)},
            )
        elif telemetry_requested:
            if http_client is None or identity is None:
                raise RuntimeError("Azure telemetry requires HTTP and workload identity bindings")
            container = _attach_runtime_metric_provider(
                container,
                http_client=http_client,
                identity=identity,
            )
            container = _attach_runtime_knowledge_source(container)

        start_consumer = os.environ.get("FDAI_START_CONSUMER", "").lower() in (
            "1",
            "true",
        )
        control_loop: ControlLoop | None = None

        if start_consumer:
            from fdai.delivery.azure.event_bus import (
                EventHubsKafkaBus,
                EventHubsKafkaBusConfig,
            )

            if identity is None:
                if http_client is None:
                    http_client = _new_http_client()
                identity = _build_runtime_workload_identity(http_client)

            bus = EventHubsKafkaBus(
                identity=identity,
                config=EventHubsKafkaBusConfig(
                    bootstrap_servers=container.config.kafka.bootstrap_servers,
                    dlq_suffix=container.config.kafka.topic_dlq_suffix,
                ),
            )
            from fdai.delivery.agent_introspection_bus import (
                EventBusAgentIntrospectionServer,
                agent_introspection_server_group_id,
            )
            from fdai.delivery.event_bus_multiplex import MultiplexedEventBus

            bus = MultiplexedEventBus(
                bus=bus,
                logical_topics=_RUNTIME_LOGICAL_TOPICS,
                physical_topic=os.environ.get(
                    "FDAI_PANTHEON_OBJECT_TOPIC", "aw.pantheon.objects"
                ).strip(),
            )
            auxiliary_bootstrap = os.environ.get(_AUXILIARY_KAFKA_BOOTSTRAP_ENV, "").strip()
            if auxiliary_bootstrap:
                auxiliary_bus = EventHubsKafkaBus(
                    identity=identity,
                    config=EventHubsKafkaBusConfig(
                        bootstrap_servers=auxiliary_bootstrap,
                        dlq_suffix=container.config.kafka.topic_dlq_suffix,
                    ),
                )
            operational_bus = _operational_event_bus(bus, auxiliary_bus)
            from fdai.delivery.read_api.streaming.agent_activity_broadcaster import (
                DEFAULT_STAGE_TOPIC,
            )
            from fdai.shared.streaming.stage_publisher import EventBusStagePublisher

            stage_topic = os.environ.get("FDAI_STAGE_TOPIC", "").strip() or DEFAULT_STAGE_TOPIC
            stage_publisher = EventBusStagePublisher(bus, topic=stage_topic)
            # A GitOps token opts into the real publisher; ensure an
            # http_client exists before _build_control_loop needs one.
            if os.environ.get("FDAI_GITOPS_TOKEN") and http_client is None:
                http_client = _new_http_client()
            if os.environ.get("FDAI_GITOPS_TOKEN") and http_client is not None:
                container = _attach_runtime_github_change_feed(
                    container,
                    http_client=http_client,
                )
            # Same for the HIL channel - an Incoming Webhook URL opts in.
            if os.environ.get("FDAI_CHATOPS_WEBHOOK_URL") and http_client is None:
                http_client = _new_http_client()
            if os.environ.get("FDAI_EMAIL_ENDPOINT") and http_client is None:
                http_client = _new_http_client()
            from fdai.core.incident import (
                IncidentAutoOpenPolicy,
                IncidentLifecycleWorkflow,
                IncidentRegistry,
                incident_severity,
                link_ticket_receipt,
                open_detected_incident_candidate,
            )

            incident_audit_store = _build_audit_store()
            from fdai.delivery.runtime_settings import RuntimeSettingsService

            runtime_settings = RuntimeSettingsService(
                store=incident_audit_store,
                env=os.environ,
                durable=bool(os.environ.get("FDAI_STATE_STORE_DSN", "").strip()),
            )
            runtime_values = await runtime_settings.effective_values()
            logging.getLogger().setLevel(str(runtime_values["logging.level"]))
            incident_auto_open_policy = IncidentAutoOpenPolicy(
                enabled=runtime_values["incident.auto_open.enabled"] is True,
                minimum_severity=incident_severity(
                    runtime_values["incident.auto_open.min_severity"]
                ),
            )
            incident_registry = IncidentRegistry(state_store=incident_audit_store)
            incident_entries = await incident_audit_store.read_incident_transitions()
            incident_registry.rehydrate(incident_entries)
            incident_notifier = _build_incident_notifier(
                incident_audit_store,
                http_client=http_client,
            )
            await incident_notifier.replay(incident_entries)
            incident_workflow = IncidentLifecycleWorkflow(
                registry=incident_registry,
                notifier=incident_notifier,
                allowed_agent_principals={"Huginn", "Heimdall", "Forseti"},
            )

            async def _open_incident_candidate(candidate: dict[str, Any]) -> bool:
                result = await open_detected_incident_candidate(
                    workflow=incident_workflow,
                    candidate=candidate,
                    policy=incident_auto_open_policy,
                )
                return result is not None

            async def _observe_tool_receipt(request: Any, receipt: Any) -> None:
                incident_id = request.metadata.get("incident_id") or request.arguments.get(
                    "incident_id"
                )
                provider = request.metadata.get("ticket_provider") or request.arguments.get(
                    "ticket_provider"
                )
                if not incident_id or not provider:
                    return
                await link_ticket_receipt(
                    registry=incident_registry,
                    request=request,
                    receipt=receipt,
                    actor_oid="Thor",
                )

            runtime_symptom_index = build_from_promoted()

            async def _relay_response_outcome(outcome: Any) -> None:
                await bus.publish(
                    container.config.kafka.topic_events,
                    outcome.idempotency_key,
                    {
                        "id": outcome.idempotency_key,
                        "event_id": str(outcome.event_id),
                        "correlation_id": str(outcome.action_id),
                        "idempotency_key": outcome.idempotency_key,
                        "source": "fdai.measurement",
                        "event_type": "measurement.action_outcome.v1",
                        "resource_id": outcome.target_digest,
                        "attributes": outcome.model_dump(mode="json", exclude_none=True),
                    },
                )

            control_loop = _build_control_loop(
                container,
                http_client=http_client,
                stage_publisher=stage_publisher,
                audit_store=incident_audit_store,
                tool_receipt_observer=_observe_tool_receipt,
                symptom_index=runtime_symptom_index,
                identity=identity,
                response_outcome_sink=_relay_response_outcome,
            )
            operating_model_result = await project_operating_model_from_env(
                store=control_loop.ontology_instance_store,
                object_types=container.ontology_object_types,
                link_types=container.ontology_link_types,
                status_store=incident_audit_store,
            )
            _LOGGER.info(
                "control_loop_ready",
                extra={
                    "topic": container.config.kafka.topic_events,
                    "stage_topic": stage_topic,
                    "group_id": "fdai-core",
                    "operating_model_revision": (
                        operating_model_result.source_revision
                        if operating_model_result is not None
                        else None
                    ),
                },
            )
            startup_readiness_runtime = build_startup_readiness_runtime(
                state_store=incident_audit_store,
                event_bus=bus,
                event_validator=container.event_validator,
                identity=identity,
                embedding_model=container.require_llm_bindings().embedding_model,
                policy_compile_probe=OpaCompileStartupProbe(
                    probe_id="policy.compile",
                    policies_root=_resolve_policies_root(_resolve_catalog_root()),
                ),
                cross_check_models=container.require_llm_bindings().cross_check_models,
                environment=os.environ,
                registered_specs=container.startup_probe_specs,
                registered_probes=container.startup_probes,
            )
            startup_report = await startup_readiness_runtime.evaluate()
            _LOGGER.info(
                "startup_readiness_evaluated",
                extra={
                    "decision": startup_report.decision.value,
                    "probe_count": len(startup_report.results),
                    "missing_count": len(startup_report.missing_probe_ids),
                    "stale_count": len(startup_report.stale_probe_ids),
                },
            )

            # Pantheon: the 15 named agents consume the same
            # ingress topic under distinct consumer groups (fan-out) and
            # react immediately. Enabled by default; FDAI_START_PANTHEON=0
            # is the explicit maintenance escape hatch. Thor stays shadow
            # by default - the agents use in-memory audit / issue / admin
            # adapters and Thor's executor stays in shadow, so running it
            # beside the P1 loop adds no autonomous mutation. See
            # docs/roadmap/agents/agent-pantheon-implementation.md.
            start_pantheon = pantheon_start_enabled(os.environ)
            if start_pantheon:
                pantheon_enforce = os.environ.get("FDAI_PANTHEON_ENFORCE", "").lower() in (
                    "1",
                    "true",
                )
                if (
                    startup_report.authority_ceilings.get("autonomous-action")
                    is not AuthorityCeiling.DEPLOYMENT
                ):
                    pantheon_enforce = False
                disabled_raw = os.environ.get("FDAI_PANTHEON_DISABLED_AGENTS", "").strip()
                disabled_agents = (
                    frozenset(n.strip() for n in disabled_raw.split(",") if n.strip())
                    if disabled_raw
                    else None
                )
                # Shared ledger: the pantheon observer records its shadow
                # verdict, the P1 consumer records the authoritative
                # decision; joined by correlation id to measure shadow
                # agreement (the promotion baseline).
                divergence_ledger = ShadowDivergenceLedger()
                post_turn_models: tuple[PostTurnProposalModel, ...] = ()
                if container.config.llm.mode == LlmMode.AZURE:
                    if http_client is None or identity is None:
                        raise RuntimeError(
                            "Azure post-turn review requires HTTP and workload identity bindings"
                        )
                    resolved_models_path = container.config.llm.resolved_models_path
                    if resolved_models_path is None:
                        raise RuntimeError(
                            "Azure post-turn review requires resolved model configuration"
                        )
                    post_turn_models = build_azure_post_turn_models(
                        repo_root=Path(__file__).resolve().parents[3],
                        resolved_models_path=resolved_models_path,
                        endpoint=os.environ["FDAI_LLM_ENDPOINT"],
                        identity=identity,
                        http_client=http_client,
                    )
                post_turn_review = build_post_turn_review_runtime(
                    state_store=incident_audit_store,
                    operator_memory=_build_operator_memory_store(),
                    models=post_turn_models,
                    dsn=post_turn_review_dsn(),
                )
                case_history_container_url = (
                    os.environ.get("FDAI_CASE_HISTORY_CONTAINER_URL", "").strip() or None
                )
                case_history_identity = None
                if case_history_container_url is not None:
                    if http_client is None:
                        raise RuntimeError("case history storage requires an HTTP client")
                    case_history_identity = _build_runtime_workload_identity(
                        http_client,
                        client_id_env="FDAI_CASE_HISTORY_MI_CLIENT_ID",
                        require_client_id=True,
                    )
                case_history_runtime = build_case_history_runtime(
                    container_url=case_history_container_url,
                    state_store=incident_audit_store,
                    identity=case_history_identity,
                    http_client=http_client,
                    dsn=os.environ.get("FDAI_STATE_STORE_DSN"),
                    relational_read_authority=(
                        os.environ.get("FDAI_CASE_HISTORY_RELATIONAL_READ", "").strip() == "1"
                    ),
                    models=post_turn_models,
                )
                if (
                    case_history_runtime is not None
                    and os.environ.get("FDAI_STATE_STORE_DSN", "").strip()
                ):
                    relational_metadata = PostgresCaseHistoryMetadataStore(
                        config=PostgresCaseHistoryMetadataStoreConfig(
                            dsn=os.environ["FDAI_STATE_STORE_DSN"]
                        )
                    )
                    await relational_metadata.verify_schema()
                    if os.environ.get("FDAI_CASE_HISTORY_RELATIONAL_READ", "").strip() == "1":
                        await relational_metadata.verify_read_cutover()
                forecast_learning_runtime = build_forecast_learning_runtime(
                    dsn=os.environ.get("FDAI_STATE_STORE_DSN"),
                    targets_json=os.environ.get("FDAI_FORECAST_TARGETS_JSON"),
                    metric_provider=container.metric_provider,
                )
                if forecast_learning_runtime is not None:
                    await forecast_learning_runtime.store.verify_schema()
                if case_history_runtime is not None:
                    case_history_retention_publisher = CaseHistoryRetentionTickPublisher(
                        bus=bus,
                        topic=container.config.kafka.topic_events,
                        interval_seconds=_runtime_positive_integer(
                            runtime_values,
                            "case_history.retention_tick_seconds",
                        ),
                        runtime_settings=runtime_settings,
                    )
                case_retention_days = _runtime_positive_integer(
                    runtime_values,
                    "case_history.retention_days",
                )
                case_deletion_days = _runtime_positive_integer(
                    runtime_values,
                    "case_history.deletion_days",
                )
                pantheon_runtime = PantheonRuntime.build(
                    provider=bus,
                    raw_event_topic=container.config.kafka.topic_events,
                    consumer_group_prefix=os.environ.get(
                        "FDAI_PANTHEON_CONSUMER_GROUP_PREFIX",
                        "fdai-pantheon",
                    ).strip(),
                    enforce=pantheon_enforce,
                    saga=_build_runtime_saga(incident_audit_store),
                    muninn_state_store=incident_audit_store,
                    disabled_agents=disabled_agents,
                    divergence=divergence_ledger,
                    incident_candidate_hook=_open_incident_candidate,
                    heimdall_rate_threshold=_runtime_positive_integer(
                        runtime_values,
                        "incident.repeat_threshold",
                    ),
                    heimdall_rate_window=_runtime_positive_integer(
                        runtime_values,
                        "incident.repeat_window_seconds",
                    ),
                    discovery_projector=_build_inventory_delta_projector(),
                    scenario_coverage_aggregator=ScenarioCoverageAggregator(
                        index=runtime_symptom_index
                    ),
                    post_turn_review=post_turn_review.coordinator,
                    case_history_materializer=(
                        case_history_runtime.materializer
                        if case_history_runtime is not None
                        else None
                    ),
                    case_history_analyzer=(
                        case_history_runtime.analyzer if case_history_runtime is not None else None
                    ),
                    operational_context_materializer=(
                        OperationalContextMaterializer(store=control_loop.ontology_instance_store)
                        if control_loop.ontology_instance_store is not None
                        else None
                    ),
                    case_history_retention=(
                        case_history_runtime.retention if case_history_runtime is not None else None
                    ),
                    case_retention_days=case_retention_days,
                    case_deletion_days=case_deletion_days,
                    forecast_evaluator=(
                        forecast_learning_runtime.evaluator
                        if forecast_learning_runtime is not None
                        else None
                    ),
                    forecast_closer=(
                        forecast_learning_runtime.closer
                        if forecast_learning_runtime is not None
                        else None
                    ),
                    forecast_store=(
                        forecast_learning_runtime.store
                        if forecast_learning_runtime is not None
                        else None
                    ),
                    handler_observer=EventBusPantheonActivityObserver(
                        event_bus=bus,
                        topic=stage_topic,
                    ),
                    action_types=control_loop.action_types,
                    conversation_embedding_model=(
                        container.llm_bindings.embedding_model
                        if container.llm_bindings is not None
                        else None
                    ),
                    conversation_t2_synthesizer=(
                        container.llm_bindings.conversation_t2_synthesizer
                        if container.llm_bindings is not None
                        else None
                    ),
                    conversation_metering=(
                        container.llm_bindings.conversation_metering
                        if container.llm_bindings is not None
                        else None
                    ),
                    conversation_pricing=(
                        container.llm_bindings.conversation_pricing
                        if container.llm_bindings is not None
                        else None
                    ),
                    conversation_t2_model_key=(
                        container.llm_bindings.conversation_t2_model_key
                        if container.llm_bindings is not None
                        else ""
                    ),
                    semantic_router_config=_semantic_router_config_from_env(),
                )
                from fdai.runtime.t2_recovery import bind_t2_recovery_observer

                bind_t2_recovery_observer(
                    proposer=container.require_llm_bindings().require_t2_proposer(),
                    store=incident_audit_store,
                    ingress=pantheon_runtime.ingest_raw_event,
                )
                agent_introspection_server = EventBusAgentIntrospectionServer(
                    event_bus=bus,
                    runtime=pantheon_runtime,
                    group_id=agent_introspection_server_group_id(
                        local_process=os.environ.get("FDAI_RUNTIME_LOCAL_AZURE_CLI", "").strip()
                        == "1"
                    ),
                )
                runtime_state_publisher = AgentRuntimeStatePublisher(
                    event_bus=bus,
                    snapshot_factory=lambda: runtime_agent_state_snapshot(
                        pantheon_runtime.health()
                    ),
                    topic=stage_topic,
                )
                norns = pantheon_runtime.agents.get("Norns")
                if norns is not None:
                    post_turn_review.bind_rule_hints(cast(RuleHintSubmitter, norns))
                hb_raw = os.environ.get("FDAI_PANTHEON_HEARTBEAT_SECONDS", "").strip()
                if hb_raw:
                    try:
                        pantheon_heartbeat = float(hb_raw)
                    except ValueError as hb_exc:
                        raise RuntimeError(
                            f"FDAI_PANTHEON_HEARTBEAT_SECONDS={hb_raw!r} is not a float"
                        ) from hb_exc
                    if pantheon_heartbeat <= 0:
                        raise RuntimeError(
                            f"FDAI_PANTHEON_HEARTBEAT_SECONDS MUST be > 0; got {pantheon_heartbeat}"
                        )
                _LOGGER.info(
                    "pantheon_ready",
                    extra={
                        "agents": len(pantheon_runtime.agents),
                        "subscriptions": pantheon_runtime.subscription_count,
                        "enforce": pantheon_enforce,
                        "heartbeat_s": pantheon_heartbeat,
                    },
                )
        elif pantheon_start_enabled(os.environ):
            # Pantheon needs the same Kafka bus the consumer builds; without
            # FDAI_START_CONSUMER there is no bus to bind to. Warn rather
            # than silently no-op so a miswired container is visible.
            _LOGGER.warning("pantheon_requested_without_consumer")

        health_server = await _start_health_server(
            control_loop=control_loop,
            startup_readiness=startup_readiness_runtime,
        )
        stop = _install_shutdown_signals()

        if bus is not None and control_loop is not None and startup_readiness_runtime is not None:
            readiness_refresh_task = asyncio.create_task(
                startup_readiness_runtime.refresh_until_stopped(stop),
                name="startup-readiness-refresh",
            )
            consumer_task = asyncio.create_task(
                startup_readiness_runtime.run_when_ready(
                    stop,
                    lambda: _consume(
                        bus=bus,
                        topic=container.config.kafka.topic_events,
                        group_id=os.environ.get(
                            "FDAI_CORE_CONSUMER_GROUP_ID",
                            "fdai-core",
                        ).strip(),
                        control_loop=control_loop,
                        stop=stop,
                        divergence=divergence_ledger,
                        irp_handler=_build_irp_event_handler(
                            container=container,
                            bus=bus,
                            runtime_settings=runtime_settings,
                        ),
                    ),
                )
            )
            resource_change_task: asyncio.Task[None] | None = None
            inventory_raw_topic = os.environ.get("FDAI_INVENTORY_RAW_TOPIC", "").strip()
            if inventory_raw_topic:
                resource_change_task = asyncio.create_task(
                    startup_readiness_runtime.run_when_ready(
                        stop,
                        lambda: _consume_resource_changes(
                            bus=operational_bus,
                            raw_topic=inventory_raw_topic,
                            canonical_topic=container.config.kafka.topic_events,
                            resource_types=_load_resource_types(),
                            stop=stop,
                        ),
                    ),
                    name="huginn-resource-discovery",
                )
            canary_task: asyncio.Task[None] | None = None
            canary_topic = os.environ.get("FDAI_CANARY_TOPIC", "").strip()
            if canary_topic:
                canary_task = asyncio.create_task(
                    startup_readiness_runtime.run_when_ready(
                        stop,
                        lambda: _consume_canaries(
                            bus=operational_bus,
                            topic=canary_topic,
                            control_loop=control_loop,
                            stop=stop,
                        ),
                    ),
                    name="canary-consumer",
                )
            hil_decision_task: asyncio.Task[None] | None = None
            hil_reminder_task: asyncio.Task[None] | None = None
            if control_loop._hil_resume_coordinator is not None:
                from fdai.delivery.chatops.hil_decision import DEFAULT_HIL_DECISION_TOPIC

                hil_coordinator = control_loop._hil_resume_coordinator
                hil_decision_task = asyncio.create_task(
                    startup_readiness_runtime.run_when_ready(
                        stop,
                        lambda: _consume_hil_decisions(
                            bus=bus,
                            topic=os.environ.get(
                                "FDAI_HIL_DECISION_TOPIC",
                                DEFAULT_HIL_DECISION_TOPIC,
                            ),
                            coordinator=hil_coordinator,
                            stop=stop,
                        ),
                    ),
                    name="hil-decision-consumer",
                )
                reminder_dispatcher = hil_coordinator.reminder_dispatcher
                if reminder_dispatcher is not None:
                    hil_reminder_task = asyncio.create_task(
                        startup_readiness_runtime.run_when_ready(
                            stop,
                            lambda: reminder_dispatcher.run(stop),
                        ),
                        name="hil-approval-reminders",
                    )
            wait_task = asyncio.create_task(stop.wait())

            # Blast-radius isolation: the pantheon runs OUTSIDE the P1 wait
            # set. A pantheon crash is logged via a done-callback but MUST
            # NOT bring down the P1 control plane; P1 shutdown cancels it
            # in turn. The pantheon is a shadow overlay, never a dependency
            # of the primary pipeline.
            pantheon_task: asyncio.Task[None] | None = None
            agent_introspection_task: asyncio.Task[None] | None = None
            runtime_state_task: asyncio.Task[None] | None = None
            case_history_retention_task: asyncio.Task[None] | None = None
            if pantheon_runtime is not None:
                pantheon_task = asyncio.create_task(
                    startup_readiness_runtime.run_when_ready(
                        stop,
                        lambda: pantheon_runtime.run(heartbeat_interval=pantheon_heartbeat),
                    ),
                    name="pantheon-runtime",
                )
                pantheon_task.add_done_callback(_log_pantheon_exit)
            if agent_introspection_server is not None:
                agent_introspection_task = asyncio.create_task(
                    startup_readiness_runtime.run_when_ready(
                        stop,
                        agent_introspection_server.run,
                    ),
                    name="agent-introspection-server",
                )
            if runtime_state_publisher is not None:
                runtime_state_task = asyncio.create_task(
                    startup_readiness_runtime.run_when_ready(
                        stop,
                        runtime_state_publisher.run,
                    ),
                    name="pantheon-runtime-state",
                )
            if case_history_retention_publisher is not None:
                case_history_retention_task = asyncio.create_task(
                    startup_readiness_runtime.run_when_ready(
                        stop,
                        lambda: case_history_retention_publisher.run(stop=stop),
                    ),
                    name="case-history-retention-ticks",
                )

            await _supervise_runtime_tasks(
                required=(
                    consumer_task,
                    readiness_refresh_task,
                    wait_task,
                    resource_change_task,
                    canary_task,
                    hil_decision_task,
                    hil_reminder_task,
                    case_history_retention_task,
                ),
                background=(
                    pantheon_task,
                    agent_introspection_task,
                    runtime_state_task,
                ),
            )
        else:
            await stop.wait()

        _LOGGER.info("shutdown_complete")
        return 0
    finally:
        if health_server is not None:
            try:
                await health_server.close()
            except Exception:  # noqa: BLE001
                _LOGGER.warning("health_server_stop_failed", exc_info=True)
        if pantheon_runtime is not None:
            try:
                await pantheon_runtime.stop()
            except Exception:  # noqa: BLE001
                _LOGGER.warning("pantheon_stop_failed", exc_info=True)
        if runtime_state_publisher is not None:
            await runtime_state_publisher.stop()
        if auxiliary_bus is not None:
            close = getattr(auxiliary_bus, "close", None)
            if callable(close):
                try:
                    await close()
                except Exception:  # noqa: BLE001
                    _LOGGER.warning("auxiliary_bus_close_failed", exc_info=True)
        if bus is not None:
            close = getattr(bus, "close", None)
            if callable(close):
                try:
                    await close()
                except Exception:  # noqa: BLE001
                    _LOGGER.warning("bus_close_failed", exc_info=True)
        if http_client is not None:
            try:
                await http_client.aclose()
            except Exception:  # noqa: BLE001
                _LOGGER.warning("http_client_close_failed", exc_info=True)


def main() -> int:
    return _run_main(_run)
