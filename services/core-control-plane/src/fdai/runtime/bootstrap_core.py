"""Active Core runtime assembly for the headless control-plane process."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fdai.composition import Container
from fdai.composition.readiness import (
    OperationalReadinessEventHandler,
    build_operational_readiness_event_handler,
)
from fdai.core.chaos.symptom_index import build_from_promoted
from fdai.core.control_loop import ControlLoop
from fdai.delivery.azure.diagnostic_event_ingest import DiagnosticEventIngestBridge
from fdai.delivery.azure.monitor_events import DiagnosticNormalizerOptions
from fdai.delivery.runtime_settings import RuntimeSettingsService
from fdai.delivery.startup_probe import OpaCompileStartupProbe
from fdai.runtime.bootstrap_bindings import (
    EffectReconciliationRequestRuntimeBinding,
)
from fdai.runtime.bootstrap_bindings import (
    build_effect_reconciliation_request_binding as _build_effect_reconciliation_request_binding,
)
from fdai.runtime.bootstrap_bindings import (
    build_effect_reconciliation_worker as _build_effect_reconciliation_worker,
)
from fdai.runtime.bootstrap_bindings import (
    build_runtime_workload_identity as _build_runtime_workload_identity,
)
from fdai.runtime.bootstrap_bindings import (
    build_vertical_execution_identities as _build_vertical_execution_identities,
)
from fdai.runtime.bootstrap_incidents import (
    IncidentNotificationReplayWorker,
    build_incident_runtime,
)
from fdai.runtime.bootstrap_lifecycle import (
    DiscoveryActivationRuntime,
    build_discovery_activation_runtime,
)
from fdai.runtime.bootstrap_lifecycle import (
    build_mutation_dependency_readiness as _build_mutation_dependency_readiness,
)
from fdai.runtime.bootstrap_lifecycle import build_runtime_saga as _build_runtime_saga
from fdai.runtime.bootstrap_lifecycle import (
    runtime_positive_integer as _runtime_positive_integer,
)
from fdai.runtime.bootstrap_lifecycle import (
    semantic_router_config_from_env as _semantic_router_config_from_env,
)
from fdai.runtime.bootstrap_messaging import MessagingRuntime, build_messaging_runtime
from fdai.runtime.bootstrap_pantheon import (
    PantheonInitialization,
    PantheonInitializationResult,
    initialize_pantheon,
)
from fdai.runtime.bootstrap_plan import BootstrapPlan
from fdai.runtime.bootstrap_resources import RuntimeResources
from fdai.runtime.bootstrap_semantics import SemanticRuntime, build_semantic_runtime
from fdai.runtime.bootstrap_tasks import RuntimeTaskConfiguration
from fdai.runtime.catalog_ontology import project_catalog_ontology, sync_ontology_catalog
from fdai.runtime.configuration import (
    _attach_runtime_github_change_feed,
    _new_http_client,
    _resolve_catalog_root,
    _resolve_policies_root,
)
from fdai.runtime.continuous_operating_model import (
    build_continuous_operating_model_worker,
    project_initial_operating_model_from_env,
)
from fdai.runtime.control_loop import (
    EventBusDirectApiExecutionClient,
    _build_control_loop,
)
from fdai.runtime.dynamic_evidence import bind_dynamic_evidence_from_env
from fdai.runtime.human_assignment_reconciliation import AssignmentReconciliationWorker
from fdai.runtime.operating_model import project_operating_model_from_env
from fdai.runtime.providers import (
    _build_audit_store,
    _build_inventory_delta_projector,
    _build_operator_memory_store,
    _build_resource_lock,
)
from fdai.runtime.readiness import StartupReadinessRuntime, build_startup_readiness_runtime
from fdai.shared.contracts.models import ResponseOutcome
from fdai.shared.providers.state_store import StateStore

_LOGGER = logging.getLogger("fdai.startup")


@dataclass(frozen=True, slots=True)
class CoreRuntime:
    """Fully assembled active runtime consumed by health and task supervision."""

    container: Container
    messaging: MessagingRuntime
    control_loop: ControlLoop
    readiness: StartupReadinessRuntime
    runtime_settings: RuntimeSettingsService
    discovery_activation: DiscoveryActivationRuntime | None
    semantic: SemanticRuntime
    pantheon: PantheonInitializationResult
    assignment_reconciliation_worker: AssignmentReconciliationWorker | None
    effect_reconciliation_worker: Any
    effect_reconciliation_request_binding: EffectReconciliationRequestRuntimeBinding | None
    operational_readiness_handler: OperationalReadinessEventHandler | None
    continuous_operating_model_worker: Any
    incident_notification_replay_worker: IncidentNotificationReplayWorker
    environment: Mapping[str, str]
    diagnostic_event_ingest_bridge: DiagnosticEventIngestBridge | None = None

    def task_configuration(self, stop: asyncio.Event) -> RuntimeTaskConfiguration:
        """Project assembled bindings into the task-supervision contract."""

        return RuntimeTaskConfiguration(
            container=self.container,
            bus=self.messaging.bus,
            operational_bus=self.messaging.operational_bus,
            control_loop=self.control_loop,
            readiness=self.readiness,
            stop=stop,
            runtime_settings=self.runtime_settings,
            discovery_activation=self.discovery_activation,
            semantic_turn_binding=self.semantic.semantic_turn_binding,
            divergence_ledger=self.pantheon.divergence_ledger,
            pantheon_runtime=self.pantheon.runtime,
            pantheon_heartbeat=self.pantheon.heartbeat,
            agent_introspection_server=self.pantheon.agent_introspection_server,
            runtime_state_publisher=self.pantheon.runtime_state_publisher,
            t2_recovery_maintenance=self.pantheon.t2_recovery_maintenance,
            assignment_reconciliation_worker=self.assignment_reconciliation_worker,
            effect_reconciliation_worker=self.effect_reconciliation_worker,
            effect_reconciliation_request_binding=(self.effect_reconciliation_request_binding),
            continuous_operating_model_worker=self.continuous_operating_model_worker,
            rule_generation_binding=self.semantic.rule_generation_binding,
            rule_generation_reconciliation=self.semantic.rule_generation_reconciliation,
            case_history_retention_publisher=(self.pantheon.case_history_retention_publisher),
            environment=self.environment,
            read_investigation_binding=self.semantic.read_investigation_binding,
            operational_readiness_handler=self.operational_readiness_handler,
            incident_notification_replay_worker=self.incident_notification_replay_worker,
            diagnostic_event_ingest_bridge=self.diagnostic_event_ingest_bridge,
        )


async def build_core_runtime(
    *,
    container: Container,
    plan: BootstrapPlan,
    resources: RuntimeResources,
    identity: Any,
    environment: Mapping[str, str],
) -> CoreRuntime:
    """Assemble one active consumer runtime without starting supervised tasks."""

    resources.messaging = build_messaging_runtime(
        plan=plan,
        kafka=container.config.kafka,
        identity=identity,
    )
    messaging = resources.messaging
    diagnostic_event_ingest_bridge: DiagnosticEventIngestBridge | None = None
    if messaging.diagnostic_bus is not None:
        if plan.diagnostic_topic is None or not plan.diagnostic_metric_whitelist:
            raise RuntimeError("diagnostic messaging prerequisites are incomplete")
        diagnostic_event_ingest_bridge = DiagnosticEventIngestBridge(
            source_bus=messaging.diagnostic_bus,
            target_bus=messaging.bus,
            source_topic=plan.diagnostic_topic,
            target_topic=container.config.kafka.topic_events,
            consumer_group=environment.get(
                "FDAI_DIAGNOSTIC_CONSUMER_GROUP_ID",
                "fdai-diagnostic-normalizer",
            ).strip(),
            options=DiagnosticNormalizerOptions(
                metric_whitelist=plan.diagnostic_metric_whitelist,
            ),
        )
    if plan.requires_channel_http_client and resources.http_client is None:
        resources.http_client = _new_http_client()
    if plan.github_change_feed_enabled and resources.http_client is not None:
        container = _attach_runtime_github_change_feed(
            container,
            http_client=resources.http_client,
        )

    state_store: StateStore = _build_audit_store()
    operational_readiness_handler = build_operational_readiness_event_handler(
        posture=container.operational_readiness_posture,
        publisher=container.operational_readiness_report_publisher,
        feasibility_probes=container.feasibility_probes,
        event_validator=container.event_validator,
        state_store=state_store,
    )
    if operational_readiness_handler is None:
        _LOGGER.info(
            "operational_readiness_unavailable",
            extra={"reason": "posture_and_report_publisher_absent"},
        )
    else:
        _LOGGER.info("operational_readiness_ready")
    if plan.isolated_executor_authority_cutover:
        if messaging.auxiliary_bus is None:
            raise RuntimeError(
                "isolated Executor authority cutover requires the auxiliary EventBus"
            )
        resources.isolated_executor_client = EventBusDirectApiExecutionClient(
            event_bus=messaging.auxiliary_bus,
            audit_store=state_store,
            instance_id=environment.get("HOSTNAME", "fdai-core"),
        )
        await resources.isolated_executor_client.start()

    runtime_settings = RuntimeSettingsService(
        store=state_store,
        env=environment,
        durable=bool(environment.get("FDAI_STATE_STORE_DSN", "").strip()),
    )
    runtime_values = await runtime_settings.effective_values()
    assignment_worker: AssignmentReconciliationWorker | None = None
    if runtime_settings.durable:
        from fdai.core.human_assignment import AssignmentReconciler

        assignment_worker = AssignmentReconciliationWorker(
            reconciler=AssignmentReconciler(store=state_store),
            interval_seconds=_runtime_positive_integer(
                runtime_values,
                "human_access.reconciliation_interval_seconds",
            ),
        )
    logging.getLogger().setLevel(str(runtime_values["logging.level"]))
    incident_runtime = await build_incident_runtime(
        state_store=state_store,
        runtime_values=runtime_values,
        http_client=resources.http_client,
    )
    symptom_index = build_from_promoted(_resolve_catalog_root() / "chaos-scenarios")

    async def relay_response_outcome(outcome: ResponseOutcome) -> None:
        await messaging.bus.publish(
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
        state_store=state_store,
        environ=environment,
    )
    if container.graph_dynamic_simulation_request_provider is None:
        _LOGGER.info(
            "graph_dynamic_runtime_unavailable",
            extra={"reason": "graph_evidence_prerequisites_absent"},
        )
    effect_request_binding = _build_effect_reconciliation_request_binding(
        state_store=state_store,
        event_bus=messaging.bus,
        artifact_source=container.executed_action_reconciliation_artifact_source,
        observation_source=container.executed_action_observation_source,
        observation_verifier=container.reconciliation_observation_verifier,
        environment=environment,
    )
    if effect_request_binding is not None:
        _LOGGER.info("effect_reconciliation_request_producer_ready")
    else:
        _LOGGER.info(
            "effect_reconciliation_request_producer_unavailable",
            extra={"reason": "executed_action_sources_absent"},
        )
    runtime_saga = _build_runtime_saga(state_store)
    mutation_readiness = _build_mutation_dependency_readiness(
        saga=runtime_saga,
        rollback_executors=None,
    )
    control_loop = _build_control_loop(
        container,
        http_client=resources.http_client,
        stage_publisher=messaging.stage_publisher,
        audit_store=state_store,
        tool_receipt_observer=incident_runtime.observe_tool_receipt,
        symptom_index=symptom_index,
        identity=identity,
        execution_identities=_build_vertical_execution_identities(
            http_client=resources.http_client,
        ),
        direct_api_execution_port=resources.isolated_executor_client,
        response_outcome_sink=relay_response_outcome,
        effect_reconciliation_request_sink=(
            effect_request_binding.producer if effect_request_binding is not None else None
        ),
        human_access_enabled=runtime_values["human_access.enabled"] is True,
        mutation_dependency_readiness=mutation_readiness,
    )
    if control_loop.ontology_instance_store is not None:
        await sync_ontology_catalog(control_loop.ontology_instance_store)
        await incident_runtime.bind_projection(control_loop.ontology_instance_store)
    effect_worker = _build_effect_reconciliation_worker(
        state_store=state_store,
        event_bus=messaging.bus,
        artifact_resolver=container.reconciliation_artifact_resolver,
        observation_verifier=container.reconciliation_observation_verifier,
        ontology_instance_store=control_loop.ontology_instance_store,
        environment=environment,
    )
    if effect_worker is not None:
        _LOGGER.info("effect_reconciliation_ready")
    else:
        _LOGGER.info(
            "effect_reconciliation_unavailable",
            extra={"reason": "artifact_resolver_and_observation_verifier_absent"},
        )
    catalog_projection_result = await project_catalog_ontology(control_loop)
    operating_model_topic = environment.get("FDAI_OPERATING_MODEL_TOPIC", "").strip()
    operating_model_lock = _build_resource_lock(environment) if operating_model_topic else None
    if operating_model_lock is None:
        operating_model_result = await project_operating_model_from_env(
            store=control_loop.ontology_instance_store,
            object_types=container.ontology_object_types,
            link_types=container.ontology_link_types,
            status_store=state_store,
        )
    else:
        operating_model_result = await project_initial_operating_model_from_env(
            store=control_loop.ontology_instance_store,
            object_types=container.ontology_object_types,
            link_types=container.ontology_link_types,
            state_store=state_store,
            environment=environment,
            resource_lock=operating_model_lock,
        )
    continuous_operating_model_worker = build_continuous_operating_model_worker(
        bus=messaging.operational_bus,
        store=control_loop.ontology_instance_store,
        object_types=container.ontology_object_types,
        link_types=container.ontology_link_types,
        state_store=state_store,
        environment=environment,
        resource_lock=operating_model_lock,
    )
    semantic = await build_semantic_runtime(
        container=container,
        control_loop=control_loop,
        state_store=state_store,
        event_bus=messaging.bus,
        operational_event_bus=messaging.operational_bus,
        runtime_saga=runtime_saga,
        identity=identity,
        http_client=resources.http_client,
        stage_topic=plan.stage_topic,
        environment=environment,
    )
    _LOGGER.info(
        "control_loop_ready",
        extra={
            "topic": container.config.kafka.topic_events,
            "stage_topic": plan.stage_topic,
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
    readiness = build_startup_readiness_runtime(
        state_store=state_store,
        event_bus=messaging.operational_bus,
        transition_event_bus=messaging.bus,
        event_validator=container.event_validator,
        identity=identity,
        embedding_model=container.require_llm_bindings().embedding_model,
        policy_compile_probe=OpaCompileStartupProbe(
            probe_id="policy.compile",
            policies_root=_resolve_policies_root(_resolve_catalog_root()),
        ),
        cross_check_models=container.require_llm_bindings().cross_check_models,
        environment=environment,
        registered_specs=(*container.startup_probe_specs, *semantic.readiness_specs),
        registered_probes=(*container.startup_probes, *semantic.readiness_probes),
    )
    startup_report = await readiness.evaluate()
    _LOGGER.info(
        "startup_readiness_evaluated",
        extra={
            "decision": startup_report.decision.value,
            "probe_count": len(startup_report.results),
            "missing_count": len(startup_report.missing_probe_ids),
            "stale_count": len(startup_report.stale_probe_ids),
        },
    )
    discovery_activation = build_discovery_activation_runtime(
        state_store=state_store,
        runtime_settings=runtime_settings,
        startup_readiness=readiness.state,
    )
    resources.pantheon = await initialize_pantheon(
        PantheonInitialization(
            container=container,
            http_client=resources.http_client,
            identity=identity,
            bus=messaging.bus,
            incident_audit_store=state_store,
            startup_readiness=readiness.state,
            runtime_saga=runtime_saga,
            runtime_values=runtime_values,
            runtime_settings=runtime_settings,
            discovery_activation=discovery_activation,
            control_loop=control_loop,
            rule_generation_reconciliation=semantic.rule_generation_reconciliation,
            rule_generation_binding=semantic.rule_generation_binding,
            open_incident_candidate=incident_runtime.open_incident_candidate,
            read_investigation_hook=semantic.read_investigation_hook,
            runtime_symptom_index=symptom_index,
            stage_topic=plan.stage_topic,
            environment=environment,
            build_runtime_workload_identity=_build_runtime_workload_identity,
            build_operator_memory_store=_build_operator_memory_store,
            build_inventory_delta_projector=_build_inventory_delta_projector,
            runtime_positive_integer=_runtime_positive_integer,
            build_mutation_dependency_readiness=_build_mutation_dependency_readiness,
            semantic_router_config_from_env=_semantic_router_config_from_env,
        )
    )
    return CoreRuntime(
        container=container,
        messaging=messaging,
        control_loop=control_loop,
        readiness=readiness,
        runtime_settings=runtime_settings,
        discovery_activation=resources.pantheon.discovery_activation,
        semantic=semantic,
        pantheon=resources.pantheon,
        assignment_reconciliation_worker=assignment_worker,
        effect_reconciliation_worker=effect_worker,
        effect_reconciliation_request_binding=effect_request_binding,
        operational_readiness_handler=operational_readiness_handler,
        continuous_operating_model_worker=continuous_operating_model_worker,
        incident_notification_replay_worker=incident_runtime.notification_replay_worker,
        environment=environment,
        diagnostic_event_ingest_bridge=diagnostic_event_ingest_bridge,
    )


__all__ = [
    "CoreRuntime",
    "build_core_runtime",
]
