"""Application coordination for bounded chat request preparation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fdai.core.conversation.answer_plan import AnswerPlan, build_answer_plan
from fdai.core.conversation.answer_preferences import ResponsePreferenceProfile
from fdai.delivery.operator_api.application.conversation.backend import (
    ChatContentPolicyError,
    reject_direct_override,
)
from fdai.delivery.operator_api.application.conversation.capabilities.action_context import (
    needs_action_context,
)
from fdai.delivery.operator_api.application.conversation.capabilities.conversation_context import (
    load_verified_prior_context,
    needs_conversation_context,
)
from fdai.delivery.operator_api.application.conversation.capabilities.inventory.followup import (
    contextualize_inventory_scope_followup,
    contextualize_inventory_screen_scope,
)
from fdai.delivery.operator_api.application.conversation.capabilities.llm_usage import (
    is_llm_usage_followup,
)
from fdai.delivery.operator_api.application.conversation.capabilities.log_query import (
    needs_log_query_context,
)
from fdai.delivery.operator_api.application.conversation.capabilities.subscription_health import (
    needs_subscription_health_context,
)
from fdai.delivery.operator_api.application.conversation.freshness_context import (
    EvidenceFreshnessContext,
    missing_evidence_freshness_context_evidence,
    needs_evidence_freshness_context,
    parse_evidence_freshness_context,
)
from fdai.delivery.operator_api.application.conversation.vision_evidence import (
    VisionAttachment,
    parse_vision_attachments,
)
from fdai.shared.providers.document_ingestion import DocumentAccessDeniedError
from fdai.shared.providers.user_context import (
    ConversationHistoryStore,
    UserContextConflictError,
)

from .document_evidence import (
    ChatDocumentEvidenceResolver,
    resolve_document_refs,
)
from .history import (
    DEFAULT_CHAT_HISTORY_POLICY,
    ChatHistoryCompressor,
    ChatHistoryPolicy,
    resolve_chat_history_result,
)
from .identity import (
    AnswerPreferenceResolver,
    ModelPreferenceResolver,
    parse_conversation_context,
    resolve_request_id,
    resolve_session_id,
    resolve_target_agent,
)
from .replay import content_policy_replay_stage
from .resource_context import (
    contextualize_resource_followup,
    missing_read_investigation_context_evidence,
    parse_resource_context,
)


class InvalidChatRequestError(ValueError):
    """Raised when bounded chat request fields are invalid."""


class ChatContentRejectedError(ValueError):
    """Raised when request content violates the chat input policy."""


class ChatRequestConflictError(RuntimeError):
    """Raised when a request id conflicts with durable conversation state."""


class ChatDocumentAccessDeniedError(PermissionError):
    """Raised when the principal cannot access a referenced document."""


class ChatDocumentEvidenceUnavailableError(RuntimeError):
    """Raised when configured document evidence cannot be resolved."""


@dataclass(frozen=True, slots=True)
class ChatRequestPreparationInput:
    """Authenticated, byte-bounded JSON object passed by an HTTP adapter."""

    principal_id: str
    body: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ContentPolicyReplayRequest:
    user_id: str
    session_id: str
    request_id: str
    clean_prompt: str
    stage: str


@dataclass(frozen=True, slots=True)
class PreparedChatStreamRequest:
    user_id: str
    preferred_model: str | None
    answer_preferences: ResponsePreferenceProfile | None
    document_evidence_refs: tuple[str, ...]
    clean_prompt: str
    evidence_prompt: str
    resource_context: dict[str, str] | None
    freshness_context: EvidenceFreshnessContext | None
    resource_followup: bool
    inventory_screen_scope: bool
    inventory_scope_followup: bool
    view_context: dict[str, Any]
    conversation_context: dict[str, str] | None
    target_agent: str | None
    history: list[dict[str, str]]
    history_metadata: dict[str, str]
    answer_plan: AnswerPlan
    session_id: str
    request_id: str
    include_model_trace: bool
    vision_attachments: list[VisionAttachment]


async def prepare_chat_request(
    request_input: ChatRequestPreparationInput,
    *,
    model_preference_resolver: ModelPreferenceResolver | None,
    answer_preference_resolver: AnswerPreferenceResolver | None,
    document_evidence_resolver: ChatDocumentEvidenceResolver | None,
    conversation_history_store: ConversationHistoryStore | None,
    history_compressor: ChatHistoryCompressor,
    history_policy: ChatHistoryPolicy = DEFAULT_CHAT_HISTORY_POLICY,
) -> PreparedChatStreamRequest | ContentPolicyReplayRequest:
    """Prepare one authenticated chat request without owning HTTP transport."""

    user_id = request_input.principal_id
    body = request_input.body
    prompt = body.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise InvalidChatRequestError("prompt MUST be a non-empty string")
    clean_prompt = prompt.strip()
    try:
        reject_direct_override(clean_prompt)
    except ChatContentPolicyError as exc:
        raise ChatContentRejectedError(str(exc)) from exc
    try:
        session_id = resolve_session_id(body)
        request_id = resolve_request_id(body)
    except ValueError as exc:
        raise InvalidChatRequestError(str(exc)) from exc
    if conversation_history_store is not None:
        try:
            replay_stage = await content_policy_replay_stage(
                store=conversation_history_store,
                principal_id=user_id,
                conversation_id=session_id,
                request_id=request_id,
                content=clean_prompt,
            )
        except UserContextConflictError as exc:
            raise ChatRequestConflictError(
                "chat request id conflicts with an existing turn"
            ) from exc
        if replay_stage is not None:
            return ContentPolicyReplayRequest(
                user_id=user_id,
                session_id=session_id,
                request_id=request_id,
                clean_prompt=clean_prompt,
                stage=replay_stage,
            )
    preferred_model = (
        await model_preference_resolver(user_id) if model_preference_resolver is not None else None
    )
    answer_preferences = (
        await answer_preference_resolver(user_id)
        if answer_preference_resolver is not None
        else None
    )
    try:
        document_evidence_refs = await resolve_document_refs(
            body=body,
            principal_id=user_id,
            resolver=document_evidence_resolver,
        )
    except ValueError as exc:
        raise InvalidChatRequestError(str(exc)) from exc
    except DocumentAccessDeniedError as exc:
        raise ChatDocumentAccessDeniedError("document reference access denied") from exc
    except RuntimeError as exc:
        raise ChatDocumentEvidenceUnavailableError(str(exc)) from exc

    view_context = body.get("view_context")
    if view_context is None:
        view_context = {}
    if not isinstance(view_context, dict):
        raise InvalidChatRequestError("view_context MUST be an object")
    view_context.pop("_answer_plan", None)
    view_context.pop("_turn_plan", None)
    view_context.pop("_attachments", None)
    view_context.pop("_model_trace", None)
    view_context.pop("_inventory_screen_scope", None)
    view_context.pop("_resource_followup", None)
    view_context.pop("_verified_prior_context", None)
    include_model_trace = body.get("include_model_trace", False)
    if not isinstance(include_model_trace, bool):
        raise InvalidChatRequestError("include_model_trace MUST be a boolean")
    try:
        vision_attachments = parse_vision_attachments(body, request_id=request_id)
    except ValueError as exc:
        raise InvalidChatRequestError(str(exc)) from exc
    if vision_attachments:
        view_context["_attachments"] = [
            attachment.to_view_dict() for attachment in vision_attachments
        ]

    history_raw = body.get("history", [])
    if not isinstance(history_raw, list):
        raise InvalidChatRequestError("history MUST be a list")
    history: list[dict[str, str]] = []
    for turn in history_raw:
        if isinstance(turn, dict):
            role = turn.get("role")
            content = turn.get("content")
            if isinstance(role, str) and isinstance(content, str):
                history.append({"role": role, "content": content})

    history_result = await resolve_chat_history_result(
        store=conversation_history_store,
        principal_id=user_id,
        conversation_id=session_id,
        client_history=history,
        compressor=history_compressor,
        policy=history_policy,
    )
    history = list(history_result.messages)
    prior_context = None
    if (
        needs_conversation_context(clean_prompt)
        or is_llm_usage_followup(clean_prompt)
        or needs_subscription_health_context(clean_prompt)
        or needs_log_query_context(clean_prompt)
        or needs_evidence_freshness_context(clean_prompt)
    ):
        prior_context = await load_verified_prior_context(
            store=conversation_history_store,
            principal_id=user_id,
            conversation_id=session_id,
        )
        if prior_context is not None:
            view_context["_verified_prior_context"] = prior_context.to_dict()
    try:
        resource_context = parse_resource_context(body.get("resource_context"))
        freshness_context = parse_evidence_freshness_context(
            prior_context.evidence_freshness_context if prior_context is not None else None
        )
    except ValueError as exc:
        raise InvalidChatRequestError(str(exc)) from exc
    selector_hold = (
        None
        if needs_action_context(clean_prompt)
        or needs_conversation_context(clean_prompt)
        or needs_subscription_health_context(clean_prompt)
        else missing_read_investigation_context_evidence(clean_prompt, resource_context)
    )
    if selector_hold is None:
        selector_hold = missing_evidence_freshness_context_evidence(
            clean_prompt,
            freshness_context,
        )
    if selector_hold is not None:
        view_context["_read_investigation_context_hold"] = selector_hold
    evidence_prompt, resource_followup = contextualize_resource_followup(
        clean_prompt,
        resource_context,
    )
    if resource_followup:
        view_context["_resource_followup"] = {"authority": "selector_hint"}
    evidence_prompt, inventory_scope_followup = contextualize_inventory_scope_followup(
        evidence_prompt,
        history,
    )
    evidence_prompt, inventory_screen_scope_resolution = contextualize_inventory_screen_scope(
        evidence_prompt,
        view_context,
    )
    if inventory_screen_scope_resolution is not None:
        view_context["_inventory_screen_scope"] = inventory_screen_scope_resolution.to_context()
    answer_plan = build_answer_plan(
        evidence_prompt,
        route_id=str(view_context.get("routeId") or "") or None,
        preferences=answer_preferences,
    )
    view_context["_answer_plan"] = answer_plan.to_dict()
    try:
        conversation_context = parse_conversation_context(body)
        target_agent = resolve_target_agent(body, conversation_context)
    except ValueError as exc:
        raise InvalidChatRequestError(str(exc)) from exc
    return PreparedChatStreamRequest(
        user_id=user_id,
        preferred_model=preferred_model,
        answer_preferences=answer_preferences,
        document_evidence_refs=document_evidence_refs,
        clean_prompt=clean_prompt,
        evidence_prompt=evidence_prompt,
        resource_context=resource_context,
        freshness_context=freshness_context,
        resource_followup=resource_followup,
        inventory_screen_scope=inventory_screen_scope_resolution is not None,
        inventory_scope_followup=inventory_scope_followup,
        view_context=view_context,
        conversation_context=conversation_context,
        target_agent=target_agent,
        history=history,
        history_metadata=history_result.metadata(),
        answer_plan=answer_plan,
        session_id=session_id,
        request_id=request_id,
        include_model_trace=include_model_trace,
        vision_attachments=vision_attachments,
    )
