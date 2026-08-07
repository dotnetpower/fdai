"""Typed Operator API configuration assembly for interactive local composition."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from fdai.core.audit.what_if_replay import WhatIfEvaluator
from fdai.core.execution_authorization import AccessGrantRequestService
from fdai.core.human_assignment import AssignmentCaseService
from fdai.core.measurement.promotion_gate import InMemoryShadowVerdictSource
from fdai.core.onboarding import EmptyResourceProbe
from fdai.core.operator_memory import (
    InMemoryMemoryCompactionRepository,
    InMemoryOperatorMemoryStore,
    OperatorMemoryReviewService,
)
from fdai.core.rbac.access_request import AccessRequestService
from fdai.core.scheduler import (
    InMemoryScheduleRunLedger,
    ScheduleRunHistoryService,
)
from fdai.delivery.configuration_review_store import (
    StateStoreConfigurationReviewCampaignStore,
)
from fdai.delivery.operator_api.app.catalog_reference import load_mcsb_reference
from fdai.delivery.operator_api.dev.azure_cli_identity import LocalAzureCliIdentity
from fdai.delivery.operator_api.dev.command_transport import LocalCommandTransport
from fdai.delivery.operator_api.dev.fixtures.dynamic_views import _build_blast_radius_graph
from fdai.delivery.operator_api.dev.fixtures.seed_data import _synthetic_verdicts
from fdai.delivery.operator_api.dev.iam_directory import LocalIamDirectory
from fdai.delivery.operator_api.dev.model_wiring import LocalModelWiring
from fdai.delivery.operator_api.dev.read_investigation import LocalReadInvestigationWiring
from fdai.delivery.operator_api.dev.runtime_wiring import LocalRuntimeWiring
from fdai.delivery.operator_api.main import OperatorApiConfig
from fdai.delivery.operator_api.postgres_read_model import PostgresConsoleReadModel
from fdai.delivery.operator_api.production.persistence import ProductionPersistence
from fdai.delivery.operator_api.read_model import ConsoleReadModel
from fdai.delivery.operator_api.routes.arb_status import ArchitectureReviewStatusPanel
from fdai.delivery.operator_api.routes.chat_agent_delegate import PantheonChatDelegate
from fdai.delivery.operator_api.routes.configuration_baselines import ConfigurationBaselinesPanel
from fdai.delivery.operator_api.routes.data_sources import ReadDataSourceStatus
from fdai.delivery.operator_api.routes.llm_cost import LlmCostPanel
from fdai.delivery.operator_api.routes.measurement_summary import AutonomyMeasurementPanel
from fdai.delivery.operator_api.routes.onboarding import OnboardingPanel
from fdai.delivery.operator_api.routes.operator_memory import OperatorMemoryPanel
from fdai.delivery.operator_api.routes.panels import (
    CapabilityCatalogPanel,
    ExampleFinOpsPanel,
    ReadPanel,
)
from fdai.delivery.operator_api.routes.scheduler_runs import SchedulerRunsPanel
from fdai.delivery.operator_api.routes.skills import RuntimeSkillsPanel
from fdai.delivery.operator_api.streaming.provision_stream import ProvisionStreamConfig
from fdai.delivery.runtime_settings import RuntimeSettingsService
from fdai.shared.contracts.models import OntologyDeclarationKind
from fdai.shared.ontology.release import build_ontology_release

_LifecycleCallback = Callable[[], Awaitable[None]]


class LocalDataSourceBuilder(Protocol):
    """Build the local source manifest from composition-owned availability facts."""

    def __call__(
        self,
        *,
        test_fixtures: bool,
        authoritative_proxy_configured: bool,
        local_database_configured: bool,
        local_database_startup_verified: bool,
        runtime_streams_configured: bool,
        scope_configured: bool,
        python_tasks_configured: bool,
    ) -> tuple[ReadDataSourceStatus, ...]: ...


class InventoryLifecycleBuilder(Protocol):
    """Resolve optional inventory startup and shutdown hooks."""

    def __call__(
        self,
        provider: Any,
    ) -> tuple[tuple[_LifecycleCallback, ...], tuple[_LifecycleCallback, ...]]: ...


@dataclass(frozen=True, slots=True)
class LocalAppConfigDependencies:
    """Inputs already resolved by the local composition root."""

    repo_root: Path
    environ: Mapping[str, str]
    dev_mode: bool
    test_fixtures: bool
    local_database_configured: bool
    local_cli_identity: LocalAzureCliIdentity | None
    read_model: ConsoleReadModel
    postgres_read_model: PostgresConsoleReadModel | None
    persistence: ProductionPersistence | None
    authoritative_read_proxy: Any
    live_stream_config: Any
    agent_activity_config: Any
    conversation_history_store: Any
    assurance_ledger: Any
    assurance_policy_runtime: Any
    user_context: Any
    conversation_policy_store: Any
    user_context_ontology_projector: Any
    assurance_submitter: Any
    workflow_definitions: Any
    models: LocalModelWiring
    workflow_authoring: Any
    workflow_execution: Any
    inventory_graph_provider: Any
    inventory_activity_provider: Any
    kubernetes_workload_provider: Any
    local_read_investigation: LocalReadInvestigationWiring | None
    log_query_provider: Any
    best_practice_controls: tuple[Any, ...]
    rule_catalog_rules: tuple[Any, ...]
    rule_catalog_collected: tuple[Any, ...]
    policies_root: Path
    remediation_root: Path
    rule_catalog_findings_provider: Any
    rule_catalog_findings_summary_provider: Any
    scope_source: Any
    durable_panels: tuple[ReadPanel, ...]
    conversation_delivery_store: Any
    trace_reader: Any
    what_if_evaluators: Mapping[str, WhatIfEvaluator]
    metering: Any
    skill_disclosure: Any
    knowledge_context: Any
    configuration_drift_context: Any
    remote_agent_delegate: Any
    runtime: LocalRuntimeWiring | None
    command_transport: LocalCommandTransport | None
    iam: LocalIamDirectory
    reporting: Any
    process_views: Any
    user_context_startup_callbacks: tuple[_LifecycleCallback, ...]
    post_turn_review_queue: Any
    log_query_shutdown_callbacks: tuple[_LifecycleCallback, ...]
    ontology_object_types: tuple[Any, ...]
    ontology_link_types: tuple[Any, ...]
    action_types: tuple[Any, ...]
    data_source_builder: LocalDataSourceBuilder
    inventory_lifecycle_builder: InventoryLifecycleBuilder
    cors_allow_origins: tuple[str, ...]
    stewardship_map: Any
    chat_probe_interval_seconds: int


def build_local_operator_api_config(
    dependencies: LocalAppConfigDependencies,
) -> OperatorApiConfig:
    """Assemble the local HTTP configuration without importing the local factory."""
    process_views = dependencies.process_views
    arb_status_panels = (
        (
            ArchitectureReviewStatusPanel(
                manifest_path=dependencies.repo_root / "config" / "architecture-review.yaml",
                repo_root=dependencies.repo_root,
                engine=process_views.engine,
            ),
        )
        if process_views is not None
        else ()
    )

    async def open_narrator_endpoint() -> None:
        from fdai.delivery.operator_api.dev.narrator_endpoint_access import (
            ensure_narrator_endpoint_open,
        )

        await ensure_narrator_endpoint_open(dependencies.models.backend)

    fixture_panels: tuple[ReadPanel, ...] = (
        (
            ExampleFinOpsPanel(dependencies.read_model),
            AutonomyMeasurementPanel(dependencies.read_model),
            OperatorMemoryPanel(
                service=OperatorMemoryReviewService(store=InMemoryOperatorMemoryStore()),
                compactions=InMemoryMemoryCompactionRepository(),
            ),
            SchedulerRunsPanel(
                service=ScheduleRunHistoryService(ledger=InMemoryScheduleRunLedger()),
                source="synthetic-dev",
                durable=False,
            ),
        )
        if dependencies.test_fixtures
        else ()
    )
    local_panels: tuple[ReadPanel, ...] = (
        dependencies.durable_panels
        if dependencies.durable_panels
        else (
            CapabilityCatalogPanel(),
            OnboardingPanel(probe=EmptyResourceProbe(), configured=False),
            LlmCostPanel(
                dependencies.metering,
                source=("synthetic-dev" if dependencies.test_fixtures else "local-process"),
            ),
        )
    )
    extra_panels = (
        fixture_panels
        + local_panels
        + (RuntimeSkillsPanel(dependencies.skill_disclosure), *arb_status_panels)
        + (
            (
                ConfigurationBaselinesPanel(
                    dependencies.configuration_drift_context,
                    review_store=(
                        StateStoreConfigurationReviewCampaignStore(
                            dependencies.persistence.state_store
                        )
                        if dependencies.persistence is not None
                        else None
                    ),
                ),
            )
            if dependencies.configuration_drift_context is not None
            else ()
        )
    )
    runtime_settings = RuntimeSettingsService(
        store=(
            dependencies.persistence.state_store
            if dependencies.persistence is not None
            else dependencies.models.settings.store
        ),
        env=dependencies.environ,
        durable=dependencies.persistence is not None,
    )
    assignment_store = (
        dependencies.persistence.state_store
        if dependencies.persistence is not None
        else dependencies.models.settings.store
    )

    from fdai.delivery.catalog_search.ontology_function import catalog_query_function_type
    from fdai.delivery.kubernetes.ontology_functions import diagnostic_function_types
    from fdai.delivery.operator_api.application.conversation.capabilities.inventory import (
        EmbeddingInventorySemanticResolver,
        inventory_query_function_type,
    )

    ontology_function_types = (
        inventory_query_function_type(),
        catalog_query_function_type(),
        *diagnostic_function_types(),
    )
    local_ontology_release = build_ontology_release(
        object_types=dependencies.ontology_object_types,
        link_types=dependencies.ontology_link_types,
        action_types=dependencies.action_types,
        function_types=ontology_function_types,
    )
    inventory_semantic_resolver = (
        EmbeddingInventorySemanticResolver(
            embedder=dependencies.models.embedder,
            target_ref=local_ontology_release.type_ref(
                OntologyDeclarationKind.FUNCTION,
                "inventory.select_resources",
            ),
        )
        if dependencies.models.embedder is not None
        else None
    )
    inventory_startup_callbacks, inventory_shutdown_callbacks = (
        dependencies.inventory_lifecycle_builder(dependencies.inventory_graph_provider)
    )
    runtime = dependencies.runtime
    command_transport = dependencies.command_transport
    local_read_investigation = dependencies.local_read_investigation
    remote_agent_delegate = dependencies.remote_agent_delegate
    chat_agent_delegate = (
        remote_agent_delegate
        if remote_agent_delegate is not None
        else local_read_investigation.chat_delegate
        if local_read_investigation is not None
        else PantheonChatDelegate(runtime.pantheon_runtime)
        if dependencies.test_fixtures and runtime is not None
        else None
    )
    postgres_startup_callbacks = (
        (dependencies.postgres_read_model.verify_connection,)
        if dependencies.postgres_read_model is not None
        else ()
    )
    return OperatorApiConfig(
        dev_mode=dependencies.dev_mode,
        local_cli_principal=(
            dependencies.local_cli_identity.principal
            if dependencies.local_cli_identity is not None
            else None
        ),
        local_cli_profile=(
            dependencies.local_cli_identity.to_dict()
            if dependencies.local_cli_identity is not None
            else None
        ),
        cors_allow_origins=dependencies.cors_allow_origins,
        live_stream=dependencies.live_stream_config,
        provision_stream=(ProvisionStreamConfig() if dependencies.test_fixtures else None),
        agent_activity=dependencies.agent_activity_config,
        blast_radius_graph=(_build_blast_radius_graph() if dependencies.test_fixtures else None),
        ontology_object_types=dependencies.ontology_object_types,
        ontology_link_types=dependencies.ontology_link_types,
        ontology_action_types=dependencies.action_types,
        ontology_function_types=ontology_function_types,
        conversation_history_store=dependencies.conversation_history_store,
        conversation_assurance_ledger=dependencies.assurance_ledger,
        conversation_assurance_runtime=dependencies.assurance_policy_runtime,
        conversation_search=dependencies.user_context.conversation_search,
        conversation_policy_store=dependencies.conversation_policy_store,
        user_context_ontology_projector=dependencies.user_context_ontology_projector,
        post_turn_review_submitter=dependencies.assurance_submitter,
        user_context=dependencies.user_context,
        model_settings=dependencies.models.settings,
        runtime_settings=runtime_settings,
        workflow_definitions=dependencies.workflow_definitions,
        inventory_graph_provider=dependencies.inventory_graph_provider,
        inventory_semantic_resolver=inventory_semantic_resolver,
        inventory_activity_provider=dependencies.inventory_activity_provider,
        kubernetes_workload_provider=dependencies.kubernetes_workload_provider,
        detection_readiness_reader=(
            dependencies.persistence.state_store if dependencies.persistence is not None else None
        ),
        t2_recovery_reader=(
            dependencies.persistence.state_store if dependencies.persistence is not None else None
        ),
        subscription_health_provider=(
            local_read_investigation.subscription_health_provider
            if local_read_investigation is not None
            else None
        ),
        log_query_provider=dependencies.log_query_provider,
        network_reachability_provider=(
            local_read_investigation.network_reachability_provider
            if local_read_investigation is not None
            else None
        ),
        best_practice_controls=dependencies.best_practice_controls,
        mcsb_catalogs=load_mcsb_reference(dependencies.repo_root),
        rule_catalog_rules=dependencies.rule_catalog_rules,
        rule_catalog_collected_rules=dependencies.rule_catalog_collected,
        rule_catalog_policies_root=(
            dependencies.policies_root if dependencies.policies_root.is_dir() else None
        ),
        rule_catalog_remediation_root=(
            dependencies.remediation_root if dependencies.remediation_root.is_dir() else None
        ),
        rule_catalog_findings_provider=dependencies.rule_catalog_findings_provider,
        rule_catalog_findings_summary_provider=(
            dependencies.rule_catalog_findings_summary_provider
        ),
        promotion_gate_action_types=(
            dependencies.action_types if dependencies.test_fixtures else ()
        ),
        promotion_gate_source=(
            InMemoryShadowVerdictSource(verdicts=_synthetic_verdicts())
            if dependencies.test_fixtures
            else None
        ),
        scope_source=dependencies.scope_source,
        extra_panels=extra_panels,
        conversation_delivery_store=dependencies.conversation_delivery_store,
        data_sources=dependencies.data_source_builder(
            test_fixtures=dependencies.test_fixtures,
            authoritative_proxy_configured=(dependencies.authoritative_read_proxy is not None),
            local_database_configured=dependencies.local_database_configured,
            local_database_startup_verified=dependencies.local_database_configured,
            runtime_streams_configured=(
                dependencies.live_stream_config is not None
                and dependencies.agent_activity_config is not None
            ),
            scope_configured=dependencies.scope_source is not None,
            python_tasks_configured=(runtime is not None and runtime.python_tasks is not None),
        ),
        authoritative_read_proxy=dependencies.authoritative_read_proxy,
        trace_reader=dependencies.trace_reader if dependencies.test_fixtures else None,
        bitemporal_reader=dependencies.trace_reader if dependencies.test_fixtures else None,
        what_if_reader=dependencies.trace_reader if dependencies.test_fixtures else None,
        what_if_evaluators=(dependencies.what_if_evaluators if dependencies.test_fixtures else {}),
        chat=dependencies.models.backend,
        llm_usage_reader=dependencies.metering,
        skill_disclosure=dependencies.skill_disclosure,
        knowledge_context=dependencies.knowledge_context,
        configuration_drift_context=dependencies.configuration_drift_context,
        chat_web_search=dependencies.models.web_search,
        chat_probe_interval_seconds=dependencies.chat_probe_interval_seconds,
        chat_agent_delegate=chat_agent_delegate,
        console_action=(
            runtime.console_action
            if runtime is not None and runtime.console_action is not None
            else command_transport.console_action
            if command_transport is not None
            else None
        ),
        iam_access=AccessRequestService(store=assignment_store),
        execution_access_grants=AccessGrantRequestService(store=assignment_store),
        iam_directory=dependencies.iam.directory,
        iam_role_group_ids=dependencies.iam.role_group_ids,
        human_assignments=AssignmentCaseService(store=assignment_store),
        expose_pantheon=True,
        stewardship_map=dependencies.stewardship_map,
        workflow_authoring=dependencies.workflow_authoring,
        workflow_execution=dependencies.workflow_execution,
        python_tasks=runtime.python_tasks if runtime is not None else None,
        reporting=dependencies.reporting,
        process_views=process_views,
        startup_callbacks=(
            inventory_startup_callbacks
            + postgres_startup_callbacks
            + dependencies.user_context_startup_callbacks
            + (open_narrator_endpoint,)
            + ((local_read_investigation.start,) if local_read_investigation is not None else ())
            + ((remote_agent_delegate.start,) if remote_agent_delegate is not None else ())
            + ((runtime.start_pantheon_runtime,) if runtime is not None else ())
            + ((command_transport.start,) if command_transport is not None else ())
            + (
                (runtime.operator_runtime.start,)
                if runtime is not None and runtime.operator_runtime is not None
                else ()
            )
        ),
        shutdown_callbacks=(
            inventory_shutdown_callbacks
            + ((runtime.stop_pantheon_runtime,) if runtime is not None else ())
            + ((remote_agent_delegate.stop,) if remote_agent_delegate is not None else ())
            + (
                (dependencies.post_turn_review_queue.close,)
                if dependencies.post_turn_review_queue is not None
                else ()
            )
            + (dependencies.assurance_submitter.close,)
            + (
                (runtime.operator_runtime.stop,)
                if runtime is not None and runtime.operator_runtime is not None
                else ()
            )
            + ((command_transport.shutdown,) if command_transport is not None else ())
            + (
                (dependencies.authoritative_read_proxy.aclose,)
                if dependencies.authoritative_read_proxy is not None
                else ()
            )
            + ((local_read_investigation.close,) if local_read_investigation is not None else ())
            + dependencies.log_query_shutdown_callbacks
            + dependencies.models.shutdown_callbacks
            + dependencies.iam.shutdown_callbacks
        ),
    )


__all__ = ["LocalAppConfigDependencies", "build_local_operator_api_config"]
