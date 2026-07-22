"""Command Deck route registration for the read API composition root."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Collection
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from starlette.requests import Request
from starlette.routing import BaseRoute

from fdai.core.conversation.answer_plan import AnswerFormat, AnswerIntent, DetailLevel
from fdai.core.conversation.answer_preferences import ResponsePreferenceProfile
from fdai.core.skills import RuntimeSkillDisclosure
from fdai.core.user_context_projection import UserContextOntologyProjector
from fdai.delivery.read_api.read_model import ConsoleReadModel
from fdai.delivery.read_api.routes.busy_input import make_busy_input_routes
from fdai.delivery.read_api.routes.busy_input_runtime import BusyInputRuntime
from fdai.delivery.read_api.routes.chat import (
    DEFAULT_ROUTE_PATH,
    AgentChatDelegate,
    ChatBackend,
    ChatWebSearchEvidenceResolver,
    LatencyRoutedChatBackend,
    describe_backend,
    make_chat_health_route,
    make_chat_route,
    make_chat_stream_route,
)
from fdai.delivery.read_api.routes.chat_answer_planning import compatible_planning_delegate
from fdai.delivery.read_api.routes.chat_behavior_evidence import (
    RepositoryBehaviorEvidenceResolver,
)
from fdai.delivery.read_api.routes.chat_data_sources import DataSourceChatTools
from fdai.delivery.read_api.routes.chat_evidence import OperationalEvidenceResolver
from fdai.delivery.read_api.routes.chat_inventory import InventoryChatTools
from fdai.delivery.read_api.routes.chat_log_query import LogQueryChatTools
from fdai.delivery.read_api.routes.chat_skills import RuntimeSkillChatTools
from fdai.delivery.read_api.routes.chat_subscription_health import (
    SubscriptionHealthChatTools,
    SubscriptionHealthProvider,
)
from fdai.delivery.read_api.routes.chat_system_health import SystemHealthChatTools
from fdai.delivery.read_api.routes.chat_tools import ReadModelChatTools
from fdai.delivery.read_api.routes.data_sources import ReadDataSourceStatus
from fdai.delivery.read_api.routes.inventory_graph import InventoryGraphProvider
from fdai.delivery.read_api.routes.post_turn_review import PostTurnReviewSubmitter
from fdai.shared.providers.briefing import ConversationPolicyStore
from fdai.shared.providers.conversation_search import ConversationSearch
from fdai.shared.providers.user_context import ConversationHistoryStore, UserPreferenceStore


def append_chat_routes(
    routes: list[BaseRoute],
    *,
    backend: ChatBackend | None,
    skill_disclosure: RuntimeSkillDisclosure | None = None,
    busy_input_runtime: BusyInputRuntime | None = None,
    agent_delegate: AgentChatDelegate | None,
    web_search_resolver: ChatWebSearchEvidenceResolver | None = None,
    conversation_policy_store: ConversationPolicyStore | None = None,
    conversation_history_store: ConversationHistoryStore | None = None,
    conversation_search: ConversationSearch | None = None,
    inventory_graph_provider: InventoryGraphProvider | None = None,
    subscription_health_provider: SubscriptionHealthProvider | None = None,
    log_query_provider: Any = None,
    data_sources: tuple[ReadDataSourceStatus, ...] = (),
    answer_preference_store: UserPreferenceStore | None = None,
    post_turn_review_submitter: PostTurnReviewSubmitter | None = None,
    user_context_ontology_projector: UserContextOntologyProjector | None = None,
    model_settings: object | None = None,
    authorize: Callable[[Request], Awaitable[str]],
    read_model: ConsoleReadModel,
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
    log_tools = (
        read_tools
        if log_query_provider is None
        else LogQueryChatTools(log_query_provider, fallback=read_tools)
    )
    inventory_tools = (
        log_tools
        if inventory_graph_provider is None
        else InventoryChatTools(inventory_graph_provider, fallback=log_tools)
    )
    subscription_health_tools = (
        inventory_tools
        if subscription_health_provider is None
        else SubscriptionHealthChatTools(
            subscription_health_provider,
            fallback=inventory_tools,
        )
    )
    skill_tools = (
        subscription_health_tools
        if skill_disclosure is None
        else RuntimeSkillChatTools(skill_disclosure, fallback=subscription_health_tools)
    )
    data_source_tools = DataSourceChatTools(data_sources, fallback=skill_tools)
    tools = SystemHealthChatTools(
        read_model,
        data_source_tools,
    )
    routes.extend(
        (
            make_chat_route(
                backend=backend,
                authorize=authorize,
                behavior_resolver=behavior,
                evidence_resolver=evidence,
                tool_resolver=tools,
                web_search_resolver=web_search_resolver,
                agent_delegate=agent_delegate,
                answer_planning_delegate=compatible_planning_delegate(agent_delegate),
                conversation_policy_store=conversation_policy_store,
                conversation_history_store=conversation_history_store,
                user_context_ontology_projector=user_context_ontology_projector,
                model_preference_resolver=(
                    getattr(model_settings, "preferred_model", None)
                    if model_settings is not None
                    else None
                ),
                answer_preference_resolver=_answer_preference_resolver(answer_preference_store),
                post_turn_review_submitter=post_turn_review_submitter,
                busy_input_coordinator=(
                    busy_input_runtime.coordinator if busy_input_runtime is not None else None
                ),
            ),
            make_chat_stream_route(
                backend=backend,
                authorize=authorize,
                behavior_resolver=behavior,
                evidence_resolver=evidence,
                tool_resolver=tools,
                web_search_resolver=web_search_resolver,
                agent_delegate=agent_delegate,
                answer_planning_delegate=compatible_planning_delegate(agent_delegate),
                conversation_policy_store=conversation_policy_store,
                conversation_history_store=conversation_history_store,
                user_context_ontology_projector=user_context_ontology_projector,
                model_preference_resolver=(
                    getattr(model_settings, "preferred_model", None)
                    if model_settings is not None
                    else None
                ),
                answer_preference_resolver=_answer_preference_resolver(answer_preference_store),
                post_turn_review_submitter=post_turn_review_submitter,
                busy_input_coordinator=(
                    busy_input_runtime.coordinator if busy_input_runtime is not None else None
                ),
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
            logging.getLogger("fdai.delivery.read_api").info(
                "%s latency benchmark selected candidate=%s",
                label,
                chose,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - best-effort probe
            logging.getLogger("fdai.delivery.read_api").warning(
                "%s latency benchmark failed: %s",
                label,
                type(exc).__name__,
            )
        first_round = False
        await asyncio.sleep(interval_seconds)


__all__ = ["append_chat_routes", "is_routed_chat_backend", "periodic_latency_probe"]
