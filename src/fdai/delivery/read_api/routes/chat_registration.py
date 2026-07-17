"""Command Deck route registration for the read API composition root."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Collection
from datetime import UTC, datetime
from typing import Any

from starlette.requests import Request
from starlette.routing import BaseRoute

from fdai.core.conversation.answer_plan import AnswerFormat, AnswerIntent, DetailLevel
from fdai.core.conversation.answer_preferences import ResponsePreferenceProfile
from fdai.core.user_context_projection import UserContextOntologyProjector
from fdai.delivery.read_api.read_model import ConsoleReadModel
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
from fdai.delivery.read_api.routes.chat_evidence import OperationalEvidenceResolver
from fdai.delivery.read_api.routes.chat_system_health import SystemHealthChatTools
from fdai.delivery.read_api.routes.chat_tools import ReadModelChatTools
from fdai.shared.providers.briefing import ConversationPolicyStore
from fdai.shared.providers.user_context import ConversationHistoryStore, UserPreferenceStore


def append_chat_routes(
    routes: list[BaseRoute],
    *,
    backend: ChatBackend | None,
    agent_delegate: AgentChatDelegate | None,
    web_search_resolver: ChatWebSearchEvidenceResolver | None = None,
    conversation_policy_store: ConversationPolicyStore | None = None,
    conversation_history_store: ConversationHistoryStore | None = None,
    answer_preference_store: UserPreferenceStore | None = None,
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
    tools = SystemHealthChatTools(read_model, ReadModelChatTools(read_model))
    routes.extend(
        (
            make_chat_route(
                backend=backend,
                authorize=authorize,
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
            ),
            make_chat_stream_route(
                backend=backend,
                authorize=authorize,
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
            ),
            make_chat_health_route(
                backend=backend,
                authorize=authorize,
                web_search_resolver=web_search_resolver,
            ),
        )
    )

    descriptor = describe_backend(backend)
    if descriptor.get("available"):
        logger.warning(
            "CommandDeck chat backend ready: mode=%s model=%s endpoint=%s",
            descriptor.get("mode"),
            descriptor.get("model"),
            descriptor.get("endpoint"),
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
