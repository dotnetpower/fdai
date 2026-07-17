"""Production user-context and workflow-definition persistence wiring."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fdai.core.briefing import BriefingCoordinator, OpeningBriefingService
from fdai.core.report_feed import ReportFeed
from fdai.core.user_context_projection import UserContextOntologyProjector
from fdai.core.workflow.definition import build_workflow_definition
from fdai.delivery.persistence import (
    PostgresBriefingRunStore,
    PostgresBriefingStoreConfig,
    PostgresBriefingSubscriptionStore,
    PostgresConversationHistoryStore,
    PostgresConversationPolicyStore,
    PostgresReportSignalStore,
    PostgresReportSignalStoreConfig,
    PostgresUserContextStoreConfig,
    PostgresUserMemoryStore,
    PostgresUserPreferenceStore,
    PostgresWorkflowBindingStore,
    PostgresWorkflowDefinitionStore,
    PostgresWorkflowDefinitionStoreConfig,
)
from fdai.delivery.persistence.postgres_ontology import (
    PostgresOntologyInstanceStore,
    PostgresOntologyInstanceStoreConfig,
)
from fdai.delivery.read_api.routes.user_context import UserContextRoutesConfig
from fdai.delivery.read_api.routes.workflow_definitions import WorkflowDefinitionRoutesConfig
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.workflow_definition import (
    WorkflowLifecycle,
    WorkflowOrigin,
    WorkflowVisibility,
)


@dataclass(frozen=True, slots=True)
class ProductionUserContext:
    conversation_history_store: Any
    conversation_policy_store: Any
    ontology_projector: UserContextOntologyProjector
    routes: UserContextRoutesConfig
    workflow_definitions: WorkflowDefinitionRoutesConfig
    startup_callbacks: tuple[Callable[[], Awaitable[None]], ...]


def build_production_user_context(
    *,
    read_model: Any,
    object_types: Sequence[Any],
    link_types: Sequence[Any],
    action_types: Sequence[Any],
    workflows: Sequence[Any],
) -> ProductionUserContext:
    """Build durable user context, briefing, and workflow definition stores."""
    connection = {
        "dsn": read_model._config.dsn,
        "statement_timeout_ms": read_model._config.statement_timeout_ms,
        "connect_timeout_s": read_model._config.connect_timeout_s,
    }
    user_store_config = PostgresUserContextStoreConfig(**connection)
    briefing_store_config = PostgresBriefingStoreConfig(**connection)
    workflow_store_config = PostgresWorkflowDefinitionStoreConfig(**connection)
    conversations = PostgresConversationHistoryStore(config=user_store_config)
    ontology_store = PostgresOntologyInstanceStore(
        config=PostgresOntologyInstanceStoreConfig(**connection),
        object_types=object_types,
        link_types=link_types,
    )
    projector = UserContextOntologyProjector(store=ontology_store)
    preferences = PostgresUserPreferenceStore(config=user_store_config)
    memories = PostgresUserMemoryStore(config=user_store_config)
    policies = PostgresConversationPolicyStore(config=briefing_store_config)
    subscriptions = PostgresBriefingSubscriptionStore(config=briefing_store_config)
    runs = PostgresBriefingRunStore(config=briefing_store_config)
    report_feed = ReportFeed(
        (PostgresReportSignalStore(config=PostgresReportSignalStoreConfig(**connection)),)
    )
    routes = UserContextRoutesConfig(
        conversations=conversations,
        preferences=preferences,
        memories=memories,
        policies=policies,
        subscriptions=subscriptions,
        runs=runs,
        opening_briefing=OpeningBriefingService(
            policies=policies,
            runs=runs,
            coordinator=BriefingCoordinator(report_feed=report_feed),
        ),
        ontology_projector=projector,
    )
    definitions = PostgresWorkflowDefinitionStore(config=workflow_store_config)
    bindings = PostgresWorkflowBindingStore(config=workflow_store_config)
    action_types_by_name = {item.name: item for item in action_types}
    built_in_definitions = tuple(
        build_workflow_definition(
            workflow,
            action_types=action_types_by_name,
            origin=WorkflowOrigin.UPSTREAM,
            visibility=WorkflowVisibility.GLOBAL,
            lifecycle=WorkflowLifecycle.SHADOW,
            created_at=datetime.now(tz=UTC),
            source_ref=f"catalog:{workflow.name}@{workflow.version}",
        )
        for workflow in workflows
    )

    async def seed_workflow_definitions() -> None:
        for definition in built_in_definitions:
            stored = await definitions.put(definition)
            await projector.project_workflow_definition(stored)

    workflow_definitions = WorkflowDefinitionRoutesConfig(
        definitions=definitions,
        bindings=bindings,
        schema_registry=PackageResourceSchemaRegistry(),
        action_types=tuple(action_types),
        ontology_projector=projector,
    )
    return ProductionUserContext(
        conversation_history_store=conversations,
        conversation_policy_store=policies,
        ontology_projector=projector,
        routes=routes,
        workflow_definitions=workflow_definitions,
        startup_callbacks=(ontology_store.sync_catalog, seed_workflow_definitions),
    )


__all__ = ["ProductionUserContext", "build_production_user_context"]
