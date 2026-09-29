"""Off-path Operator binding for Bragi-owned post-turn review publication."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from fdai_operator_service.postgres_semantic_turn_store import (
    StoredSemanticResult,
)
from fdai_service_contracts import SemanticTurnDisposition, SemanticTurnResult
from fdai_service_contracts.post_turn_review import (
    POST_TURN_REVIEW_REQUEST_TOPIC,
    MemoryScopeKind,
    PostTurnReviewInputWire,
    PostTurnToolReceipt,
    post_turn_review_request_payload,
)

_LOGGER = logging.getLogger(__name__)
_MAX_QUEUE_SIZE = 256


class PostTurnReviewSource(Protocol):
    """Read bounded state needed by the asynchronous post-turn publisher."""

    async def read_post_turn_review_consent(self, *, principal_id: str) -> bool: ...


class PostTurnReviewPublisher(Protocol):
    """Publish one Operator-owned post-turn request through the configured transport."""

    async def publish(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, object],
    ) -> object: ...


class PostTurnPreferenceStore(Protocol):
    async def read_user_context_records(
        self,
        *,
        principal_id: str,
        limit: int,
    ) -> dict[str, list[dict[str, object]]]: ...


@dataclass(frozen=True, slots=True)
class PostTurnReviewPreferenceSource:
    """Read post-turn review consent through the existing user-context store seam."""

    store: PostTurnPreferenceStore

    async def read_post_turn_review_consent(self, *, principal_id: str) -> bool:
        records = await self.store.read_user_context_records(principal_id=principal_id, limit=1)
        preferences = records.get("preference", [])
        return bool(preferences and preferences[0].get("share_with_learner") is True)


@dataclass(frozen=True, slots=True)
class PostTurnReviewQueueSnapshot:
    enqueued: int = 0
    published: int = 0
    skipped: int = 0
    dropped: int = 0
    failed: int = 0


class NonBlockingPostTurnReviewQueue:
    """Bounded worker queue that never waits on the semantic response path."""

    def __init__(
        self,
        *,
        source: PostTurnReviewSource,
        publisher: PostTurnReviewPublisher,
        topic: str = POST_TURN_REVIEW_REQUEST_TOPIC,
        max_size: int = _MAX_QUEUE_SIZE,
    ) -> None:
        if max_size < 1:
            raise ValueError("post-turn review queue size MUST be positive")
        self._source = source
        self._publisher = publisher
        self._topic = topic
        self._queue: asyncio.Queue[StoredSemanticResult] = asyncio.Queue(maxsize=max_size)
        self._task: asyncio.Task[None] | None = None
        self._snapshot = PostTurnReviewQueueSnapshot()

    @property
    def snapshot(self) -> PostTurnReviewQueueSnapshot:
        return self._snapshot

    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def enqueue_terminal(self, result: StoredSemanticResult) -> None:
        """Offer one terminal result without awaiting reviewer transport."""

        if result.duplicate:
            self._bump("skipped")
            return
        try:
            self._queue.put_nowait(result)
        except asyncio.QueueFull:
            self._bump("dropped")
            _LOGGER.warning("post_turn_review_queue_full", extra={"request_id": result.request_id})
            return
        self._bump("enqueued")

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="operator-post-turn-review")

    async def aclose(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def drain_once(self) -> bool:
        """Process one queued result for focused tests and graceful local drains."""

        try:
            result = self._queue.get_nowait()
        except asyncio.QueueEmpty:
            return False
        try:
            await self._publish(result)
        finally:
            self._queue.task_done()
        return True

    async def _run(self) -> None:
        while True:
            result = await self._queue.get()
            try:
                await self._publish(result)
            finally:
                self._queue.task_done()

    async def _publish(self, result: StoredSemanticResult) -> None:
        try:
            if not await self._source.read_post_turn_review_consent(
                principal_id=result.principal_id
            ):
                self._bump("skipped")
                return
            review_input = post_turn_review_input_from_projection(result)
            if review_input is None:
                self._bump("skipped")
                return
            await self._publisher.publish(
                self._topic,
                f"operator-post-turn-review:{review_input.review_id}",
                post_turn_review_request_payload(review_input),
            )
            self._bump("published")
        except Exception as exc:  # noqa: BLE001 - async review MUST NOT affect the turn
            self._bump("failed")
            _LOGGER.warning(
                "post_turn_review_publish_failed",
                extra={"request_id": result.request_id, "failure_type": type(exc).__name__},
            )

    def _bump(self, field: str) -> None:
        self._snapshot = PostTurnReviewQueueSnapshot(
            enqueued=self._snapshot.enqueued + (1 if field == "enqueued" else 0),
            published=self._snapshot.published + (1 if field == "published" else 0),
            skipped=self._snapshot.skipped + (1 if field == "skipped" else 0),
            dropped=self._snapshot.dropped + (1 if field == "dropped" else 0),
            failed=self._snapshot.failed + (1 if field == "failed" else 0),
        )


def post_turn_review_input_from_projection(
    result: StoredSemanticResult,
) -> PostTurnReviewInputWire | None:
    """Build one bounded review input from a consented terminal semantic projection."""

    semantic_payload = result.data.get("semantic_result")
    if not isinstance(semantic_payload, Mapping):
        return None
    semantic_result = SemanticTurnResult.model_validate(semantic_payload)
    if semantic_result.disposition is not SemanticTurnDisposition.ANSWERED:
        return None
    completed_at = _completed_at(result.data)
    extension = result.data.get("payload")
    post_turn = extension.get("post_turn_review") if isinstance(extension, Mapping) else None
    hints = post_turn if isinstance(post_turn, Mapping) else {}
    return PostTurnReviewInputWire(
        review_id=f"review-{_digest(result.projection_id)[:32]}",
        principal_scope=f"principal-{_digest(result.principal_id)[:32]}",
        operator_turn_id=f"operator-{_digest(result.request_id)[:32]}",
        assistant_turn_id=f"assistant-{semantic_result.turn_id}",
        completed_at=completed_at,
        operator_body=_optional_string(hints, "operator_body"),
        assistant_body=_optional_string(hints, "assistant_body") or semantic_result.answer,
        tool_receipts=_tool_receipts(hints),
        validation_outcomes=_string_tuple(hints, "validation_outcomes"),
        explicit_corrections=_string_tuple(hints, "explicit_corrections"),
        evidence_refs=tuple(semantic_result.evidence_refs),
        memory_scope_kind=_memory_scope_kind(hints),
        memory_scope_ref=_optional_string(hints, "memory_scope_ref"),
        failure_recovered=hints.get("failure_recovered") is True,
        procedure_fingerprint=_optional_string(hints, "procedure_fingerprint"),
        repeated_procedure_count=_non_negative_int(hints, "repeated_procedure_count"),
    )


def _completed_at(projection: Mapping[str, object]) -> datetime:
    recorded_at = projection.get("recorded_at")
    if not isinstance(recorded_at, str):
        raise ValueError("semantic projection recorded_at MUST be a string")
    return datetime.fromisoformat(recorded_at)


def _tool_receipts(hints: Mapping[str, object]) -> tuple[PostTurnToolReceipt, ...]:
    raw = hints.get("tool_receipts", ())
    if not isinstance(raw, (list, tuple)):
        return ()
    receipts: list[PostTurnToolReceipt] = []
    for item in raw:
        if isinstance(item, Mapping):
            receipts.append(
                PostTurnToolReceipt(
                    tool_name=_required_string(item, "tool_name"),
                    status=_required_string(item, "status"),
                    evidence_ref=_required_string(item, "evidence_ref"),
                )
            )
    return tuple(receipts)


def _string_tuple(hints: Mapping[str, object], key: str) -> tuple[str, ...]:
    raw = hints.get(key, ())
    if not isinstance(raw, (list, tuple)) or not all(isinstance(item, str) for item in raw):
        return ()
    return tuple(raw)


def _required_string(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str):
        raise ValueError(f"post-turn {key} MUST be a string")
    return item


def _optional_string(value: Mapping[str, object], key: str) -> str | None:
    item = value.get(key)
    return item if isinstance(item, str) else None


def _memory_scope_kind(value: Mapping[str, object]) -> MemoryScopeKind | None:
    item = value.get("memory_scope_kind")
    if item == "resource-group" or item == "resource":
        return item
    return None


def _non_negative_int(value: Mapping[str, object], key: str) -> int:
    item = value.get(key, 0)
    return item if isinstance(item, int) and not isinstance(item, bool) and item >= 0 else 0


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


__all__ = [
    "NonBlockingPostTurnReviewQueue",
    "PostTurnPreferenceStore",
    "PostTurnReviewPreferenceSource",
    "PostTurnReviewPublisher",
    "PostTurnReviewQueueSnapshot",
    "PostTurnReviewSource",
    "post_turn_review_input_from_projection",
]
