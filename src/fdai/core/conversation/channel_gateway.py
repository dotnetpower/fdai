"""Route authenticated channel turns through the conversation coordinator."""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol

from fdai.core.conversation.busy_input import (
    BusyInput,
    BusyInputDecision,
    BusyInputKind,
    BusyInputMode,
)
from fdai.core.conversation.busy_input_coordinator import BusyInputCoordinator
from fdai.core.conversation.coordinator import ConversationCoordinator
from fdai.core.conversation.session import ConversationSession, Principal
from fdai.core.conversation.tools import AbstainResult, ToolResult
from fdai.shared.contracts import DocumentPurpose
from fdai.shared.providers.conversation_channel import (
    AgentHandoffActivity,
    ChannelProgressStatus,
    ChannelProgressUpdate,
    ConversationChannelAdapter,
    InboundTurn,
    ObservedExecutionActivity,
    OutboundResponse,
)
from fdai.shared.providers.conversation_delivery import OutboundDeliveryRecord
from fdai.shared.telemetry.transitions import (
    RoutingTransition,
    RoutingTransitionSink,
    default_transition_emitter,
    emit_transition_safely,
)


class ChannelPrincipalResolver(Protocol):
    """Resolve one channel sender to an FDAI principal or deny access."""

    async def resolve(self, turn: InboundTurn) -> Principal | None: ...


class ChannelMessageLedger(Protocol):
    """Atomically claim inbound messages so redelivery is a no-op."""

    async def claim(self, idempotency_key: str) -> bool: ...

    async def release(self, idempotency_key: str) -> None: ...


class ChannelBusyInputModeResolver(Protocol):
    """Resolve a session's busy-input mode without changing typed action state."""

    async def resolve(
        self,
        *,
        session_id: str,
        principal: Principal,
    ) -> BusyInputMode: ...


@dataclass(frozen=True, slots=True)
class ChannelDeliveryContext:
    principal_id: str
    scope_ref: str
    conversation_id: str
    binding_id: str | None


class ChannelDeliveryContextResolver(Protocol):
    """Resolve a verified active binding before durable outbound delivery."""

    async def resolve(
        self,
        *,
        turn: InboundTurn,
        principal: Principal,
        session_id: str,
    ) -> ChannelDeliveryContext | None: ...


class DurableChannelDelivery(Protocol):
    async def submit(
        self,
        *,
        origin_ref: str,
        principal_id: str,
        scope_ref: str,
        conversation_id: str,
        binding_id: str | None,
        response: OutboundResponse,
        send_immediately: bool = True,
    ) -> OutboundDeliveryRecord: ...


@dataclass(frozen=True, slots=True)
class AttachmentIngestionResult:
    status: Literal["ready", "rejected"]
    evidence_refs: tuple[str, ...] = ()
    reason: str = ""
    purpose: DocumentPurpose = DocumentPurpose.KNOWLEDGE_BASE
    message: str | None = None

    def __post_init__(self) -> None:
        if self.status == "ready" and (
            self.reason
            or not self.evidence_refs
            or any(not reference.startswith("doc:") for reference in self.evidence_refs)
        ):
            raise ValueError("ready attachment ingestion MUST carry only doc citations")
        if self.status == "rejected" and (not self.reason or self.evidence_refs):
            raise ValueError("rejected attachment ingestion MUST carry only a reason")


class ChannelAttachmentIngestor(Protocol):
    async def ingest(
        self,
        *,
        turn: InboundTurn,
        principal: Principal,
    ) -> AttachmentIngestionResult: ...


SessionLoader = Callable[[str, Principal, str], Awaitable[ConversationSession]]


@dataclass(frozen=True, slots=True)
class _HandledChannelResponse:
    response: OutboundResponse
    principal: Principal
    session_id: str


class ConversationChannelGateway:
    """Authenticate, deduplicate, route, and reply to channel messages."""

    def __init__(
        self,
        *,
        coordinator: ConversationCoordinator,
        principal_resolver: ChannelPrincipalResolver,
        ledger: ChannelMessageLedger,
        load_session: SessionLoader,
        attachment_ingestor: ChannelAttachmentIngestor | None = None,
        transition_sink: RoutingTransitionSink | None = None,
        busy_input_coordinator: BusyInputCoordinator | None = None,
        busy_input_mode_resolver: ChannelBusyInputModeResolver | None = None,
        outbound_delivery: DurableChannelDelivery | None = None,
        delivery_context_resolver: ChannelDeliveryContextResolver | None = None,
    ) -> None:
        if (outbound_delivery is None) != (delivery_context_resolver is None):
            raise ValueError(
                "durable channel delivery requires a verified delivery context resolver"
            )
        self._coordinator = coordinator
        self._principal_resolver = principal_resolver
        self._ledger = ledger
        self._load_session = load_session
        self._attachment_ingestor = attachment_ingestor
        self._transition_sink = transition_sink or default_transition_emitter()
        self._busy_input_coordinator = busy_input_coordinator
        self._busy_input_mode_resolver = busy_input_mode_resolver
        self._outbound_delivery = outbound_delivery
        self._delivery_context_resolver = delivery_context_resolver

    def bind_attachment_ingestor(self, ingestor: ChannelAttachmentIngestor) -> None:
        """Bind one production attachment ingestor before channel consumers start."""
        if self._attachment_ingestor is not None and self._attachment_ingestor is not ingestor:
            raise RuntimeError("channel attachment ingestor is already bound")
        self._attachment_ingestor = ingestor

    async def run(self, adapter: ConversationChannelAdapter) -> None:
        """Consume one adapter until its receive stream ends."""
        async for turn in adapter.receive():
            try:
                handled = await self._handle(adapter=adapter, turn=turn)
            except Exception as exc:  # noqa: BLE001 - isolate one malformed/provider turn
                self._emit(
                    turn,
                    "message.processing",
                    "rejected",
                    {
                        "reason_code": "processing_error",
                        "exception_type": type(exc).__name__,
                    },
                )
                continue
            if handled is None:
                continue
            try:
                if self._outbound_delivery is None:
                    await adapter.send(handled.response)
                    continue
                context_resolver = self._delivery_context_resolver
                if context_resolver is None:
                    raise RuntimeError("durable channel delivery context resolver is unavailable")
                context = await context_resolver.resolve(
                    turn=turn,
                    principal=handled.principal,
                    session_id=handled.session_id,
                )
                if context is None or context.principal_id != handled.principal.id:
                    self._emit(
                        turn,
                        "delivery.binding",
                        "rejected",
                        {"reason_code": "binding_unavailable"},
                    )
                    continue
                await self._outbound_delivery.submit(
                    origin_ref=f"channel-message:{_message_key(turn)}",
                    principal_id=context.principal_id,
                    scope_ref=context.scope_ref,
                    conversation_id=context.conversation_id,
                    binding_id=context.binding_id,
                    response=handled.response,
                )
            except Exception as exc:  # noqa: BLE001 - isolate one delivery attempt
                self._emit(
                    turn,
                    "delivery.submit",
                    "rejected",
                    {
                        "reason_code": "delivery_error",
                        "exception_type": type(exc).__name__,
                    },
                )
                continue

    async def handle(
        self,
        *,
        adapter: ConversationChannelAdapter,
        turn: InboundTurn,
    ) -> OutboundResponse | None:
        """Handle one normalized turn; return ``None`` for denied or duplicate input."""
        handled = await self._handle(adapter=adapter, turn=turn)
        return handled.response if handled is not None else None

    async def _handle(
        self,
        *,
        adapter: ConversationChannelAdapter,
        turn: InboundTurn,
    ) -> _HandledChannelResponse | None:
        if adapter.channel_kind is not turn.channel_kind:
            raise ValueError("channel adapter kind does not match inbound turn")
        principal = await self._principal_resolver.resolve(turn)
        if principal is None:
            self._emit(turn, "principal.resolve", "rejected", {"reason_code": "unresolved"})
            return None
        idempotency_key = _message_key(turn)
        if not await self._ledger.claim(idempotency_key):
            self._emit(turn, "message.claim", "rejected", {"reason_code": "duplicate"})
            return None
        session_id = _session_id(turn, principal)
        busy_turn_started = False
        attachment_ingestion_completed = False
        try:
            if self._busy_input_coordinator is not None:
                state = await self._busy_input_coordinator.status(
                    session_id=session_id,
                    principal_id=principal.id,
                )
                if state is not None and state.active_turn_id is not None:
                    decision = await self._busy_input_coordinator.submit(
                        _busy_input(turn, session_id, principal.id, idempotency_key)
                    )
                    return _HandledChannelResponse(
                        response=_busy_ack(turn, decision),
                        principal=principal,
                        session_id=session_id,
                    )
                mode = (
                    await self._busy_input_mode_resolver.resolve(
                        session_id=session_id,
                        principal=principal,
                    )
                    if self._busy_input_mode_resolver is not None
                    else None
                )
                await self._busy_input_coordinator.begin_turn(
                    session_id=session_id,
                    turn_id=turn.message_id,
                    principal_id=principal.id,
                    mode=mode,
                )
                busy_turn_started = True
            attachment_evidence: tuple[str, ...] = ()
            attachment_message: str | None = None
            if turn.attachments:
                if self._attachment_ingestor is None:
                    self._emit(
                        turn,
                        "attachment.ingestion",
                        "rejected",
                        {"reason_code": "ingestor_unavailable"},
                    )
                    return _HandledChannelResponse(
                        response=_attachment_error(
                            turn,
                            "channel attachment ingestion is unavailable",
                        ),
                        principal=principal,
                        session_id=session_id,
                    )
                ingestion = await self._attachment_ingestor.ingest(
                    turn=turn,
                    principal=principal,
                )
                if ingestion.status == "rejected":
                    self._emit(
                        turn,
                        "attachment.ingestion",
                        "rejected",
                        {"reason_code": "ingestion_rejected"},
                    )
                    return _HandledChannelResponse(
                        response=_attachment_error(turn, ingestion.reason),
                        principal=principal,
                        session_id=session_id,
                    )
                attachment_evidence = ingestion.evidence_refs
                attachment_message = ingestion.message
                attachment_ingestion_completed = True
                self._emit(
                    turn,
                    "attachment.ingestion",
                    "accepted",
                    {"status": "ready"},
                )
                if ingestion.purpose is DocumentPurpose.HANDOVER_BOOTSTRAP:
                    return _HandledChannelResponse(
                        response=_handover_attachment_ready(turn, attachment_evidence),
                        principal=principal,
                        session_id=session_id,
                    )
                if attachment_message == "":
                    return _HandledChannelResponse(
                        response=_knowledge_attachment_ready(turn, attachment_evidence),
                        principal=principal,
                        session_id=session_id,
                    )
            session = await self._load_session(session_id, principal, turn.channel_id)
            result = self._coordinator.handle_turn(
                session=session,
                message=attachment_message if attachment_message is not None else turn.text,
            )
            result_status = result.status if isinstance(result, ToolResult) else "abstain"
            self._emit(turn, "message.handled", "accepted", {"status": result_status})
            return _HandledChannelResponse(
                response=_to_response(
                    turn,
                    result,
                    attachment_evidence=attachment_evidence,
                ),
                principal=principal,
                session_id=session_id,
            )
        except Exception:
            if attachment_ingestion_completed:
                self._emit(
                    turn,
                    "message.processing",
                    "rejected",
                    {"reason_code": "post_ingestion_error"},
                )
                return _HandledChannelResponse(
                    response=_attachment_error(
                        turn,
                        "channel turn failed after attachment ingestion",
                    ),
                    principal=principal,
                    session_id=session_id,
                )
            await self._ledger.release(idempotency_key)
            raise
        finally:
            if busy_turn_started and self._busy_input_coordinator is not None:
                await self._busy_input_coordinator.finish_turn(
                    session_id=session_id,
                    turn_id=turn.message_id,
                    principal_id=principal.id,
                )

    def _emit(
        self,
        turn: InboundTurn,
        name: str,
        outcome: str,
        attributes: dict[str, str],
    ) -> None:
        emit_transition_safely(
            self._transition_sink,
            RoutingTransition(
                domain="channel",
                name=name,
                outcome=outcome,
                attributes={"channel_kind": turn.channel_kind.value, **attributes},
            ),
        )


def _message_key(turn: InboundTurn) -> str:
    raw = f"{turn.channel_kind.value}\0{turn.channel_id}\0{turn.message_id}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _session_id(turn: InboundTurn, principal: Principal) -> str:
    thread = turn.thread_id or turn.sender_id
    raw = f"{turn.channel_kind.value}\0{turn.channel_id}\0{thread}\0{principal.id}"
    return "channel:" + hashlib.sha256(raw.encode()).hexdigest()[:40]


def _busy_input(
    turn: InboundTurn,
    session_id: str,
    principal_id: str,
    idempotency_key: str,
) -> BusyInput:
    received_at = datetime.now(UTC)
    return BusyInput(
        input_id=turn.message_id,
        idempotency_key=idempotency_key,
        session_id=session_id,
        principal_id=principal_id,
        content=turn.text,
        kind=BusyInputKind.PROSE,
        received_at=received_at,
        expires_at=received_at + timedelta(minutes=5),
    )


def _busy_ack(turn: InboundTurn, decision: BusyInputDecision) -> OutboundResponse:
    record = decision.record
    return OutboundResponse(
        channel_kind=turn.channel_kind,
        channel_id=turn.channel_id,
        in_reply_to=turn.message_id,
        thread_id=turn.thread_id,
        status="accepted",
        text="Follow-up accepted.",
        data={
            "disposition": record.disposition.value,
            "session_id": record.input.session_id,
            "input_id": record.input.input_id,
            "sequence": record.sequence,
            "reason": decision.reason,
            "duplicate": decision.duplicate,
        },
    )


def _to_response(
    turn: InboundTurn,
    result: ToolResult | AbstainResult,
    *,
    attachment_evidence: tuple[str, ...] = (),
) -> OutboundResponse:
    if isinstance(result, ToolResult):
        return OutboundResponse(
            channel_kind=turn.channel_kind,
            channel_id=turn.channel_id,
            in_reply_to=turn.message_id,
            thread_id=turn.thread_id,
            status=result.status,
            text=result.preview,
            data=result.data,
            evidence_refs=tuple(dict.fromkeys((*result.evidence_refs, *attachment_evidence))),
            activities=result.activities,
            progress_updates=_progress_updates(result),
        )
    return OutboundResponse(
        channel_kind=turn.channel_kind,
        channel_id=turn.channel_id,
        in_reply_to=turn.message_id,
        thread_id=turn.thread_id,
        status="abstain",
        text=result.reason,
        data={"tool_inventory": list(result.tool_inventory)},
    )


def _progress_updates(result: ToolResult) -> tuple[ChannelProgressUpdate, ...]:
    if not result.activities:
        return ()
    updates = tuple(
        ChannelProgressUpdate(
            revision=index,
            status=ChannelProgressStatus.RUNNING,
            text=_activity_progress_text(activity),
            activity_count=index + 1,
        )
        for index, activity in enumerate(result.activities)
    )
    return (
        *updates,
        ChannelProgressUpdate(
            revision=len(updates),
            status=ChannelProgressStatus.CONFIRMED,
            text=result.preview,
            activity_count=len(result.activities),
        ),
    )


def _activity_progress_text(
    activity: AgentHandoffActivity | ObservedExecutionActivity,
) -> str:
    if isinstance(activity, AgentHandoffActivity):
        return f"{activity.from_agent} -> {activity.to_agent}: {activity.task}"
    return f"{activity.agent}: {activity.label} [{activity.status.value}]"


def _attachment_error(turn: InboundTurn, reason: str) -> OutboundResponse:
    return OutboundResponse(
        channel_kind=turn.channel_kind,
        channel_id=turn.channel_id,
        in_reply_to=turn.message_id,
        thread_id=turn.thread_id,
        status="error",
        text=reason,
    )


def _handover_attachment_ready(
    turn: InboundTurn,
    evidence_refs: tuple[str, ...],
) -> OutboundResponse:
    return OutboundResponse(
        channel_kind=turn.channel_kind,
        channel_id=turn.channel_id,
        in_reply_to=turn.message_id,
        thread_id=turn.thread_id,
        status="ready",
        text=(
            "The attachment completed protected ownership-handover ingestion. "
            "Review the generated draft and governance pull request before merge."
        ),
        evidence_refs=evidence_refs,
    )


def _knowledge_attachment_ready(
    turn: InboundTurn,
    evidence_refs: tuple[str, ...],
) -> OutboundResponse:
    return OutboundResponse(
        channel_kind=turn.channel_kind,
        channel_id=turn.channel_id,
        in_reply_to=turn.message_id,
        thread_id=turn.thread_id,
        status="ready",
        text="The attachment completed protected ingestion and is ready as governed evidence.",
        evidence_refs=evidence_refs,
    )


__all__ = [
    "AttachmentIngestionResult",
    "ChannelDeliveryContext",
    "ChannelDeliveryContextResolver",
    "DurableChannelDelivery",
    "ChannelAttachmentIngestor",
    "ChannelBusyInputModeResolver",
    "ChannelMessageLedger",
    "ChannelPrincipalResolver",
    "ConversationChannelGateway",
    "SessionLoader",
]
