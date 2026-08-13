"""Run the durable no-authority Operator side of semantic-turn transport."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections import deque
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
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
from fdai_operator_service.families.conversation.semantic_turn_presentation import (
    semantic_done_event_data as _done_event_data,
)
from fdai_operator_service.postgres_family_store import (
    SemanticTurnClaim,
    StoredSemanticResult,
    StoredSemanticTurn,
)
from fdai_service_contracts import (
    ContractValidationError,
    RuleSearchProjection,
    SemanticTurnDisposition,
    SemanticTurnRequest,
    SemanticTurnResult,
)
from pydantic import ValidationError

SEMANTIC_REQUEST_TOPIC = "operator.semantic-turn.requests"
SEMANTIC_RESULT_TOPIC = "core.semantic-turn.projections"
SEMANTIC_RESULT_GROUP = "operator-semantic-turn-v1"
_IDENTITY_NAMESPACE = UUID("00000000-0000-0000-0000-000000000000")
_LOGGER = logging.getLogger(__name__)


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


@dataclass(frozen=True, slots=True)
class _SemanticReplayCursor:
    projection_sequence: int
    phase: str


class _SemanticEventIterator(AsyncIterator[StreamEvent]):
    """Stream observed semantic acceptance, waiting, and durable terminal phases."""

    def __init__(
        self,
        *,
        store: SemanticTurnStore,
        consumer: SemanticTurnProjectionConsumer,
        stored: StoredSemanticTurn,
        principal_id: str,
        cursor: _SemanticReplayCursor | None,
        retry_seconds: float,
    ) -> None:
        semantic = stored.envelope.get("semantic_turn")
        if not isinstance(semantic, Mapping):
            raise ValueError("stored semantic request is missing")
        self._store = store
        self._consumer = consumer
        self._stored = stored
        self._principal_id = principal_id
        self._cursor = cursor
        self._retry_seconds = retry_seconds
        self._request = SemanticTurnRequest.model_validate(semantic)
        self._events: deque[StreamEvent] = deque()
        self._closed = False
        self._terminal_loaded = False
        self._stream_sequence = 0
        self._queue_pending_progress()

    def __aiter__(self) -> _SemanticEventIterator:
        return self

    async def __anext__(self) -> StreamEvent:
        if self._events:
            return self._events.popleft()
        if self._closed or self._terminal_loaded:
            raise StopAsyncIteration
        await self._load_terminal_events()
        if self._events:
            return self._events.popleft()
        raise StopAsyncIteration

    async def aclose(self) -> None:
        """Stop polling for a durable semantic terminal after HTTP disconnect."""
        self._closed = True

    def _queue_pending_progress(self) -> None:
        if self._cursor is not None and self._cursor.projection_sequence > 0:
            return
        for phase, label in _pending_progress(self._request.locale):
            if _cursor_includes(self._cursor, 0, phase):
                continue
            self._append_event("status", phase, label, event_id=f"0:{phase}")

    def _append_event(
        self,
        event: str,
        phase: str,
        label: str,
        *,
        event_id: str,
        completed: int | None = None,
        total: int | None = None,
    ) -> None:
        self._stream_sequence += 1
        self._events.append(
            StreamEvent(
                event=event,
                event_id=event_id,
                data=cast(
                    JsonObject,
                    {
                        "seq": self._stream_sequence,
                        "revision": 0,
                        "phase": phase,
                        "label": label,
                        "completed": completed,
                        "total": total,
                        "sources": [],
                    },
                ),
            )
        )

    async def _load_terminal_events(self) -> None:
        store_after = _store_after_sequence(self._cursor)
        while not self._closed:
            results = await self._store.replay_semantic_turn(
                principal_id=self._principal_id,
                request_id=self._stored.request_id,
                after_sequence=store_after,
            )
            if results:
                for result in results:
                    self._queue_result(result)
                self._terminal_loaded = True
                return
            if self._cursor is not None and self._cursor.phase == "done":
                self._terminal_loaded = True
                return
            remaining = (self._request.deadline_at - datetime.now(UTC)).total_seconds()
            if remaining <= 0:
                await self._consumer.consume(_held_projection(self._stored.envelope))
                store_after = _store_after_sequence(self._cursor)
                continue
            await asyncio.sleep(min(self._retry_seconds, remaining))

    def _queue_result(self, result: StoredSemanticResult) -> None:
        semantic = result.data.get("semantic_result")
        if not isinstance(semantic, Mapping):
            raise ValueError("stored semantic projection is missing semantic_result")
        disposition = semantic.get("disposition")
        checks_completed = semantic.get("checks_completed", 0)
        checks_total = semantic.get("checks_total", 0)
        if (
            disposition == "answered"
            and isinstance(checks_completed, int)
            and isinstance(checks_total, int)
        ):
            labels = _terminal_progress(self._request.locale)
            for event, phase in (
                ("status", "evidence"),
                ("verification", "verification"),
                ("status", "presentation"),
            ):
                if _cursor_includes(self._cursor, result.sequence, phase):
                    continue
                self._append_event(
                    event,
                    phase,
                    labels[phase],
                    event_id=f"{result.sequence}:{phase}",
                    completed=checks_completed,
                    total=checks_total,
                )
        if _cursor_includes(self._cursor, result.sequence, "done"):
            return
        self._stream_sequence += 1
        done = _done_event_data(result.data, locale=self._request.locale)
        done["seq"] = self._stream_sequence
        self._events.append(
            StreamEvent(
                event="done",
                event_id=str(result.sequence),
                data=done,
            )
        )


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
        extension_payload = decoded.get("payload")
        if not isinstance(extension_payload, dict):
            raise ValueError("semantic projection payload MUST be an object")
        rule_search = extension_payload.get("rule_search")
        if rule_search is not None:
            RuleSearchProjection.model_validate(rule_search)
        return await self.store.project_semantic_turn_result(projection=decoded)


@dataclass(frozen=True, slots=True)
class SemanticTurnOutboxDrainer:
    """Lease and publish persisted requests with retry-safe compare-and-set closure."""

    store: SemanticTurnStore
    publisher: SemanticTurnEventPublisher
    worker_id: str
    request_topic: str = SEMANTIC_REQUEST_TOPIC
    lease_seconds: int = 120

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
            return False
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
        return _SemanticEventIterator(
            store=self._store,
            consumer=self._consumer,
            stored=stored,
            principal_id=request.scope.subject_id,
            cursor=_after_sequence(request.after_event_id),
            retry_seconds=self._retry_seconds,
        )

    def health(self) -> JsonObject:
        """Return a credential-free projection of semantic transport readiness."""
        configured = self._publisher is not None and self._result_source is not None
        available = configured and self.workers_ready()
        return {
            "available": available,
            "configured": configured,
            "mode": "event-bridge" if available else ("starting" if configured else "held"),
            "request_topic": self._request_topic,
            "result_topic": self._result_topic,
        }

    def workers_ready(self) -> bool:
        """Return whether both configured background workers remain active."""
        return len(self._tasks) == 2 and all(not task.done() for task in self._tasks)

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
            try:
                published = await self._drainer.run_once()
            except Exception:  # noqa: BLE001 - transient store failures retry in-process
                _LOGGER.warning("semantic_outbox_drainer_retrying", exc_info=True)
                published = False
            await asyncio.sleep(0 if published else self._retry_seconds)

    async def _run_consumer(self) -> None:
        if self._result_source is None or self._publisher is None:
            return
        while True:
            try:
                async for payload in self._result_source.subscribe(
                    self._result_topic,
                    self._result_group,
                ):
                    try:
                        await self._consumer.consume(payload)
                    except (ContractValidationError, ValidationError, ValueError):
                        quarantine_key = _projection_quarantine_key(payload)
                        await self._publisher.publish(
                            f"{self._result_topic}.dlq",
                            quarantine_key,
                            {
                                "original_topic": self._result_topic,
                                "projection_ref": quarantine_key,
                                "reason": "semantic_turn_projection_rejected",
                            },
                        )
            except Exception:  # noqa: BLE001 - preserve offset and resubscribe after backoff
                _LOGGER.warning("semantic_projection_consumer_retrying", exc_info=True)
            await asyncio.sleep(self._retry_seconds)


@dataclass(frozen=True, slots=True)
class SemanticTurnConversationAdapters:
    """Route only chat.stream through semantic transport and preserve other family adapters."""

    bridge: SemanticTurnBridge
    fallback_projections: ConversationProjectionReader
    fallback_outbox: ConversationProposalOutbox
    fallback_streams: ConversationStreamReader

    async def read(self, query: ConversationQuery) -> ConversationResponse:
        """Serve bridge-owned health and delegate every durable projection read."""
        if query.operation != "chat.health":
            return await self.fallback_projections.read(query)
        health = self.bridge.health()
        return ConversationResponse(
            body={
                "available": health["available"],
                "mode": health["mode"],
                "model": None,
                "endpoint": None,
                "semantic_bridge": health,
            },
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
        unavailable_reason="semantic_planner_unavailable",
        session_id=_mapping_text(semantic, "session_id"),
        turn_id=_mapping_text(semantic, "turn_id"),
        turn_sequence=_mapping_int(semantic, "turn_sequence"),
        answer=(
            "검증된 semantic transport를 사용할 수 없어 온톨로지 쿼리를 보류했습니다. "
            "(semantic_transport_unavailable)"
            if _mapping_text(semantic, "locale").casefold().startswith("ko")
            else "The ontology query was held because verified semantic transport is unavailable. "
            "(semantic_transport_unavailable)"
        ),
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


def _projection_quarantine_key(payload: Mapping[str, object]) -> str:
    projection_id = payload.get("projection_id")
    identity = projection_id if isinstance(projection_id, str) else "missing-projection-id"
    return f"semantic-projection-rejected:{hashlib.sha256(identity.encode()).hexdigest()}"


_SEMANTIC_PHASES = (
    "accepted",
    "planning",
    "evidence",
    "verification",
    "presentation",
    "done",
)


def _after_sequence(value: str | None) -> _SemanticReplayCursor | None:
    if value is None:
        return None
    if ":" in value:
        raw_sequence, phase = value.split(":", 1)
    else:
        raw_sequence, phase = value, "done"
    try:
        parsed = int(raw_sequence)
    except ValueError as exc:
        raise ConversationBoundaryError(
            400,
            "invalid_replay_cursor",
            "Last-Event-ID is invalid",
        ) from exc
    if parsed < 0 or phase not in _SEMANTIC_PHASES:
        raise ConversationBoundaryError(400, "invalid_replay_cursor", "Last-Event-ID is invalid")
    if parsed == 0 and phase not in {"accepted", "planning"}:
        raise ConversationBoundaryError(400, "invalid_replay_cursor", "Last-Event-ID is invalid")
    return _SemanticReplayCursor(parsed, phase)


def _store_after_sequence(cursor: _SemanticReplayCursor | None) -> int | None:
    if cursor is None or cursor.projection_sequence == 0:
        return None
    if cursor.phase == "done":
        return cursor.projection_sequence
    return cursor.projection_sequence - 1


def _cursor_includes(
    cursor: _SemanticReplayCursor | None,
    projection_sequence: int,
    phase: str,
) -> bool:
    if cursor is None or cursor.projection_sequence != projection_sequence:
        return False
    return _SEMANTIC_PHASES.index(phase) <= _SEMANTIC_PHASES.index(cursor.phase)


def _pending_progress(locale: str) -> tuple[tuple[str, str], ...]:
    if locale.casefold().startswith("ko"):
        return (
            ("accepted", "의미 요청을 수락했습니다."),
            ("planning", "검증된 의미 계획을 기다리는 중입니다."),
        )
    return (
        ("accepted", "Semantic request accepted."),
        ("planning", "Waiting for a verified semantic plan."),
    )


def _terminal_progress(locale: str) -> dict[str, str]:
    if locale.casefold().startswith("ko"):
        return {
            "evidence": "근거 실행이 완료되었습니다.",
            "verification": "근거 검증이 완료되었습니다.",
            "presentation": "운영자 답변을 준비했습니다.",
        }
    return {
        "evidence": "Evidence execution completed.",
        "verification": "Evidence verification completed.",
        "presentation": "Operator answer prepared.",
    }


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
