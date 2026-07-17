"""Shared validation, metadata, and policy helpers for chat routes."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Final

from starlette.exceptions import HTTPException
from starlette.requests import Request

from fdai.core.conversation.answer_preferences import ResponsePreferenceProfile
from fdai.core.conversation.policy_prompt import UserPolicyCompiler
from fdai.delivery.read_api.routes.chat_prompt import _COMPILED_USER_POLICY_KEY
from fdai.shared.providers.briefing import ConversationPolicyStore

DEFAULT_MAX_BODY_BYTES: Final[int] = 200_000


DEFAULT_MAX_HISTORY_ITEMS: Final[int] = 200


DEFAULT_MAX_SESSION_ID_CHARS: Final[int] = 200


def _turn_metadata(
    *,
    model: str,
    view_context: Mapping[str, Any],
    answer_planning: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    """Persist replay evidence while keeping it out of the browser payload."""

    metadata: dict[str, Any] = {"model": model}
    web = view_context.get("_web_evidence")
    if isinstance(web, Mapping):
        metadata["web_evidence"] = dict(web)
    if answer_planning is not None:
        metadata["answer_planning"] = dict(answer_planning)
    return metadata


def _session_id(body: Mapping[str, Any]) -> str:
    raw = body.get("session_id")
    if raw is None:
        return "default"
    if not isinstance(raw, str) or not raw.strip():
        raise HTTPException(status_code=400, detail="session_id MUST be a non-empty string")
    value = raw.strip()
    if len(value) > DEFAULT_MAX_SESSION_ID_CHARS:
        raise HTTPException(
            status_code=400,
            detail=f"session_id exceeds cap ({len(value)} > {DEFAULT_MAX_SESSION_ID_CHARS})",
        )
    return value


def _request_id(body: Mapping[str, Any]) -> str:
    raw = body.get("request_id")
    if raw is None:
        return f"chat-{uuid.uuid4()}"
    if not isinstance(raw, str) or not raw.strip():
        raise HTTPException(status_code=400, detail="request_id MUST be a non-empty string")
    value = raw.strip()
    if len(value) > 128:
        raise HTTPException(status_code=400, detail="request_id exceeds cap (128)")
    return value


def _semantic_verification_enabled(body: Mapping[str, Any]) -> bool:
    raw = body.get("verification_preferences")
    if raw is None:
        return False
    if not isinstance(raw, Mapping):
        raise HTTPException(
            status_code=400,
            detail="verification_preferences MUST be an object",
        )
    enabled = raw.get("semantic_enabled", False)
    if not isinstance(enabled, bool):
        raise HTTPException(
            status_code=400,
            detail="verification_preferences.semantic_enabled MUST be boolean",
        )
    return enabled


def _uses_evidence_fast_path(view_context: Mapping[str, Any]) -> bool:
    """Return whether server evidence can render the answer without a model."""

    raw = view_context.get("_operational_evidence")
    if not isinstance(raw, Mapping):
        return False
    if raw.get("status") != "matched":
        return True
    hypotheses = raw.get("grounded_hypotheses")
    return not isinstance(hypotheses, list) or len(hypotheses) == 0


AuthorizeFn = Callable[[Request], Awaitable[str]]


ModelPreferenceResolver = Callable[[str], Awaitable[str | None]]


AnswerPreferenceResolver = Callable[[str], Awaitable[ResponsePreferenceProfile | None]]


async def _with_compiled_user_policy(
    view_context: dict[str, Any],
    *,
    user_id: str,
    store: ConversationPolicyStore | None,
) -> dict[str, Any]:
    enriched = dict(view_context)
    enriched.pop(_COMPILED_USER_POLICY_KEY, None)
    if store is None:
        return enriched
    policies = tuple(await store.list_for_principal(principal_id=user_id))
    compiled = UserPolicyCompiler().compile(policies)
    if compiled is None:
        return enriched
    enriched[_COMPILED_USER_POLICY_KEY] = {
        "text": compiled.system_text,
        "policy_refs": list(compiled.policy_refs),
        "compiler_version": compiled.compiler_version,
    }
    return enriched
