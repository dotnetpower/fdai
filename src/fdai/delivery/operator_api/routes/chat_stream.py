"""Server-Sent Events transport for read-only console chat."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Any, Final

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import StreamingResponse
from starlette.routing import Route

from fdai.core.conversation.busy_input_coordinator import BusyInputCoordinator
from fdai.core.conversation_assurance import ConversationPolicyRuntime
from fdai.core.user_context_projection import UserContextOntologyProjector
from fdai.delivery.conversation_images import ConversationImageStore
from fdai.delivery.operator_api.application import ConversationTurnApplicationService
from fdai.delivery.operator_api.application.conversation.backend import ChatBackend
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
from fdai.delivery.operator_api.application.conversation.request_preparation import (
    DEFAULT_CHAT_HISTORY_POLICY,
    AnswerPreferenceResolver,
    BackendChatHistoryCompressor,
    ChatDocumentEvidenceResolver,
    ChatHistoryPolicy,
    ModelPreferenceResolver,
)
from fdai.delivery.operator_api.application.conversation.review_submission import (
    PostTurnReviewSubmitter,
)
from fdai.delivery.operator_api.application.conversation.turn_execution import (
    StreamTurnExecutionError,
    StreamTurnExecutionService,
)
from fdai.delivery.operator_api.application.conversation.turn_plan import TurnPlanner, TurnTool
from fdai.delivery.operator_api.routes.chat_stream_protocol import (
    DEFAULT_STREAM_HEARTBEAT_S,
    _chunk_answer_for_stream,
    _sse,
    _sse_heartbeat,
    _with_sse_heartbeats,
)
from fdai.delivery.operator_api.routes.chat_stream_request import (
    DEFAULT_MAX_CHAT_BODY_BYTES,
    AuthorizeFn,
    prepare_chat_stream_request,
)
from fdai.shared.providers.briefing import ConversationPolicyStore
from fdai.shared.providers.user_context import ConversationHistoryStore
from fdai.shared.telemetry import ConversationProgressMetrics

DEFAULT_STREAM_PATH: Final[str] = "/chat/stream"


def make_chat_stream_route(
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
    progress_metrics: ConversationProgressMetrics | None = None,
    turn_planner: TurnPlanner | IntentGraphPlanner | None = None,
    turn_tools: tuple[TurnTool, ...] | Callable[[], tuple[TurnTool, ...]] = (),
    history_policy: ChatHistoryPolicy = DEFAULT_CHAT_HISTORY_POLICY,
    turn_service: ConversationTurnApplicationService | None = None,
    path: str = DEFAULT_STREAM_PATH,
    max_body_bytes: int = DEFAULT_MAX_CHAT_BODY_BYTES,
) -> Route:
    """Build the authenticated ``POST /chat/stream`` SSE transport route."""

    history_compressor = BackendChatHistoryCompressor(
        backend=backend,
        max_summary_chars=history_policy.max_summary_chars,
    )

    def idle_events(
        source: AsyncIterator[dict[str, Any]],
    ) -> AsyncIterator[dict[str, Any] | None]:
        return _with_sse_heartbeats(source, interval=DEFAULT_STREAM_HEARTBEAT_S)

    def upstream_status(exc: BaseException) -> int | None:
        if not isinstance(exc, HTTPException):
            return None
        return exc.status_code if 400 <= exc.status_code <= 599 else 500

    execution_service = StreamTurnExecutionService(
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
        post_turn_review_submitter=post_turn_review_submitter,
        busy_input_coordinator=busy_input_coordinator,
        progress_metrics=progress_metrics,
        turn_planner=turn_planner,
        turn_tools=turn_tools,
        history_policy=history_policy,
        turn_service=turn_service,
        idle_events=idle_events,
        chunk_answer=_chunk_answer_for_stream,
        upstream_status=upstream_status,
    )

    async def handler(request: Request) -> StreamingResponse:
        prepared = await prepare_chat_stream_request(
            request,
            authorize=authorize,
            model_preference_resolver=model_preference_resolver,
            answer_preference_resolver=answer_preference_resolver,
            document_evidence_resolver=document_evidence_resolver,
            conversation_history_store=conversation_history_store,
            history_compressor=history_compressor,
            history_policy=history_policy,
            max_body_bytes=max_body_bytes,
        )
        try:
            execution = await execution_service.start(prepared)
        except StreamTurnExecutionError as exc:
            raise HTTPException(
                status_code=_setup_error_status(exc.code),
                detail=exc.detail,
            ) from exc

        async def event_source() -> AsyncIterator[bytes]:
            sequence = 0
            async for event in execution.events:
                if event.event is None:
                    yield _sse_heartbeat()
                    continue
                sequence += 1
                try:
                    encoded = _sse(
                        event.event,
                        {
                            **(event.payload or {}),
                            "v": 1,
                            "request_id": execution.request_id,
                            "seq": sequence,
                            "revision": event.revision,
                        },
                    )
                except ValueError as exc:
                    recovered = await execution.recover_transport_error(exc)
                    if recovered is None or recovered.event is None:
                        return
                    sequence += 1
                    yield _sse(
                        recovered.event,
                        {
                            **(recovered.payload or {}),
                            "v": 1,
                            "request_id": execution.request_id,
                            "seq": sequence,
                            "revision": recovered.revision,
                        },
                    )
                    return
                yield encoded

        return StreamingResponse(
            event_source(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    return Route(path, handler, methods=["POST"])


def _setup_error_status(code: str) -> int:
    return {
        "session_busy": 409,
        "image_storage_unavailable": 503,
        "image_conflict": 409,
        "image_quota_exceeded": 429,
        "request_conflict": 409,
    }.get(code, 500)


__all__ = ["DEFAULT_STREAM_PATH", "make_chat_stream_route"]
