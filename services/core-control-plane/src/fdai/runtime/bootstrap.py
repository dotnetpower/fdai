"""Headless control-plane process lifecycle and shutdown coordination."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, datetime
from typing import Any

import httpx

from fdai.agents import (
    PantheonRuntime,
    ShadowDivergenceLedger,
)
from fdai.composition import (
    LlmBindings,
    compose_azure_semantic_query_runtime,
    compose_resource_state_shadow_hook,
    default_container_from_env,
)
from fdai.core.chaos.symptom_index import build_from_promoted
from fdai.core.control_loop import ControlLoop
from fdai.delivery.agent_activity import (
    DEFAULT_STAGE_TOPIC,
    AgentRuntimeStatePublisher,
)
from fdai.delivery.startup_probe import OpaCompileStartupProbe
from fdai.runtime.bootstrap_bindings import (
    VERTICAL_IDENTITY_ENV,
    EffectReconciliationRequestRuntimeBinding,
    RuleGenerationRuntimeBinding,
)
from fdai.runtime.bootstrap_bindings import (
    build_effect_reconciliation_request_binding as _build_effect_reconciliation_request_binding,
)
from fdai.runtime.bootstrap_bindings import (
    build_effect_reconciliation_worker as _build_effect_reconciliation_worker,
)
from fdai.runtime.bootstrap_bindings import (
    build_rule_generation_runtime_binding as _build_rule_generation_runtime_binding,
)
from fdai.runtime.bootstrap_bindings import (
    build_runtime_workload_identity as _build_runtime_workload_identity,
)
from fdai.runtime.bootstrap_bindings import (
    build_vertical_execution_identities as _build_vertical_execution_identities_impl,
)
from fdai.runtime.bootstrap_bindings import (
    case_history_identity_client_id as _case_history_identity_client_id,
)
from fdai.runtime.bootstrap_bindings import (
    operational_event_bus as _operational_event_bus,
)
from fdai.runtime.bootstrap_bindings import (
    semantic_query_providers as _semantic_query_providers,
)
from fdai.runtime.bootstrap_lifecycle import (
    DiscoveryActivationRuntime,
    bind_health_readiness,
    build_discovery_activation_runtime,
    install_shutdown_signals,
    open_health_port,
)
from fdai.runtime.bootstrap_lifecycle import (
    build_catalog_semantic_runtime_binding as _build_catalog_semantic_runtime_binding,
)
from fdai.runtime.bootstrap_lifecycle import (
    build_mutation_dependency_readiness as _build_mutation_dependency_readiness,
)
from fdai.runtime.bootstrap_lifecycle import (
    build_runtime_saga as _build_runtime_saga,
)
from fdai.runtime.bootstrap_lifecycle import (
    build_semantic_turn_binding as _build_semantic_turn_binding,
)
from fdai.runtime.bootstrap_lifecycle import (
    catalog_semantic_readiness_registration as _catalog_semantic_readiness_registration,
)
from fdai.runtime.bootstrap_lifecycle import (
    log_rule_generation_outbox_exit as _log_rule_generation_outbox_exit,
)
from fdai.runtime.bootstrap_lifecycle import (
    publish_rule_generation_reconciliation as _publish_rule_generation_reconciliation,
)
from fdai.runtime.bootstrap_lifecycle import (
    run_effect_reconciliation as _run_effect_reconciliation,
)
from fdai.runtime.bootstrap_lifecycle import (
    run_effect_reconciliation_request_outbox as _run_effect_reconciliation_request_outbox,
)
from fdai.runtime.bootstrap_lifecycle import (
    run_main as _run_main,
)
from fdai.runtime.bootstrap_lifecycle import (
    run_rule_generation_outbox_publisher as _run_rule_generation_outbox_publisher,
)
from fdai.runtime.bootstrap_lifecycle import (
    runtime_positive_integer as _runtime_positive_integer,
)
from fdai.runtime.bootstrap_lifecycle import (
    semantic_router_config_from_env as _semantic_router_config_from_env,
)
from fdai.runtime.bootstrap_lifecycle import (
    semantic_turn_readiness_registration as _semantic_turn_readiness_registration,
)
from fdai.runtime.bootstrap_lifecycle import (
    supervise_runtime_tasks as _supervise_runtime_tasks,
)
from fdai.runtime.bootstrap_pantheon import PantheonInitialization, initialize_pantheon
from fdai.runtime.bootstrap_shutdown import close_runtime_resources as _close_runtime_resources
from fdai.runtime.bootstrap_tasks import (
    RuntimeTaskConfiguration,
    RuntimeTaskHooks,
    run_runtime_tasks,
)
from fdai.runtime.bootstrap_tasks import (
    schedule_semantic_turn_consumer as _schedule_semantic_turn_consumer,
)
from fdai.runtime.bootstrap_topics import RUNTIME_LOGICAL_TOPICS as _RUNTIME_LOGICAL_TOPICS
from fdai.runtime.case_history import (
    CaseHistoryRetentionTickPublisher,
)
from fdai.runtime.catalog_ontology import project_catalog_ontology, sync_ontology_catalog
from fdai.runtime.configuration import (
    _attach_runtime_github_change_feed,
    _attach_runtime_knowledge_source,
    _attach_runtime_metric_provider,
    _direct_model_endpoint_resolver,
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
    EventBusDirectApiExecutionClient,
    _build_control_loop,
    _build_irp_event_handler,
    _load_resource_types,
)
from fdai.runtime.delivery import _build_incident_notifier
from fdai.runtime.dynamic_evidence import bind_dynamic_evidence_from_env
from fdai.runtime.health import RuntimeHealthServer
from fdai.runtime.operating_model import project_operating_model_from_env
from fdai.runtime.providers import (
    _build_audit_store,
    _build_inventory_delta_projector,
    _build_operator_memory_store,
    _build_read_investigation_provider,
)
from fdai.runtime.readiness import (
    StartupReadinessRuntime,
    build_startup_readiness_runtime,
)
from fdai.runtime.rule_generation_documents import (
    RuleGenerationDocumentsUnavailableError,
    RuleGenerationReconciliation,
    build_rule_generation_reconciliation,
)
from fdai.runtime.venue import (
    bus_security_protocol,
    resolve_execution_venue,
    uses_workload_identity,
)
from fdai.shared.config.models import LlmMode
from fdai.shared.config.runtime_flags import pantheon_start_enabled
from fdai.shared.providers.event_bus import EventBus

_LOGGER = logging.getLogger("fdai.startup")
_AUXILIARY_KAFKA_BOOTSTRAP_ENV = "FDAI_AUXILIARY_KAFKA_BOOTSTRAP_SERVERS"


def _build_vertical_execution_identities(
    *,
    http_client: httpx.AsyncClient | None,
) -> dict[str, Any]:
    """Preserve the bootstrap test seam while delegating provider construction."""
    return _build_vertical_execution_identities_impl(
        http_client,
        identity_environment=VERTICAL_IDENTITY_ENV,
        identity_builder=_build_runtime_workload_identity,
    )


async def _run() -> int:
    container = default_container_from_env()
    summary = _summarize_config(container)
    _LOGGER.info("startup_ok", extra={"config": summary})

    http_client: httpx.AsyncClient | None = None
    identity: Any = None
    bus: EventBus | None = None
    auxiliary_bus: EventBus | None = None
    isolated_executor_client: Any = None
    pantheon_runtime: PantheonRuntime | None = None
    agent_introspection_server: Any = None
    runtime_state_publisher: AgentRuntimeStatePublisher | None = None
    pantheon_heartbeat: float | None = None
    divergence_ledger: ShadowDivergenceLedger | None = None
    health_server: RuntimeHealthServer | None = None
    case_history_retention_publisher: CaseHistoryRetentionTickPublisher | None = None
    startup_readiness_runtime: StartupReadinessRuntime | None = None
    discovery_activation_runtime: DiscoveryActivationRuntime | None = None
    t2_recovery_maintenance: Any = None
    assignment_reconciliation_worker: Any = None
    effect_reconciliation_worker: Any = None
    effect_reconciliation_request_binding: EffectReconciliationRequestRuntimeBinding | None = None
    semantic_turn_binding: Any = None
    rule_generation_binding: RuleGenerationRuntimeBinding | None = None
    rule_generation_reconciliation: RuleGenerationReconciliation | None = None

    try:
        health_server = await open_health_port()
        telemetry_requested = bool(
            os.environ.get("FDAI_MONITOR_WORKSPACE_ID", "").strip()
            or os.environ.get("FDAI_PROMETHEUS_ENDPOINT", "").strip()
        )
        gateway_requested = bool(os.environ.get("FDAI_DEV_OPERATIONS_GATEWAY_URL", "").strip())
        case_history_requested = bool(os.environ.get("FDAI_CASE_HISTORY_CONTAINER_URL", "").strip())
        vertical_execution_requested = any(
            os.environ.get(env_var, "").strip() for env_var in VERTICAL_IDENTITY_ENV.values()
        )
        if case_history_requested:
            _case_history_identity_client_id(os.environ)
        if (
            container.config.llm.mode == LlmMode.AZURE
            or telemetry_requested
            or gateway_requested
            or case_history_requested
            or vertical_execution_requested
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

            venue = resolve_execution_venue()
            if identity is None and uses_workload_identity(venue):
                if http_client is None:
                    http_client = _new_http_client()
                identity = _build_runtime_workload_identity(http_client)

            bus = EventHubsKafkaBus(
                identity=identity,
                config=EventHubsKafkaBusConfig(
                    bootstrap_servers=container.config.kafka.bootstrap_servers,
                    dlq_suffix=container.config.kafka.topic_dlq_suffix,
                    security_protocol=bus_security_protocol(venue),
                ),
            )
            from fdai.delivery.event_bus_multiplex import MultiplexedEventBus

            bus = MultiplexedEventBus(
                bus=bus,
                logical_topics=_RUNTIME_LOGICAL_TOPICS,
                physical_topic=os.environ.get(
                    "FDAI_PANTHEON_OBJECT_TOPIC", "fdai.pantheon.objects"
                ).strip(),
            )
            auxiliary_bootstrap = os.environ.get(_AUXILIARY_KAFKA_BOOTSTRAP_ENV, "").strip()
            if auxiliary_bootstrap:
                auxiliary_bus = EventHubsKafkaBus(
                    identity=identity,
                    config=EventHubsKafkaBusConfig(
                        bootstrap_servers=auxiliary_bootstrap,
                        dlq_suffix=container.config.kafka.topic_dlq_suffix,
                        security_protocol=bus_security_protocol(venue),
                    ),
                )
            operational_bus = _operational_event_bus(bus, auxiliary_bus)
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
                IncidentOntologyProjector,
                IncidentRegistry,
                incident_severity,
                link_ticket_receipt,
                open_detected_incident_candidate,
            )

            incident_audit_store = _build_audit_store()
            if os.environ.get("FDAI_ISOLATED_EXECUTOR_AUTHORITY_CUTOVER", "").strip() == "1":
                if auxiliary_bus is None:
                    raise RuntimeError(
                        "isolated Executor authority cutover requires the auxiliary EventBus"
                    )
                isolated_executor_client = EventBusDirectApiExecutionClient(
                    event_bus=auxiliary_bus,
                    audit_store=incident_audit_store,
                    instance_id=os.environ.get("HOSTNAME", "fdai-core"),
                )
                await isolated_executor_client.start()
            from fdai.delivery.runtime_settings import RuntimeSettingsService

            runtime_settings = RuntimeSettingsService(
                store=incident_audit_store,
                env=os.environ,
                durable=bool(os.environ.get("FDAI_STATE_STORE_DSN", "").strip()),
            )
            runtime_values = await runtime_settings.effective_values()
            if runtime_settings.durable:
                from fdai.core.human_assignment import AssignmentReconciler
                from fdai.runtime.human_assignment_reconciliation import (
                    AssignmentReconciliationWorker,
                )

                assignment_reconciliation_worker = AssignmentReconciliationWorker(
                    reconciler=AssignmentReconciler(store=incident_audit_store),
                    interval_seconds=_runtime_positive_integer(
                        runtime_values,
                        "human_access.reconciliation_interval_seconds",
                    ),
                )
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

            runtime_symptom_index = build_from_promoted(_resolve_catalog_root() / "chaos-scenarios")

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

            container = await bind_dynamic_evidence_from_env(
                container,
                state_store=incident_audit_store,
                environ=os.environ,
            )
            if container.graph_dynamic_simulation_request_provider is None:
                _LOGGER.info(
                    "graph_dynamic_runtime_unavailable",
                    extra={"reason": "graph_evidence_prerequisites_absent"},
                )
            effect_reconciliation_worker = _build_effect_reconciliation_worker(
                state_store=incident_audit_store,
                event_bus=bus,
                artifact_resolver=container.reconciliation_artifact_resolver,
                observation_verifier=container.reconciliation_observation_verifier,
                environment=os.environ,
            )
            if effect_reconciliation_worker is not None:
                _LOGGER.info("effect_reconciliation_ready")
            else:
                _LOGGER.info(
                    "effect_reconciliation_unavailable",
                    extra={"reason": "artifact_resolver_and_observation_verifier_absent"},
                )
            effect_reconciliation_request_binding = _build_effect_reconciliation_request_binding(
                state_store=incident_audit_store,
                event_bus=bus,
                artifact_source=container.executed_action_reconciliation_artifact_source,
                observation_source=container.executed_action_observation_source,
                environment=os.environ,
            )
            if effect_reconciliation_request_binding is not None:
                _LOGGER.info("effect_reconciliation_request_producer_ready")
            else:
                _LOGGER.info(
                    "effect_reconciliation_request_producer_unavailable",
                    extra={"reason": "executed_action_sources_absent"},
                )
            runtime_saga = _build_runtime_saga(incident_audit_store)
            core_mutation_readiness = _build_mutation_dependency_readiness(
                saga=runtime_saga,
                rollback_executors=None,
            )
            control_loop = _build_control_loop(
                container,
                http_client=http_client,
                stage_publisher=stage_publisher,
                audit_store=incident_audit_store,
                tool_receipt_observer=_observe_tool_receipt,
                symptom_index=runtime_symptom_index,
                identity=identity,
                execution_identities=_build_vertical_execution_identities(
                    http_client=http_client,
                ),
                direct_api_execution_port=isolated_executor_client,
                response_outcome_sink=_relay_response_outcome,
                effect_reconciliation_request_sink=(
                    effect_reconciliation_request_binding.producer
                    if effect_reconciliation_request_binding is not None
                    else None
                ),
                human_access_enabled=runtime_values["human_access.enabled"] is True,
                mutation_dependency_readiness=core_mutation_readiness,
            )
            if control_loop.ontology_instance_store is not None:
                await sync_ontology_catalog(control_loop.ontology_instance_store)
                await incident_registry.bind_projection(
                    IncidentOntologyProjector(store=control_loop.ontology_instance_store),
                    entries=incident_entries,
                )
            catalog_projection_result = await project_catalog_ontology(control_loop)
            operating_model_result = await project_operating_model_from_env(
                store=control_loop.ontology_instance_store,
                object_types=container.ontology_object_types,
                link_types=container.ontology_link_types,
                status_store=incident_audit_store,
            )
            semantic_purpose = os.environ.get(
                "FDAI_SEMANTIC_TURN_PURPOSE", "operations-review"
            ).strip()
            endpoint = os.environ.get("FDAI_LLM_ENDPOINT", "").strip() or None
            catalog_semantic_binding = await _build_catalog_semantic_runtime_binding(
                config=os.environ,
                embedder=container.require_llm_bindings().embedding_model,
                rules=control_loop.rules,
                ontology_release=control_loop.ontology_release,
            )
            query_catalog_index = (
                catalog_semantic_binding.index if catalog_semantic_binding.available else None
            )
            query_catalog_digest = (
                catalog_semantic_binding.catalog_digest
                if catalog_semantic_binding.available
                else None
            )
            rule_generation_binding = _build_rule_generation_runtime_binding(
                state_store=incident_audit_store,
                event_bus=bus,
                catalog_index=catalog_semantic_binding.index,
                environment=os.environ,
            )
            if (
                catalog_semantic_binding.index is not None
                and control_loop.ontology_release is not None
            ):
                try:
                    rule_generation_reconciliation = await build_rule_generation_reconciliation(
                        catalog_root=_resolve_catalog_root(),
                        rules=control_loop.rules,
                        action_types=control_loop.action_types,
                        ontology_release=control_loop.ontology_release,
                        embedder=container.require_llm_bindings().embedding_model,
                        index=catalog_semantic_binding.index,
                        store=incident_audit_store,
                        request_generation=not catalog_semantic_binding.available,
                        requested_at=datetime.now(UTC),
                    )
                except RuleGenerationDocumentsUnavailableError as exc:
                    _LOGGER.warning(
                        "rule_generation_reconciliation_unavailable",
                        extra={"reason": str(exc)},
                    )
            topology_reader, metric_registry, metric_window_provider = _semantic_query_providers(
                state_store_dsn=os.environ.get("FDAI_STATE_STORE_DSN"),
                subscription_id=os.environ.get("AZURE_SUBSCRIPTION_ID"),
                metric_provider=container.metric_provider,
                metric_registry=control_loop.metric_semantics,
            )
            from fdai.core.ontology_platform.incident_queries import IncidentEvidenceReader

            incident_evidence_reader = (
                incident_audit_store
                if isinstance(incident_audit_store, IncidentEvidenceReader)
                else None
            )
            read_investigation_provider = _build_read_investigation_provider(
                identity=identity,
                http_client=http_client,
            )
            semantic_composition = compose_azure_semantic_query_runtime(
                container=container,
                ontology_release=control_loop.ontology_release,
                ontology_store=control_loop.ontology_instance_store,
                identity=identity,
                http_client=http_client,
                endpoint=endpoint,
                endpoint_resolver=(
                    _direct_model_endpoint_resolver(endpoint) if endpoint is not None else None
                ),
                catalog_root=_resolve_catalog_root(),
                owner_loop=asyncio.get_running_loop(),
                purpose=semantic_purpose,
                catalog_index=query_catalog_index,
                catalog_digest=query_catalog_digest,
                topology_reader=topology_reader,
                metric_registry=metric_registry,
                metric_window_provider=metric_window_provider,
                incident_evidence_reader=incident_evidence_reader,
                read_investigation_provider=read_investigation_provider,
            )
            semantic_turn_binding = _build_semantic_turn_binding(
                state_store=incident_audit_store,
                config=os.environ,
                runtime=semantic_composition.runtime,
                unavailable_reason=semantic_composition.unavailable_reason,
            )
            from fdai.delivery.operational_activity import EventBusOperationalActivityPublisher

            read_investigation_hook = compose_resource_state_shadow_hook(
                provider=read_investigation_provider,
                state_store=incident_audit_store,
                ontology_release=control_loop.ontology_release,
                ontology_store=control_loop.ontology_instance_store,
                schema_registry=container.schema_registry,
                catalog_root=_resolve_catalog_root(),
                activity_publisher=EventBusOperationalActivityPublisher(
                    event_bus=operational_bus,
                    topic=stage_topic,
                ),
            )
            if semantic_turn_binding is not None and not semantic_turn_binding.available:
                _LOGGER.warning(
                    "semantic_turn_runtime_unavailable",
                    extra={"reason": semantic_turn_binding.unavailable_reason},
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
                    "catalog_ontology_objects": (
                        catalog_projection_result.object_count
                        if catalog_projection_result is not None
                        else 0
                    ),
                },
            )
            semantic_readiness_specs, semantic_readiness_probes = (
                _semantic_turn_readiness_registration(semantic_turn_binding)
            )
            catalog_semantic_specs, catalog_semantic_probes = (
                _catalog_semantic_readiness_registration(catalog_semantic_binding)
            )
            startup_readiness_runtime = build_startup_readiness_runtime(
                state_store=incident_audit_store,
                event_bus=operational_bus,
                transition_event_bus=bus,
                event_validator=container.event_validator,
                identity=identity,
                embedding_model=container.require_llm_bindings().embedding_model,
                policy_compile_probe=OpaCompileStartupProbe(
                    probe_id="policy.compile",
                    policies_root=_resolve_policies_root(_resolve_catalog_root()),
                ),
                cross_check_models=container.require_llm_bindings().cross_check_models,
                environment=os.environ,
                registered_specs=(
                    *container.startup_probe_specs,
                    *semantic_readiness_specs,
                    *catalog_semantic_specs,
                ),
                registered_probes=(
                    *container.startup_probes,
                    *semantic_readiness_probes,
                    *catalog_semantic_probes,
                ),
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
            discovery_activation_runtime = build_discovery_activation_runtime(
                state_store=incident_audit_store,
                runtime_settings=runtime_settings,
                startup_readiness=startup_readiness_runtime.state,
            )

            pantheon = await initialize_pantheon(
                PantheonInitialization(
                    container=container,
                    http_client=http_client,
                    identity=identity,
                    bus=bus,
                    incident_audit_store=incident_audit_store,
                    startup_report=startup_report,
                    runtime_saga=runtime_saga,
                    runtime_values=runtime_values,
                    runtime_settings=runtime_settings,
                    discovery_activation=discovery_activation_runtime,
                    control_loop=control_loop,
                    rule_generation_reconciliation=rule_generation_reconciliation,
                    rule_generation_binding=rule_generation_binding,
                    open_incident_candidate=_open_incident_candidate,
                    read_investigation_hook=read_investigation_hook,
                    runtime_symptom_index=runtime_symptom_index,
                    stage_topic=stage_topic,
                    environment=os.environ,
                    build_runtime_workload_identity=_build_runtime_workload_identity,
                    build_operator_memory_store=_build_operator_memory_store,
                    build_inventory_delta_projector=_build_inventory_delta_projector,
                    runtime_positive_integer=_runtime_positive_integer,
                    build_mutation_dependency_readiness=_build_mutation_dependency_readiness,
                    semantic_router_config_from_env=_semantic_router_config_from_env,
                )
            )
            pantheon_runtime = pantheon.runtime
            agent_introspection_server = pantheon.agent_introspection_server
            runtime_state_publisher = pantheon.runtime_state_publisher
            pantheon_heartbeat = pantheon.heartbeat
            divergence_ledger = pantheon.divergence_ledger
            case_history_retention_publisher = pantheon.case_history_retention_publisher
            t2_recovery_maintenance = pantheon.t2_recovery_maintenance
            discovery_activation_runtime = pantheon.discovery_activation
        elif pantheon_start_enabled(os.environ):
            # Pantheon needs the same Kafka bus the consumer builds; without
            # FDAI_START_CONSUMER there is no bus to bind to. Warn rather
            # than silently no-op so a miswired container is visible.
            _LOGGER.warning("pantheon_requested_without_consumer")

        bind_health_readiness(
            health_server,
            control_loop=control_loop,
            startup_readiness=startup_readiness_runtime,
        )
        stop = install_shutdown_signals()
        if bus is not None and control_loop is not None and startup_readiness_runtime is not None:
            await run_runtime_tasks(
                RuntimeTaskConfiguration(
                    container=container,
                    bus=bus,
                    operational_bus=operational_bus,
                    control_loop=control_loop,
                    readiness=startup_readiness_runtime,
                    stop=stop,
                    runtime_settings=runtime_settings,
                    discovery_activation=discovery_activation_runtime,
                    semantic_turn_binding=semantic_turn_binding,
                    divergence_ledger=divergence_ledger,
                    pantheon_runtime=pantheon_runtime,
                    pantheon_heartbeat=pantheon_heartbeat,
                    agent_introspection_server=agent_introspection_server,
                    runtime_state_publisher=runtime_state_publisher,
                    t2_recovery_maintenance=t2_recovery_maintenance,
                    assignment_reconciliation_worker=assignment_reconciliation_worker,
                    effect_reconciliation_worker=effect_reconciliation_worker,
                    effect_reconciliation_request_binding=effect_reconciliation_request_binding,
                    rule_generation_binding=rule_generation_binding,
                    rule_generation_reconciliation=rule_generation_reconciliation,
                    case_history_retention_publisher=case_history_retention_publisher,
                    environment=os.environ,
                ),
                RuntimeTaskHooks(
                    consume=_consume,
                    consume_resource_changes=_consume_resource_changes,
                    consume_canaries=_consume_canaries,
                    consume_hil_decisions=_consume_hil_decisions,
                    build_irp_event_handler=_build_irp_event_handler,
                    load_resource_types=_load_resource_types,
                    schedule_semantic_turn_consumer=_schedule_semantic_turn_consumer,
                    log_pantheon_exit=_log_pantheon_exit,
                    run_effect_reconciliation=_run_effect_reconciliation,
                    run_effect_reconciliation_request_outbox=(
                        _run_effect_reconciliation_request_outbox
                    ),
                    run_rule_generation_outbox_publisher=(_run_rule_generation_outbox_publisher),
                    log_rule_generation_outbox_exit=_log_rule_generation_outbox_exit,
                    publish_rule_generation_reconciliation=(
                        _publish_rule_generation_reconciliation
                    ),
                    supervise_runtime_tasks=_supervise_runtime_tasks,
                ),
            )
        else:
            await stop.wait()

        _LOGGER.info("shutdown_complete")
        return 0
    finally:
        if isolated_executor_client is not None:
            await isolated_executor_client.stop()
        await _close_runtime_resources(
            health_server=health_server,
            pantheon_runtime=pantheon_runtime,
            runtime_state_publisher=runtime_state_publisher,
            auxiliary_bus=auxiliary_bus,
            bus=bus,
            http_client=http_client,
        )


def main() -> int:
    return _run_main(_run)
