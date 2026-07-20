"""In-memory user-context and workflow-definition wiring for local development."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fdai.core.briefing import BriefingCoordinator, OpeningBriefingService
from fdai.core.report_feed import ReportFeed
from fdai.core.scheduler.continuation import (
    InMemoryContinuationAuditSink,
    InMemoryScheduledConversationAnchorStore,
    ScheduledContinuationService,
)
from fdai.core.user_context_projection import UserContextOntologyProjector
from fdai.core.workflow.definition import (
    build_workflow_definition,
    built_in_workflow_lifecycle,
)
from fdai.delivery.read_api.routes.user_context import UserContextRoutesConfig
from fdai.delivery.read_api.routes.workflow_definitions import WorkflowDefinitionRoutesConfig
from fdai.shared.providers.testing import (
    InMemoryBriefingRunStore,
    InMemoryBriefingSubscriptionStore,
    InMemoryConversationHistoryStore,
    InMemoryConversationPolicyStore,
    InMemoryConversationSearch,
    InMemoryOntologyInstanceStore,
    InMemoryUserMemoryStore,
    InMemoryUserPreferenceStore,
    InMemoryWorkflowBindingStore,
    InMemoryWorkflowDefinitionStore,
)
from fdai.shared.providers.workflow_definition import (
    WorkflowOrigin,
    WorkflowVisibility,
)


@dataclass(frozen=True, slots=True)
class LocalUserContext:
    conversation_history_store: InMemoryConversationHistoryStore
    conversation_policy_store: InMemoryConversationPolicyStore
    ontology_projector: UserContextOntologyProjector
    routes: UserContextRoutesConfig
    workflow_definitions: WorkflowDefinitionRoutesConfig
    seed_callback: Callable[[], Awaitable[None]]


def build_local_user_context(
    *,
    schema_registry: Any,
    object_types: Sequence[Any],
    link_types: Sequence[Any],
    action_types: Sequence[Any],
    workflows: Sequence[Any],
    rule_ids: frozenset[str],
    promoted_workflows: frozenset[str] = frozenset(),
) -> LocalUserContext:
    """Build local user context and upstream workflow projections."""
    conversations = InMemoryConversationHistoryStore()
    ontology_store = InMemoryOntologyInstanceStore(
        object_types=object_types,
        link_types=link_types,
    )
    projector = UserContextOntologyProjector(store=ontology_store)
    preferences = InMemoryUserPreferenceStore()
    memories = InMemoryUserMemoryStore()
    policies = InMemoryConversationPolicyStore()
    subscriptions = InMemoryBriefingSubscriptionStore()
    runs = InMemoryBriefingRunStore()
    continuations = InMemoryScheduledConversationAnchorStore()
    routes = UserContextRoutesConfig(
        conversations=conversations,
        conversation_search=InMemoryConversationSearch(history=conversations),
        preferences=preferences,
        memories=memories,
        policies=policies,
        subscriptions=subscriptions,
        runs=runs,
        opening_briefing=OpeningBriefingService(
            policies=policies,
            runs=runs,
            coordinator=BriefingCoordinator(report_feed=ReportFeed()),
        ),
        ontology_projector=projector,
        continuations=continuations,
        continuation_service=ScheduledContinuationService(
            store=continuations,
            audit=InMemoryContinuationAuditSink(),
        ),
    )
    action_types_by_name = {item.name: item for item in action_types}
    built_in_definitions = tuple(
        build_workflow_definition(
            workflow,
            action_types=action_types_by_name,
            origin=WorkflowOrigin.UPSTREAM,
            visibility=WorkflowVisibility.GLOBAL,
            lifecycle=built_in_workflow_lifecycle(
                workflow.name,
                promoted_workflows=promoted_workflows,
            ),
            created_at=datetime.now(tz=UTC),
            source_ref=f"catalog:{workflow.name}@{workflow.version}",
        )
        for workflow in workflows
    )
    workflow_definitions = WorkflowDefinitionRoutesConfig(
        definitions=InMemoryWorkflowDefinitionStore(built_in_definitions),
        bindings=InMemoryWorkflowBindingStore(),
        schema_registry=schema_registry,
        action_types=tuple(action_types),
        rule_ids=rule_ids,
        ontology_projector=projector,
    )

    async def seed_user_workflow_ontology() -> None:
        for definition in built_in_definitions:
            await projector.project_workflow_definition(definition)

    return LocalUserContext(
        conversation_history_store=conversations,
        conversation_policy_store=policies,
        ontology_projector=projector,
        routes=routes,
        workflow_definitions=workflow_definitions,
        seed_callback=seed_user_workflow_ontology,
    )


__all__ = ["LocalUserContext", "build_local_user_context"]
