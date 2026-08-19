"""Join authenticated channel turns to semantic replay and durable delivery."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from uuid import UUID, uuid5

from fdai_operator_service.families.conversation.channel_delivery_models import (
    ChannelBindingState,
    ChannelBreakerMode,
    ChannelDeliveryAcknowledgement,
    ChannelDeliveryRecord,
    ChannelDeliveryState,
    ChannelKind,
    PrincipalChannelBinding,
    VerifiedChannelEndpoint,
    channel_response_digest,
)
from fdai_operator_service.families.conversation.channel_edge.models import (
    AuthenticatedInboundTurn,
    ChannelDeliveryError,
    RenderedChannelMessage,
)
from fdai_operator_service.families.conversation.channel_edge.pipeline_contracts import (
    ChannelBindingStore,
    ChannelDeliveryPipelineConfig,
    ChannelDeliveryStore,
    ChannelMessageLedger,
    ChannelPipelineResult,
    ChannelPrincipalContext,
    ChannelPrincipalResolver,
    ChannelPublisher,
)
from fdai_operator_service.families.conversation.channel_edge.presentation import (
    normalize_terminal_presentation,
)
from fdai_operator_service.families.conversation.channel_edge.renderers import (
    SlackPresentationRenderer,
    TeamsPresentationRenderer,
)
from fdai_operator_service.families.conversation.contracts import (
    ConversationEventStream,
    ConversationProposal,
    ConversationProposalOutbox,
    ConversationStreamReader,
    ConversationStreamRequest,
    JsonObject,
)

_IDENTITY_NAMESPACE = UUID("00000000-0000-0000-0000-000000000000")


class ChannelDeliveryPipeline:
    """Persist semantic terminal data before acquiring provider-send authority."""

    def __init__(
        self,
        *,
        messages: ChannelMessageLedger,
        principals: ChannelPrincipalResolver,
        bindings: ChannelBindingStore,
        deliveries: ChannelDeliveryStore,
        semantic_outbox: ConversationProposalOutbox,
        semantic_streams: ConversationStreamReader,
        publishers: Mapping[ChannelKind, ChannelPublisher],
        config: ChannelDeliveryPipelineConfig | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if set(publishers) - {ChannelKind.SLACK, ChannelKind.TEAMS}:
            raise ValueError("channel pipeline publisher map contains an unsupported channel")
        self._messages = messages
        self._principals = principals
        self._bindings = bindings
        self._deliveries = deliveries
        self._semantic_outbox = semantic_outbox
        self._semantic_streams = semantic_streams
        self._publishers = dict(publishers)
        self._config = config or ChannelDeliveryPipelineConfig()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._slack = SlackPresentationRenderer()
        self._teams = TeamsPresentationRenderer()

    async def process(self, authenticated: AuthenticatedInboundTurn) -> ChannelPipelineResult:
        """Own one inbound turn through durable delivery and optional immediate send."""
        now = _aware(self._clock())
        inbound_key = _inbound_key(authenticated)
        delivery_id = _delivery_id(inbound_key)
        if not await self._messages.claim(inbound_key):
            existing = await self._deliveries.get(delivery_id)
            return ChannelPipelineResult(
                delivery_id=delivery_id,
                state=existing.state if existing is not None else ChannelDeliveryState.PENDING,
                duplicate=True,
            )
        durable_owned = False
        try:
            context = await self._principals.resolve(authenticated.principal_id)
            if context.scope.subject_id != authenticated.principal_id:
                raise ValueError(
                    "resolved channel principal does not match authenticated principal"
                )
            binding = await self._binding(authenticated, context=context, now=now)
            terminal = await self._semantic_terminal(
                authenticated,
                context=context,
                conversation_id=binding.conversation_id,
                idempotency_key=inbound_key,
            )
            record = _delivery_record(
                delivery_id=delivery_id,
                inbound_key=inbound_key,
                binding=binding,
                terminal=terminal,
                now=now,
                config=self._config,
            )
            stored = await self._deliveries.put(record)
            durable_owned = True
            await self._messages.complete(inbound_key)
            if stored.state is not ChannelDeliveryState.PENDING:
                return ChannelPipelineResult(delivery_id, stored.state)
            breaker = await self._deliveries.get_breaker(
                f"operator-channel-edge:{stored.channel_kind.value}"
            )
            if breaker is None or breaker.mode is not ChannelBreakerMode.CLOSED:
                return ChannelPipelineResult(delivery_id, stored.state)
            claimed = await self._deliveries.claim(
                delivery_id=delivery_id,
                now=now,
                worker_id=self._config.worker_id,
                lease_seconds=self._config.lease_seconds,
            )
            if claimed is None:
                current = await self._deliveries.get(delivery_id)
                return ChannelPipelineResult(
                    delivery_id,
                    current.state if current is not None else stored.state,
                )
            closed = await self._deliver_claimed(claimed, binding=binding)
            return ChannelPipelineResult(delivery_id, closed.state)
        except BaseException:
            if not durable_owned:
                await self._messages.release(inbound_key)
            raise

    async def deliver_claimed(
        self,
        record: ChannelDeliveryRecord,
    ) -> ChannelDeliveryRecord:
        """Deliver one externally claimed due record using its durable binding."""
        if record.binding_id is None:
            return await self._abandon(record, "binding_missing")
        binding = await self._bindings.get(record.binding_id)
        if binding is None or not _binding_matches_record(binding, record):
            return await self._abandon(record, "binding_unavailable")
        return await self._deliver_claimed(record, binding=binding)

    async def _binding(
        self,
        authenticated: AuthenticatedInboundTurn,
        *,
        context: ChannelPrincipalContext,
        now: datetime,
    ) -> PrincipalChannelBinding:
        turn = authenticated.turn
        identity = "\0".join(
            (
                authenticated.principal_id,
                context.scope_ref,
                turn.channel_kind.value,
                turn.channel_id,
                turn.sender_id,
                turn.thread_id or "",
            )
        )
        digest = hashlib.sha256(identity.encode()).hexdigest()
        binding_id = f"channel-binding:{digest}"
        existing = await self._bindings.get(binding_id)
        if existing is not None:
            endpoint = existing.endpoint
            if (
                existing.state is not ChannelBindingState.ACTIVE
                or existing.principal_id != authenticated.principal_id
                or existing.scope_ref != context.scope_ref
                or endpoint.channel_kind is not turn.channel_kind
                or endpoint.channel_id != turn.channel_id
                or endpoint.sender_id != turn.sender_id
                or endpoint.thread_id != turn.thread_id
            ):
                raise ValueError("durable channel binding identity does not match ingress")
            return existing
        binding = PrincipalChannelBinding(
            binding_id=binding_id,
            principal_id=authenticated.principal_id,
            scope_ref=context.scope_ref,
            conversation_id=str(uuid5(_IDENTITY_NAMESPACE, f"channel-conversation\0{identity}")),
            endpoint=VerifiedChannelEndpoint(
                principal_id=authenticated.principal_id,
                scope_ref=context.scope_ref,
                channel_kind=turn.channel_kind,
                channel_id=turn.channel_id,
                sender_id=turn.sender_id,
                thread_id=turn.thread_id,
                verification_ref=authenticated.verification_ref,
                verified_at=now,
            ),
            created_by=self._config.worker_id,
            created_at=now,
        )
        return await self._bindings.create(binding)

    async def _semantic_terminal(
        self,
        authenticated: AuthenticatedInboundTurn,
        *,
        context: ChannelPrincipalContext,
        conversation_id: str,
        idempotency_key: str,
    ) -> JsonObject:
        receipt = await self._semantic_outbox.append(
            ConversationProposal(
                operation="chat.stream",
                scope=context.scope,
                idempotency_key=idempotency_key,
                body={
                    "prompt": authenticated.turn.text,
                    "locale": context.locale,
                    "conversation_id": conversation_id,
                },
            )
        )
        stream = await self._semantic_streams.open(
            ConversationStreamRequest(
                operation="chat.stream",
                scope=context.scope,
                proposal_id=receipt.proposal_id,
                idempotency_key=idempotency_key,
            )
        )
        try:
            return await _terminal_event(stream)
        finally:
            await stream.aclose()

    async def _deliver_claimed(
        self,
        record: ChannelDeliveryRecord,
        *,
        binding: PrincipalChannelBinding,
    ) -> ChannelDeliveryRecord:
        now = _aware(self._clock())
        publisher = self._publishers.get(record.channel_kind)
        if publisher is None:
            return await self._abandon(record, "publisher_unavailable", at=now)
        try:
            message = self._render(record, binding=binding)
        except (TypeError, ValueError):
            return await self._abandon(record, "render_failed", at=now)
        try:
            receipt = await publisher.send(message)
        except ChannelDeliveryError as exc:
            if exc.acknowledgement_ambiguous:
                return await self._deliveries.finish(
                    delivery_id=record.delivery_id,
                    worker_id=self._config.worker_id,
                    expected_attempt_count=record.attempt_count,
                    state=ChannelDeliveryState.AMBIGUOUS,
                    at=now,
                    error_code=exc.code,
                )
            retry_at = now + self._config.retry_delay
            if retry_at >= record.expires_at:
                return await self._abandon(record, exc.code, at=now)
            return await self._deliveries.finish(
                delivery_id=record.delivery_id,
                worker_id=self._config.worker_id,
                expected_attempt_count=record.attempt_count,
                state=ChannelDeliveryState.FAILED,
                at=now,
                next_due_at=retry_at,
                error_code=exc.code,
            )
        acknowledgement = ChannelDeliveryAcknowledgement(
            delivery_id=record.delivery_id,
            attempt_id=f"{record.delivery_id}:attempt:{record.attempt_count}",
            provider_message_id=receipt.message_id,
            acknowledged_at=now,
            degraded_to_text=receipt.degraded_to_text,
        )
        return await self._deliveries.finish(
            delivery_id=record.delivery_id,
            worker_id=self._config.worker_id,
            expected_attempt_count=record.attempt_count,
            state=ChannelDeliveryState.DELIVERED,
            at=now,
            acknowledgement=acknowledgement,
        )

    def _render(
        self,
        record: ChannelDeliveryRecord,
        *,
        binding: PrincipalChannelBinding,
    ) -> RenderedChannelMessage:
        envelope = normalize_terminal_presentation(record.response)
        if record.channel_kind is ChannelKind.SLACK:
            rendered = self._slack.render(envelope)
        elif record.channel_kind is ChannelKind.TEAMS:
            rendered = self._teams.render(envelope)
        else:
            raise ValueError("channel delivery renderer is unavailable")
        return RenderedChannelMessage(
            channel_kind=record.channel_kind,
            channel_id=binding.endpoint.channel_id,
            thread_id=binding.endpoint.thread_id,
            payload=rendered.body,
            degraded_to_text=rendered.degraded_to_text,
        )

    async def _abandon(
        self,
        record: ChannelDeliveryRecord,
        error_code: str,
        *,
        at: datetime | None = None,
    ) -> ChannelDeliveryRecord:
        return await self._deliveries.finish(
            delivery_id=record.delivery_id,
            worker_id=self._config.worker_id,
            expected_attempt_count=record.attempt_count,
            state=ChannelDeliveryState.ABANDONED,
            at=at or _aware(self._clock()),
            error_code=error_code,
        )


async def _terminal_event(stream: ConversationEventStream) -> JsonObject:
    async for event in stream:
        if event.event == "done":
            return event.data
    raise ValueError("semantic event stream closed before terminal done")


def _inbound_key(authenticated: AuthenticatedInboundTurn) -> str:
    turn = authenticated.turn
    identity = "\0".join((turn.channel_kind.value, turn.channel_id, turn.message_id))
    return hashlib.sha256(identity.encode()).hexdigest()


def _delivery_id(inbound_key: str) -> str:
    return f"channel-delivery:{inbound_key}"


def _binding_matches_record(
    binding: PrincipalChannelBinding,
    record: ChannelDeliveryRecord,
) -> bool:
    return (
        binding.state is ChannelBindingState.ACTIVE
        and binding.principal_id == record.principal_id
        and binding.scope_ref == record.scope_ref
        and binding.conversation_id == record.conversation_id
        and binding.endpoint.channel_kind is record.channel_kind
    )


def _delivery_record(
    *,
    delivery_id: str,
    inbound_key: str,
    binding: PrincipalChannelBinding,
    terminal: JsonObject,
    now: datetime,
    config: ChannelDeliveryPipelineConfig,
) -> ChannelDeliveryRecord:
    expires_at = now + config.delivery_ttl
    return ChannelDeliveryRecord(
        delivery_id=delivery_id,
        idempotency_key=f"channel-terminal:{inbound_key}",
        principal_id=binding.principal_id,
        scope_ref=binding.scope_ref,
        conversation_id=binding.conversation_id,
        binding_id=binding.binding_id,
        channel_kind=binding.endpoint.channel_kind,
        response=terminal,
        response_digest=channel_response_digest(terminal),
        state=ChannelDeliveryState.PENDING,
        created_at=now,
        due_at=now,
        expires_at=expires_at,
        retention_until=now + config.retention,
    )


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("channel pipeline clock MUST be timezone-aware")
    return value.astimezone(UTC)


__all__ = [
    "ChannelDeliveryPipeline",
    "ChannelDeliveryPipelineConfig",
    "ChannelPipelineResult",
    "ChannelPrincipalContext",
    "ChannelPrincipalResolver",
]
