"""Run the durable no-authority Operator side of semantic-turn transport."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import sys
from collections import OrderedDict, deque
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Protocol, cast
from uuid import UUID, uuid5

from fdai_operator_service.adaptive_relationship import AdaptiveRelationshipResolution
from fdai_operator_service.contract_codecs import CORE_PROJECTION_CONSUMER_V17
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
from fdai_operator_service.families.conversation.document_export import ConversationDocumentExporter
from fdai_operator_service.families.conversation.semantic_document_presentation import (
    apply_document_answer as _apply_document_answer,
)
from fdai_operator_service.families.conversation.semantic_runtime_activity import (
    progress_query_activity as _progress_query_activity,
)
from fdai_operator_service.families.conversation.semantic_runtime_activity import (
    verified_query_activities as _verified_query_activities,
)
from fdai_operator_service.families.conversation.semantic_turn import SemanticTurnEnvelopeBuilder
from fdai_operator_service.families.conversation.semantic_turn_presentation import (
    semantic_done_event_data as _done_event_data,
)
from fdai_operator_service.families.conversation.t1_model_health import (
    T1ModelHealthReader,
    t1_model_health,
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
    OperatorPrincipalKind,
    OperatorRole,
    RuleSearchProjection,
    SemanticInvestigationContinuation,
    SemanticQueryProgress,
    SemanticTurnDisposition,
    SemanticTurnRequest,
    SemanticTurnResult,
)
from fdai_service_contracts.adaptive_answer import AdaptiveAgentName
from fdai_service_contracts.adaptive_relationship import (
    AdaptiveRelationshipProof,
    AdaptiveRelationshipUnknownReason,
)
from fdai_service_contracts.test_context import TestContextDraft
from fdai_service_contracts.venue import ExecutionVenue, resolve_execution_venue
from pydantic import TypeAdapter, ValidationError

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
_MAX_CONSUMER_RETRY_MULTIPLIER = 16.0
_RUNTIME_CALL_LOG_SCHEMA = "fdai.runtime-call-endpoint-log@1.0.0"
_LOGGER = logging.getLogger(__name__)
_RELATIONSHIP_REASON = TypeAdapter(AdaptiveRelationshipUnknownReason)


def _emit_runtime_call_record(record: str) -> None:
    sys.stdout.write(f"{record}\n")
    sys.stdout.flush()


class DialogueRelationshipResolver(Protocol):
    """Read current relationship facts for a fixed authenticated principal and target."""

    async def resolve(
        self,
        *,
        principal_id: str,
        roles: frozenset[OperatorRole],
        target_agent: AdaptiveAgentName,
    ) -> AdaptiveRelationshipResolution: ...


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
        self._terminals: OrderedDict[str, None] = OrderedDict()

    def terminal_committed(self, request_id: str) -> None:
        """Wake readers only after terminal validation and durable persistence succeed."""
        self._terminals[request_id] = None
        self._terminals.move_to_end(request_id)
        if len(self._terminals) > _MAX_TRACKED_PROGRESS_REQUESTS:
            self._terminals.popitem(last=False)
            _LOGGER.warning(
                "semantic_progress_capacity_evicted",
                extra={"kind": "terminal", "capacity": _MAX_TRACKED_PROGRESS_REQUESTS},
            )
        signal = self._signals.get(request_id)
        if signal is not None:
            signal.set()

    def consume(self, payload: Mapping[str, object]) -> bool:
        """Validate and retain one monotonic update, ignoring stale redelivery."""
        progress = SemanticQueryProgress.model_validate(payload)
        updates = self._updates.get(progress.request_id)
        if updates is None:
            if len(self._updates) >= _MAX_TRACKED_PROGRESS_REQUESTS:
                expired_request_id, _expired = self._updates.popitem(last=False)
                self._signals.pop(expired_request_id, None)
                _LOGGER.warning(
                    "semantic_progress_capacity_evicted",
                    extra={"kind": "progress", "capacity": _MAX_TRACKED_PROGRESS_REQUESTS},
                )
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
        self._terminals.pop(request_id, None)

    async def wait_for_update(
        self,
        request_id: str,
        progress_sequence: int,
        *,
        timeout: float,
    ) -> None:
        """Wake one active stream as soon as a newer progress record arrives."""
        if request_id in self._terminals or self.after(request_id, progress_sequence):
            return
        signal = self._signals.setdefault(request_id, asyncio.Event())
        signal.clear()
        if request_id in self._terminals or self.after(request_id, progress_sequence):
            return
        try:
            await asyncio.wait_for(signal.wait(), timeout=timeout)
        except TimeoutError:
            return


@dataclass(frozen=True, slots=True)
class _SemanticReplayCursor:
    projection_sequence: int
    phase: str
    answer_segment_index: int | None = None


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
                            reason_code="semantic_deadline_exceeded",
                        )
                    )
                except SemanticTurnTerminalClosedError:
                    _LOGGER.info(
                        "semantic_projection_late_ignored",
                        extra={"request_id": self._stored.request_id},
                    )
                store_after = _store_after_sequence(self._cursor)
                continue
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
        document_answer_replaced = await _apply_document_answer(
            done,
            projection=result.data,
            result_request_id=result.request_id,
            source_request_id=self._stored.source_request_id,
            principal_id=self._principal_id,
            locale=self._request.locale,
            exporter=self._document_exporter,
        )
        answer_segment_start = _answer_segment_start(self._cursor, result.sequence)
        if disposition == "answered" and answer_segment_start is not None:
            chunks = _verified_answer_chunks(done.get("answer"))
            semantic_receipt = done.get("semantic_receipt")
            semantic_result = done.get("semantic_result")
            evidence_refs = (
                semantic_result.get("evidence_refs")
                if isinstance(semantic_result, Mapping)
                else None
            )
            verification = done.get("verification")
            receipt_bound = (
                not document_answer_replaced
                and isinstance(verification, Mapping)
                and verification.get("status") == "verified"
                and isinstance(semantic_receipt, Mapping)
                and semantic_receipt.get("disposition") == "answered"
                and semantic_receipt.get("reason_code") == "semantic_answer_verified"
                and isinstance(evidence_refs, list)
                and all(isinstance(item, str) for item in evidence_refs)
            )
            confirmed_text = ""
            for segment_index, delta in enumerate(chunks):
                confirmed_text += delta
                if segment_index < answer_segment_start:
                    continue
                self._stream_sequence += 1
                self._events.append(
                    StreamEvent(
                        event="confirmed" if receipt_bound else "token",
                        event_id=f"{result.sequence}:answer:{segment_index}",
                        data=cast(
                            JsonObject,
                            {
                                "seq": self._stream_sequence,
                                "revision": 0,
                                **(
                                    {
                                        "segment_index": segment_index,
                                        "text": confirmed_text,
                                        "status": "consistent",
                                        "evidence_refs": evidence_refs,
                                        "semantic_receipt": semantic_receipt,
                                    }
                                    if receipt_bound
                                    else {"delta": delta}
                                ),
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
        decoded = CORE_PROJECTION_CONSUMER_V17.decode_mapping(payload)
        semantic_payload = decoded.get("semantic_result")
        extension_payload = decoded.get("payload")
        if not isinstance(extension_payload, dict):
            raise ValueError("semantic projection payload MUST be an object")
        if not isinstance(semantic_payload, dict):
            raise ValueError("semantic projection MUST contain semantic_result")
        result = SemanticTurnResult.model_validate(semantic_payload)
        context_draft = extension_payload.get("test_context_draft")
        if context_draft is not None:
            if result.disposition is not SemanticTurnDisposition.ACTION_DRAFT:
                raise ValueError("test context draft requires a draft-only semantic result")
            TestContextDraft.model_validate(context_draft)
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
class RuntimeCallEndpointObserver:
    """Emit one authority-free exact-endpoint witness after broker acceptance."""

    caller_resource_id: str
    target_resource_id: str
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    emit: Callable[[str], None] = _emit_runtime_call_record

    def __post_init__(self) -> None:
        _container_app_name(self.caller_resource_id, field_name="caller_resource_id")
        _container_app_name(self.target_resource_id, field_name="target_resource_id")
        if self.caller_resource_id.casefold() == self.target_resource_id.casefold():
            raise ValueError("runtime call caller and target Resource IDs MUST be distinct")

    def record(self, request: Mapping[str, object]) -> str:
        """Build a replay-stable witness without request content or authority."""

        request_id = request.get("request_id")
        if not isinstance(request_id, str) or not request_id.strip() or len(request_id) > 512:
            raise ValueError("runtime call request_id MUST be bounded non-empty text")
        observed_at = self.clock()
        if observed_at.tzinfo is None:
            raise ValueError("runtime call observation clock MUST be timezone-aware")
        payload = {
            "schema_version": _RUNTIME_CALL_LOG_SCHEMA,
            "message": "runtime_call_endpoint_observed",
            "endpoint_role": "caller",
            "observation_id": _runtime_call_observation_id(
                request_id=request_id,
                caller_resource_id=self.caller_resource_id,
                target_resource_id=self.target_resource_id,
            ),
            "caller_resource_id": self.caller_resource_id,
            "target_resource_id": self.target_resource_id,
            "observed_at": observed_at.astimezone(UTC).isoformat(),
            "execution_authority": False,
            "mutation_authority": False,
        }
        return json.dumps(payload, separators=(",", ":"), sort_keys=True)

    def emit_record(self, record: str) -> None:
        """Write one prevalidated record to the container log stream."""

        self.emit(record)


@dataclass(frozen=True, slots=True)
class SemanticTurnOutboxDrainer:
    """Lease and publish persisted requests with retry-safe compare-and-set closure."""

    store: SemanticTurnStore
    publisher: SemanticTurnEventPublisher
    worker_id: str
    request_topic: str = SEMANTIC_REQUEST_TOPIC
    lease_seconds: int = 120
    runtime_call_observer: RuntimeCallEndpointObserver | None = None
    worker_observer: Callable[[str, bool], None] | None = None

    async def run_once(self) -> bool:
        """Publish at most one leased request and release transport failures for retry."""
        claim = await self.store.claim_semantic_turn(
            worker_id=self.worker_id,
            lease_seconds=self.lease_seconds,
        )
        if claim is None:
            return False
        try:
            partition_key = claim.envelope.get("resource_ref")
            if not isinstance(partition_key, str) or not partition_key.startswith(
                "operator-conversation:"
            ):
                raise ValueError("semantic request resource_ref is not a conversation partition")
            await self.publisher.publish(
                self.request_topic,
                partition_key,
                claim.envelope,
            )
        except Exception as exc:  # noqa: BLE001 - durable row remains retryable
            _LOGGER.warning(
                "semantic_outbox_publish_failed",
                extra={"failure_type": type(exc).__name__},
            )
            if self.worker_observer is not None:
                self.worker_observer("outbox", False)
            await self.store.release_semantic_turn_claim(
                key=claim.key,
                claim_id=claim.claim_id,
            )
            return False
        if self.runtime_call_observer is not None:
            try:
                runtime_call_record = self.runtime_call_observer.record(claim.envelope)
                self.runtime_call_observer.emit_record(runtime_call_record)
            except Exception as exc:  # noqa: BLE001 - optional evidence cannot block delivery
                _LOGGER.warning(
                    "semantic_runtime_call_observation_failed",
                    extra={"failure_type": type(exc).__name__},
                )
        try:
            closed = await self.store.mark_semantic_turn_published(
                key=claim.key,
                claim_id=claim.claim_id,
            )
        except Exception as exc:  # noqa: BLE001 - release the lease for at-least-once retry
            _LOGGER.warning(
                "semantic_outbox_close_failed",
                extra={"failure_type": type(exc).__name__},
            )
            if self.worker_observer is not None:
                self.worker_observer("outbox", False)
            await self.store.release_semantic_turn_claim(
                key=claim.key,
                claim_id=claim.claim_id,
            )
            return False
        if not closed:
            return False
        if self.worker_observer is not None:
            self.worker_observer("outbox", True)
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
        relationship_resolver: DialogueRelationshipResolver | None = None,
        worker_id: str = "operator-semantic-turn",
        request_topic: str = SEMANTIC_REQUEST_TOPIC,
        result_topic: str = SEMANTIC_RESULT_TOPIC,
        result_group: str = SEMANTIC_RESULT_GROUP,
        progress_topic: str = SEMANTIC_PROGRESS_TOPIC,
        progress_group: str = SEMANTIC_PROGRESS_GROUP,
        retry_seconds: float = 1.0,
        runtime_call_observer: RuntimeCallEndpointObserver | None = None,
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
        self._relationship_resolver = relationship_resolver
        self._acceptance_started = False
        self._consumer = SemanticTurnProjectionConsumer(store)
        self._progress_relay = _SemanticProgressRelay()
        self._degraded_workers: set[str] = set()
        self._drainer = (
            SemanticTurnOutboxDrainer(
                store,
                publisher,
                worker_id,
                request_topic,
                runtime_call_observer=runtime_call_observer,
                worker_observer=self._observe_worker,
            )
            if publisher is not None
            else None
        )
        self._request_topic = request_topic
        self._result_topic = result_topic
        self._result_group = result_group
        self._progress_topic = progress_topic
        self._progress_group = progress_group
        self._retry_seconds = retry_seconds
        self._outbox_wakeup = asyncio.Event()
        self._tasks: tuple[asyncio.Task[None], ...] = ()

    def bind_relationship_resolver(self, resolver: DialogueRelationshipResolver) -> None:
        """Bind composition-owned readers once, before request acceptance or startup."""
        if self._relationship_resolver is not None or self._acceptance_started or self._tasks:
            raise RuntimeError("relationship resolver MUST be bound once before bridge use")
        self._relationship_resolver = resolver

    async def append(self, proposal: ConversationProposal) -> OutboxReceipt:
        """Accept one authorized stream proposal and persist a typed held fallback if unbound."""
        self._acceptance_started = True
        envelope = self._builder.build(proposal)
        semantic = SemanticTurnRequest.model_validate(envelope["semantic_turn"])
        relationship = await self._resolve_relationship(semantic)
        envelope = self._builder.build(
            proposal,
            relationship_proof=relationship.proof,
            relationship_unknown_reason=relationship.reason,
        )
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
                relationship_proof=relationship.proof,
                relationship_unknown_reason=relationship.reason,
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
        self._outbox_wakeup.set()
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
        available = configured and self.workers_ready() and not self._degraded_workers
        return cast(
            JsonObject,
            {
                "available": available,
                "configured": configured,
                "mode": "event-bridge" if available else ("starting" if configured else "held"),
                "request_topic": self._request_topic,
                "result_topic": self._result_topic,
                "progress_topic": self._progress_topic,
                "degraded_workers": sorted(self._degraded_workers),
            },
        )

    def workers_ready(self) -> bool:
        """Return whether both configured background workers remain active."""
        return len(self._tasks) == 2 and all(not task.done() for task in self._tasks)

    def _observe_worker(self, worker: str, succeeded: bool) -> None:
        """Retain content-free worker degradation until that worker succeeds."""

        if succeeded:
            self._degraded_workers.discard(worker)
        else:
            self._degraded_workers.add(worker)

    async def start(self) -> None:
        """Start one publisher drainer and one result consumer when transport is injected."""
        self._acceptance_started = True
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

    async def _resolve_relationship(
        self, request: SemanticTurnRequest
    ) -> AdaptiveRelationshipResolution:
        if request.principal.principal_kind is not OperatorPrincipalKind.HUMAN:
            return AdaptiveRelationshipResolution(
                request.target_agent,
                "unknown",
                "human_principal_required",
                None,
            )
        if self._relationship_resolver is None:
            return AdaptiveRelationshipResolution(
                request.target_agent,
                "unknown",
                "resolver_unavailable",
                None,
            )
        try:
            async with asyncio.timeout(5):
                resolution = await self._relationship_resolver.resolve(
                    principal_id=request.principal.subject_id,
                    roles=frozenset(request.principal.roles),
                    target_agent=request.target_agent,
                )
            proof = resolution.proof
            if resolution.target_agent != request.target_agent:
                raise ValueError("relationship resolution target mismatch")
            if resolution.status != "matched" or proof is None:
                return AdaptiveRelationshipResolution(
                    request.target_agent,
                    "unknown",
                    _RELATIONSHIP_REASON.validate_python(resolution.reason),
                    None,
                )
            if (
                not isinstance(proof, AdaptiveRelationshipProof)
                or proof.principal_id != request.principal.subject_id
                or proof.target_agent != request.target_agent
            ):
                raise ValueError("relationship proof binding mismatch")
            return resolution
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            reason = "resolver_timeout"
        except (TypeError, ValueError, ValidationError):
            reason = "resolver_invalid"
        except Exception:  # noqa: BLE001 - failed optional context cannot assert a relationship
            reason = "resolver_unavailable"
        _LOGGER.info(
            "semantic_relationship_unknown",
            extra={"target_agent": request.target_agent, "reason": reason},
        )
        return AdaptiveRelationshipResolution(
            request.target_agent,
            "unknown",
            reason,
            None,
        )

    async def _run_drainer(self) -> None:
        if self._drainer is None:
            return
        while True:
            self._outbox_wakeup.clear()
            try:
                published = await self._drainer.run_once()
            except Exception:  # noqa: BLE001 - transient store failures retry in-process
                _LOGGER.warning("semantic_outbox_drainer_retrying", exc_info=True)
                self._observe_worker("outbox", False)
                published = False
            if published:
                continue
            try:
                await asyncio.wait_for(
                    self._outbox_wakeup.wait(),
                    timeout=self._retry_seconds,
                )
            except TimeoutError:
                pass

    async def _run_consumer(self) -> None:
        async with asyncio.TaskGroup() as group:
            group.create_task(self._run_result_consumer())
            group.create_task(self._run_progress_consumer())

    async def _run_result_consumer(self) -> None:
        if self._result_source is None or self._publisher is None:
            return
        conflicts: OrderedDict[str, int] = OrderedDict()
        retry_delay = self._retry_seconds
        while True:
            try:
                async for payload in self._result_source.subscribe(
                    self._result_topic,
                    self._result_group,
                ):
                    retry_delay = self._retry_seconds
                    quarantine_key = _projection_quarantine_key(payload)
                    try:
                        committed = await self._consumer.consume(payload)
                    except (ContractValidationError, ValidationError, ValueError):
                        await self._quarantine(quarantine_key)
                    except SemanticTurnRequestAbsentError:
                        # A projection can arrive before its durable request commits, so
                        # retry that race a bounded number of times. Retrying forever
                        # instead stalls every later projection behind one poison record.
                        attempts = _next_projection_conflict_attempt(
                            conflicts,
                            quarantine_key,
                        )
                        if attempts < _MAX_PROJECTION_CONFLICT_ATTEMPTS:
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
                        self._progress_relay.terminal_committed(committed.request_id)
                        self._observe_worker("result", True)
            except SemanticTurnRequestAbsentError:
                _LOGGER.info(
                    "semantic_projection_conflict_retrying",
                    extra={"failure_type": "durable_request_absent"},
                )
            except Exception:  # noqa: BLE001 - preserve offset and resubscribe after backoff
                self._observe_worker("result", False)
                _LOGGER.warning("semantic_projection_consumer_retrying", exc_info=True)
            await asyncio.sleep(retry_delay)
            retry_delay = _next_consumer_retry_delay(retry_delay, self._retry_seconds)

    async def _run_progress_consumer(self) -> None:
        if self._result_source is None or self._publisher is None:
            return
        retry_delay = self._retry_seconds
        while True:
            try:
                async for payload in self._result_source.subscribe(
                    self._progress_topic,
                    self._progress_group,
                ):
                    retry_delay = self._retry_seconds
                    try:
                        if self._progress_relay.consume(payload):
                            _LOGGER.info("semantic_query_progress_received")
                            self._observe_worker("progress", True)
                    except (ValidationError, ValueError):
                        await self._quarantine_progress(payload)
            except Exception:  # noqa: BLE001 - preserve offset and resubscribe after backoff
                self._observe_worker("progress", False)
                _LOGGER.warning("semantic_progress_consumer_retrying", exc_info=True)
            await asyncio.sleep(retry_delay)
            retry_delay = _next_consumer_retry_delay(retry_delay, self._retry_seconds)

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


def _next_projection_conflict_attempt(
    conflicts: OrderedDict[str, int],
    quarantine_key: str,
) -> int:
    """Advance one bounded conflict counter while preserving unrelated retry histories."""

    attempts = conflicts.get(quarantine_key, 0) + 1
    if quarantine_key not in conflicts and len(conflicts) >= _MAX_TRACKED_PROJECTION_CONFLICTS:
        conflicts.popitem(last=False)
        _LOGGER.warning(
            "semantic_projection_conflict_capacity_evicted",
            extra={"capacity": _MAX_TRACKED_PROJECTION_CONFLICTS},
        )
    conflicts[quarantine_key] = attempts
    conflicts.move_to_end(quarantine_key)
    return attempts


def _next_consumer_retry_delay(current: float, base: float) -> float:
    return min(current * 2, base * _MAX_CONSUMER_RETRY_MULTIPLIER)


@dataclass(frozen=True, slots=True)
class SemanticTurnConversationAdapters:
    """Route only chat.stream through semantic transport and preserve other family adapters."""

    bridge: SemanticTurnBridge
    fallback_projections: ConversationProjectionReader
    fallback_outbox: ConversationProposalOutbox
    fallback_streams: ConversationStreamReader
    document_exporter: ConversationDocumentExporter | None = None
    t1_model_health_reader: T1ModelHealthReader | None = None

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
        routing = (
            await self.t1_model_health_reader.read()
            if self.t1_model_health_reader is not None
            else (await self.fallback_projections.read(query)).body
        )
        return ConversationResponse(
            body={
                "available": health["available"],
                "mode": health["mode"],
                **t1_model_health(routing),
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


def _held_projection(
    envelope: Mapping[str, object],
    *,
    recorded_at: datetime | None = None,
    reason_code: str = "semantic_transport_unavailable",
) -> dict[str, object]:
    request_id = _mapping_text(envelope, "request_id")
    semantic = envelope.get("semantic_turn")
    if not isinstance(semantic, Mapping):
        raise ValueError("semantic request payload is missing")
    result = SemanticTurnResult(
        disposition=SemanticTurnDisposition.HELD,
        reason_code=reason_code,
        unavailable_reason="semantic_planner_unavailable",
        session_id=_mapping_text(semantic, "session_id"),
        turn_id=_mapping_text(semantic, "turn_id"),
        turn_sequence=_mapping_int(semantic, "turn_sequence"),
        answer=(
            (
                "의미 조회 기한 안에 검증된 결과를 받지 못해 요청을 보류했습니다. "
                "(semantic_deadline_exceeded)"
                if reason_code == "semantic_deadline_exceeded"
                else "검증된 semantic transport를 사용할 수 없어 요청을 보류했습니다. "
                "(semantic_transport_unavailable)"
            )
            if _mapping_text(semantic, "locale").casefold().startswith("ko")
            else (
                "The request was held because no verified result arrived before the semantic "
                "deadline. (semantic_deadline_exceeded)"
                if reason_code == "semantic_deadline_exceeded"
                else "The request was held because verified semantic transport is unavailable. "
                "(semantic_transport_unavailable)"
            )
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
        "payload": {"reason_code": reason_code},
        "semantic_result": result_payload,
    }


def _pantheon_assurance_payload(
    projection: Mapping[str, object],
) -> Mapping[str, object] | None:
    payload = projection.get("payload")
    assurance = payload.get("pantheon_assurance") if isinstance(payload, Mapping) else None
    if not isinstance(assurance, Mapping):
        return None
    assessment_state = assurance.get("assessment_state")
    assessment_reasons = assurance.get("assessment_reasons")
    answer_generation = assurance.get("answer_generation")
    evaluator_models = assurance.get("pantheon_evaluator_models")
    if (
        assurance.get("schema_version") != "1.0.0"
        or not isinstance(assurance.get("answer"), str)
        or not assurance["answer"]
        or not _valid_answer_generation(answer_generation)
        or not _valid_evaluator_models(evaluator_models)
        or not isinstance(assurance.get("assessment_id"), str)
        or not isinstance(assurance.get("trace_receipt_id"), str)
        or not isinstance(assurance.get("pantheon_trace"), Mapping)
        or not isinstance(assurance.get("pantheon_observations"), Mapping)
        or not isinstance(assurance.get("pantheon_semantic_reviews"), list)
        or not isinstance(assurance.get("pantheon_diagnostic"), Mapping)
        or (
            assessment_state is not None
            and assessment_state not in {"completed", "deferred", "held"}
        )
        or (
            assessment_reasons is not None
            and (
                not isinstance(assessment_reasons, list)
                or any(not isinstance(reason, str) or not reason for reason in assessment_reasons)
            )
        )
        or assurance.get("execution_authority") is not False
    ):
        raise ValueError("Pantheon conversation assurance projection is malformed")
    return assurance


def _valid_answer_generation(value: object) -> bool:
    if value is None:
        return True
    if not isinstance(value, Mapping) or set(value) != {
        "mode",
        "model_identity",
        "model_family",
    }:
        return False
    mode = value.get("mode")
    identity = value.get("model_identity")
    family = value.get("model_family")
    return mode in {"agent_projection", "semantic_model", "t2_model"} and (
        (identity is None and family is None and mode == "agent_projection")
        or (
            isinstance(identity, str)
            and bool(identity.strip())
            and family is None
            and mode == "semantic_model"
        )
        or (
            isinstance(identity, str)
            and bool(identity.strip())
            and isinstance(family, str)
            and bool(family.strip())
            and mode == "t2_model"
        )
    )


def _valid_evaluator_models(value: object) -> bool:
    return (
        value is None
        or isinstance(value, list)
        and len(value) <= 3
        and all(
            isinstance(item, Mapping)
            and set(item) == {"model_identity", "model_family", "output_available"}
            and isinstance(item.get("model_identity"), str)
            and bool(str(item["model_identity"]).strip())
            and isinstance(item.get("model_family"), str)
            and bool(str(item["model_family"]).strip())
            and type(item.get("output_available")) is bool
            for item in value
        )
    )


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


def _verified_answer_chunks(answer: object) -> tuple[str, ...]:
    """Split a terminal verified answer without changing its content."""

    if not isinstance(answer, str) or not answer:
        return ()
    chunk_chars = max(
        _MAX_ANSWER_CHUNK_CHARS,
        (len(answer) + 63) // 64,
    )
    return tuple(
        answer[index : index + chunk_chars] for index in range(0, len(answer), chunk_chars)
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
    answer_segment_index: int | None = None
    if phase.startswith("answer:"):
        _, raw_segment_index = phase.split(":", 1)
        try:
            answer_segment_index = int(raw_segment_index)
        except ValueError as exc:
            raise ConversationBoundaryError(
                400,
                "invalid_replay_cursor",
                "Last-Event-ID is invalid",
            ) from exc
        phase = "answer"
    if (
        parsed < 0
        or phase not in _SEMANTIC_PHASES
        or (answer_segment_index is not None and answer_segment_index < 0)
    ):
        raise ConversationBoundaryError(400, "invalid_replay_cursor", "Last-Event-ID is invalid")
    if parsed == 0 and phase not in {"accepted", "planning"}:
        raise ConversationBoundaryError(400, "invalid_replay_cursor", "Last-Event-ID is invalid")
    return _SemanticReplayCursor(parsed, phase, answer_segment_index)


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


def _answer_segment_start(
    cursor: _SemanticReplayCursor | None,
    projection_sequence: int,
) -> int | None:
    if cursor is None or cursor.projection_sequence != projection_sequence:
        return 0
    if cursor.phase == "answer":
        return None if cursor.answer_segment_index is None else cursor.answer_segment_index + 1
    if _SEMANTIC_PHASES.index(cursor.phase) > _SEMANTIC_PHASES.index("answer"):
        return None
    return 0


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
            "planning": "답변 경로를 확인하는 중입니다.",
        }
    return {
        "accepted": "Semantic request accepted.",
        "planning": "Determining the answer path.",
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


def runtime_call_endpoint_observer_from_config(
    config: Mapping[str, str],
) -> RuntimeCallEndpointObserver | None:
    """Bind exact endpoint evidence only in the deployed Operator producer."""

    caller = config.get("FDAI_RUNTIME_CALL_CALLER_RESOURCE_ID", "").strip()
    target = config.get("FDAI_RUNTIME_CALL_TARGET_RESOURCE_ID", "").strip()
    if bool(caller) != bool(target):
        raise RuntimeError(
            "runtime call caller and target Resource IDs MUST be configured together"
        )
    if not caller:
        return None
    if resolve_execution_venue(config) is not ExecutionVenue.DEPLOYED:
        raise RuntimeError("runtime call Resource IDs are valid only in the deployed venue")
    return RuntimeCallEndpointObserver(
        caller_resource_id=caller,
        target_resource_id=target,
    )


def _runtime_call_observation_id(
    *,
    request_id: str,
    caller_resource_id: str,
    target_resource_id: str,
) -> str:
    body = json.dumps(
        {
            "caller_resource_id": caller_resource_id,
            "request_id": request_id,
            "schema_version": _RUNTIME_CALL_LOG_SCHEMA,
            "target_resource_id": target_resource_id,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(body).hexdigest()


def _container_app_name(value: str, *, field_name: str) -> str:
    segments = value.split("/")
    if (
        len(segments) != 9
        or segments[0] != ""
        or segments[1].casefold() != "subscriptions"
        or not segments[2]
        or segments[3].casefold() != "resourcegroups"
        or not segments[4]
        or segments[5].casefold() != "providers"
        or f"{segments[6]}/{segments[7]}".casefold() != "microsoft.app/containerapps"
        or not segments[8]
    ):
        raise ValueError(f"runtime call {field_name} MUST identify a Container App")
    return segments[8]


__all__ = [
    "SEMANTIC_REQUEST_TOPIC",
    "SEMANTIC_PROGRESS_TOPIC",
    "SEMANTIC_PROGRESS_GROUP",
    "SEMANTIC_RESULT_GROUP",
    "SEMANTIC_RESULT_TOPIC",
    "RuntimeCallEndpointObserver",
    "SemanticTurnBridge",
    "SemanticTurnConversationAdapters",
    "SemanticTurnEventPublisher",
    "SemanticTurnOutboxDrainer",
    "SemanticTurnProjectionConsumer",
    "SemanticTurnResultSource",
    "SemanticTurnStore",
    "T1ModelHealthReader",
    "runtime_call_endpoint_observer_from_config",
]
