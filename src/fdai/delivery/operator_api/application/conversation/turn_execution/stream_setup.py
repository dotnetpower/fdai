"""Prepare streamed conversation state before transport delivery begins.

Responsibility:
Register the active turn, persist the operator input, resolve terminal replay,
and compute deterministic planning eligibility before a stream is opened.

Boundary:
Accept application-owned prepared values and return a semantic execution.
HTTP status mapping and SSE delivery remain outside this module.

Authority and state:
This module has no approval or execution authority. Conversation writes occur
only through the injected lifecycle owner and its stores.

Dependencies:
Typed turn lifecycle, read-only capability classifiers, and progress metrics.

Deployment:
Runs in-process inside the Operator API and creates no network boundary.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any, cast

from fdai.delivery.operator_api.application import (
    ConversationTurnApplicationService,
    ConversationTurnExecution,
    ConversationTurnInput,
    ConversationTurnTerminalStatus,
)
from fdai.delivery.operator_api.application.conversation.capabilities.action_context import (
    needs_action_context,
)
from fdai.delivery.operator_api.application.conversation.capabilities.conversation_context import (
    needs_conversation_context,
)
from fdai.delivery.operator_api.application.conversation.capabilities.current_time import (
    needs_current_time,
)
from fdai.delivery.operator_api.application.conversation.capabilities.inventory.compiler import (
    compile_inventory_query,
    inventory_query_requires_semantic_completion,
)
from fdai.delivery.operator_api.application.conversation.capabilities.llm_usage import (
    is_llm_usage_followup,
    needs_llm_usage,
)
from fdai.delivery.operator_api.application.conversation.capabilities.log_query import (
    needs_log_query,
)
from fdai.delivery.operator_api.application.conversation.capabilities.subscription_health import (
    needs_subscription_health,
)
from fdai.delivery.operator_api.application.conversation.evidence import (
    ChatToolResolver,
    has_bound_incident_analysis_context,
    has_screen_incident_analysis_context,
    needs_operational_evidence,
)
from fdai.delivery.operator_api.application.conversation.freshness_context import (
    needs_evidence_freshness_context,
)
from fdai.delivery.operator_api.application.conversation.intents import is_topology_question
from fdai.delivery.operator_api.application.conversation.prompt import _response_locale
from fdai.delivery.operator_api.application.conversation.request_preparation import (
    ContentPolicyReplayRequest,
    PreparedChatStreamRequest,
)
from fdai.delivery.operator_api.application.conversation.response_completion import (
    metering_correlation_id,
)
from fdai.delivery.operator_api.projections.conversation.terminal import completed_replay_payload
from fdai.shared.providers.user_context import ConversationTurnRecord
from fdai.shared.telemetry import ConversationProgressMetrics

from .lifecycle import JsonTurnLifecycle
from .models import (
    JsonTurnExecutionError,
    StreamTurnEvent,
    StreamTurnExecution,
    StreamTurnExecutionError,
)


@dataclass(frozen=True, slots=True)
class PreparedStreamSession:
    """Application state fixed before the first streamed event is delivered."""

    request: PreparedChatStreamRequest
    deterministic_followup: bool
    semantic_inventory_completion: bool
    turn_execution: ConversationTurnExecution
    active_turn: Any | None
    operator_turn: ConversationTurnRecord | None
    completed_payload: dict[str, Any] | None


class StreamTurnSetup:
    """Prepare one stream while preserving pre-response failure semantics."""

    def __init__(
        self,
        *,
        turn_service: ConversationTurnApplicationService,
        lifecycle: JsonTurnLifecycle,
        tool_resolver: ChatToolResolver | None,
        progress_metrics: ConversationProgressMetrics | None,
    ) -> None:
        self._turn_service = turn_service
        self._lifecycle = lifecycle
        self._tool_resolver = tool_resolver
        self._progress_metrics = progress_metrics

    async def start(
        self,
        prepared: PreparedChatStreamRequest | ContentPolicyReplayRequest,
        run: Callable[[PreparedStreamSession], AsyncIterator[StreamTurnEvent]],
    ) -> StreamTurnExecution:
        """Return a single-use event stream after completing setup writes."""

        if isinstance(prepared, ContentPolicyReplayRequest):
            events = self._policy_replay(prepared)
            return StreamTurnExecution(
                prepared.request_id,
                events,
                self._transport_error_handler(events),
            )
        compiled_inventory = (
            compile_inventory_query(prepared.evidence_prompt)
            if self._tool_resolver is not None
            else None
        )
        semantic_inventory_completion = compiled_inventory is not None and (
            inventory_query_requires_semantic_completion(
                compiled_inventory,
                prompt=prepared.evidence_prompt,
            )
        )
        turn_execution = self._turn_service.start_turn(
            ConversationTurnInput(
                principal_id=prepared.user_id,
                conversation_id=prepared.session_id,
                request_id=prepared.request_id,
                correlation_id=metering_correlation_id(
                    prepared.user_id,
                    prepared.session_id,
                ),
                prompt=prepared.clean_prompt,
                response_locale=_response_locale(
                    prepared.clean_prompt,
                    prepared.view_context,
                ),
                target_agent=prepared.target_agent,
                evidence_refs=prepared.document_evidence_refs,
                history_turn_count=len(prepared.history),
                streaming=True,
            )
        )
        active_turn = None
        try:
            active_turn = await self._lifecycle.begin_active_turn(
                principal_id=prepared.user_id,
                session_id=prepared.session_id,
                request_id=prepared.request_id,
                turn_execution=turn_execution,
            )
            operator_turn, completed_turn = await self._lifecycle.persist_operator_turn(
                principal_id=prepared.user_id,
                session_id=prepared.session_id,
                request_id=prepared.request_id,
                clean_prompt=prepared.clean_prompt,
                document_evidence_refs=prepared.document_evidence_refs,
                vision_attachments=prepared.vision_attachments,
                history_metadata=prepared.history_metadata,
            )
        except asyncio.CancelledError:
            await self.finish_active(prepared, active_turn)
            self._terminate_open(
                turn_execution,
                ConversationTurnTerminalStatus.CANCELLED,
                "chat_turn_cancelled",
                "chat turn cancelled",
            )
            raise
        except JsonTurnExecutionError as exc:
            await self.finish_active(prepared, active_turn)
            self._terminate_open(
                turn_execution,
                ConversationTurnTerminalStatus.FAILED,
                "chat_stream_setup_failed",
                "chat stream setup failed",
            )
            raise StreamTurnExecutionError(code=exc.code, detail=exc.detail) from exc
        session = PreparedStreamSession(
            request=prepared,
            deterministic_followup=self._is_deterministic_followup(
                prepared,
                compiled_inventory,
            ),
            semantic_inventory_completion=semantic_inventory_completion,
            turn_execution=turn_execution,
            active_turn=active_turn,
            operator_turn=operator_turn,
            completed_payload=(
                completed_replay_payload(completed_turn) if completed_turn is not None else None
            ),
        )
        events = run(session)
        return StreamTurnExecution(
            prepared.request_id,
            events,
            self._transport_error_handler(events),
        )

    def _transport_error_handler(
        self,
        events: AsyncIterator[StreamTurnEvent],
    ) -> Callable[[BaseException], Awaitable[StreamTurnEvent | None]]:
        async def recover(exc: BaseException) -> StreamTurnEvent | None:
            throw = cast(
                Callable[[BaseException], Awaitable[StreamTurnEvent]],
                getattr(events, "athrow", None),
            )
            if throw is None:
                return None
            try:
                return await throw(exc)
            except StopAsyncIteration:
                return None

        return recover

    async def finish_active(
        self,
        request: PreparedChatStreamRequest,
        active_turn: Any | None,
    ) -> None:
        """Release the registered busy-input turn exactly once per caller cleanup."""

        await self._lifecycle.finish_active_turn(
            request.user_id,
            request.session_id,
            request.request_id,
            active_turn,
        )

    async def _policy_replay(
        self,
        prepared: ContentPolicyReplayRequest,
    ) -> AsyncIterator[StreamTurnEvent]:
        if self._progress_metrics is not None:
            self._progress_metrics.increment("content_policy_blocks")
        execution = self._turn_service.start_turn(
            ConversationTurnInput(
                principal_id=prepared.user_id,
                conversation_id=prepared.session_id,
                request_id=prepared.request_id,
                correlation_id=metering_correlation_id(
                    prepared.user_id,
                    prepared.session_id,
                ),
                prompt=prepared.clean_prompt,
                history_turn_count=0,
                streaming=True,
            )
        )
        detail = "chat request blocked by content policy"
        payload = {
            "code": "content_policy_block",
            "stage": prepared.stage,
            "receipt_persisted": True,
            "detail": detail,
        }
        result = self._turn_service.terminate_turn(
            execution,
            terminal_status=ConversationTurnTerminalStatus.ABSTAINED,
            code="content_policy_block",
            detail=detail,
            wire_payload=payload,
        )
        yield StreamTurnEvent("error", result.to_wire_payload())

    def _is_deterministic_followup(
        self,
        request: PreparedChatStreamRequest,
        compiled_inventory: Any | None,
    ) -> bool:
        return bool(
            request.resource_followup
            or has_bound_incident_analysis_context(
                request.clean_prompt,
                request.view_context,
                request.conversation_context,
            )
            or has_screen_incident_analysis_context(
                request.clean_prompt,
                request.view_context,
            )
            or request.inventory_screen_scope
            or request.inventory_scope_followup
            or "_read_investigation_context_hold" in request.view_context
            or is_topology_question(request.evidence_prompt)
            or (
                compiled_inventory is not None
                and not inventory_query_requires_semantic_completion(
                    compiled_inventory,
                    prompt=request.evidence_prompt,
                )
            )
            or needs_subscription_health(request.evidence_prompt)
            or needs_log_query(request.evidence_prompt)
            or needs_action_context(request.evidence_prompt)
            or needs_conversation_context(request.evidence_prompt)
            or needs_llm_usage(request.evidence_prompt)
            or is_llm_usage_followup(request.evidence_prompt)
            or needs_operational_evidence(request.evidence_prompt, request.view_context)
            or needs_current_time(request.evidence_prompt)
            or (
                request.freshness_context is not None
                and needs_evidence_freshness_context(request.clean_prompt)
            )
        )

    def _terminate_open(
        self,
        execution: ConversationTurnExecution,
        status: ConversationTurnTerminalStatus,
        code: str,
        detail: str,
    ) -> None:
        if not execution.closed:
            self._turn_service.terminate_turn(
                execution,
                terminal_status=status,
                code=code,
                detail=detail,
                wire_payload={"detail": detail},
            )


__all__ = ["PreparedStreamSession", "StreamTurnSetup"]
