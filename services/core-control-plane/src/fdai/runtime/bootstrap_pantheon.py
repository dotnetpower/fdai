"""Pantheon runtime initialization for the headless control-plane process."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import httpx

from fdai.agents import (
    Norns,
    PantheonRuntime,
    Saga,
    SemanticRouterConfig,
    ShadowDivergenceLedger,
    StateStoreActionRunStore,
)
from fdai.agents.vidar import RollbackExecutor
from fdai.composition import Container
from fdai.composition.cost_governance_activation import build_cost_runtime_bindings
from fdai.core.capacity import CapacityGraduationController
from fdai.core.chaos.coverage import ScenarioCoverageAggregator
from fdai.core.control_loop import ControlLoop
from fdai.core.executor import MutationDependencyReadiness
from fdai.core.impact_analysis import ChangeAssessmentService, ImpactAnalyzer
from fdai.core.learning import PostTurnProposalModel, RuleHintSubmitter
from fdai.core.operational_context import OperationalContextMaterializer
from fdai.core.operational_planning import (
    AssuranceTwinPlanningSimulator,
    ConstitutionalPlanningConstraintEvaluator,
    ProcessPlanningRecorder,
    SpecialistPlanningCoordinator,
    operational_planning_capability_status,
)
from fdai.core.readiness import AuthorityCeiling
from fdai.delivery.agent_activity import (
    AgentRuntimeStatePublisher,
    EventBusPantheonActivityObserver,
    runtime_agent_state_snapshot,
)
from fdai.delivery.evidence_conflict import StateStoreEvidenceConflictProjection
from fdai.delivery.kinetic_proposal import StateStoreKineticActionProposalStore
from fdai.delivery.persistence import (
    PostgresCaseHistoryMetadataStore,
    PostgresCaseHistoryMetadataStoreConfig,
    StateStoreSemanticFeedbackCandidateStore,
)
from fdai.delivery.prospective_lineage import (
    OperationalPlanningProspectiveFinalizer,
    StateStoreProspectiveLineageMaterializer,
)
from fdai.delivery.runtime_settings import RuntimeSettingsService
from fdai.rule_catalog.schema.capacity_graduation_policy import (
    load_capacity_graduation_policy,
)
from fdai.runtime.bootstrap_bindings import RuleGenerationRuntimeBinding
from fdai.runtime.case_history import (
    CaseHistoryRetentionTickPublisher,
    build_case_history_runtime,
)
from fdai.runtime.configuration import _model_endpoint_resolver
from fdai.runtime.discovery_activation import DiscoveryActivationRuntime
from fdai.runtime.forecast_learning import build_forecast_learning_runtime
from fdai.runtime.operational_catalog_review import build_operational_catalog_review_bindings
from fdai.runtime.post_turn_review import (
    build_azure_post_turn_models,
    build_post_turn_review_runtime,
    post_turn_review_dsn,
)
from fdai.runtime.providers import _build_resource_lock
from fdai.runtime.readiness import RuntimeReadinessState
from fdai.runtime.rule_generation_documents import RuleGenerationReconciliation
from fdai.runtime.t2_route_registry import T2RouteRegistry, bind_t2_route_selector
from fdai.shared.config.models import LlmMode
from fdai.shared.config.runtime_flags import pantheon_start_enabled
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.state_store import StateStore
from fdai.shared.providers.workload_identity import WorkloadIdentity

_LOGGER = logging.getLogger("fdai.startup")


@dataclass(frozen=True, slots=True)
class PantheonInitialization:
    """Inputs required to bind the optional Pantheon overlay."""

    container: Container
    http_client: httpx.AsyncClient | None
    identity: WorkloadIdentity | None
    bus: EventBus
    incident_audit_store: StateStore
    startup_readiness: RuntimeReadinessState
    runtime_saga: Saga
    runtime_values: dict[str, object]
    runtime_settings: RuntimeSettingsService
    discovery_activation: DiscoveryActivationRuntime
    control_loop: ControlLoop
    rule_generation_reconciliation: RuleGenerationReconciliation | None
    rule_generation_binding: RuleGenerationRuntimeBinding
    open_incident_candidate: Callable[[dict[str, Any]], Awaitable[bool]]
    read_investigation_hook: Any
    runtime_symptom_index: Any
    stage_topic: str
    environment: Mapping[str, str]
    build_runtime_workload_identity: Callable[..., WorkloadIdentity]
    build_operator_memory_store: Callable[[], Any]
    build_inventory_delta_projector: Callable[[], Any]
    runtime_positive_integer: Callable[[dict[str, object], str], int]
    build_mutation_dependency_readiness: Callable[..., MutationDependencyReadiness]
    semantic_router_config_from_env: Callable[[], SemanticRouterConfig]


@dataclass(frozen=True, slots=True)
class PantheonInitializationResult:
    """Pantheon resources retained by task supervision and ordered cleanup."""

    runtime: PantheonRuntime | None = None
    agent_introspection_server: Any = None
    runtime_state_publisher: AgentRuntimeStatePublisher | None = None
    heartbeat: float | None = None
    divergence_ledger: ShadowDivergenceLedger | None = None
    case_history_retention_publisher: CaseHistoryRetentionTickPublisher | None = None
    t2_recovery_maintenance: Any = None
    discovery_activation: DiscoveryActivationRuntime | None = None


def _pantheon_enforce_enabled(
    environment: Mapping[str, str],
    startup_readiness: RuntimeReadinessState,
) -> bool:
    requested = environment.get("FDAI_PANTHEON_ENFORCE", "").lower() in ("1", "true")
    return requested and (
        startup_readiness.authority_ceiling("autonomous-action") is AuthorityCeiling.DEPLOYMENT
    )


def _approver_authorizer_from_env(
    environment: Mapping[str, str],
) -> Callable[[str, str], bool] | None:
    """Load an explicit principal-to-ActionType approval policy."""

    raw = environment.get("FDAI_PANTHEON_APPROVER_ACTIONS_JSON", "").strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("FDAI_PANTHEON_APPROVER_ACTIONS_JSON MUST be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("FDAI_PANTHEON_APPROVER_ACTIONS_JSON MUST be an object")
    policy: dict[str, frozenset[str]] = {}
    for principal, actions in parsed.items():
        if (
            not isinstance(principal, str)
            or not principal.strip()
            or not isinstance(actions, list)
            or not actions
            or any(not isinstance(action, str) or not action.strip() for action in actions)
        ):
            raise ValueError(
                "FDAI_PANTHEON_APPROVER_ACTIONS_JSON entries MUST map principals "
                "to non-empty ActionType arrays"
            )
        normalized = principal.strip().casefold()
        if normalized in policy:
            raise ValueError("FDAI_PANTHEON_APPROVER_ACTIONS_JSON principals MUST be unique")
        policy[normalized] = frozenset(action.strip() for action in actions)

    return lambda principal, action_type: (
        action_type
        in policy.get(
            principal.strip().casefold(),
            frozenset(),
        )
    )


async def initialize_pantheon(
    config: PantheonInitialization,
) -> PantheonInitializationResult:
    """Bind Pantheon resources without starting their supervised tasks."""

    if not pantheon_start_enabled(config.environment):
        return PantheonInitializationResult()

    cost_runtime = await build_cost_runtime_bindings(config.environment)
    _LOGGER.info(
        "cost_governance_runtime_binding",
        extra={
            "enabled": cost_runtime.package_enabled,
            "advisory_bound": cost_runtime.advisory_provider is not None,
            "activation_reader_bound": cost_runtime.activation_reader is not None,
            "restored_samples": len(cost_runtime.initial_samples),
        },
    )
    pantheon_enforce = _pantheon_enforce_enabled(
        config.environment,
        config.startup_readiness,
    )
    disabled_raw = config.environment.get("FDAI_PANTHEON_DISABLED_AGENTS", "").strip()
    disabled_agents = (
        frozenset(name.strip() for name in disabled_raw.split(",") if name.strip())
        if disabled_raw
        else None
    )
    divergence_ledger = ShadowDivergenceLedger()
    t2_proposer = config.container.require_llm_bindings().require_t2_proposer()
    t2_route_registry = T2RouteRegistry(store=config.incident_audit_store)
    t2_route_selector_bound = bind_t2_route_selector(
        proposer=t2_proposer,
        registry=t2_route_registry,
    )
    post_turn_models: tuple[PostTurnProposalModel, ...] = ()
    if config.container.config.llm.mode == LlmMode.AZURE:
        if config.http_client is None or config.identity is None:
            raise RuntimeError(
                "Azure post-turn review requires HTTP and workload identity bindings"
            )
        resolved_models_path = config.container.config.llm.resolved_models_path
        if resolved_models_path is None:
            raise RuntimeError("Azure post-turn review requires resolved model configuration")
        post_turn_models = build_azure_post_turn_models(
            repo_root=Path(__file__).resolve().parents[5],
            resolved_models_path=resolved_models_path,
            endpoint=config.environment["FDAI_LLM_ENDPOINT"],
            endpoint_resolver=_model_endpoint_resolver(
                config.environment["FDAI_LLM_ENDPOINT"],
                config.environment.get("FDAI_MODEL_ENDPOINTS_JSON"),
            ),
            identity=config.identity,
            http_client=config.http_client,
        )
    post_turn_review = build_post_turn_review_runtime(
        state_store=config.incident_audit_store,
        operator_memory=config.build_operator_memory_store(),
        models=post_turn_models,
        dsn=post_turn_review_dsn(),
    )
    case_history_container_url = (
        config.environment.get("FDAI_CASE_HISTORY_CONTAINER_URL", "").strip() or None
    )
    case_history_identity = None
    if case_history_container_url is not None:
        if config.http_client is None:
            raise RuntimeError("case history storage requires an HTTP client")
        case_history_identity = config.build_runtime_workload_identity(
            config.http_client,
            client_id_env="FDAI_CASE_HISTORY_MI_CLIENT_ID",
            require_client_id=True,
        )
    state_store_dsn = config.environment.get("FDAI_STATE_STORE_DSN")
    case_history_runtime = build_case_history_runtime(
        container_url=case_history_container_url,
        state_store=config.incident_audit_store,
        identity=case_history_identity,
        http_client=config.http_client,
        dsn=state_store_dsn,
        relational_read_authority=(
            config.environment.get("FDAI_CASE_HISTORY_RELATIONAL_READ", "").strip() == "1"
        ),
        models=post_turn_models,
    )
    if case_history_runtime is not None and state_store_dsn and state_store_dsn.strip():
        relational_metadata = PostgresCaseHistoryMetadataStore(
            config=PostgresCaseHistoryMetadataStoreConfig(dsn=state_store_dsn)
        )
        await relational_metadata.verify_schema()
        if config.environment.get("FDAI_CASE_HISTORY_RELATIONAL_READ", "").strip() == "1":
            await relational_metadata.verify_read_cutover()
    forecast_learning_runtime = build_forecast_learning_runtime(
        dsn=state_store_dsn,
        targets_json=config.environment.get("FDAI_FORECAST_TARGETS_JSON"),
        metric_provider=config.container.metric_provider,
    )
    if forecast_learning_runtime is not None:
        await forecast_learning_runtime.store.verify_schema()
    case_history_retention_publisher = None
    if case_history_runtime is not None:
        case_history_retention_publisher = CaseHistoryRetentionTickPublisher(
            bus=config.bus,
            topic=config.container.config.kafka.topic_events,
            interval_seconds=config.runtime_positive_integer(
                config.runtime_values,
                "case_history.retention_tick_seconds",
            ),
            runtime_settings=config.runtime_settings,
        )
    case_retention_days = config.runtime_positive_integer(
        config.runtime_values,
        "case_history.retention_days",
    )
    case_deletion_days = config.runtime_positive_integer(
        config.runtime_values,
        "case_history.deletion_days",
    )
    operational_context_materializer = (
        OperationalContextMaterializer(
            store=config.control_loop.ontology_instance_store,
            require_decision_evidence=True,
            catalog_versions=(
                {"ontology": config.control_loop.ontology_release.digest}
                if config.control_loop.ontology_release is not None
                else None
            ),
        )
        if config.control_loop.ontology_instance_store is not None
        else None
    )
    ontology_release = config.control_loop.ontology_release
    process_store = config.control_loop.process_runtime_store
    effect_model_reader = config.container.effect_model_reader
    causal_evidence_verifier = config.container.effect_model_causal_evidence_verifier
    operational_planner = None
    planning_status = operational_planning_capability_status(
        ontology_release_available=ontology_release is not None,
        operational_context_available=operational_context_materializer is not None,
        process_store_available=process_store is not None,
        effect_model_reader_available=effect_model_reader is not None,
        causal_verifier_available=causal_evidence_verifier is not None,
    )
    _LOGGER.info(
        "operational_planning_capability",
        extra={"capability": planning_status.to_mapping()},
    )
    if planning_status.can_plan:
        if operational_context_materializer is None:
            raise RuntimeError("planning status requires operational context")
        if ontology_release is None:
            raise RuntimeError("planning status requires an ontology release")
        if process_store is None:
            raise RuntimeError("planning status requires a Process store")
        if effect_model_reader is None:
            raise RuntimeError("planning status requires an effect model reader")
        if causal_evidence_verifier is None:
            raise RuntimeError("planning status requires a causal evidence verifier")
        operational_planner = SpecialistPlanningCoordinator(
            logic_release_digest=ontology_release.digest,
            constraint_evaluator=ConstitutionalPlanningConstraintEvaluator(),
            simulator=AssuranceTwinPlanningSimulator(
                model_reader=effect_model_reader,
                causal_evidence_verifier=causal_evidence_verifier,
                clock=lambda: datetime.now(tz=UTC),
            ),
            recorder=ProcessPlanningRecorder(store=process_store),
        )
    prospective_lineage_finalizer = None
    prospective_lineage_materializer = None
    if ontology_release is not None and config.control_loop.ontology_instance_store is not None:
        proposal_store = StateStoreKineticActionProposalStore(store=config.incident_audit_store)
        prospective_lineage_finalizer = OperationalPlanningProspectiveFinalizer(
            proposal_store=proposal_store,
            ontology_store=config.control_loop.ontology_instance_store,
            ontology_release=ontology_release,
            action_types=config.control_loop.action_types,
        )
        prospective_lineage_materializer = StateStoreProspectiveLineageMaterializer(
            state_store=config.incident_audit_store,
            proposal_store=proposal_store,
            ontology_store=config.control_loop.ontology_instance_store,
        )
    thor_mutation_bound = pantheon_enforce and t2_route_selector_bound
    rollback_executors: dict[str, RollbackExecutor] | None = (
        {"state_forward_only": t2_route_registry.rollback} if thor_mutation_bound else None
    )
    execution_resource_lock = _build_resource_lock(config.environment) if pantheon_enforce else None
    thor_safety_readiness = config.build_mutation_dependency_readiness(
        saga=config.runtime_saga,
        rollback_executors=rollback_executors,
    )
    thor_safety_readiness.require_for_mode(enforce=thor_mutation_bound)
    _LOGGER.info(
        "thor_safety_dependency_readiness",
        extra={
            "mutation_ready": thor_safety_readiness.mutation_ready,
            "saga_audit_durable": thor_safety_readiness.saga_audit_durable,
            "vidar_recovery_contracts": sorted(thor_safety_readiness.vidar_recovery_contracts),
        },
    )
    heimdall_action_observation_hook = None
    observation_collector = config.container.executed_action_observation_collector
    if observation_collector is not None:
        observation_verifier = config.container.reconciliation_observation_verifier
        if observation_verifier is None:  # pragma: no cover - Container invariant
            raise RuntimeError("Heimdall action observation requires a verifier")
        from fdai.delivery.executed_action_observation import (
            HeimdallExecutedActionObservationHandler,
        )
        from fdai.delivery.reconciliation_artifacts import (
            StateStoreExecutedActionArtifactStore,
        )
        from fdai.delivery.reconciliation_observations import (
            StateStoreExecutedActionObservationStore,
        )

        heimdall_action_observation_hook = HeimdallExecutedActionObservationHandler(
            artifacts=StateStoreExecutedActionArtifactStore(store=config.incident_audit_store),
            collector=observation_collector,
            observations=StateStoreExecutedActionObservationStore(
                store=config.incident_audit_store,
                verifier=observation_verifier,
            ),
        ).handle
    pantheon_runtime = PantheonRuntime.build(
        provider=config.bus,
        raw_event_topic=config.container.config.kafka.topic_events,
        consumer_group_prefix=config.environment.get(
            "FDAI_PANTHEON_CONSUMER_GROUP_PREFIX",
            "fdai-pantheon",
        ).strip(),
        enforce=pantheon_enforce,
        thor_executor=(t2_route_registry.execute if thor_mutation_bound else None),
        thor_state_store=(
            StateStoreActionRunStore(config.incident_audit_store) if thor_mutation_bound else None
        ),
        rollback_executors=rollback_executors,
        execution_resource_lock=execution_resource_lock,
        approver_authorizer=_approver_authorizer_from_env(config.environment),
        saga=config.runtime_saga,
        muninn_state_store=config.incident_audit_store,
        evidence_conflict_sink=StateStoreEvidenceConflictProjection(config.incident_audit_store),
        prospective_lineage_finalizer=prospective_lineage_finalizer,
        prospective_lineage_materializer=prospective_lineage_materializer,
        capacity_graduation_controller=CapacityGraduationController(
            load_capacity_graduation_policy(
                Path(__file__).resolve().parents[5]
                / "rule-catalog"
                / "capacity-graduation-policy.yaml"
            )
        ),
        rule_generation_workers=(
            config.rule_generation_reconciliation.workers
            if config.rule_generation_reconciliation is not None
            else None
        ),
        rule_generation_activation_binder=config.rule_generation_binding.activation_binder,
        rule_generation_state_store=config.incident_audit_store,
        semantic_feedback_store=StateStoreSemanticFeedbackCandidateStore(
            config.incident_audit_store
        ),
        disabled_agents=disabled_agents,
        divergence=divergence_ledger,
        incident_candidate_hook=config.open_incident_candidate,
        heimdall_rate_threshold=config.runtime_positive_integer(
            config.runtime_values,
            "incident.repeat_threshold",
        ),
        heimdall_rate_window=config.runtime_positive_integer(
            config.runtime_values,
            "incident.repeat_window_seconds",
        ),
        heimdall_security_high_threshold=config.runtime_positive_integer(
            config.runtime_values,
            "incident.security_high_threshold",
        ),
        heimdall_security_window_events=config.runtime_positive_integer(
            config.runtime_values,
            "incident.security_window_events",
        ),
        heimdall_alert_rate_per_hour=config.runtime_positive_integer(
            config.runtime_values,
            "incident.alert_rate_per_hour",
        ),
        read_investigation_hook=config.read_investigation_hook,
        heimdall_action_observation_hook=heimdall_action_observation_hook,
        discovery_projector=config.build_inventory_delta_projector(),
        scenario_coverage_aggregator=ScenarioCoverageAggregator(index=config.runtime_symptom_index),
        post_turn_review=post_turn_review.coordinator,
        case_history_materializer=(
            case_history_runtime.materializer if case_history_runtime is not None else None
        ),
        catalog_review=build_operational_catalog_review_bindings(
            control_loop=config.control_loop,
            http_client=config.http_client,
            environment=config.environment,
            catalog_root=Path(__file__).resolve().parents[5] / "rule-catalog",
            policies_root=Path(__file__).resolve().parents[5] / "policies",
        ),
        case_history_analyzer=(
            case_history_runtime.analyzer if case_history_runtime is not None else None
        ),
        operational_context_materializer=operational_context_materializer,
        operational_planner=operational_planner,
        change_assessor=(
            ChangeAssessmentService(
                analyzer=ImpactAnalyzer(store=config.control_loop.ontology_instance_store)
            )
            if config.control_loop.ontology_instance_store is not None
            else None
        ),
        case_history_retention=(
            case_history_runtime.retention if case_history_runtime is not None else None
        ),
        case_retention_days=case_retention_days,
        case_deletion_days=case_deletion_days,
        forecast_evaluator=(
            forecast_learning_runtime.evaluator if forecast_learning_runtime is not None else None
        ),
        forecast_closer=(
            forecast_learning_runtime.closer if forecast_learning_runtime is not None else None
        ),
        forecast_store=(
            forecast_learning_runtime.store if forecast_learning_runtime is not None else None
        ),
        handler_observer=EventBusPantheonActivityObserver(
            event_bus=config.bus,
            topic=config.stage_topic,
        ),
        action_types=config.control_loop.action_types,
        conversation_semantic_judgment=(
            config.container.llm_bindings.conversation_semantic_judgment_factory(
                asyncio.get_running_loop()
            )
            if config.container.llm_bindings is not None
            and config.container.llm_bindings.conversation_semantic_judgment_factory is not None
            else None
        ),
        conversation_embedding_model=(
            config.container.llm_bindings.embedding_model
            if config.container.llm_bindings is not None
            else None
        ),
        conversation_t2_synthesizer=(
            config.container.llm_bindings.conversation_t2_synthesizer
            if config.container.llm_bindings is not None
            else None
        ),
        conversation_metering=(
            config.container.llm_bindings.conversation_metering
            if config.container.llm_bindings is not None
            else None
        ),
        conversation_pricing=(
            config.container.llm_bindings.conversation_pricing
            if config.container.llm_bindings is not None
            else None
        ),
        conversation_t2_model_key=(
            config.container.llm_bindings.conversation_t2_model_key
            if config.container.llm_bindings is not None
            else ""
        ),
        semantic_router_config=config.semantic_router_config_from_env(),
        cost_runtime=cost_runtime,
    )
    thor_agent = pantheon_runtime.agents.get("Thor")
    if thor_agent is None:  # pragma: no cover - fixed Pantheon invariant
        raise RuntimeError("Pantheon runtime is missing Thor")
    cast(Any, thor_agent).set_shadow_required(
        lambda: (
            not _pantheon_enforce_enabled(
                config.environment,
                config.startup_readiness,
            )
        )
    )
    from fdai.runtime.t2_recovery import T2RecoveryMaintenance, bind_t2_recovery_observer

    recovery_observer = bind_t2_recovery_observer(
        proposer=t2_proposer,
        store=config.incident_audit_store,
        ingress=pantheon_runtime.ingest_raw_event,
    )
    t2_recovery_maintenance: T2RecoveryMaintenance | None = None
    if recovery_observer is not None:
        legacy_reader = None
        legacy_state_store_dsn = (state_store_dsn or "").strip()
        if legacy_state_store_dsn:
            from fdai.delivery.persistence.postgres import PostgresStateStoreConfig
            from fdai.delivery.persistence.postgres_t2_recovery import (
                PostgresT2RecoveryLegacyReader,
            )

            legacy_reader = PostgresT2RecoveryLegacyReader(
                config=PostgresStateStoreConfig(dsn=legacy_state_store_dsn)
            )
        t2_recovery_maintenance = T2RecoveryMaintenance(
            observer=recovery_observer,
            legacy_reader=legacy_reader,
        )
    from fdai.delivery.agent_introspection_bus import (
        EventBusAgentIntrospectionServer,
        agent_introspection_server_group_id,
    )

    agent_introspection_server = EventBusAgentIntrospectionServer(
        event_bus=config.bus,
        runtime=pantheon_runtime,
        group_id=agent_introspection_server_group_id(
            local_process=config.environment.get("FDAI_RUNTIME_LOCAL_AZURE_CLI", "").strip() == "1"
        ),
    )
    runtime_state_publisher = AgentRuntimeStatePublisher(
        event_bus=config.bus,
        snapshot_factory=lambda: runtime_agent_state_snapshot(pantheon_runtime.health()),
        topic=config.stage_topic,
    )
    norns = pantheon_runtime.agents.get("Norns")
    discovery_activation = None
    if norns is not None:
        norns_agent = cast(Norns, norns)
        post_turn_review.bind_rule_hints(cast(RuleHintSubmitter, norns))
        norns_agent.bind_candidate_publication_gate(config.discovery_activation.is_enabled)
        config.discovery_activation.bind_shadow_decision_count(
            lambda: sum(pantheon_runtime.shadow_decisions.values())
        )
        discovery_report = await config.discovery_activation.evaluate()
        discovery_activation = config.discovery_activation
        _LOGGER.info(
            "discovery_activation_evaluated",
            extra={
                "decision": discovery_report.decision.value,
                "reason_codes": [reason.value for reason in discovery_report.reason_codes],
            },
        )
    pantheon_heartbeat = _pantheon_heartbeat(config.environment)
    _LOGGER.info(
        "pantheon_ready",
        extra={
            "agents": len(pantheon_runtime.agents),
            "subscriptions": pantheon_runtime.subscription_count,
            "enforce": pantheon_enforce,
            "heartbeat_s": pantheon_heartbeat,
        },
    )
    return PantheonInitializationResult(
        runtime=pantheon_runtime,
        agent_introspection_server=agent_introspection_server,
        runtime_state_publisher=runtime_state_publisher,
        heartbeat=pantheon_heartbeat,
        divergence_ledger=divergence_ledger,
        case_history_retention_publisher=case_history_retention_publisher,
        t2_recovery_maintenance=t2_recovery_maintenance,
        discovery_activation=discovery_activation,
    )


def _pantheon_heartbeat(environment: Mapping[str, str]) -> float | None:
    raw = environment.get("FDAI_PANTHEON_HEARTBEAT_SECONDS", "").strip()
    if not raw:
        return None
    try:
        heartbeat = float(raw)
    except ValueError as exc:
        raise RuntimeError(f"FDAI_PANTHEON_HEARTBEAT_SECONDS={raw!r} is not a float") from exc
    if heartbeat <= 0:
        raise RuntimeError(f"FDAI_PANTHEON_HEARTBEAT_SECONDS MUST be > 0; got {heartbeat}")
    return heartbeat


__all__ = [
    "PantheonInitialization",
    "PantheonInitializationResult",
    "initialize_pantheon",
]
