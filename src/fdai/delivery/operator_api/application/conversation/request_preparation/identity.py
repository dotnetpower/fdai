"""Bounded identity and preference contracts for chat request preparation."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Final

from fdai.agents import PANTHEON_NAMES
from fdai.core.conversation.answer_preferences import ResponsePreferenceProfile

DEFAULT_MAX_SESSION_ID_CHARS: Final[int] = 200

ModelPreferenceResolver = Callable[[str], Awaitable[str | None]]
AnswerPreferenceResolver = Callable[[str], Awaitable[ResponsePreferenceProfile | None]]


def parse_conversation_context(body: Mapping[str, Any]) -> dict[str, str] | None:
    """Validate an optional incident or action conversation selector."""

    raw = body.get("conversation_context")
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise ValueError("conversation_context MUST be an object")
    kind = raw.get("kind")
    if kind not in {"incident", "action"}:
        raise ValueError("conversation_context kind MUST be incident or action")
    context: dict[str, str] = {"kind": kind}
    required_fields = ("incident_id", "correlation_id") if kind == "incident" else ()
    optional_fields = (
        ()
        if kind == "incident"
        else ("action_id", "approval_id", "idempotency_key", "correlation_id")
    )
    for field in (*required_fields, *optional_fields):
        value = raw.get(field)
        if field in optional_fields and value is None:
            continue
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} MUST be a non-empty string")
        normalized = value.strip()
        if len(normalized) > 256:
            raise ValueError(f"{field} exceeds cap (256)")
        context[field] = normalized
    if kind == "action":
        if not any(field in context for field in ("action_id", "approval_id", "idempotency_key")):
            raise ValueError("action conversation_context requires an exact selector")
        if "correlation_id" not in context:
            raise ValueError("action conversation_context requires correlation_id")
    selected_agent = raw.get("selected_agent")
    if selected_agent is not None:
        if not isinstance(selected_agent, str) or selected_agent not in PANTHEON_NAMES:
            raise ValueError("selected_agent MUST name a Pantheon agent")
        context["selected_agent"] = selected_agent
    return context


def resolve_target_agent(
    body: Mapping[str, Any],
    conversation_context: Mapping[str, str] | None,
) -> str | None:
    """Validate the requested Pantheon target against conversation context."""

    raw = body.get("target_agent")
    if raw is None:
        return None
    if not isinstance(raw, str) or raw not in PANTHEON_NAMES:
        raise ValueError("target_agent MUST name a Pantheon agent")
    selected_agent = (
        conversation_context.get("selected_agent") if conversation_context is not None else None
    )
    if selected_agent is not None and raw != selected_agent:
        raise ValueError("target_agent MUST match conversation_context.selected_agent")
    return raw


def resolve_session_id(body: Mapping[str, Any]) -> str:
    """Return the bounded conversation id for a chat request."""

    raw = body.get("session_id")
    if raw is None:
        return "default"
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("session_id MUST be a non-empty string")
    value = raw.strip()
    if len(value) > DEFAULT_MAX_SESSION_ID_CHARS:
        raise ValueError(f"session_id exceeds cap ({len(value)} > {DEFAULT_MAX_SESSION_ID_CHARS})")
    return value


def resolve_request_id(body: Mapping[str, Any]) -> str:
    """Return a bounded caller id or create a process-local request id."""

    raw = body.get("request_id")
    if raw is None:
        return f"chat-{uuid.uuid4()}"
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("request_id MUST be a non-empty string")
    value = raw.strip()
    if len(value) > 128:
        raise ValueError("request_id exceeds cap (128)")
    return value


__all__ = [
    "AnswerPreferenceResolver",
    "DEFAULT_MAX_SESSION_ID_CHARS",
    "ModelPreferenceResolver",
    "parse_conversation_context",
    "resolve_request_id",
    "resolve_session_id",
    "resolve_target_agent",
]
