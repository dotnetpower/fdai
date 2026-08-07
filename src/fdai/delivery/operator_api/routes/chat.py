"""HTTP transport and compatibility facade for Operator API conversations.

The JSON route owns authentication, bounded HTTP body parsing, application
error-to-status mapping, and ``JSONResponse`` delivery. One-shot lifecycle
coordination lives in ``application.conversation.turn_execution``. SSE remains
owned by ``chat_stream`` until its reserved extraction slice.
"""

# ruff: noqa: F401 - this module intentionally re-exports reviewed compatibility symbols

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Final

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from fdai.core.conversation.busy_input_coordinator import BusyInputCoordinator
from fdai.core.conversation_assurance import ConversationPolicyRuntime
from fdai.core.user_context_projection import UserContextOntologyProjector
from fdai.delivery.conversation_images import ConversationImageStore
from fdai.delivery.handover_events import HandoverAvailabilityPublisher
from fdai.delivery.operator_api.application import ConversationTurnApplicationService
from fdai.delivery.operator_api.application.conversation.backend import (
    ChatBackend,
    describe_backend,
)
from fdai.delivery.operator_api.application.conversation.evidence import (
    AgentChatDelegate,
    ChatBehaviorEvidenceResolver,
    ChatToolResolver,
    ChatWebSearchEvidenceResolver,
    OperationalEvidenceResolverProtocol,
    PlannedChatToolResolver,
)
from fdai.delivery.operator_api.application.conversation.intent_graph import IntentGraphPlanner
from fdai.delivery.operator_api.application.conversation.planning import AnswerPlanningDelegate
from fdai.delivery.operator_api.application.conversation.prompt import (
    _AGENT_EVIDENCE_DIRECTIVE,
    _AGENT_NAME_TOKEN,
    _CAPABILITIES,
    _CAPABILITY_INTENT,
    _COMPILED_USER_POLICY_KEY,
    _CONCEPT_DOMAIN,
    _CONCEPT_EVIDENCE_DIRECTIVE,
    _CONCEPT_INTENT,
    _CONCEPT_PHRASING,
    _DATA_WORD,
    _GLOSSARY,
    _GLOSSARY_ALIASES,
    _GLOSSARY_STOP,
    _HOW_TO_GET_INTENT,
    _KOREAN_TEXT,
    _LOCALE_TAG,
    _OPERATIONAL_EVIDENCE_DIRECTIVE,
    _ROLE_EXPLAIN_INTENT,
    _ROLE_TOKEN,
    _SCREEN_EXPLANATION_DIRECTIVE,
    _SYSTEM_PROMPT,
    _TOOL_EVIDENCE_DIRECTIVE,
    _WEB_EVIDENCE_DIRECTIVE,
    _WHO_TOKEN,
    DEFAULT_MAX_CONTEXT_BYTES,
    DEFAULT_MAX_EXPLANATION_ITEMS,
    DEFAULT_MAX_RECORDS_PER_KEY,
    _build_messages,
    _concept_answer,
    _extract_locale,
    _glossary_matches,
    _is_capability_query,
    _is_concept_query,
    _is_grounded_concept_query,
    _locale_directive,
    _ontology_browse_answer,
    _response_locale,
    _snapshot_json_capped,
    _trim_view_context,
    _with_concept_evidence,
)
from fdai.delivery.operator_api.application.conversation.request_preparation import (
    DEFAULT_CHAT_HISTORY_POLICY,
    AnswerPreferenceResolver,
    ChatDocumentEvidenceResolver,
    ChatHistoryPolicy,
    ModelPreferenceResolver,
)
from fdai.delivery.operator_api.application.conversation.turn_execution import (
    JsonTurnExecutionError,
    JsonTurnExecutionService,
    JsonTurnOutcome,
)
from fdai.delivery.operator_api.application.conversation.turn_plan import TurnPlanner, TurnTool
from fdai.delivery.operator_api.routes.chat_stream import (
    DEFAULT_STREAM_PATH,
    make_chat_stream_route,
)
from fdai.delivery.operator_api.routes.chat_stream_protocol import (
    _CHUNK_RE,
    DEFAULT_STREAM_HEARTBEAT_S,
    _chunk_answer_for_stream,
    _sse,
    _sse_heartbeat,
    _with_sse_heartbeats,
)
from fdai.delivery.operator_api.routes.chat_stream_request import (
    DEFAULT_MAX_CHAT_BODY_BYTES,
    AuthorizeFn,
)
from fdai.delivery.operator_api.routes.post_turn_review import PostTurnReviewSubmitter
from fdai.shared.providers.briefing import ConversationPolicyStore
from fdai.shared.providers.user_context import ConversationHistoryStore

DEFAULT_ROUTE_PATH: Final[str] = "/chat"

_APPLICATION_ERROR_STATUSES: Final[dict[str, int]] = {
    "backend_unavailable": 501,
    "content_policy_block": 422,
    "content_policy_receipt_unavailable": 503,
    "document_access_denied": 403,
    "document_evidence_unavailable": 501,
    "image_conflict": 409,
    "image_quota_exceeded": 429,
    "image_storage_unavailable": 503,
    "invalid_request": 400,
    "request_conflict": 409,
    "session_busy": 409,
}
_OUTCOME_STATUSES: Final[dict[JsonTurnOutcome, int]] = {
    JsonTurnOutcome.COMPLETED: 200,
    JsonTurnOutcome.INTERRUPTED: 409,
    JsonTurnOutcome.CONFLICT: 409,
    JsonTurnOutcome.UNAVAILABLE: 503,
}


def make_chat_health_route(
    *,
    backend: ChatBackend,
    authorize: AuthorizeFn,
    web_search_resolver: ChatWebSearchEvidenceResolver | None = None,
    path: str = "/chat/health",
) -> Route:
    """Return the authenticated chat backend health route."""

    async def handler(request: Request) -> JSONResponse:
        await authorize(request)
        descriptor = describe_backend(backend)
        web_descriptor = getattr(web_search_resolver, "descriptor", None)
        descriptor["web_search"] = (
            web_descriptor() if web_descriptor is not None else {"available": False}
        )
        return JSONResponse(descriptor)

    return Route(path, handler, methods=["GET"])


def make_chat_route(
    *,
    backend: ChatBackend,
    authorize: AuthorizeFn,
    behavior_resolver: ChatBehaviorEvidenceResolver | None = None,
    evidence_resolver: OperationalEvidenceResolverProtocol | None = None,
    tool_resolver: ChatToolResolver | None = None,
    planned_tool_resolver: PlannedChatToolResolver | None = None,
    web_search_resolver: ChatWebSearchEvidenceResolver | None = None,
    agent_delegate: AgentChatDelegate | None = None,
    answer_planning_delegate: AnswerPlanningDelegate | None = None,
    conversation_policy_store: ConversationPolicyStore | None = None,
    conversation_assurance_runtime: ConversationPolicyRuntime | None = None,
    conversation_history_store: ConversationHistoryStore | None = None,
    conversation_image_store: ConversationImageStore | None = None,
    user_context_ontology_projector: UserContextOntologyProjector | None = None,
    model_preference_resolver: ModelPreferenceResolver | None = None,
    answer_preference_resolver: AnswerPreferenceResolver | None = None,
    post_turn_review_submitter: PostTurnReviewSubmitter | None = None,
    busy_input_coordinator: BusyInputCoordinator | None = None,
    document_evidence_resolver: ChatDocumentEvidenceResolver | None = None,
    turn_planner: TurnPlanner | IntentGraphPlanner | None = None,
    turn_tools: tuple[TurnTool, ...] | Callable[[], tuple[TurnTool, ...]] = (),
    handover_availability_publisher: HandoverAvailabilityPublisher | None = None,
    history_policy: ChatHistoryPolicy = DEFAULT_CHAT_HISTORY_POLICY,
    turn_service: ConversationTurnApplicationService | None = None,
    path: str = DEFAULT_ROUTE_PATH,
    max_body_bytes: int = DEFAULT_MAX_CHAT_BODY_BYTES,
) -> Route:
    """Build the authenticated ``POST /chat`` transport adapter."""

    executor = JsonTurnExecutionService(
        backend=backend,
        behavior_resolver=behavior_resolver,
        evidence_resolver=evidence_resolver,
        tool_resolver=tool_resolver,
        planned_tool_resolver=planned_tool_resolver,
        web_search_resolver=web_search_resolver,
        agent_delegate=agent_delegate,
        answer_planning_delegate=answer_planning_delegate,
        conversation_policy_store=conversation_policy_store,
        conversation_assurance_runtime=conversation_assurance_runtime,
        conversation_history_store=conversation_history_store,
        conversation_image_store=conversation_image_store,
        user_context_ontology_projector=user_context_ontology_projector,
        model_preference_resolver=model_preference_resolver,
        answer_preference_resolver=answer_preference_resolver,
        post_turn_review_submitter=post_turn_review_submitter,
        busy_input_coordinator=busy_input_coordinator,
        document_evidence_resolver=document_evidence_resolver,
        turn_planner=turn_planner,
        turn_tools=turn_tools,
        handover_availability_publisher=handover_availability_publisher,
        history_policy=history_policy,
        turn_service=turn_service,
    )

    async def handler(request: Request) -> JSONResponse:
        principal_id = await authorize(request)
        body = await _read_json_body(request, max_body_bytes=max_body_bytes)
        try:
            result = await executor.execute(principal_id=principal_id, body=body)
        except JsonTurnExecutionError as exc:
            status_code = _APPLICATION_ERROR_STATUSES.get(exc.code)
            if status_code is None:
                raise RuntimeError(f"unmapped JSON turn error code: {exc.code}") from exc
            raise HTTPException(status_code=status_code, detail=exc.detail) from exc
        return JSONResponse(result.payload, status_code=_OUTCOME_STATUSES[result.outcome])

    return Route(path, handler, methods=["POST"])


async def _read_json_body(request: Request, *, max_body_bytes: int) -> dict[str, Any]:
    declared_len = request.headers.get("content-length")
    if declared_len is not None:
        try:
            if int(declared_len) > max_body_bytes:
                raise HTTPException(status_code=413, detail="chat body too large")
        except ValueError:
            pass
    body_bytes = await request.body()
    if len(body_bytes) > max_body_bytes:
        raise HTTPException(status_code=413, detail="chat body too large")
    try:
        body = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="chat body MUST be JSON") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="chat body MUST be a JSON object")
    return body


__all__ = [
    "AgentChatDelegate",
    "ChatWebSearchEvidenceResolver",
    "make_chat_health_route",
    "make_chat_route",
    "make_chat_stream_route",
]
