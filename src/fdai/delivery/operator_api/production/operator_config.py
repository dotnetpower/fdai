"""Final production Operator API configuration assembly."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fdai.core.execution_authorization import AccessGrantRequestService
from fdai.core.human_assignment import AssignmentCaseService, HandoverGoalService
from fdai.core.rbac.access_request import AccessRequestService
from fdai.core.rbac.kill_switch_command import KillSwitchCommandService
from fdai.delivery.catalog_search import load_shipped_catalog_reference_sources
from fdai.delivery.configuration_review_store import (
    StateStoreConfigurationReviewCampaignStore,
)
from fdai.delivery.handover_events import EventBusHandoverAvailabilityPublisher
from fdai.delivery.ingestion_gateway.chat_evidence import UploaderDocumentEvidenceResolver
from fdai.delivery.operator_api.app.catalog_reference import (
    load_best_practice_reference,
    load_mcsb_reference,
)
from fdai.delivery.operator_api.main import OperatorApiConfig
from fdai.delivery.operator_api.production import env_contract as _env
from fdai.delivery.operator_api.production.config import _parse_positive_int
from fdai.delivery.operator_api.production.data_sources import build_production_data_sources
from fdai.delivery.operator_api.production.panels import build_production_panels
from fdai.delivery.operator_api.routes.arb_status import ArchitectureReviewStatusPanel
from fdai.delivery.operator_api.routes.configuration_baselines import (
    ConfigurationBaselinesPanel,
)
from fdai.delivery.persistence.postgres_document_ingestion import (
    PostgresDocumentMetadataStore,
    PostgresDocumentMetadataStoreConfig,
)
from fdai.delivery.persistence.postgres_inventory_snapshot import (
    PostgresInventoryGraphProvider,
    PostgresInventorySnapshotStoreConfig,
)
from fdai.delivery.persistence.postgres_task_worker import (
    PostgresTaskWorkerStore,
    PostgresTaskWorkerStoreConfig,
)

_AsyncCallback = Callable[[], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class ProductionOperatorConfigInputs:
    """Inputs already constructed by the production composition root."""

    env: Mapping[str, str]
    repo_root: Path
    read_model: Any
    state_store: Any
    cors_origins: tuple[str, ...]
    object_types: Any
    link_types: Any
    action_types: Any
    ontology_function_types: Any
    inventory_semantic_resolver: Any
    catalog_semantic_index: Any
    scope_source: Any
    log_query_provider: Any
    reporting: Any
    process_views: Any
    workflow_authoring: Any
    workflow_execution: Any
    stewardship_map: Any
    stewardship_startup_callbacks: tuple[_AsyncCallback, ...]
    user_context_group: Any
    model_settings: Any
    runtime_settings: Any
    python_tasks: Any
    chat: Any
    metering_sink: Any
    skill_runtime: Any
    skill_sources: Any
    knowledge_context: Any
    read_investigation: Any
    busy_input_runtime: Any
    conversation_delivery_store: Any
    chat_web_search: Any
    assurance_ledger: Any
    assurance_policy_runtime: Any
    assurance_submitter: Any
    runtime: Any
    onboarding: Any
    identity: Any
    shutdown_callbacks: tuple[_AsyncCallback, ...]


def build_production_operator_config(
    inputs: ProductionOperatorConfigInputs,
) -> OperatorApiConfig:
    """Assemble the final route configuration from production wiring bundles."""
    catalog_reference_sources = load_shipped_catalog_reference_sources(repo_root=inputs.repo_root)

    read_investigation = inputs.read_investigation
    runtime = inputs.runtime
    user_context = inputs.user_context_group.routes
    configuration_review = read_investigation.configuration_review
    identity = inputs.identity
    return OperatorApiConfig(
        dev_mode=False,
        cors_allow_origins=inputs.cors_origins,
        ontology_object_types=inputs.object_types,
        ontology_link_types=inputs.link_types,
        ontology_action_types=inputs.action_types,
        ontology_function_types=inputs.ontology_function_types,
        operating_model_status_reader=inputs.state_store,
        inventory_graph_provider=PostgresInventoryGraphProvider(
            config=PostgresInventorySnapshotStoreConfig(
                dsn=inputs.read_model._config.dsn,
                freshness_budget_seconds=_parse_positive_int(
                    inputs.env,
                    _env.INVENTORY_FRESHNESS_ENV,
                    86_400,
                ),
                statement_timeout_ms=inputs.read_model._config.statement_timeout_ms,
                connect_timeout_s=inputs.read_model._config.connect_timeout_s,
            )
        ),
        inventory_semantic_resolver=inputs.inventory_semantic_resolver,
        inventory_activity_provider=read_investigation.inventory_activity_provider,
        subscription_health_provider=read_investigation.subscription_health_provider,
        detection_readiness_reader=inputs.state_store,
        execution_access_grants=AccessGrantRequestService(store=inputs.state_store),
        t2_recovery_reader=inputs.state_store,
        best_practice_controls=load_best_practice_reference(inputs.repo_root),
        mcsb_catalogs=load_mcsb_reference(inputs.repo_root),
        rule_catalog_rules=catalog_reference_sources.rules,
        rule_catalog_policies_root=inputs.repo_root / "policies",
        rule_catalog_remediation_root=inputs.repo_root / "rule-catalog" / "remediation",
        rule_catalog_semantic_index=inputs.catalog_semantic_index,
        scope_source=inputs.scope_source,
        log_query_provider=inputs.log_query_provider,
        reporting=inputs.reporting,
        process_views=inputs.process_views,
        workflow_authoring=inputs.workflow_authoring,
        workflow_execution=inputs.workflow_execution,
        workflow_definitions=inputs.user_context_group.workflow_definitions,
        stewardship_map=inputs.stewardship_map,
        stewardship_health_reader=inputs.state_store,
        user_context=user_context,
        model_settings=inputs.model_settings,
        runtime_settings=inputs.runtime_settings,
        python_tasks=inputs.python_tasks,
        chat=inputs.chat,
        llm_usage_reader=inputs.metering_sink,
        chat_document_evidence=UploaderDocumentEvidenceResolver(
            metadata=PostgresDocumentMetadataStore(
                config=PostgresDocumentMetadataStoreConfig(
                    dsn=inputs.read_model._config.dsn,
                    statement_timeout_ms=inputs.read_model._config.statement_timeout_ms,
                    connect_timeout_s=inputs.read_model._config.connect_timeout_s,
                )
            )
        ),
        chat_agent_delegate=read_investigation.chat_agent_delegate,
        skill_disclosure=inputs.skill_runtime.disclosure,
        skill_sources=inputs.skill_sources.routes,
        knowledge_context=inputs.knowledge_context,
        configuration_drift_context=read_investigation.configuration_drift_context,
        configuration_review_runtime=(
            configuration_review.runtime if configuration_review is not None else None
        ),
        automation_blueprint_review=(
            configuration_review.blueprints if configuration_review is not None else None
        ),
        busy_input_runtime=inputs.busy_input_runtime,
        conversation_delivery_store=inputs.conversation_delivery_store,
        chat_web_search=inputs.chat_web_search,
        chat_probe_interval_seconds=_parse_positive_int(
            inputs.env,
            "FDAI_NARRATOR_PROBE_INTERVAL_SECONDS",
            300,
        ),
        conversation_history_store=inputs.user_context_group.conversation_history_store,
        conversation_assurance_ledger=inputs.assurance_ledger,
        conversation_assurance_runtime=inputs.assurance_policy_runtime,
        conversation_search=user_context.conversation_search,
        conversation_policy_store=inputs.user_context_group.conversation_policy_store,
        user_context_ontology_projector=inputs.user_context_group.ontology_projector,
        post_turn_review_submitter=inputs.assurance_submitter,
        task_worker_store=PostgresTaskWorkerStore(
            config=PostgresTaskWorkerStoreConfig(
                dsn=inputs.read_model._config.dsn,
                statement_timeout_ms=inputs.read_model._config.statement_timeout_ms,
                connect_timeout_s=inputs.read_model._config.connect_timeout_s,
            )
        ),
        background_tasks=(
            read_investigation.background_runtime.routes
            if read_investigation.background_runtime is not None
            else None
        ),
        read_investigations=read_investigation.read_investigations,
        extra_panels=(
            *build_production_panels(
                read_model=inputs.read_model,
                onboarding_probe=inputs.onboarding.probe,
                onboarding_configured=inputs.onboarding.configured,
                state_store=inputs.state_store,
                action_types=inputs.action_types,
                active_rule_count=sum(
                    1 for _ in (inputs.repo_root / "rule-catalog" / "catalog").glob("*.yaml")
                ),
            ),
            *(
                (
                    ConfigurationBaselinesPanel(
                        read_investigation.configuration_drift_context,
                        review_store=StateStoreConfigurationReviewCampaignStore(inputs.state_store),
                    ),
                )
                if read_investigation.configuration_drift_context is not None
                else ()
            ),
            inputs.skill_runtime.panel,
            ArchitectureReviewStatusPanel(
                manifest_path=inputs.repo_root / "config" / "architecture-review.yaml",
                repo_root=inputs.repo_root,
                engine=inputs.process_views.engine,
            ),
        ),
        hil_callback=runtime.hil_callback,
        hil_registry=runtime.hil_registry,
        hil_decision_publisher=runtime.hil_decision_publisher,
        console_action=runtime.console_action,
        kill_switch_command=KillSwitchCommandService(store=inputs.state_store),
        iam_access=AccessRequestService(store=inputs.state_store),
        iam_directory=identity.iam_directory,
        iam_identity_provider=identity.iam_provider or "entra",
        iam_role_group_ids={
            "Reader": identity.group_mapping.reader_group_id,
            "Contributor": identity.group_mapping.contributor_group_id,
            "Approver": identity.group_mapping.approver_group_id,
            "Owner": identity.group_mapping.owner_group_id,
            "BreakGlass": identity.group_mapping.break_glass_group_id,
        },
        human_assignments=AssignmentCaseService(store=inputs.state_store),
        handover_goals=HandoverGoalService(
            store=inputs.state_store,
            assignments=AssignmentCaseService(store=inputs.state_store),
        ),
        handover_availability_publisher=(
            EventBusHandoverAvailabilityPublisher(
                event_bus=runtime.event_bus,
                topic=runtime.event_topic,
            )
            if runtime.event_bus is not None and runtime.event_topic
            else None
        ),
        live_stream=runtime.live_stream,
        agent_activity=runtime.agent_activity,
        data_sources=build_production_data_sources(
            scope_configured=inputs.scope_source is not None,
            onboarding_configured=inputs.onboarding.configured,
            model_settings_configured=inputs.model_settings is not None,
            streams_configured=runtime.live_stream is not None,
        ),
        startup_callbacks=(
            inputs.read_model.verify_connection,
            *read_investigation.schema_verification_callbacks,
            *read_investigation.reader_startup_callbacks,
            *runtime.startup_callbacks,
            *read_investigation.delegate_startup_callbacks,
            *inputs.stewardship_startup_callbacks,
        ),
        shutdown_callbacks=inputs.shutdown_callbacks,
    )


__all__ = ["ProductionOperatorConfigInputs", "build_production_operator_config"]
