"""Frozen legacy-compatible route manifest for the conversation family."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

RouteMode = Literal["read", "proposal", "stream"]
RouteMethod = Literal["DELETE", "GET", "POST", "PUT"]


@dataclass(frozen=True, slots=True)
class ConversationRouteSpec:
    """Declare one owned route and its boundary behavior."""

    method: RouteMethod
    path: str
    name: str
    operation: str
    mode: RouteMode
    success_status: int = 200
    max_body_bytes: int = 0
    requires_confirmation: bool = False


CONVERSATION_ROUTE_MANIFEST: tuple[ConversationRouteSpec, ...] = (
    ConversationRouteSpec("GET", "/chat/health", "handler", "chat.health", "read"),
    ConversationRouteSpec("POST", "/chat", "handler", "chat.exchange", "proposal", 200, 1_048_576),
    ConversationRouteSpec(
        "POST", "/chat/stream", "handler", "chat.stream", "stream", 200, 1_048_576
    ),
    ConversationRouteSpec(
        "POST", "/chat/busy-input", "submit", "busy.submit", "proposal", 202, 8_192
    ),
    ConversationRouteSpec("GET", "/chat/busy-input", "inspect", "busy.inspect", "read"),
    ConversationRouteSpec(
        "PUT", "/chat/busy-input/mode", "set_mode", "busy.set_mode", "proposal", 200, 8_192
    ),
    ConversationRouteSpec(
        "POST",
        "/chat/busy-input/cancel-current",
        "cancel_current",
        "busy.cancel_current",
        "proposal",
        202,
        8_192,
    ),
    ConversationRouteSpec(
        "POST", "/background-tasks", "create_task", "background.create", "proposal", 202, 16_000
    ),
    ConversationRouteSpec("GET", "/background-tasks", "list_tasks", "background.list", "read"),
    ConversationRouteSpec(
        "GET", "/background-tasks/{task_id}", "get_task", "background.get", "read"
    ),
    ConversationRouteSpec(
        "GET",
        "/background-tasks/{task_id}/progress",
        "get_progress",
        "background.progress",
        "read",
    ),
    ConversationRouteSpec(
        "GET",
        "/background-tasks/{task_id}/progress/stream",
        "stream_progress",
        "background.progress_stream",
        "stream",
    ),
    ConversationRouteSpec(
        "POST",
        "/background-tasks/{task_id}/cancel",
        "cancel_task",
        "background.cancel",
        "proposal",
        200,
        16_000,
    ),
    ConversationRouteSpec("GET", "/task-workers", "list_workers", "workers.list", "read"),
    ConversationRouteSpec("GET", "/task-workers/{worker_id}", "get_worker", "workers.get", "read"),
    ConversationRouteSpec(
        "GET",
        "/task-workers/{worker_id}/events",
        "list_events",
        "workers.events",
        "read",
    ),
    ConversationRouteSpec("GET", "/me/context", "context", "user.context", "read"),
    ConversationRouteSpec(
        "GET", "/me/conversations", "conversation_page", "user.conversations", "read"
    ),
    ConversationRouteSpec(
        "GET",
        "/me/conversations/search",
        "search_conversations",
        "user.conversations.search",
        "read",
    ),
    ConversationRouteSpec(
        "GET",
        "/me/conversations/search/{result_id:str}/context",
        "conversation_search_context",
        "user.conversations.search_context",
        "read",
    ),
    ConversationRouteSpec(
        "GET",
        "/me/conversations/{conversation_id:str}/lineage",
        "conversation_lineage",
        "user.conversations.lineage",
        "read",
    ),
    ConversationRouteSpec(
        "GET",
        "/me/conversations/{conversation_id:str}/turns",
        "conversation_turns",
        "user.conversations.turns",
        "read",
    ),
    ConversationRouteSpec(
        "GET",
        "/me/conversations/{conversation_id:str}/images/{image_id:str}",
        "conversation_image",
        "user.conversations.image",
        "read",
    ),
    ConversationRouteSpec(
        "DELETE",
        "/me/conversations/{conversation_id:str}",
        "delete_conversation",
        "user.conversations.delete",
        "proposal",
        204,
    ),
    ConversationRouteSpec(
        "PUT", "/me/preferences", "put_preference", "user.preferences.put", "proposal", 200, 65_536
    ),
    ConversationRouteSpec(
        "DELETE", "/me/preferences", "delete_preference", "user.preferences.delete", "proposal", 204
    ),
    ConversationRouteSpec(
        "POST",
        "/me/memories",
        "create_memory",
        "user.memories.create",
        "proposal",
        201,
        65_536,
        True,
    ),
    ConversationRouteSpec(
        "DELETE",
        "/me/memories/{memory_id:str}",
        "delete_memory",
        "user.memories.delete",
        "proposal",
        204,
    ),
    ConversationRouteSpec(
        "PUT",
        "/me/policies",
        "put_policy",
        "user.policies.put",
        "proposal",
        200,
        65_536,
        True,
    ),
    ConversationRouteSpec(
        "DELETE",
        "/me/policies/{policy_id:str}",
        "delete_policy",
        "user.policies.delete",
        "proposal",
        204,
    ),
    ConversationRouteSpec(
        "POST",
        "/me/briefing-subscriptions",
        "create_subscription",
        "user.briefings.subscribe",
        "proposal",
        201,
        65_536,
        True,
    ),
    ConversationRouteSpec(
        "DELETE",
        "/me/briefing-subscriptions/{subscription_id:str}",
        "delete_subscription",
        "user.briefings.unsubscribe",
        "proposal",
        204,
    ),
    ConversationRouteSpec(
        "POST",
        "/me/opening-briefing",
        "opening_briefing",
        "user.briefings.open",
        "proposal",
        200,
        65_536,
    ),
    ConversationRouteSpec(
        "POST",
        "/me/scheduled-continuations/{anchor_id:str}/open",
        "open_continuation",
        "user.continuations.open",
        "proposal",
        200,
        65_536,
    ),
    ConversationRouteSpec(
        "DELETE",
        "/me/scheduled-continuations/{anchor_id:str}",
        "expire_continuation",
        "user.continuations.expire",
        "proposal",
        200,
    ),
    ConversationRouteSpec(
        "GET", "/conversation-assurance", "get_assurance", "assurance.list", "read"
    ),
    ConversationRouteSpec(
        "GET",
        "/conversation-assurance/{assessment_id:str}",
        "get_assessment_detail",
        "assurance.get",
        "read",
    ),
    ConversationRouteSpec(
        "POST",
        "/conversation-assurance/{assessment_id:str}/disputes",
        "post_dispute",
        "assurance.dispute",
        "proposal",
        201,
        8_000,
    ),
)


__all__ = ["CONVERSATION_ROUTE_MANIFEST", "ConversationRouteSpec"]
