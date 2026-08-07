"""Request-local policy, planning, persistence, and active-turn lifecycle."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from fdai.core.conversation.busy_input_coordinator import BusyInputCoordinator
from fdai.core.user_context_projection import UserContextOntologyProjector
from fdai.delivery.conversation_images import (
    ConversationImageConflictError,
    ConversationImageQuotaError,
    ConversationImageStore,
)
from fdai.delivery.handover_events import HandoverAvailabilityPublisher
from fdai.delivery.operator_api.application import (
    ConversationTurnApplicationService,
    ConversationTurnExecution,
    ConversationTurnTerminalStatus,
)
from fdai.delivery.operator_api.application.conversation.backend import (
    ChatContentPolicyError,
    reject_direct_override,
)
from fdai.delivery.operator_api.application.conversation.capabilities.action_context import (
    is_explicit_action_draft_request,
)
from fdai.delivery.operator_api.application.conversation.intent_graph import (
    IntentGraph,
    IntentGraphPlanner,
    draft_capability_available,
    plan_semantic_turn,
    planner_context_envelope,
)
from fdai.delivery.operator_api.application.conversation.prompt import (
    _is_grounded_concept_query,
)
from fdai.delivery.operator_api.application.conversation.request_preparation import (
    ChatDocumentEvidenceResolver,
    content_policy_replay_stage,
    resolve_document_refs,
)
from fdai.delivery.operator_api.application.conversation.turn_plan import TurnPlanner, TurnTool
from fdai.delivery.operator_api.persistence.conversation import (
    append_content_policy_receipt,
    image_turn_metadata,
    persist_operator_turn_with_images,
)
from fdai.shared.providers.document_ingestion import DocumentAccessDeniedError
from fdai.shared.providers.user_context import (
    ConversationHistoryStore,
    UserContextConflictError,
)

from .models import JsonTurnExecutionError, JsonTurnExecutionResult, JsonTurnOutcome

_LOG = logging.getLogger(__name__)


class JsonTurnLifecycle:
    """Own one-shot policy, planning, persistence, and active-turn transitions."""

    def __init__(
        self,
        *,
        turn_service: ConversationTurnApplicationService,
        conversation_history_store: ConversationHistoryStore | None,
        conversation_image_store: ConversationImageStore | None,
        user_context_ontology_projector: UserContextOntologyProjector | None,
        busy_input_coordinator: BusyInputCoordinator | None,
        document_evidence_resolver: ChatDocumentEvidenceResolver | None,
        turn_planner: TurnPlanner | IntentGraphPlanner | None,
        turn_tools: tuple[TurnTool, ...] | Callable[[], tuple[TurnTool, ...]],
        handover_availability_publisher: HandoverAvailabilityPublisher | None,
    ) -> None:
        self._turn_service = turn_service
        self._conversation_history_store = conversation_history_store
        self._conversation_image_store = conversation_image_store
        self._user_context_ontology_projector = user_context_ontology_projector
        self._busy_input_coordinator = busy_input_coordinator
        self._document_evidence_resolver = document_evidence_resolver
        self._turn_planner = turn_planner
        self._turn_tools = turn_tools
        self._handover_availability_publisher = handover_availability_publisher

    async def resolve_document_refs(
        self,
        body: dict[str, Any],
        principal_id: str,
    ) -> tuple[str, ...]:
        """Resolve exact document evidence with transport-neutral failures."""

        try:
            return await resolve_document_refs(
                body=body,
                principal_id=principal_id,
                resolver=self._document_evidence_resolver,
            )
        except ValueError as exc:
            raise _error("invalid_request", str(exc)) from exc
        except DocumentAccessDeniedError as exc:
            raise _error("document_access_denied", "document reference access denied") from exc
        except RuntimeError as exc:
            raise _error(
                "document_evidence_unavailable",
                "web chat document evidence is unavailable",
            ) from exc

    async def enforce_input_policy(
        self,
        *,
        principal_id: str,
        session_id: str,
        request_id: str,
        clean_prompt: str,
    ) -> None:
        """Apply direct-override and durable content-policy replay checks."""

        try:
            reject_direct_override(clean_prompt)
        except ChatContentPolicyError as exc:
            raise _error("content_policy_block", str(exc)) from exc
        if self._conversation_history_store is None:
            return
        try:
            replay_stage = await content_policy_replay_stage(
                store=self._conversation_history_store,
                principal_id=principal_id,
                conversation_id=session_id,
                request_id=request_id,
                content=clean_prompt,
            )
        except UserContextConflictError as exc:
            raise _error(
                "request_conflict",
                "chat request id conflicts with an existing turn",
            ) from exc
        if replay_stage is not None:
            raise _error("content_policy_block", "chat request blocked by content policy")

    def publish_handover_availability(self, principal_id: str, session_id: str) -> None:
        """Publish optional handover availability without delaying the turn."""

        if self._handover_availability_publisher is None:
            return
        task = asyncio.create_task(
            self._handover_availability_publisher.publish(
                subject_ref=principal_id,
                session_id=session_id,
            )
        )
        task.add_done_callback(_log_handover_availability_failure)

    async def begin_active_turn(
        self,
        *,
        principal_id: str,
        session_id: str,
        request_id: str,
        turn_execution: ConversationTurnExecution,
    ) -> Any | None:
        """Register the request with the existing busy-input authority."""

        if self._busy_input_coordinator is None:
            return None
        try:
            return await self._busy_input_coordinator.begin_turn(
                session_id=session_id,
                turn_id=request_id,
                principal_id=principal_id,
            )
        except RuntimeError as exc:
            detail = "conversation session already has an active turn"
            self._turn_service.terminate_turn(
                turn_execution,
                terminal_status=ConversationTurnTerminalStatus.FAILED,
                code="chat_session_busy",
                detail=detail,
                wire_payload={"detail": detail},
            )
            raise _error("session_busy", detail) from exc

    async def finish_active_turn(
        self,
        principal_id: str,
        session_id: str,
        request_id: str,
        active_turn: Any | None,
    ) -> None:
        """Finish an active turn exactly when one was registered."""

        if self._busy_input_coordinator is not None and active_turn is not None:
            await self._busy_input_coordinator.finish_turn(
                session_id=session_id,
                turn_id=request_id,
                principal_id=principal_id,
            )

    def should_plan(
        self,
        *,
        clean_prompt: str,
        vision_attachments: list[Any],
        deterministic_followup: bool,
        semantic_inventory_completion: bool,
    ) -> bool:
        """Return whether semantic planning is eligible for this turn."""

        return (
            self._turn_planner is not None
            and not vision_attachments
            and not _is_grounded_concept_query(clean_prompt)
            and (
                not deterministic_followup
                or semantic_inventory_completion
                or is_explicit_action_draft_request(clean_prompt)
            )
        )

    async def plan_turn(
        self,
        *,
        clean_prompt: str,
        history: list[dict[str, str]],
        view_context: dict[str, Any],
        resource_context: Any,
        conversation_context: Any,
        document_evidence_refs: tuple[str, ...],
        request_id: str,
    ) -> Any | None:
        """Run the bounded shadow semantic planner and degrade closed."""

        if self._turn_planner is None:
            return None
        try:
            return await plan_semantic_turn(
                self._turn_planner,
                prompt=clean_prompt,
                tools=self.resolved_turn_tools(),
                history=history,
                attachments=view_context.get("_attachments"),
                context=planner_context_envelope(
                    view_context,
                    resource_context=resource_context,
                    conversation_context=conversation_context,
                    document_refs=document_evidence_refs,
                ),
            )
        except Exception as exc:  # noqa: BLE001 - shadow plan degrades closed
            _LOG.warning(
                "chat turn planning unavailable: %s",
                type(exc).__name__,
                extra={"request_id": request_id},
            )
            return None

    def resolved_turn_tools(self) -> tuple[TurnTool, ...]:
        """Return the current server-owned tool set."""

        return self._turn_tools() if callable(self._turn_tools) else self._turn_tools

    async def persist_operator_turn(
        self,
        *,
        principal_id: str,
        session_id: str,
        request_id: str,
        clean_prompt: str,
        document_evidence_refs: tuple[str, ...],
        vision_attachments: list[Any],
        history_metadata: dict[str, Any],
    ) -> tuple[Any | None, Any | None]:
        """Persist the operator turn and resolve any completed assistant replay."""

        if self._conversation_history_store is None:
            return None, None
        if vision_attachments and self._conversation_image_store is None:
            raise _error(
                "image_storage_unavailable",
                "conversation image storage is unavailable",
            )
        try:
            operator_turn = await persist_operator_turn_with_images(
                history_store=self._conversation_history_store,
                image_store=self._conversation_image_store,
                attachments=vision_attachments,
                principal_id=principal_id,
                conversation_id=session_id,
                request_id=request_id,
                content=clean_prompt,
                recorded_at=datetime.now(tz=UTC),
                metadata={
                    "document_refs": list(document_evidence_refs),
                    **image_turn_metadata(vision_attachments),
                    **history_metadata,
                },
                ontology_projector=self._user_context_ontology_projector,
            )
        except ConversationImageConflictError as exc:
            raise _error(
                "image_conflict",
                "chat image id conflicts with existing content",
            ) from exc
        except ConversationImageQuotaError as exc:
            raise _error(
                "image_quota_exceeded",
                "conversation image storage quota exceeded",
            ) from exc
        except UserContextConflictError as exc:
            raise _error(
                "request_conflict",
                "chat request id conflicts with an existing turn",
            ) from exc
        completed_turn = await self._conversation_history_store.get_turn_by_idempotency(
            principal_id=principal_id,
            idempotency_key=f"{request_id}:assistant",
        )
        return operator_turn, completed_turn

    def confirmation_result(
        self,
        *,
        semantic_plan: Any | None,
        request_id: str,
        session_id: str,
        turn_execution: ConversationTurnExecution,
    ) -> JsonTurnExecutionResult | None:
        """Return an action draft or unavailable result when confirmation is required."""

        if semantic_plan is None or not semantic_plan.requires_confirmation:
            return None
        if isinstance(semantic_plan, IntentGraph) and not draft_capability_available(
            semantic_plan,
            self.resolved_turn_tools(),
        ):
            payload = {"detail": "draft capability is no longer available"}
            unavailable = self._turn_service.terminate_turn(
                turn_execution,
                terminal_status=ConversationTurnTerminalStatus.UNAVAILABLE,
                code="draft_capability_unavailable",
                detail=payload["detail"],
                wire_payload=payload,
            )
            return JsonTurnExecutionResult(
                unavailable.to_wire_payload(),
                JsonTurnOutcome.CONFLICT,
            )
        payload = {
            "answer": "Review this action draft before submitting it.",
            "model": "semantic-turn-planner",
            "source": "action-draft",
            "action_draft": semantic_plan.confirmation_payload(
                request_id=request_id,
                session_id=session_id,
            ),
        }
        draft = self._turn_service.complete_turn(
            turn_execution,
            payload,
            terminal_status=ConversationTurnTerminalStatus.UNVERIFIED,
        )
        return JsonTurnExecutionResult(draft.to_wire_payload())

    async def record_content_policy_block(
        self,
        *,
        exc: ChatContentPolicyError,
        principal_id: str,
        session_id: str,
        request_id: str,
        operator_turn: Any | None,
        history_metadata: dict[str, Any],
        turn_execution: ConversationTurnExecution,
    ) -> None:
        """Persist the content-free policy receipt and close the typed turn."""

        if self._conversation_history_store is not None and operator_turn is not None:
            try:
                await append_content_policy_receipt(
                    store=self._conversation_history_store,
                    principal_id=principal_id,
                    conversation_id=session_id,
                    request_id=request_id,
                    stage=exc.stage,
                    recorded_at=datetime.now(tz=UTC),
                    history_metadata=history_metadata,
                )
            except Exception as receipt_error:  # noqa: BLE001 - preserve policy response
                _LOG.error(
                    "chat content-policy receipt failed: %s",
                    type(receipt_error).__name__,
                    extra={"request_id": request_id},
                )
                detail = "content policy receipt unavailable"
                self._turn_service.terminate_turn(
                    turn_execution,
                    terminal_status=ConversationTurnTerminalStatus.FAILED,
                    code="content_policy_receipt_unavailable",
                    detail=detail,
                    wire_payload={"detail": detail},
                )
                raise _error("content_policy_receipt_unavailable", detail) from receipt_error
        self._turn_service.terminate_turn(
            turn_execution,
            terminal_status=ConversationTurnTerminalStatus.ABSTAINED,
            code="content_policy_block",
            detail=str(exc),
            wire_payload={"detail": str(exc)},
        )

    def terminate_open_turn(
        self,
        turn_execution: ConversationTurnExecution,
        terminal_status: ConversationTurnTerminalStatus,
        code: str,
        detail: str,
    ) -> None:
        """Close an unclosed typed turn with the supplied terminal failure."""

        if not turn_execution.closed:
            self._turn_service.terminate_turn(
                turn_execution,
                terminal_status=terminal_status,
                code=code,
                detail=detail,
                wire_payload={"detail": detail},
            )


def _error(code: str, detail: str) -> JsonTurnExecutionError:
    return JsonTurnExecutionError(code=code, detail=detail)


def _log_handover_availability_failure(task: asyncio.Task[object]) -> None:
    try:
        task.result()
    except Exception as exc:  # noqa: BLE001 - availability never blocks chat
        _LOG.warning("handover availability publish failed: %s", type(exc).__name__)


__all__ = ["JsonTurnLifecycle"]
