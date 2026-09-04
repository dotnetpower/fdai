"""Run the durable no-authority Operator side of semantic-turn transport."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections import OrderedDict, deque
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Protocol, cast
from uuid import UUID, uuid5

from fdai_operator_service.contract_codecs import CORE_PROJECTION_CONSUMER_V14
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
from fdai_operator_service.families.conversation.document_export import (
    ConversationDocumentExporter,
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
from fdai_operator_service.postgres_semantic_turn_store import (
    SemanticTurnConflictError,
    SemanticTurnRequestAbsentError,
    SemanticTurnTerminalClosedError,
)
from fdai_service_contracts import (
    MAX_INTENT_GRAPH_GOALS,
    ContractValidationError,
    OperationalEvidenceProjection,
    RuleSearchProjection,
    SemanticInvestigationContinuation,
    SemanticQueryProgress,
    SemanticTurnDisposition,
    SemanticTurnRequest,
    SemanticTurnResult,
)
from pydantic import ValidationError

SEMANTIC_REQUEST_TOPIC = "operator.semantic-turn.requests"
SEMANTIC_RESULT_TOPIC = "core.semantic-turn.projections"
SEMANTIC_PROGRESS_TOPIC = "core.semantic-turn.progress"
SEMANTIC_RESULT_GROUP = "operator-semantic-turn-v1"
SEMANTIC_PROGRESS_GROUP = "operator-semantic-progress-v1"
_IDENTITY_NAMESPACE = UUID("00000000-0000-0000-0000-000000000000")
_MAX_PROJECTION_CONFLICT_ATTEMPTS = 5
_MAX_TRACKED_PROJECTION_CONFLICTS = 256
_MAX_EXECUTION_OUTPUT_CHARS = 64 * 1024
_MAX_ANSWER_CHUNK_CHARS = 64
_MAX_TRACKED_PROGRESS_REQUESTS = 256
_MAX_PROGRESS_UPDATES_PER_REQUEST = MAX_INTENT_GRAPH_GOALS * 2
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
        source_request_id: str | None = None,
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

    async def latest_semantic_investigation_continuation(
        self,
        *,
        principal_id: str,
        session_id: str,
    ) -> SemanticInvestigationContinuation | None: ...

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


class _SemanticProgressRelay:
    """Retain a bounded best-effort timeline until the terminal replay arrives."""

    def __init__(self) -> None:
        self._updates: OrderedDict[str, deque[SemanticQueryProgress]] = OrderedDict()
        self._signals: dict[str, asyncio.Event] = {}

    def consume(self, payload: Mapping[str, object]) -> bool:
        """Validate and retain one monotonic update, ignoring stale redelivery."""
        progress = SemanticQueryProgress.model_validate(payload)
        updates = self._updates.get(progress.request_id)
        if updates is None:
            if len(self._updates) >= _MAX_TRACKED_PROGRESS_REQUESTS:
                expired_request_id, _expired = self._updates.popitem(last=False)
                self._signals.pop(expired_request_id, None)
            updates = deque(maxlen=_MAX_PROGRESS_UPDATES_PER_REQUEST)
            self._updates[progress.request_id] = updates
        elif updates and progress.progress_sequence <= updates[-1].progress_sequence:
            return False
        updates.append(progress)
        self._signals.setdefault(progress.request_id, asyncio.Event()).set()
        self._updates.move_to_end(progress.request_id)
        return True

    def after(self, request_id: str, progress_sequence: int) -> tuple[SemanticQueryProgress, ...]:
        """Return retained updates after one iterator-local sequence cursor."""
        return tuple(
            update
            for update in self._updates.get(request_id, ())
            if update.progress_sequence > progress_sequence
        )

    def discard(self, request_id: str) -> None:
        """Drop transient updates once durable terminal replay is authoritative."""
        self._updates.pop(request_id, None)
        self._signals.pop(request_id, None)

    async def wait_for_update(
        self,
        request_id: str,
        progress_sequence: int,
        *,
        timeout: float,
    ) -> None:
        """Wake one active stream as soon as a newer progress record arrives."""
        if self.after(request_id, progress_sequence):
            return
        signal = self._signals.setdefault(request_id, asyncio.Event())
        signal.clear()
        if self.after(request_id, progress_sequence):
            return
        try:
            await asyncio.wait_for(signal.wait(), timeout=timeout)
        except TimeoutError:
            return


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
        progress_relay: _SemanticProgressRelay,
        stored: StoredSemanticTurn,
        principal_id: str,
        cursor: _SemanticReplayCursor | None,
        retry_seconds: float,
        document_exporter: ConversationDocumentExporter | None = None,
    ) -> None:
        semantic = stored.envelope.get("semantic_turn")
        if not isinstance(semantic, Mapping):
            raise ValueError("stored semantic request is missing")
        self._store = store
        self._consumer = consumer
        self._progress_relay = progress_relay
        self._stored = stored
        self._principal_id = principal_id
        self._cursor = cursor
        self._retry_seconds = retry_seconds
        self._document_exporter = document_exporter
        self._request = SemanticTurnRequest.model_validate(semantic)
        self._events: deque[StreamEvent] = deque()
        self._closed = False
        self._terminal_loaded = False
        self._terminal_absent_observed = False
        self._stream_sequence = 0
        self._progress_sequence = 0
        self._running_activities: dict[str, tuple[str, str | None]] = {}
        self._queue_initial_progress()

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

    def _queue_initial_progress(self) -> None:
        """Queue replay-safe progress for states observed by the Operator itself."""
        labels = _initial_progress(self._request.locale)
        for phase in ("accepted", "planning"):
            if self._cursor is not None and (
                self._cursor.projection_sequence > 0 or _cursor_includes(self._cursor, 0, phase)
            ):
                continue
            self._append_event(
                "status",
                phase,
                labels[phase],
                event_id=f"0:{phase}",
            )

    def _append_activity(
        self,
        phase: str,
        label: str,
        *,
        status: str,
        event_id: str,
        completed: int | None = None,
        total: int | None = None,
        execution: JsonObject | None = None,
        activity_id: str | None = None,
        kind: str = "semantic_turn",
        detail: str | None = None,
        observed_at: str | None = None,
    ) -> None:
        """Queue one bounded step record for the observed-process timeline."""
        if status == "running":
            self._running_activities[phase] = (label, detail)
        else:
            self._running_activities.pop(phase, None)
        self._stream_sequence += 1
        self._events.append(
            StreamEvent(
                event="activity",
                event_id=event_id,
                data=cast(
                    JsonObject,
                    {
                        "seq": self._stream_sequence,
                        "revision": 0,
                        "activity_id": activity_id or f"semantic:{phase}",
                        "kind": kind,
                        "status": status,
                        "label": label,
                        "authority": "read_only",
                        "completed": completed,
                        "total": total,
                        **({"detail": detail} if detail is not None else {}),
                        **({"observed_at": observed_at} if observed_at is not None else {}),
                        **({"execution": execution} if execution is not None else {}),
                    },
                ),
            )
        )

    def _settle_pending_activities(self, sequence: int) -> None:
        """Complete every step still reported as running before the terminal."""
        for phase, (label, detail) in tuple(self._running_activities.items()):
            self._append_activity(
                phase,
                label,
                status="completed",
                event_id=f"{sequence}:done",
                detail=detail,
            )

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
            if not results:
                self._terminal_absent_observed = True
            progress_updates = self._progress_relay.after(
                self._stored.request_id,
                self._progress_sequence,
            )
            if progress_updates and self._terminal_absent_observed:
                progress = progress_updates[0]
                self._progress_sequence = progress.progress_sequence
                if (
                    progress.session_id == self._request.session_id
                    and progress.turn_id == self._request.turn_id
                    and progress.turn_sequence == self._request.turn_sequence
                ):
                    self._queue_progress(progress)
                    return
                continue
            if results:
                self._progress_relay.discard(self._stored.request_id)
                for result in results:
                    await self._queue_result(result)
                self._terminal_loaded = True
                return
            if self._cursor is not None and self._cursor.phase == "done":
                self._terminal_loaded = True
                return
            remaining = (self._request.deadline_at - datetime.now(UTC)).total_seconds()
            if remaining <= 0:
                try:
                    await self._consumer.consume(
                        _held_projection(
                            self._stored.envelope,
                            recorded_at=datetime.now(UTC),
                        )
                    )
                except SemanticTurnTerminalClosedError:
                    _LOGGER.info(
                        "semantic_projection_late_ignored",
                        extra={"request_id": self._stored.request_id},
                    )
                store_after = _store_after_sequence(self._cursor)
                continue
            await self._progress_relay.wait_for_update(
                self._stored.request_id,
                self._progress_sequence,
                timeout=min(self._retry_seconds, remaining),
            )

    def _queue_progress(self, progress: SemanticQueryProgress) -> None:
        _LOGGER.info("semantic_query_progress_streamed")
        activity = _progress_query_activity(progress, locale=self._request.locale)
        self._append_activity(
            f"goal:{progress.step_index}",
            cast(str, activity["label"]),
            status=cast(str, activity["status"]),
            event_id="0:planning",
            activity_id=cast(str, activity["activity_id"]),
            kind="ontology_query",
            detail=cast(str, activity["detail"]),
            observed_at=cast(str, activity["observed_at"]),
            completed=cast(int, activity["completed"]),
            total=cast(int, activity["total"]),
            execution=cast(JsonObject, activity["execution"]),
        )

    async def _queue_result(self, result: StoredSemanticResult) -> None:
        if _pantheon_assurance_payload(result.data) is not None:
            self._queue_pantheon_result(result)
            return
        semantic = result.data.get("semantic_result")
        if not isinstance(semantic, Mapping):
            raise ValueError("stored semantic projection is missing semantic_result")
        disposition = semantic.get("disposition")
        checks_completed = semantic.get("checks_completed", 0)
        checks_total = semantic.get("checks_total", 0)
        query_activities = _verified_query_activities(
            result.data,
            locale=self._request.locale,
        )
        if not _cursor_includes(self._cursor, result.sequence, "evidence"):
            for index, activity in enumerate(query_activities, start=1):
                self._append_activity(
                    f"goal:{index}",
                    cast(str, activity["label"]),
                    status=cast(str, activity["status"]),
                    event_id=f"{result.sequence}:goal:{index}",
                    activity_id=cast(str, activity["activity_id"]),
                    kind="ontology_query",
                    detail=cast(str, activity["detail"]),
                    observed_at=cast(str, activity["observed_at"]),
                    execution=cast(JsonObject, activity["execution"]),
                )
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
                self._append_activity(
                    phase,
                    labels[phase],
                    status="completed",
                    event_id=f"{result.sequence}:{phase}",
                    completed=checks_completed,
                    total=checks_total,
                    detail=_terminal_progress_detail(phase, self._request.locale),
                    # Only the evidence step ran a query. Attaching the same
                    # record to a step that executed nothing would report work
                    # the turn never did.
                    execution=None,
                )
        # The waiting step is observed as finished only once a terminal
        # projection exists. Settling it here keeps the timeline from holding a
        # step that already ended, whatever the disposition turned out to be.
        self._settle_pending_activities(result.sequence)
        done = _done_event_data(result.data, locale=self._request.locale)
        if _is_document_draft(result.data) and self._stored.source_request_id is not None:
            if self._document_exporter is None:
                done["answer"] = _document_unavailable_answer(self._request.locale)
            else:
                try:
                    document = await self._document_exporter.materialize(
                        principal_id=self._principal_id,
                        source_request_id=self._stored.source_request_id,
                    )
                except ConversationBoundaryError:
                    done["answer"] = _document_unavailable_answer(self._request.locale)
                else:
                    done["answer"] = _document_ready_answer(
                        self._request.locale,
                        included_rows=document.included_rows,
                    )
                    done["document_artifact"] = document.metadata(
                        pdf_available=self._document_exporter.pdf_encoder is not None
                    )
        if disposition == "answered" and not _cursor_includes(
            self._cursor, result.sequence, "answer"
        ):
            for delta in _verified_answer_chunks(done.get("answer")):
                self._stream_sequence += 1
                self._events.append(
                    StreamEvent(
                        event="token",
                        event_id=f"{result.sequence}:answer",
                        data=cast(
                            JsonObject,
                            {
                                "seq": self._stream_sequence,
                                "revision": 0,
                                "delta": delta,
                            },
                        ),
                    )
                )
        if _cursor_includes(self._cursor, result.sequence, "done"):
            return
        self._stream_sequence += 1
        done["seq"] = self._stream_sequence
        self._events.append(
            StreamEvent(
                event="done",
                event_id=str(result.sequence),
                data=done,
            )
        )

    def _queue_pantheon_result(self, result: StoredSemanticResult) -> None:
        done = _done_event_data(result.data, locale=self._request.locale)
        self._settle_pending_activities(result.sequence)
        if not _cursor_includes(self._cursor, result.sequence, "answer"):
            for delta in _verified_answer_chunks(done.get("answer")):
                self._stream_sequence += 1
                self._events.append(
                    StreamEvent(
                        event="token",
                        event_id=f"{result.sequence}:answer",
                        data=cast(
                            JsonObject,
                            {
                                "seq": self._stream_sequence,
                                "revision": 0,
                                "delta": delta,
                            },
                        ),
                    )
                )
        if _cursor_includes(self._cursor, result.sequence, "done"):
            return
        self._stream_sequence += 1
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
        decoded = CORE_PROJECTION_CONSUMER_V14.decode_mapping(payload)
        semantic_payload = decoded.get("semantic_result")
        extension_payload = decoded.get("payload")
        if not isinstance(extension_payload, dict):
            raise ValueError("semantic projection payload MUST be an object")
        if not isinstance(semantic_payload, dict):
            raise ValueError("semantic projection MUST contain semantic_result")
        result = SemanticTurnResult.model_validate(semantic_payload)
        if decoded.get("status") != result.disposition.value:
            raise ValueError("semantic projection status MUST match result disposition")
        operational_evidence = extension_payload.get("operational_evidence")
        if operational_evidence is not None:
            if result.disposition is not SemanticTurnDisposition.ANSWERED:
                raise ValueError("operational evidence requires an answered semantic result")
            OperationalEvidenceProjection.model_validate(operational_evidence)
        _pantheon_assurance_payload(decoded)
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
        progress_topic: str = SEMANTIC_PROGRESS_TOPIC,
        progress_group: str = SEMANTIC_PROGRESS_GROUP,
        retry_seconds: float = 1.0,
    ) -> None:
        if (publisher is None) != (result_source is None):
            raise ValueError("semantic publisher and result source MUST be bound together")
        if retry_seconds <= 0:
            raise ValueError("semantic retry_seconds MUST be positive")
        if not request_topic or not result_topic or not result_group or not progress_topic:
            raise ValueError("semantic transport topics and consumer group MUST be non-empty")
        if not progress_group or progress_topic in {request_topic, result_topic}:
            raise ValueError("semantic progress transport MUST be distinct and non-empty")
        self._store = store
        self._publisher = publisher
        self._result_source = result_source
        self._builder = builder or SemanticTurnEnvelopeBuilder()
        self._consumer = SemanticTurnProjectionConsumer(store)
        self._progress_relay = _SemanticProgressRelay()
        self._drainer = (
            SemanticTurnOutboxDrainer(store, publisher, worker_id, request_topic)
            if publisher is not None
            else None
        )
        self._request_topic = request_topic
        self._result_topic = result_topic
        self._result_group = result_group
        self._progress_topic = progress_topic
        self._progress_group = progress_group
        self._retry_seconds = retry_seconds
        self._tasks: tuple[asyncio.Task[None], ...] = ()

    async def append(self, proposal: ConversationProposal) -> OutboxReceipt:
        """Accept one authorized stream proposal and persist a typed held fallback if unbound."""
        envelope = self._builder.build(proposal)
        semantic = SemanticTurnRequest.model_validate(envelope["semantic_turn"])
        continuation = await self._store.latest_semantic_investigation_continuation(
            principal_id=proposal.scope.subject_id,
            session_id=semantic.session_id,
        )
        if continuation is not None:
            proposal = replace(
                proposal,
                body={
                    **proposal.body,
                    "turn_sequence": continuation.source_turn_sequence + 1,
                },
            )
            envelope = self._builder.build(
                proposal,
                investigation_continuation=continuation,
            )
        source_request_id = _source_request_id(proposal.body.get("source_request_id"))
        if source_request_id == envelope["request_id"]:
            raise ConversationBoundaryError(
                400,
                "source_request_invalid",
                "source request id must refer to an earlier request",
            )
        stored = await self._store.append_semantic_turn(
            principal_id=proposal.scope.subject_id,
            idempotency_key=proposal.idempotency_key,
            request_digest=_proposal_digest(proposal),
            envelope=envelope,
            source_request_id=source_request_id,
        )
        dispatch_status = "pending"
        if self._publisher is None:
            try:
                await self._consumer.consume(_held_projection(stored.envelope))
            except SemanticTurnTerminalClosedError:
                _LOGGER.info(
                    "semantic_projection_late_ignored",
                    extra={"request_id": stored.request_id},
                )
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

    async def open(
        self,
        request: ConversationStreamRequest,
        *,
        document_exporter: ConversationDocumentExporter | None = None,
    ) -> ConversationEventStream:
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
            progress_relay=self._progress_relay,
            stored=stored,
            principal_id=request.scope.subject_id,
            cursor=_after_sequence(request.after_event_id),
            retry_seconds=self._retry_seconds,
            document_exporter=document_exporter,
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
            "progress_topic": self._progress_topic,
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
        async with asyncio.TaskGroup() as group:
            group.create_task(self._run_result_consumer())
            group.create_task(self._run_progress_consumer())

    async def _run_result_consumer(self) -> None:
        if self._result_source is None or self._publisher is None:
            return
        conflicts: dict[str, int] = {}
        while True:
            try:
                async for payload in self._result_source.subscribe(
                    self._result_topic,
                    self._result_group,
                ):
                    quarantine_key = _projection_quarantine_key(payload)
                    try:
                        await self._consumer.consume(payload)
                    except (ContractValidationError, ValidationError, ValueError):
                        await self._quarantine(quarantine_key)
                    except SemanticTurnRequestAbsentError:
                        # A projection can arrive before its durable request commits, so
                        # retry that race a bounded number of times. Retrying forever
                        # instead stalls every later projection behind one poison record.
                        attempts = conflicts.get(quarantine_key, 0) + 1
                        if attempts < _MAX_PROJECTION_CONFLICT_ATTEMPTS:
                            # Losing a counter only costs extra retries, so keep the map
                            # bounded rather than growing it per untrusted identity.
                            if len(conflicts) >= _MAX_TRACKED_PROJECTION_CONFLICTS:
                                conflicts.clear()
                            conflicts[quarantine_key] = attempts
                            raise
                        conflicts.pop(quarantine_key, None)
                        _LOGGER.warning(
                            "semantic_projection_unmatched_quarantined",
                            extra={"failure_type": "durable_request_absent"},
                        )
                        await self._quarantine(quarantine_key)
                    except SemanticTurnTerminalClosedError:
                        conflicts.pop(quarantine_key, None)
                        _LOGGER.info("semantic_projection_late_ignored")
                    except SemanticTurnConflictError as exc:
                        conflicts.pop(quarantine_key, None)
                        _LOGGER.warning(
                            "semantic_projection_conflict_quarantined",
                            extra={"failure_type": exc.failure_type},
                        )
                        await self._quarantine(quarantine_key)
                    else:
                        conflicts.pop(quarantine_key, None)
            except SemanticTurnRequestAbsentError:
                _LOGGER.info(
                    "semantic_projection_conflict_retrying",
                    extra={"failure_type": "durable_request_absent"},
                )
            except Exception:  # noqa: BLE001 - preserve offset and resubscribe after backoff
                _LOGGER.warning("semantic_projection_consumer_retrying", exc_info=True)
            await asyncio.sleep(self._retry_seconds)

    async def _run_progress_consumer(self) -> None:
        if self._result_source is None or self._publisher is None:
            return
        while True:
            try:
                async for payload in self._result_source.subscribe(
                    self._progress_topic,
                    self._progress_group,
                ):
                    try:
                        if self._progress_relay.consume(payload):
                            _LOGGER.info("semantic_query_progress_received")
                    except (ValidationError, ValueError):
                        await self._quarantine_progress(payload)
            except Exception:  # noqa: BLE001 - preserve offset and resubscribe after backoff
                _LOGGER.warning("semantic_progress_consumer_retrying", exc_info=True)
            await asyncio.sleep(self._retry_seconds)

    async def _quarantine(self, quarantine_key: str) -> None:
        if self._publisher is None:  # pragma: no cover - bound with the result source
            raise RuntimeError("semantic publisher is unavailable")
        await self._publisher.publish(
            f"{self._result_topic}.dlq",
            quarantine_key,
            {
                "original_topic": self._result_topic,
                "projection_ref": quarantine_key,
                "reason": "semantic_turn_projection_rejected",
            },
        )

    async def _quarantine_progress(self, payload: Mapping[str, object]) -> None:
        if self._publisher is None:  # pragma: no cover - bound with the result source
            raise RuntimeError("semantic publisher is unavailable")
        request_id = payload.get("request_id")
        identity = request_id if isinstance(request_id, str) else "missing-request-id"
        quarantine_key = (
            f"semantic-progress-rejected:{hashlib.sha256(identity.encode()).hexdigest()}"
        )
        await self._publisher.publish(
            f"{self._progress_topic}.dlq",
            quarantine_key,
            {
                "original_topic": self._progress_topic,
                "progress_ref": quarantine_key,
                "reason": "semantic_query_progress_rejected",
            },
        )


@dataclass(frozen=True, slots=True)
class SemanticTurnConversationAdapters:
    """Route only chat.stream through semantic transport and preserve other family adapters."""

    bridge: SemanticTurnBridge
    fallback_projections: ConversationProjectionReader
    fallback_outbox: ConversationProposalOutbox
    fallback_streams: ConversationStreamReader
    document_exporter: ConversationDocumentExporter | None = None

    async def read(self, query: ConversationQuery) -> ConversationResponse:
        """Serve bridge-owned health and delegate every durable projection read."""
        if query.operation == "chat.document.download":
            if self.document_exporter is None:
                raise ConversationBoundaryError(
                    503,
                    "document_export_unavailable",
                    "conversation document export is unavailable",
                )
            return await self.document_exporter.read(query)
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
            return await self.bridge.open(
                request,
                document_exporter=self.document_exporter,
            )
        return await self.fallback_streams.open(request)


def _is_document_draft(projection: Mapping[str, object]) -> bool:
    semantic = projection.get("semantic_result")
    if not isinstance(semantic, Mapping) or semantic.get("disposition") != "action_draft":
        return False
    assurance = semantic.get("assurance_observation")
    frame = assurance.get("frame") if isinstance(assurance, Mapping) else None
    subjects = frame.get("subject_types") if isinstance(frame, Mapping) else None
    return subjects == ["Document"]


def _document_ready_answer(locale: str, *, included_rows: int) -> str:
    if locale.casefold().startswith("ko"):
        return (
            f"직전 검증 결과의 전체 행 {included_rows}개를 포함한 문서 초안을 만들었습니다. "
            "아래 미리보기를 검토하거나 Markdown 또는 PDF로 다운로드할 수 있습니다."
        )
    return (
        f"I created a document draft with all {included_rows} rows from the preceding verified "
        "result. Review the preview below or download it as Markdown or PDF."
    )


def _document_unavailable_answer(locale: str) -> str:
    if locale.casefold().startswith("ko"):
        return (
            "전체 행을 검증할 수 없어 문서 다운로드를 만들지 않았습니다. "
            "원본 조회를 다시 실행한 후 문서 생성을 요청해 주세요."
        )
    return (
        "No document download was created because the complete row set could not be verified. "
        "Run the source query again, then request the document."
    )


def _held_projection(
    envelope: Mapping[str, object],
    *,
    recorded_at: datetime | None = None,
) -> dict[str, object]:
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
            "검증된 semantic transport를 사용할 수 없어 요청을 보류했습니다. "
            "(semantic_transport_unavailable)"
            if _mapping_text(semantic, "locale").casefold().startswith("ko")
            else "The request was held because verified semantic transport is unavailable. "
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
        "recorded_at": (
            recorded_at.astimezone(UTC).isoformat()
            if recorded_at is not None
            else _mapping_text(envelope, "requested_at")
        ),
        "payload": {"reason_code": "semantic_transport_unavailable"},
        "semantic_result": result_payload,
    }


def _pantheon_assurance_payload(
    projection: Mapping[str, object],
) -> Mapping[str, object] | None:
    payload = projection.get("payload")
    assurance = payload.get("pantheon_assurance") if isinstance(payload, Mapping) else None
    if not isinstance(assurance, Mapping):
        return None
    if (
        assurance.get("schema_version") != "1.0.0"
        or not isinstance(assurance.get("answer"), str)
        or not assurance["answer"]
        or not isinstance(assurance.get("assessment_id"), str)
        or not isinstance(assurance.get("trace_receipt_id"), str)
        or not isinstance(assurance.get("pantheon_trace"), Mapping)
        or not isinstance(assurance.get("pantheon_observations"), Mapping)
        or not isinstance(assurance.get("pantheon_semantic_reviews"), list)
        or not isinstance(assurance.get("pantheon_diagnostic"), Mapping)
        or assurance.get("execution_authority") is not False
    ):
        raise ValueError("Pantheon conversation assurance projection is malformed")
    return assurance


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


_MAX_EXECUTION_COMMAND_CHARS = 16 * 1024


def _query_execution_target(capability: str) -> JsonObject:
    operation = capability.removeprefix("query.").replace(".", "_")
    return {
        "interface_kind": "internal_query",
        "service": "core-control-plane",
        "component": "OntologyQueryPlanExecutor",
        "operation": (
            "object_set_materialization" if capability == "query.object_set" else operation
        ),
        "source_kind": (
            "ontology_instance_store"
            if capability == "query.object_set"
            else "registered_query_handler"
        ),
        "transport": "event_bus",
    }


def _verified_query_activities(
    projection: Mapping[str, object],
    *,
    locale: str,
) -> tuple[JsonObject, ...]:
    """Project every exact verified goal and receipt as one readable activity."""
    semantic = projection.get("semantic_result")
    graph = semantic.get("intent_graph") if isinstance(semantic, Mapping) else None
    evidence = semantic.get("intent_graph_evidence") if isinstance(semantic, Mapping) else None
    graph_goals = graph.get("goals") if isinstance(graph, Mapping) else None
    evidence_goals = evidence.get("goals") if isinstance(evidence, Mapping) else None
    if (
        not isinstance(graph_goals, list)
        or not isinstance(evidence_goals, list)
        or not 1 <= len(graph_goals) <= MAX_INTENT_GRAPH_GOALS
        or len(graph_goals) != len(evidence_goals)
    ):
        return ()
    korean = locale.casefold().startswith("ko")
    outputs = _technical_outputs_by_node(projection)
    activities: list[JsonObject] = []
    for graph_goal, receipt in zip(graph_goals, evidence_goals, strict=True):
        if not isinstance(graph_goal, Mapping) or not isinstance(receipt, Mapping):
            return ()
        goal_id = graph_goal.get("goal_id")
        intent = graph_goal.get("intent")
        capability = graph_goal.get("capability")
        arguments = graph_goal.get("arguments")
        task_id = receipt.get("task_id")
        status = receipt.get("status")
        duration_ms = receipt.get("duration_ms")
        started_at = receipt.get("started_at")
        completed_at = receipt.get("completed_at")
        evidence_refs = receipt.get("evidence_refs", [])
        depends_on = receipt.get("depends_on", [])
        reason = receipt.get("reason")
        if (
            not isinstance(goal_id, str)
            or receipt.get("goal_id") != goal_id
            or not isinstance(intent, str)
            or receipt.get("intent") != intent
            or not isinstance(capability, str)
            or receipt.get("capability") != capability
            or not isinstance(arguments, Mapping)
            or not isinstance(task_id, str)
            or not task_id.startswith("query:")
            or status
            not in {"completed", "unavailable", "failed", "cancelled", "timed_out", "skipped"}
            or not isinstance(duration_ms, int)
            or isinstance(duration_ms, bool)
            or duration_ms < 0
            or not isinstance(started_at, str)
            or not isinstance(completed_at, str)
            or not isinstance(evidence_refs, list)
            or any(not isinstance(item, str) for item in evidence_refs)
            or not isinstance(depends_on, list)
            or any(not isinstance(item, str) for item in depends_on)
            or (reason is not None and not isinstance(reason, str))
        ):
            return ()
        if not _receipt_represents_read(status, reason):
            continue
        node_id = task_id.removeprefix("query:")
        command = capability
        if len(command) > _MAX_EXECUTION_COMMAND_CHARS:
            return ()
        node_output = outputs.get(node_id)
        output = _redacted_activity_output(
            status=status,
            reason=reason,
            evidence_count=len(evidence_refs),
            node_output=node_output,
        )
        output_truncated = isinstance(node_output, Mapping) and (
            node_output.get("display_truncated") is True
            or node_output.get("source_truncation_reason") is not None
        )
        activities.append(
            cast(
                JsonObject,
                {
                    "activity_id": f"semantic:goal:{node_id}",
                    "status": _activity_status(status),
                    "label": _query_goal_label(node_id, intent=intent, korean=korean),
                    "detail": _query_goal_detail(
                        capability=capability,
                        status=status,
                        evidence_count=len(evidence_refs),
                        dependency_count=len(depends_on),
                        reason=reason,
                        korean=korean,
                    ),
                    "observed_at": completed_at,
                    "execution": {
                        "tool": "Ontology query",
                        "input_kind": "query",
                        "target": _query_execution_target(capability),
                        "command": command,
                        "redacted": True,
                        "status": status,
                        "output_status": (
                            "available" if node_output is not None else "not_available"
                        ),
                        "output": output,
                        "output_truncated": output_truncated,
                        "started_at": started_at,
                        "completed_at": completed_at,
                        "duration_ms": duration_ms,
                    },
                },
            )
        )
    return tuple(activities)


def _progress_query_activity(
    progress: SemanticQueryProgress,
    *,
    locale: str,
) -> JsonObject:
    """Project one actual Core node update into the stable query activity shape."""
    status = str(progress.status)
    korean = locale.casefold().startswith("ko")
    command = progress.capability
    output: str | None = None
    if status != "running":
        output_value: dict[str, object] = {
            "status": status,
            "duration_ms": progress.duration_ms,
            "evidence_ref_count": len(progress.evidence_refs),
        }
        if progress.reason is not None:
            output_value["reason"] = progress.reason
        output = json.dumps(
            output_value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    return cast(
        JsonObject,
        {
            "activity_id": f"semantic:goal:{progress.node_id}",
            "status": status if status == "running" else _activity_status(status),
            "label": _query_goal_label(
                progress.node_id,
                intent=progress.node_kind.value,
                korean=korean,
            ),
            "detail": _query_goal_detail(
                capability=progress.capability,
                status=status,
                evidence_count=len(progress.evidence_refs),
                dependency_count=len(progress.depends_on),
                reason=progress.reason,
                korean=korean,
            ),
            "observed_at": (progress.completed_at or progress.started_at).isoformat(),
            "completed": progress.step_index - (1 if status == "running" else 0),
            "total": progress.step_total,
            "execution": {
                "tool": "Ontology query",
                "input_kind": "query",
                "target": _query_execution_target(progress.capability),
                "command": command,
                "redacted": True,
                "status": status,
                "output_status": "not_available",
                **({"output": output} if output is not None else {}),
                "output_truncated": False,
                "started_at": progress.started_at.isoformat(),
                **(
                    {
                        "completed_at": progress.completed_at.isoformat(),
                        "duration_ms": progress.duration_ms,
                    }
                    if progress.completed_at is not None
                    else {}
                ),
            },
        },
    )


def _redacted_activity_output(
    *,
    status: str,
    reason: object,
    evidence_count: int,
    node_output: Mapping[str, object] | None,
) -> str:
    """Summarize one receipt without exposing provider input or result values."""

    summary: dict[str, object] = {
        "status": status,
        "evidence_ref_count": evidence_count,
    }
    if isinstance(reason, str):
        summary["reason"] = reason
    if node_output is not None:
        for field in (
            "returned_rows",
            "total_rows",
            "source_complete",
            "source_truncation_reason",
            "display_truncated",
        ):
            value = node_output.get(field)
            if field in node_output and (isinstance(value, bool | int | str) or value is None):
                summary[field] = value
    encoded = json.dumps(summary, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    if len(encoded) > _MAX_EXECUTION_OUTPUT_CHARS:  # pragma: no cover - fixed fields stay bounded
        raise ValueError("semantic execution summary exceeds its bound")
    return encoded


def _technical_outputs_by_node(
    projection: Mapping[str, object],
) -> dict[str, Mapping[str, object]]:
    payload = projection.get("payload")
    details = payload.get("technical_details") if isinstance(payload, Mapping) else None
    outputs = details.get("outputs") if isinstance(details, Mapping) else None
    if not isinstance(outputs, list):
        return {}
    return {
        node_id: output
        for output in outputs
        if isinstance(output, Mapping) and isinstance((node_id := output.get("node_id")), str)
    }


def _activity_status(status: object) -> str:
    if status == "completed":
        return "completed"
    if status == "unavailable" or status == "skipped":
        return "unavailable"
    return "failed"


def _receipt_represents_read(status: str, reason: object) -> bool:
    return status not in {"cancelled", "skipped"} and reason != "capability_unavailable"


def _query_goal_label(node_id: str, *, intent: str, korean: bool) -> str:
    readable = node_id.replace("_", " ").replace("-", " ")
    if korean:
        labels = {
            "resolve-target": "정확한 대상 리소스 확인",
            "change-activity": "Activity Log의 변경 및 배포 이력 조회",
            "symptom-baseline": "기준 구간 지연 메트릭 조회",
            "symptom-current": "현재 구간 지연 메트릭 조회",
            "symptom-change": "기준 구간과 현재 구간의 증상 변화 비교",
            "topology-before": "변화 전 토폴로지 스냅샷 조회",
            "topology-after": "변화 후 토폴로지 스냅샷 조회",
            "topology-change": "변화 전후 토폴로지 차이 계산",
        }
        if node_id in labels:
            return labels[node_id]
        if node_id.startswith("expand-"):
            return "의존성 및 토폴로지 경로 확인"
        if node_id.startswith("cause-"):
            return f"원인 후보 메트릭 조회: {readable.removeprefix('cause ')}"
        if node_id.startswith("hypothesis-"):
            return f"경쟁 원인 가설 평가: {readable.removeprefix('hypothesis ')}"
        return f"검증된 의미 조회 실행: {intent.replace('_', ' ')}"
    labels = {
        "resolve-target": "Resolve the exact target resource",
        "change-activity": "Read change and deployment history from Activity Log",
        "symptom-baseline": "Read the baseline latency window",
        "symptom-current": "Read the current latency window",
        "symptom-change": "Compare symptom change across the two windows",
        "topology-before": "Read the topology snapshot before the change",
        "topology-after": "Read the topology snapshot after the change",
        "topology-change": "Calculate the before-and-after topology difference",
    }
    if node_id in labels:
        return labels[node_id]
    if node_id.startswith("expand-"):
        return "Trace dependency and topology paths"
    if node_id.startswith("cause-"):
        return f"Read candidate cause metrics: {readable.removeprefix('cause ')}"
    if node_id.startswith("hypothesis-"):
        return f"Evaluate competing cause hypothesis: {readable.removeprefix('hypothesis ')}"
    return f"Run verified semantic query: {intent.replace('_', ' ')}"


def _query_goal_detail(
    *,
    capability: str,
    status: str,
    evidence_count: int,
    dependency_count: int,
    reason: str | None,
    korean: bool,
) -> str:
    if korean:
        detail = (
            f"{capability} - {status} - 근거 참조 {evidence_count}개 - "
            f"선행 단계 {dependency_count}개"
        )
        return f"{detail} - 제한: {reason}" if reason is not None else detail
    evidence_label = "reference" if evidence_count == 1 else "references"
    dependency_label = "prerequisite" if dependency_count == 1 else "prerequisites"
    detail = (
        f"{capability} - {status} - {evidence_count} evidence {evidence_label} - "
        f"{dependency_count} {dependency_label}"
    )
    return f"{detail} - limitation: {reason}" if reason is not None else detail


def _verified_answer_chunks(answer: object) -> tuple[str, ...]:
    """Split a terminal verified answer without changing its content."""

    if not isinstance(answer, str) or not answer:
        return ()
    return tuple(
        answer[index : index + _MAX_ANSWER_CHUNK_CHARS]
        for index in range(0, len(answer), _MAX_ANSWER_CHUNK_CHARS)
    )


_SEMANTIC_PHASES = (
    "accepted",
    "planning",
    "evidence",
    "verification",
    "presentation",
    "answer",
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


def _initial_progress(locale: str) -> dict[str, str]:
    if locale.casefold().startswith("ko"):
        return {
            "accepted": "질문을 수락했습니다.",
            "planning": "검증된 조사 계획을 기다리는 중입니다.",
        }
    return {
        "accepted": "Semantic request accepted.",
        "planning": "Waiting for a verified semantic plan.",
    }


def _terminal_progress_detail(phase: str, locale: str) -> str:
    korean = locale.casefold().startswith("ko")
    details = {
        "evidence": (
            "검증된 조회 노드가 모두 최종 상태에 도달했으며 각 실행 기록은 아래 단계에 표시됩니다."
            if korean
            else (
                "Every verified query node reached a terminal state; each execution receipt "
                "is shown below."
            )
        ),
        "verification": (
            "Core가 계획 digest, 실행 receipt, 근거 참조, 권한 없음 계약을 다시 검증했습니다."
            if korean
            else (
                "Core rechecked the plan digest, execution receipts, evidence references, "
                "and no-authority contract."
            )
        ),
        "presentation": (
            "검증된 관측 사실, 경쟁 가설, 한계, 다음 읽기 전용 단계를 운영자 답변으로 구성했습니다."
            if korean
            else (
                "Prepared the operator answer from verified observations, competing "
                "hypotheses, limitations, and the next read-only step."
            )
        ),
    }
    return details[phase]


def _mapping_text(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"semantic {key} is malformed")
    return item


def _source_request_id(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConversationBoundaryError(
            400,
            "source_request_invalid",
            "source request id must be a UUID",
        )
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise ConversationBoundaryError(
            400,
            "source_request_invalid",
            "source request id must be a UUID",
        ) from exc
    if str(parsed) != value.lower():
        raise ConversationBoundaryError(
            400,
            "source_request_invalid",
            "source request id must be a canonical hyphenated UUID",
        )
    return str(parsed)


def _mapping_int(value: Mapping[str, Any], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool):
        raise ValueError(f"semantic {key} is malformed")
    return item


__all__ = [
    "SEMANTIC_REQUEST_TOPIC",
    "SEMANTIC_PROGRESS_TOPIC",
    "SEMANTIC_PROGRESS_GROUP",
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
