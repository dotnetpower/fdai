"""EventBus lifecycle and durable result binding for semantic turns."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fdai.core.conversation.semantic_runtime import SemanticConversationRuntime
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.state_store import StateStore

from .semantic_turn_processor import (
    SemanticTurnProcessor,
    SemanticTurnRejectedError,
)

_STATE_PREFIX = "semantic-turn-result:"
_CLAIM_PREFIX = "semantic-turn-claim:"


@dataclass(frozen=True, slots=True)
class SemanticTurnConsumerBinding:
    """Configured EventBus lifecycle for one optional semantic runtime."""

    request_topic: str
    projection_topic: str
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
            group_id=self.group_id,
            processor=self.processor,
            stop=stop,
        )


class StateStoreSemanticTurnResultStore:
    """Persist canonical projections with StateStore atomic create semantics."""

    def __init__(self, state_store: StateStore) -> None:
        self._state_store = state_store

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

    async def claim(self, idempotency_key: str, request_digest: str) -> bool:
        key = _claim_key(idempotency_key)
        created = await self._state_store.write_state_if_absent(
            key,
            {
                "schema_version": "1.0.0",
                "idempotency_key": idempotency_key,
                "request_digest": request_digest,
            },
        )
        if created:
            return True
        existing = await self._state_store.read_state(key)
        if existing is None or existing.get("request_digest") != request_digest:
            raise SemanticTurnRejectedError("semantic_idempotency_conflict")
        return False

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
    if not request_topic and not projection_topic:
        return None
    if not request_topic or not projection_topic:
        raise RuntimeError(
            "semantic turn request and projection topics MUST be configured together"
        )
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
    group_id: str,
    processor: SemanticTurnProcessor,
    stop: asyncio.Event,
) -> None:
    """Consume at-least-once requests and publish one idempotent projection.

    Malformed input and failed projection publication are routed through the
    injected EventBus dead-letter boundary with stable, detail-free reasons.
    """

    async for envelope in bus.subscribe(request_topic, group_id):
        if stop.is_set():
            return
        try:
            encoded = await processor.process(envelope.payload, cancelled=stop)
            projection = _projection_mapping(encoded)
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
        try:
            await bus.publish(
                projection_topic,
                str(projection["idempotency_key"]),
                projection,
            )
        except Exception:  # noqa: BLE001 - publisher detail must not enter the DLQ reason
            await bus.dead_letter(
                envelope.topic,
                envelope.key,
                envelope.payload,
                "semantic_turn_publish_failed",
            )


def _projection_mapping(encoded: bytes) -> Mapping[str, Any]:
    loaded = json.loads(encoded)
    if not isinstance(loaded, dict):
        raise ValueError("semantic projection MUST be an object")
    return loaded


def _state_key(idempotency_key: str) -> str:
    digest = hashlib.sha256(idempotency_key.encode()).hexdigest()
    return f"{_STATE_PREFIX}{digest}"


def _claim_key(idempotency_key: str) -> str:
    digest = hashlib.sha256(idempotency_key.encode()).hexdigest()
    return f"{_CLAIM_PREFIX}{digest}"


__all__ = [
    "SemanticTurnConsumerBinding",
    "StateStoreSemanticTurnResultStore",
    "build_semantic_turn_processor",
    "consume_semantic_turns",
    "semantic_turn_binding_from_config",
]
