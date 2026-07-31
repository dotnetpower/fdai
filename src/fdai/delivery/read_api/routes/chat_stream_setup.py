"""Authenticated request preparation for the chat SSE route."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from starlette.exceptions import HTTPException
from starlette.requests import Request

from fdai.core.conversation.answer_plan import AnswerPlan, build_answer_plan
from fdai.core.conversation.answer_preferences import ResponsePreferenceProfile
from fdai.delivery.read_api.routes.chat_backend_common import _reject_direct_override
from fdai.delivery.read_api.routes.chat_document_evidence import (
    ChatDocumentEvidenceResolver,
    resolve_document_refs,
)
from fdai.delivery.read_api.routes.chat_inventory_followup import (
    contextualize_inventory_scope_followup,
    contextualize_inventory_screen_scope,
)
from fdai.delivery.read_api.routes.chat_resource_context import (
    contextualize_resource_followup,
    parse_resource_context,
)
from fdai.delivery.read_api.routes.chat_route_common import (
    DEFAULT_MAX_HISTORY_ITEMS,
    AnswerPreferenceResolver,
    AuthorizeFn,
    ModelPreferenceResolver,
    _conversation_context,
    _request_id,
    _session_id,
    _target_agent,
)
from fdai.delivery.read_api.routes.chat_stream_request import read_chat_stream_body
from fdai.delivery.read_api.routes.chat_vision_evidence import parse_vision_attachments
from fdai.shared.providers.document_ingestion import DocumentAccessDeniedError


@dataclass(frozen=True, slots=True)
class PreparedChatStreamRequest:
    user_id: str
    preferred_model: str | None
    answer_preferences: ResponsePreferenceProfile | None
    document_evidence_refs: tuple[str, ...]
    clean_prompt: str
    evidence_prompt: str
    resource_context: dict[str, str] | None
    resource_followup: bool
    inventory_screen_scope: bool
    inventory_scope_followup: bool
    view_context: dict[str, Any]
    conversation_context: dict[str, str] | None
    target_agent: str | None
    history: list[dict[str, str]]
    answer_plan: AnswerPlan
    session_id: str
    request_id: str
    include_model_trace: bool


async def prepare_chat_stream_request(
    request: Request,
    *,
    authorize: AuthorizeFn,
    model_preference_resolver: ModelPreferenceResolver | None,
    answer_preference_resolver: AnswerPreferenceResolver | None,
    document_evidence_resolver: ChatDocumentEvidenceResolver | None,
    max_body_bytes: int,
) -> PreparedChatStreamRequest:
    user_id = await authorize(request)
    preferred_model = (
        await model_preference_resolver(user_id) if model_preference_resolver is not None else None
    )
    answer_preferences = (
        await answer_preference_resolver(user_id)
        if answer_preference_resolver is not None
        else None
    )
    body = await read_chat_stream_body(request, max_body_bytes=max_body_bytes)
    try:
        document_evidence_refs = await resolve_document_refs(
            body=body,
            principal_id=user_id,
            resolver=document_evidence_resolver,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DocumentAccessDeniedError as exc:
        raise HTTPException(status_code=403, detail="document reference access denied") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc

    prompt = body.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise HTTPException(status_code=400, detail="prompt MUST be a non-empty string")
    view_context = body.get("view_context")
    if view_context is None:
        view_context = {}
    if not isinstance(view_context, dict):
        raise HTTPException(status_code=400, detail="view_context MUST be an object")
    view_context.pop("_answer_plan", None)
    view_context.pop("_turn_plan", None)
    view_context.pop("_attachments", None)
    view_context.pop("_model_trace", None)
    view_context.pop("_inventory_screen_scope", None)
    include_model_trace = body.get("include_model_trace", False)
    if not isinstance(include_model_trace, bool):
        raise HTTPException(status_code=400, detail="include_model_trace MUST be a boolean")
    try:
        vision_attachments = parse_vision_attachments(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if vision_attachments:
        view_context["_attachments"] = [
            attachment.to_view_dict() for attachment in vision_attachments
        ]

    history_raw = body.get("history", [])
    if not isinstance(history_raw, list):
        raise HTTPException(status_code=400, detail="history MUST be a list")
    if len(history_raw) > DEFAULT_MAX_HISTORY_ITEMS:
        raise HTTPException(status_code=400, detail="history exceeds cap")
    history: list[dict[str, str]] = []
    for turn in history_raw:
        if isinstance(turn, dict):
            role = turn.get("role")
            content = turn.get("content")
            if isinstance(role, str) and isinstance(content, str):
                history.append({"role": role, "content": content})

    clean_prompt = prompt.strip()
    _reject_direct_override(clean_prompt)
    try:
        resource_context = parse_resource_context(body.get("resource_context"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    evidence_prompt, resource_followup = contextualize_resource_followup(
        clean_prompt,
        resource_context,
    )
    evidence_prompt, inventory_scope_followup = contextualize_inventory_scope_followup(
        evidence_prompt,
        history,
    )
    evidence_prompt, inventory_screen_scope = contextualize_inventory_screen_scope(
        evidence_prompt,
        view_context,
    )
    if inventory_screen_scope:
        view_context["_inventory_screen_scope"] = {"authority": "selector_hint"}
    answer_plan = build_answer_plan(
        evidence_prompt,
        route_id=str(view_context.get("routeId") or "") or None,
        preferences=answer_preferences,
    )
    view_context["_answer_plan"] = answer_plan.to_dict()
    conversation_context = _conversation_context(body)
    return PreparedChatStreamRequest(
        user_id=user_id,
        preferred_model=preferred_model,
        answer_preferences=answer_preferences,
        document_evidence_refs=document_evidence_refs,
        clean_prompt=clean_prompt,
        evidence_prompt=evidence_prompt,
        resource_context=resource_context,
        resource_followup=resource_followup,
        inventory_screen_scope=inventory_screen_scope,
        inventory_scope_followup=inventory_scope_followup,
        view_context=view_context,
        conversation_context=conversation_context,
        target_agent=_target_agent(body, conversation_context),
        history=history,
        answer_plan=answer_plan,
        session_id=_session_id(body),
        request_id=_request_id(body),
        include_model_trace=include_model_trace,
    )
