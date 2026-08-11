"""Run the durable no-authority Operator side of semantic-turn transport."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, cast
from uuid import UUID, uuid5

from fdai_operator_service.contract_codecs import CORE_PROJECTION_CONSUMER_V12
from fdai_operator_service.families.conversation.contracts import (
    ConversationBoundaryError,
    ConversationEventStream,
    ConversationProjectionReader,
    ConversationProposal,
    ConversationProposalOutbox,
    ConversationQuery,
    ConversationResponse,
    ConversationStreamReader,
    ConversationStreamRequest,
    JsonObject,
    OutboxReceipt,
    StreamEvent,
)
from fdai_operator_service.families.conversation.semantic_turn import SemanticTurnEnvelopeBuilder
from fdai_operator_service.postgres_family_store import (
    SemanticTurnClaim,
    StoredSemanticResult,
    StoredSemanticTurn,
)
from fdai_service_contracts import SemanticTurnDisposition, SemanticTurnResult

SEMANTIC_REQUEST_TOPIC = "operator-core-request"
SEMANTIC_RESULT_TOPIC = "core-operator-projection"
SEMANTIC_RESULT_GROUP = "operator-semantic-turn-v1"
_IDENTITY_NAMESPACE = UUID("00000000-0000-0000-0000-000000000000")


class SemanticTurnStore(Protocol):
    """Expose only public durable operations required by the semantic bridge."""

    async def append_semantic_turn(
        self,
        *,
        principal_id: str,
        idempotency_key: str,
        request_digest: str,
        envelope: Mapping[str, object],
    ) -> StoredSemanticTurn: ...

    async def claim_semantic_turn(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
    ) -> SemanticTurnClaim | None: ...

    async def mark_semantic_turn_published(self, *, key: str, claim_id: str) -> bool: ...

    async def release_semantic_turn_claim(self, *, key: str, claim_id: str) -> bool: ...

    async def read_semantic_turn(
        self,
        *,
        principal_id: str,
        proposal_id: str,
    ) -> StoredSemanticTurn | None: ...

    async def project_semantic_turn_result(
        self,
        *,
        projection: Mapping[str, object],
    ) -> StoredSemanticResult: ...

    async def replay_semantic_turn(
        self,
        *,
        principal_id: str,
        request_id: str,
        after_sequence: int | None,
        limit: int = 100,
    ) -> tuple[StoredSemanticResult, ...]: ...


class SemanticTurnEventPublisher(Protocol):
    """Publish one persisted request mapping through an injected transport."""

    async def publish(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, object],
    ) -> object: ...


class SemanticTurnResultSource(Protocol):
    """Open an injected stream of raw Core projection mappings."""

    def subscribe(
        self,
        topic: str,
        group_id: str,
    ) -> AsyncIterator[Mapping[str, object]]: ...


class _SemanticEventIterator(AsyncIterator[StreamEvent]):
    def __init__(self, events: tuple[StreamEvent, ...]) -> None:
        self._events = iter(events)

    def __aiter__(self) -> _SemanticEventIterator:
        return self

    async def __anext__(self) -> StreamEvent:
        try:
            return next(self._events)
        except StopIteration as exc:
            raise StopAsyncIteration from exc

    async def aclose(self) -> None:
        """Close the finite durable semantic replay iterator."""


@dataclass(frozen=True, slots=True)
class SemanticTurnProjectionConsumer:
    """Validate v1.2 result codecs and persist principal-scoped terminal projections."""

    store: SemanticTurnStore

    async def consume(self, payload: Mapping[str, object]) -> StoredSemanticResult:
        """Reject malformed or evidence-incomplete results before durable projection."""
        decoded = CORE_PROJECTION_CONSUMER_V12.decode_mapping(payload)
        semantic_payload = decoded.get("semantic_result")
        if not isinstance(semantic_payload, dict):
            raise ValueError("semantic projection MUST contain semantic_result")
        result = SemanticTurnResult.model_validate(semantic_payload)
        if decoded.get("status") != result.disposition.value:
            raise ValueError("semantic projection status MUST match result disposition")
        return await self.store.project_semantic_turn_result(projection=decoded)


@dataclass(frozen=True, slots=True)
class SemanticTurnOutboxDrainer:
    """Lease and publish persisted requests with retry-safe compare-and-set closure."""

    store: SemanticTurnStore
    publisher: SemanticTurnEventPublisher
    worker_id: str
    request_topic: str = SEMANTIC_REQUEST_TOPIC
    lease_seconds: int = 30

    async def run_once(self) -> bool:
        """Publish at most one leased request and release transport failures for retry."""
        claim = await self.store.claim_semantic_turn(
            worker_id=self.worker_id,
            lease_seconds=self.lease_seconds,
        )
        if claim is None:
            return False
        try:
            await self.publisher.publish(
                self.request_topic,
                claim.request_id,
                claim.envelope,
            )
        except Exception:  # noqa: BLE001 - durable row remains retryable
            await self.store.release_semantic_turn_claim(
                key=claim.key,
                claim_id=claim.claim_id,
            )
            return False
        closed = await self.store.mark_semantic_turn_published(
            key=claim.key,
            claim_id=claim.claim_id,
        )
        if not closed:
            raise RuntimeError("semantic turn publish lease was lost before closure")
        return True


class SemanticTurnBridge:
    """Own semantic proposal acceptance, replay, and optional transport lifecycle."""

    def __init__(
        self,
        *,
        store: SemanticTurnStore,
        publisher: SemanticTurnEventPublisher | None = None,
        result_source: SemanticTurnResultSource | None = None,
        builder: SemanticTurnEnvelopeBuilder | None = None,
        worker_id: str = "operator-semantic-turn",
        request_topic: str = SEMANTIC_REQUEST_TOPIC,
        result_topic: str = SEMANTIC_RESULT_TOPIC,
        result_group: str = SEMANTIC_RESULT_GROUP,
        retry_seconds: float = 1.0,
    ) -> None:
        if (publisher is None) != (result_source is None):
            raise ValueError("semantic publisher and result source MUST be bound together")
        if retry_seconds <= 0:
            raise ValueError("semantic retry_seconds MUST be positive")
        if not request_topic or not result_topic or not result_group:
            raise ValueError("semantic transport topics and consumer group MUST be non-empty")
        self._store = store
        self._publisher = publisher
        self._result_source = result_source
        self._builder = builder or SemanticTurnEnvelopeBuilder()
        self._consumer = SemanticTurnProjectionConsumer(store)
        self._drainer = (
            SemanticTurnOutboxDrainer(store, publisher, worker_id, request_topic)
            if publisher is not None
            else None
        )
        self._request_topic = request_topic
        self._result_topic = result_topic
        self._result_group = result_group
        self._retry_seconds = retry_seconds
        self._tasks: tuple[asyncio.Task[None], ...] = ()

    async def append(self, proposal: ConversationProposal) -> OutboxReceipt:
        """Accept one authorized stream proposal and persist a typed held fallback if unbound."""
        envelope = self._builder.build(proposal)
        stored = await self._store.append_semantic_turn(
            principal_id=proposal.scope.subject_id,
            idempotency_key=proposal.idempotency_key,
            request_digest=_proposal_digest(proposal),
            envelope=envelope,
        )
        dispatch_status = "pending"
        if self._publisher is None:
            await self._consumer.consume(_held_projection(stored.envelope))
            dispatch_status = "held"
        return OutboxReceipt(
            proposal_id=stored.proposal_id,
            duplicate=stored.duplicate,
            response=ConversationResponse(
                status_code=202,
                body={
                    "accepted": True,
                    "proposal_id": stored.proposal_id,
                    "operation": proposal.operation,
                    "mode": "shadow",
                    "duplicate": stored.duplicate,
                    "dispatch_status": dispatch_status,
                },
            ),
        )

    async def open(self, request: ConversationStreamRequest) -> ConversationEventStream:
        """Replay only the authenticated principal's ordered events for one accepted request."""
        if request.operation != "chat.stream" or request.proposal_id is None:
            raise ConversationBoundaryError(
                400,
                "semantic_request_required",
                "semantic replay requires an accepted chat.stream proposal",
            )
        stored = await self._store.read_semantic_turn(
            principal_id=request.scope.subject_id,
            proposal_id=request.proposal_id,
        )
        if stored is None:
            raise ConversationBoundaryError(
                404,
                "semantic_turn_not_found",
                "semantic turn not found",
            )
        after_sequence = _after_sequence(request.after_event_id)
        results = await self._store.replay_semantic_turn(
            principal_id=request.scope.subject_id,
            request_id=stored.request_id,
            after_sequence=after_sequence,
        )
        return _SemanticEventIterator(
            tuple(
                StreamEvent(
                    event=result.event,
                    event_id=str(result.sequence),
                    data=cast(JsonObject, dict(result.data)),
                )
                for result in results
            )
        )

    def health(self) -> JsonObject:
        """Return a credential-free projection of semantic transport readiness."""
        available = self._publisher is not None and self._result_source is not None
        return {
            "available": available,
            "mode": "event-bridge" if available else "held",
            "request_topic": self._request_topic,
            "result_topic": self._result_topic,
        }

    async def start(self) -> None:
        """Start one publisher drainer and one result consumer when transport is injected."""
        if self._tasks or self._drainer is None or self._result_source is None:
            return
        self._tasks = (
            asyncio.create_task(self._run_drainer(), name="operator-semantic-outbox"),
            asyncio.create_task(self._run_consumer(), name="operator-semantic-results"),
        )

    async def aclose(self) -> None:
        """Cancel and join injected transport workers during application shutdown."""
        tasks, self._tasks = self._tasks, ()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _run_drainer(self) -> None:
        if self._drainer is None:
            return
        while True:
            published = await self._drainer.run_once()
            await asyncio.sleep(0 if published else self._retry_seconds)

    async def _run_consumer(self) -> None:
        if self._result_source is None:
            return
        async for payload in self._result_source.subscribe(
            self._result_topic,
            self._result_group,
        ):
            await self._consumer.consume(payload)


@dataclass(frozen=True, slots=True)
class SemanticTurnConversationAdapters:
    """Route only chat.stream through semantic transport and preserve other family adapters."""

    bridge: SemanticTurnBridge
    fallback_projections: ConversationProjectionReader
    fallback_outbox: ConversationProposalOutbox
    fallback_streams: ConversationStreamReader

    async def read(self, query: ConversationQuery) -> ConversationResponse:
        """Delegate authoritative reads and add semantic readiness to chat health."""
        response = await self.fallback_projections.read(query)
        if query.operation != "chat.health" or not isinstance(response.body, dict):
            return response
        return ConversationResponse(
            body={**response.body, "semantic_bridge": self.bridge.health()},
            status_code=response.status_code,
            media_type=response.media_type,
            headers=response.headers,
        )

    async def append(self, proposal: ConversationProposal) -> OutboxReceipt:
        """Select semantic acceptance only for chat.stream proposals."""
        if proposal.operation == "chat.stream":
            return await self.bridge.append(proposal)
        return await self.fallback_outbox.append(proposal)

    async def open(self, request: ConversationStreamRequest) -> ConversationEventStream:
        """Select semantic replay only for chat.stream requests."""
        if request.operation == "chat.stream":
            return await self.bridge.open(request)
        return await self.fallback_streams.open(request)


def _held_projection(envelope: Mapping[str, object]) -> dict[str, object]:
    request_id = _mapping_text(envelope, "request_id")
    semantic = envelope.get("semantic_turn")
    if not isinstance(semantic, Mapping):
        raise ValueError("semantic request payload is missing")
    result = SemanticTurnResult(
        disposition=SemanticTurnDisposition.HELD,
        reason_code="semantic_transport_unavailable",
        session_id=_mapping_text(semantic, "session_id"),
        turn_id=_mapping_text(semantic, "turn_id"),
        turn_sequence=_mapping_int(semantic, "turn_sequence"),
    )
    result_payload = result.model_dump(mode="json", exclude_none=True)
    result_digest = _canonical_digest(result_payload)
    projection_id = str(uuid5(_IDENTITY_NAMESPACE, f"held\0{request_id}\0{result_digest}"))
    return {
        "schema_version": "1.2.0",
        "projection_id": projection_id,
        "request_id": request_id,
        "correlation_id": _mapping_text(envelope, "correlation_id"),
        "idempotency_key": _mapping_text(envelope, "idempotency_key"),
        "status": "held",
        "recorded_at": _mapping_text(envelope, "requested_at"),
        "payload": {"reason_code": "semantic_transport_unavailable"},
        "semantic_result": result_payload,
    }


def _proposal_digest(proposal: ConversationProposal) -> str:
    value = {
        "operation": proposal.operation,
        "principal_id": proposal.scope.subject_id,
        "roles": sorted(proposal.scope.roles),
        "idempotency_key": proposal.idempotency_key,
        "body": proposal.body,
        "query": proposal.query,
        "path_params": proposal.path_params,
        "confirmed": proposal.confirmed,
        "cancellation": proposal.cancellation,
    }
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _canonical_digest(value: Mapping[str, object]) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _after_sequence(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ConversationBoundaryError(
            400,
            "invalid_replay_cursor",
            "Last-Event-ID is invalid",
        ) from exc
    if parsed < 0:
        raise ConversationBoundaryError(400, "invalid_replay_cursor", "Last-Event-ID is invalid")
    return parsed


def _mapping_text(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"semantic {key} is malformed")
    return item


def _mapping_int(value: Mapping[str, Any], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool):
        raise ValueError(f"semantic {key} is malformed")
    return item


__all__ = [
    "SEMANTIC_REQUEST_TOPIC",
    "SEMANTIC_RESULT_GROUP",
    "SEMANTIC_RESULT_TOPIC",
    "SemanticTurnBridge",
    "SemanticTurnConversationAdapters",
    "SemanticTurnEventPublisher",
    "SemanticTurnOutboxDrainer",
    "SemanticTurnProjectionConsumer",
    "SemanticTurnResultSource",
    "SemanticTurnStore",
]
