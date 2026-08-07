"""Command Deck route registration for the Operator API composition root."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Collection, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from starlette.requests import Request
from starlette.routing import BaseRoute

from fdai.core.conversation.answer_plan import AnswerFormat, AnswerIntent, DetailLevel
from fdai.core.conversation.answer_preferences import ResponsePreferenceProfile
from fdai.core.conversation_assurance import ConversationPolicyRuntime
from fdai.core.skills import RuntimeSkillDisclosure
from fdai.core.user_context_projection import UserContextOntologyProjector
from fdai.delivery.handover_events import HandoverAvailabilityPublisher
from fdai.delivery.operator_api.application import ConversationTurnApplicationService
from fdai.delivery.operator_api.application.conversation.backend import (
    ChatBackend,
    LatencyRoutedChatBackend,
    describe_backend,
)
from fdai.delivery.operator_api.application.conversation.capabilities import (
    configuration_drift as configuration_drift_capability,
)
from fdai.delivery.operator_api.application.conversation.capabilities.behavior_evidence import (
    RepositoryBehaviorEvidenceResolver,
)
from fdai.delivery.operator_api.application.conversation.capabilities.current_time import (
    CurrentTimeChatTools,
)
from fdai.delivery.operator_api.application.conversation.capabilities.data_sources import (
    DataSourceChatTools,
)
from fdai.delivery.operator_api.application.conversation.capabilities.detection_readiness import (
    DetectionReadinessChatTools,
)
from fdai.delivery.operator_api.application.conversation.capabilities.inventory import (
    InventoryActivityProvider,
    InventoryChatTools,
    InventorySemanticResolver,
    KubernetesWorkloadProvider,
)
from fdai.delivery.operator_api.application.conversation.capabilities.llm_usage import (
    LlmUsageChatTools,
    is_llm_usage_followup,
)
from fdai.delivery.operator_api.application.conversation.capabilities.log_query import (
    LogQueryChatTools,
    needs_log_query_context,
)
from fdai.delivery.operator_api.application.conversation.capabilities.read_model_tools import (
    ReadModelChatTools,
)
from fdai.delivery.operator_api.application.conversation.capabilities.runtime_skills import (
    RuntimeSkillChatTools,
)
from fdai.delivery.operator_api.application.conversation.capabilities.subscription_health import (
    SubscriptionHealthChatTools,
    SubscriptionHealthProvider,
    needs_subscription_health_context,
)
from fdai.delivery.operator_api.application.conversation.capabilities.system_health import (
    SystemHealthChatTools,
)
from fdai.delivery.operator_api.application.conversation.capability_registry import (
    ConversationCapability,
    ConversationCapabilityRegistry,
    static_capabilities,
    validate_panel_chat_bindings,
)
from fdai.delivery.operator_api.application.conversation.evidence import (
    OperationalEvidenceResolver,
)
from fdai.delivery.operator_api.application.conversation.intent_graph import (
    BackendIntentGraphPlanner,
)
from fdai.delivery.operator_api.application.conversation.planning import (
    compatible_planning_delegate,
)
from fdai.delivery.operator_api.application.conversation.request_preparation import (
    ChatDocumentEvidenceResolver,
)
from fdai.delivery.operator_api.application.conversation.turn_plan import (
    StructuredCompletionBackend,
    action_turn_tools,
    agent_turn_tools,
    web_search_turn_tool,
)
from fdai.delivery.operator_api.read_model import ConsoleReadModel
from fdai.delivery.operator_api.routes.busy_input import make_busy_input_routes
from fdai.delivery.operator_api.routes.busy_input_runtime import BusyInputRuntime
from fdai.delivery.operator_api.routes.chat import (
    DEFAULT_ROUTE_PATH,
    AgentChatDelegate,
    ChatWebSearchEvidenceResolver,
    make_chat_health_route,
    make_chat_route,
    make_chat_stream_route,
)
from fdai.delivery.operator_api.routes.data_sources import ReadDataSourceStatus
from fdai.delivery.operator_api.routes.detection_readiness import DetectionReadinessReader
from fdai.delivery.operator_api.routes.inventory_graph import InventoryGraphProvider
from fdai.delivery.operator_api.routes.post_turn_review import PostTurnReviewSubmitter
from fdai.shared.providers.briefing import ConversationPolicyStore
from fdai.shared.providers.conversation_search import ConversationSearch
from fdai.shared.providers.user_context import ConversationHistoryStore, UserPreferenceStore
from fdai.shared.telemetry import ConversationProgressMetrics


class _PlannedToolChain:
    """Try independently validating planned read resolvers in registration order."""

    def __init__(self, *resolvers: Any) -> None:
        self._resolvers = resolvers

    async def resolve_planned(
        self,
        tool_name: str,
        arguments: Mapping[str, object],
        *,
        principal_id: str,
    ) -> dict[str, Any] | None:
        for resolver in self._resolvers:
            result = await resolver.resolve_planned(
                tool_name,
                arguments,
                principal_id=principal_id,
            )
            if result is not None:
                return dict(result)
        return None


def append_chat_routes(
    routes: list[BaseRoute],
    *,
    backend: ChatBackend | None,
    skill_disclosure: RuntimeSkillDisclosure | None = None,
    knowledge_context: Any = None,
    configuration_drift_context: Any = None,
    busy_input_runtime: BusyInputRuntime | None = None,
    progress_metrics: ConversationProgressMetrics | None = None,
    agent_delegate: AgentChatDelegate | None,
    web_search_resolver: ChatWebSearchEvidenceResolver | None = None,
    conversation_policy_store: ConversationPolicyStore | None = None,
    conversation_assurance_runtime: ConversationPolicyRuntime | None = None,
    conversation_history_store: ConversationHistoryStore | None = None,
    conversation_image_store: Any = None,
    conversation_search: ConversationSearch | None = None,
    llm_usage_reader: Any = None,
    inventory_graph_provider: InventoryGraphProvider | None = None,
    inventory_semantic_resolver: InventorySemanticResolver | None = None,
    inventory_activity_provider: InventoryActivityProvider | None = None,
    kubernetes_workload_provider: KubernetesWorkloadProvider | None = None,
    detection_readiness_reader: DetectionReadinessReader | None = None,
    t2_recovery_reader: Any = None,
    subscription_health_provider: SubscriptionHealthProvider | None = None,
    log_query_provider: Any = None,
    network_reachability_provider: Any = None,
    data_sources: tuple[ReadDataSourceStatus, ...] = (),
    answer_preference_store: UserPreferenceStore | None = None,
    post_turn_review_submitter: PostTurnReviewSubmitter | None = None,
    document_evidence_resolver: ChatDocumentEvidenceResolver | None = None,
    user_context_ontology_projector: UserContextOntologyProjector | None = None,
    model_settings: object | None = None,
    console_action: object | None = None,
    handover_availability_publisher: HandoverAvailabilityPublisher | None = None,
    authorize: Callable[[Request], Awaitable[str]],
    read_model: ConsoleReadModel,
    panels: Collection[Any] = (),
    core_paths: Collection[str],
    panel_paths: Collection[str],
    logger: logging.Logger,
) -> None:
    """Append the optional chat, stream, and health routes."""

    if backend is None:
        return
    if DEFAULT_ROUTE_PATH in core_paths:
        raise ValueError(f"chat path {DEFAULT_ROUTE_PATH!r} collides with a core route")
    if DEFAULT_ROUTE_PATH in panel_paths:
        raise ValueError(f"chat path {DEFAULT_ROUTE_PATH!r} collides with a panel path")

    evidence = OperationalEvidenceResolver(read_model)
    behavior = RepositoryBehaviorEvidenceResolver(Path.cwd())
    read_tools = ReadModelChatTools(read_model, conversation_search)
    log_tools = LogQueryChatTools(log_query_provider, fallback=read_tools)
    inventory_chat_tools = (
        None
        if inventory_graph_provider is None
        else InventoryChatTools(
            inventory_graph_provider,
            fallback=log_tools,
            workload_provider=kubernetes_workload_provider,
            activity_provider=inventory_activity_provider,
            semantic_resolver=inventory_semantic_resolver,
        )
    )
    inventory_tools = inventory_chat_tools or log_tools
    subscription_health_tools = (
        inventory_tools
        if subscription_health_provider is None
        else SubscriptionHealthChatTools(
            subscription_health_provider,
            fallback=inventory_tools,
            log_query_provider=log_query_provider,
        )
    )
    from fdai.delivery.operator_api.application.conversation.capabilities import (
        network_reachability as network_reachability_capability,
    )

    network_reachability_tools = network_reachability_capability.NetworkReachabilityChatTools(
        network_reachability_provider,
        fallback=subscription_health_tools,
    )
    detection_readiness_tools = (
        network_reachability_tools
        if detection_readiness_reader is None
        else DetectionReadinessChatTools(
            detection_readiness_reader,
            fallback=network_reachability_tools,
        )
    )
    from fdai.delivery.operator_api.application.conversation.capabilities.t2_recovery import (
        T2RecoveryChatTools,
    )

    t2_recovery_tools = (
        detection_readiness_tools
        if t2_recovery_reader is None
        else T2RecoveryChatTools(t2_recovery_reader, fallback=detection_readiness_tools)
    )
    skill_tools = (
        t2_recovery_tools
        if skill_disclosure is None
        else RuntimeSkillChatTools(skill_disclosure, fallback=t2_recovery_tools)
    )
    data_source_tools = DataSourceChatTools(data_sources, fallback=skill_tools)
    system_health_tools = SystemHealthChatTools(
        read_model,
        data_source_tools,
    )
    from fdai.delivery.operator_api.application.conversation.capabilities.action_context import (
        ActionContextChatTools,
        needs_action_context,
    )

    action_context_tools = ActionContextChatTools(
        read_model=read_model,
        fallback=system_health_tools,
    )
    configuration_drift_tools = (
        configuration_drift_context.with_fallback(action_context_tools)
        if isinstance(
            configuration_drift_context,
            configuration_drift_capability.ConfigurationDriftChatTools,
        )
        else action_context_tools
    )
    from fdai.delivery.operator_api.application.conversation.capabilities import (
        conversation_context as conversation_context_capability,
    )

    current_time_tools = CurrentTimeChatTools(
        preferences=answer_preference_store,
        fallback=configuration_drift_tools,
    )
    llm_usage_tools = (
        current_time_tools
        if llm_usage_reader is None
        else LlmUsageChatTools(llm_usage_reader, fallback=current_time_tools)
    )
    tools = conversation_context_capability.ConversationContextChatTools(
        fallback=llm_usage_tools,
        analysis_context=(
            llm_usage_tools if isinstance(llm_usage_tools, LlmUsageChatTools) else None
        ),
        analysis_predicate=(is_llm_usage_followup if llm_usage_reader is not None else None),
        knowledge_context=knowledge_context,
        inventory_context=inventory_chat_tools,
        contextual_routes=(
            (
                configuration_drift_capability.needs_configuration_drift_context,
                configuration_drift_tools,
            ),
            (needs_action_context, action_context_tools),
            (needs_subscription_health_context, subscription_health_tools),
            (needs_log_query_context, log_tools),
        ),
        contextual_fallback=(
            subscription_health_tools
            if isinstance(subscription_health_tools, SubscriptionHealthChatTools)
            else None
        ),
        contextual_predicate=needs_subscription_health_context,
    )
    turn_planner = (
        BackendIntentGraphPlanner(backend)
        if isinstance(backend, StructuredCompletionBackend)
        else None
    )
    action_names = getattr(console_action, "action_type_names", ())
    read_capabilities = (
        *read_tools.turn_tools(),
        *(llm_usage_tools.turn_tools() if isinstance(llm_usage_tools, LlmUsageChatTools) else ()),
        *(inventory_chat_tools.turn_tools() if inventory_chat_tools is not None else ()),
        *(
            subscription_health_tools.turn_tools()
            if isinstance(subscription_health_tools, SubscriptionHealthChatTools)
            else ()
        ),
    )
    capabilities = [
        *static_capabilities(
            read_capabilities,
            owner="operator_api",
            authority="read",
        ),
        *static_capabilities(
            action_turn_tools(tuple(action_names)) if console_action is not None else (),
            owner="console_action",
            authority="draft_write",
        ),
    ]
    if agent_delegate is not None:
        capabilities.extend(
            ConversationCapability(
                tool=tool,
                owner="agent_event_bus",
                authority="read",
                available=lambda: bool(getattr(agent_delegate, "available", True)),
                unavailable_reason="agent_event_bus_unavailable",
            )
            for tool in agent_turn_tools()
        )
    if web_search_resolver is not None:
        capabilities.append(
            ConversationCapability(
                tool=web_search_turn_tool(),
                owner="approved_web_search",
                authority="read",
                available=lambda: bool(getattr(web_search_resolver, "available", True)),
                enabled=lambda: bool(getattr(web_search_resolver, "enabled", True)),
                unavailable_reason="web_search_unavailable",
            )
        )
    capability_registry = ConversationCapabilityRegistry(capabilities)
    validate_panel_chat_bindings(tuple(panels), capability_registry.registered_tools())
    planned_tools = _PlannedToolChain(
        *((subscription_health_tools,) if subscription_health_provider is not None else ()),
        *((llm_usage_tools,) if isinstance(llm_usage_tools, LlmUsageChatTools) else ()),
        read_tools,
        *((inventory_chat_tools,) if inventory_chat_tools is not None else ()),
    )
    turn_service = ConversationTurnApplicationService()
    routes.extend(
        (
            make_chat_route(
                backend=backend,
                authorize=authorize,
                behavior_resolver=behavior,
                evidence_resolver=evidence,
                tool_resolver=tools,
                planned_tool_resolver=planned_tools,
                web_search_resolver=web_search_resolver,
                agent_delegate=agent_delegate,
                answer_planning_delegate=compatible_planning_delegate(agent_delegate),
                conversation_policy_store=conversation_policy_store,
                conversation_assurance_runtime=conversation_assurance_runtime,
                conversation_history_store=conversation_history_store,
                conversation_image_store=conversation_image_store,
                user_context_ontology_projector=user_context_ontology_projector,
                model_preference_resolver=(
                    getattr(model_settings, "preferred_model", None)
                    if model_settings is not None
                    else None
                ),
                answer_preference_resolver=_answer_preference_resolver(answer_preference_store),
                post_turn_review_submitter=post_turn_review_submitter,
                document_evidence_resolver=document_evidence_resolver,
                busy_input_coordinator=(
                    busy_input_runtime.coordinator if busy_input_runtime is not None else None
                ),
                turn_planner=turn_planner,
                turn_tools=capability_registry.visible_tools,
                handover_availability_publisher=handover_availability_publisher,
                turn_service=turn_service,
            ),
            make_chat_stream_route(
                backend=backend,
                authorize=authorize,
                behavior_resolver=behavior,
                evidence_resolver=evidence,
                tool_resolver=tools,
                planned_tool_resolver=planned_tools,
                web_search_resolver=web_search_resolver,
                agent_delegate=agent_delegate,
                answer_planning_delegate=compatible_planning_delegate(agent_delegate),
                conversation_policy_store=conversation_policy_store,
                conversation_assurance_runtime=conversation_assurance_runtime,
                conversation_history_store=conversation_history_store,
                conversation_image_store=conversation_image_store,
                user_context_ontology_projector=user_context_ontology_projector,
                model_preference_resolver=(
                    getattr(model_settings, "preferred_model", None)
                    if model_settings is not None
                    else None
                ),
                answer_preference_resolver=_answer_preference_resolver(answer_preference_store),
                post_turn_review_submitter=post_turn_review_submitter,
                document_evidence_resolver=document_evidence_resolver,
                busy_input_coordinator=(
                    busy_input_runtime.coordinator if busy_input_runtime is not None else None
                ),
                progress_metrics=progress_metrics,
                turn_planner=turn_planner,
                turn_tools=capability_registry.visible_tools,
                turn_service=turn_service,
            ),
            make_chat_health_route(
                backend=backend,
                authorize=authorize,
                web_search_resolver=web_search_resolver,
            ),
        )
    )
    if busy_input_runtime is not None:
        routes.extend(
            make_busy_input_routes(
                coordinator=busy_input_runtime.coordinator,
                authorize=authorize,
            )
        )

    descriptor = describe_backend(backend)
    if descriptor.get("available"):
        logger.info(
            "chat_backend_ready",
            extra={
                "mode": descriptor.get("mode"),
                "model": descriptor.get("model"),
            },
        )
    else:
        logger.warning(
            "CommandDeck chat backend NOT wired - the FE will fall back to the "
            "deterministic answerer. Set FDAI_NARRATOR_* env vars or ship "
            "resolved-models.json to enable the LLM path."
        )


def _answer_preference_resolver(
    store: UserPreferenceStore | None,
) -> Callable[[str], Awaitable[ResponsePreferenceProfile | None]] | None:
    if store is None:
        return None

    async def resolve(principal_id: str) -> ResponsePreferenceProfile | None:
        record = await store.get(principal_id=principal_id)
        if record is None:
            return None
        return ResponsePreferenceProfile(
            locale=record.locale,
            default_detail=DetailLevel(record.answer_detail),
            default_format=AnswerFormat(record.answer_format),
            intent_detail={
                AnswerIntent(intent): DetailLevel(detail)
                for intent, detail in record.answer_intent_detail.items()
            },
            intent_format={
                AnswerIntent(intent): AnswerFormat(format_)
                for intent, format_ in record.answer_intent_format.items()
            },
            explicit_only=not record.answer_preferences_enabled,
            updated_at=record.updated_at or datetime(1970, 1, 1, tzinfo=UTC),
        )

    return resolve


def is_routed_chat_backend(backend: object) -> bool:
    """Return whether the optional chat backend uses latency routing."""
    return isinstance(backend, LatencyRoutedChatBackend)


async def periodic_latency_probe(
    target: Any,
    *,
    label: str,
    interval_seconds: int,
) -> None:
    """Continuously refresh one router's bounded latency sample window."""
    first_round = True
    while True:
        try:
            chose = await target.benchmark(rounds=None if first_round else 1)
            logging.getLogger("fdai.delivery.operator_api").info(
                "%s latency benchmark selected candidate=%s",
                label,
                chose,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - best-effort probe
            logging.getLogger("fdai.delivery.operator_api").warning(
                "%s latency benchmark failed: %s",
                label,
                type(exc).__name__,
            )
        first_round = False
        await asyncio.sleep(interval_seconds)


__all__ = ["append_chat_routes", "is_routed_chat_backend", "periodic_latency_probe"]
