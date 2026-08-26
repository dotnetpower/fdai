"""EventBus lifecycle and durable result binding for semantic turns."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from fdai.core.conversation.semantic_runtime import (
    SemanticConversationRuntime,
    bind_semantic_query_progress_observer,
)
from fdai.core.ontology_platform.query_execution import QueryNodeProgress
from fdai.shared.providers.event_bus import EventBus, subscription
from fdai.shared.providers.state_store import StateStore
from fdai_service_contracts import SemanticQueryProgress

from .semantic_turn_processor import (
    SemanticTurnProcessor,
    SemanticTurnRejectedError,
)

_STATE_PREFIX = "semantic-turn-result:"
_CLAIM_PREFIX = "semantic-turn-claim:"
_DEFAULT_CLAIM_LEASE_SECONDS = 120.0
_MAX_PROGRESS_RECORDS = 64
_PROGRESS_DRAIN_SECONDS = 0.5
_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SemanticTurnConsumerBinding:
    """Configured EventBus lifecycle for one optional semantic runtime."""

    request_topic: str
    projection_topic: str
    progress_topic: str
    group_id: str
    processor: SemanticTurnProcessor
    available: bool
    unavailable_reason: str | None

    async def run(self, *, bus: EventBus, stop: asyncio.Event) -> None:
        """Consume semantic turns until the shared runtime stop event is set."""

        await consume_semantic_turns(
            bus=bus,
            request_topic=self.request_topic,
            projection_topic=self.projection_topic,
            progress_topic=self.progress_topic,
            group_id=self.group_id,
            processor=self.processor,
            stop=stop,
        )


class StateStoreSemanticTurnResultStore:
    """Persist canonical projections and recover abandoned processing claims."""

    def __init__(
        self,
        state_store: StateStore,
        *,
        claim_lease_seconds: float = _DEFAULT_CLAIM_LEASE_SECONDS,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if claim_lease_seconds <= 0:
            raise ValueError("semantic claim lease MUST be positive")
        self._state_store = state_store
        self._claim_lease_seconds = claim_lease_seconds
        self._now = now or (lambda: datetime.now(UTC))

    async def get(self, idempotency_key: str) -> bytes | None:
        record = await self._state_store.read_state(_state_key(idempotency_key))
        if record is None:
            return None
        encoded = record.get("projection_base64")
        if not isinstance(encoded, str):
            raise RuntimeError("semantic result state is malformed")
        try:
            return base64.b64decode(encoded, validate=True)
        except ValueError as exc:
            raise RuntimeError("semantic result state is malformed") from exc

    async def claim(self, idempotency_key: str, request_digest: str) -> str | None:
        key = _claim_key(idempotency_key)
        now = _claim_time(self._now())
        claim_id = str(uuid4())
        candidate = _claim_record(
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            claim_id=claim_id,
            revision=0,
            lease_expires_at=now + timedelta(seconds=self._claim_lease_seconds),
        )
        created = await self._state_store.write_state_if_absent(
            key,
            candidate,
        )
        if created:
            return claim_id
        existing = await self._state_store.read_state(key)
        if existing is None or existing.get("request_digest") != request_digest:
            raise SemanticTurnRejectedError("semantic_idempotency_conflict")
        revision, status, lease_expires_at = _claim_state(existing)
        if status == "active" and lease_expires_at > now:
            return None
        recovered = {**candidate, "revision": revision + 1}
        changed = await self._state_store.compare_and_set_state_with_audit(
            key,
            recovered,
            expected_revision=revision,
            audit_entry=_claim_audit("semantic_turn.claim_recovered"),
        )
        return claim_id if changed else None

    async def release(
        self,
        idempotency_key: str,
        request_digest: str,
        claim_id: str,
    ) -> bool:
        key = _claim_key(idempotency_key)
        existing = await self._state_store.read_state(key)
        if (
            existing is None
            or existing.get("request_digest") != request_digest
            or existing.get("claim_id") != claim_id
        ):
            return False
        revision, status, _lease_expires_at = _claim_state(existing)
        if status != "active":
            return False
        released = {
            **existing,
            "status": "released",
            "revision": revision + 1,
            "lease_expires_at": _claim_time(self._now()).isoformat(),
        }
        return await self._state_store.compare_and_set_state_with_audit(
            key,
            released,
            expected_revision=revision,
            audit_entry=_claim_audit("semantic_turn.claim_released"),
        )

    async def put_if_absent(self, idempotency_key: str, projection: bytes) -> bool:
        return await self._state_store.write_state_if_absent(
            _state_key(idempotency_key),
            {
                "schema_version": "1.0.0",
                "idempotency_key": idempotency_key,
                "projection_base64": base64.b64encode(projection).decode("ascii"),
            },
        )


def build_semantic_turn_processor(
    *,
    state_store: StateStore,
    runtime: SemanticConversationRuntime | None,
    purpose: str = "operations-review",
) -> SemanticTurnProcessor:
    """Bind the durable store and an optional composed semantic runtime.

    Passing ``runtime=None`` is the explicit unavailable production binding.
    It returns typed holds and never manufactures a planner or provider.
    """

    return SemanticTurnProcessor(
        runtime=runtime,
        results=StateStoreSemanticTurnResultStore(state_store),
        purpose=purpose,
    )


def semantic_turn_binding_from_config(
    *,
    state_store: StateStore,
    runtime: SemanticConversationRuntime | None,
    config: Mapping[str, str],
    unavailable_reason: str | None = None,
) -> SemanticTurnConsumerBinding | None:
    """Build the consumer only when both transport topics are configured.

    Core currently supplies no production semantic runtime composition. A
    configured transport therefore binds ``runtime=None`` explicitly and emits
    held projections until a real runtime is injected through this hook.
    """

    request_topic = config.get("FDAI_SEMANTIC_TURN_REQUEST_TOPIC", "").strip()
    projection_topic = config.get("FDAI_SEMANTIC_TURN_PROJECTION_TOPIC", "").strip()
    progress_topic = config.get(
        "FDAI_SEMANTIC_TURN_PROGRESS_TOPIC",
        "core.semantic-turn.progress",
    ).strip()
    if not request_topic and not projection_topic:
        return None
    if not request_topic or not projection_topic or not progress_topic:
        raise RuntimeError(
            "semantic turn request, projection, and progress topics MUST be configured together"
        )
    if progress_topic in {request_topic, projection_topic}:
        raise RuntimeError("semantic turn progress topic MUST be distinct")
    purpose = config.get("FDAI_SEMANTIC_TURN_PURPOSE", "operations-review").strip()
    if not purpose:
        raise RuntimeError("FDAI_SEMANTIC_TURN_PURPOSE MUST be non-empty")
    group_id = config.get(
        "FDAI_SEMANTIC_TURN_CONSUMER_GROUP_ID",
        "fdai-core-semantic-turn",
    ).strip()
    if not group_id:
        raise RuntimeError("FDAI_SEMANTIC_TURN_CONSUMER_GROUP_ID MUST be non-empty")
    return SemanticTurnConsumerBinding(
        request_topic=request_topic,
        projection_topic=projection_topic,
        progress_topic=progress_topic,
        group_id=group_id,
        processor=build_semantic_turn_processor(
            state_store=state_store,
            runtime=runtime,
            purpose=purpose,
        ),
        available=runtime is not None,
        unavailable_reason=(
            None if runtime is not None else unavailable_reason or "semantic_runtime_unavailable"
        ),
    )


async def consume_semantic_turns(
    *,
    bus: EventBus,
    request_topic: str,
    projection_topic: str,
    progress_topic: str = "core.semantic-turn.progress",
    group_id: str,
    processor: SemanticTurnProcessor,
    stop: asyncio.Event,
    publish_attempts: int = 3,
    publish_retry_delay_seconds: float = 0.1,
) -> None:
    """Consume at-least-once requests and publish one idempotent projection.

    Malformed input and failed projection publication are routed through the
    injected EventBus dead-letter boundary with stable, detail-free reasons.
    """

    async with subscription(bus, request_topic, group_id) as stream:
        async for envelope in stream:
            if stop.is_set():
                return
            progress_queue: asyncio.Queue[SemanticQueryProgress] = asyncio.Queue(
                maxsize=_MAX_PROGRESS_RECORDS
            )
            progress_publisher = asyncio.create_task(
                _drain_progress(
                    bus=bus,
                    topic=progress_topic,
                    queue=progress_queue,
                )
            )
            try:
                progress_sequence = 0

                async def publish_progress(
                    progress: QueryNodeProgress,
                    request_payload: Mapping[str, Any] = envelope.payload,
                    queue: asyncio.Queue[SemanticQueryProgress] = progress_queue,
                ) -> None:
                    nonlocal progress_sequence
                    progress_sequence += 1
                    payload = _progress_mapping(
                        request_payload,
                        progress,
                        progress_sequence=progress_sequence,
                    )
                    try:
                        queue.put_nowait(payload)
                    except asyncio.QueueFull:
                        return

                try:
                    with bind_semantic_query_progress_observer(publish_progress):
                        encoded = await processor.process(
                            envelope.payload,
                            cancelled=stop,
                        )
                    projection = _projection_mapping(encoded)
                finally:
                    try:
                        await asyncio.wait_for(
                            progress_queue.join(),
                            timeout=_PROGRESS_DRAIN_SECONDS,
                        )
                    except TimeoutError:
                        pass
                    progress_publisher.cancel()
                    await asyncio.gather(progress_publisher, return_exceptions=True)
            except SemanticTurnRejectedError:
                await bus.dead_letter(
                    envelope.topic,
                    envelope.key,
                    envelope.payload,
                    "semantic_turn_rejected",
                )
                continue
            except Exception:  # noqa: BLE001 - process bugs are isolated at the broker boundary
                await bus.dead_letter(
                    envelope.topic,
                    envelope.key,
                    envelope.payload,
                    "semantic_turn_process_failed",
                )
                continue
            if not await _publish_projection(
                bus=bus,
                topic=projection_topic,
                key=str(projection["idempotency_key"]),
                projection=projection,
                stop=stop,
                attempts=publish_attempts,
                retry_delay_seconds=publish_retry_delay_seconds,
            ):
                await bus.dead_letter(
                    envelope.topic,
                    envelope.key,
                    envelope.payload,
                    "semantic_turn_publish_failed",
                )


async def _drain_progress(
    *,
    bus: EventBus,
    topic: str,
    queue: asyncio.Queue[SemanticQueryProgress],
) -> None:
    while True:
        progress = await queue.get()
        try:
            await bus.publish(
                topic,
                progress.request_id,
                progress.model_dump(mode="json"),
            )
        except Exception:  # noqa: BLE001 - progress cannot control terminal truth
            _LOGGER.warning("semantic_query_progress_publish_failed")
        finally:
            queue.task_done()


async def _publish_projection(
    *,
    bus: EventBus,
    topic: str,
    key: str,
    projection: Mapping[str, Any],
    stop: asyncio.Event,
    attempts: int,
    retry_delay_seconds: float,
) -> bool:
    if attempts < 1 or retry_delay_seconds < 0:
        raise ValueError("semantic projection retry bounds are invalid")
    for attempt in range(attempts):
        try:
            await bus.publish(topic, key, projection)
            return True
        except Exception:  # noqa: BLE001 - provider detail must not escape the boundary
            if attempt + 1 == attempts or stop.is_set():
                return False
            await asyncio.sleep(retry_delay_seconds * (2**attempt))
    return False


def _projection_mapping(encoded: bytes) -> Mapping[str, Any]:
    loaded = json.loads(encoded)
    if not isinstance(loaded, dict):
        raise ValueError("semantic projection MUST be an object")
    return loaded


def _progress_mapping(
    request_envelope: Mapping[str, Any],
    progress: QueryNodeProgress,
    *,
    progress_sequence: int,
) -> SemanticQueryProgress:
    semantic = request_envelope.get("semantic_turn")
    if not isinstance(semantic, Mapping):
        raise ValueError("semantic request payload is missing")
    request_id = request_envelope.get("request_id")
    if not isinstance(request_id, str):
        raise ValueError("semantic request identity is missing")
    receipt = progress.receipt
    return SemanticQueryProgress(
        request_id=request_id,
        session_id=str(semantic["session_id"]),
        turn_id=str(semantic["turn_id"]),
        turn_sequence=int(semantic["turn_sequence"]),
        progress_sequence=progress_sequence,
        node_id=progress.node.node_id,
        node_kind=progress.node.kind,
        capability=f"query.{progress.node.kind.value}",
        arguments=dict(progress.node.arguments),
        status=progress.status,
        step_index=progress.step_index,
        step_total=progress.step_total,
        depends_on=progress.node.depends_on,
        started_at=progress.started_at,
        completed_at=receipt.completed_at if receipt is not None else None,
        duration_ms=receipt.duration_ms if receipt is not None else None,
        reason=receipt.reason if receipt is not None else None,
        evidence_refs=receipt.evidence_refs if receipt is not None else (),
    )


def _state_key(idempotency_key: str) -> str:
    digest = hashlib.sha256(idempotency_key.encode()).hexdigest()
    return f"{_STATE_PREFIX}{digest}"


def _claim_key(idempotency_key: str) -> str:
    digest = hashlib.sha256(idempotency_key.encode()).hexdigest()
    return f"{_CLAIM_PREFIX}{digest}"


def _claim_record(
    *,
    idempotency_key: str,
    request_digest: str,
    claim_id: str,
    revision: int,
    lease_expires_at: datetime,
) -> dict[str, object]:
    return {
        "schema_version": "1.1.0",
        "idempotency_key": idempotency_key,
        "request_digest": request_digest,
        "claim_id": claim_id,
        "status": "active",
        "revision": revision,
        "lease_expires_at": lease_expires_at.isoformat(),
    }


def _claim_state(record: Mapping[str, Any]) -> tuple[int, str, datetime]:
    revision = record.get("revision")
    status = record.get("status")
    lease_raw = record.get("lease_expires_at")
    if (
        not isinstance(revision, int)
        or revision < 0
        or status not in {"active", "released"}
        or not isinstance(lease_raw, str)
    ):
        raise RuntimeError("semantic claim state is malformed")
    try:
        lease_expires_at = _claim_time(datetime.fromisoformat(lease_raw))
    except ValueError as exc:
        raise RuntimeError("semantic claim state is malformed") from exc
    return revision, status, lease_expires_at


def _claim_time(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise RuntimeError("semantic claim clock MUST be timezone-aware")
    return value.astimezone(UTC)


def _claim_audit(action_kind: str) -> dict[str, str]:
    return {
        "event_id": str(uuid4()),
        "actor": "semantic-turn-consumer",
        "action_kind": action_kind,
        "mode": "shadow",
    }


__all__ = [
    "SemanticTurnConsumerBinding",
    "StateStoreSemanticTurnResultStore",
    "build_semantic_turn_processor",
    "consume_semantic_turns",
    "semantic_turn_binding_from_config",
]
