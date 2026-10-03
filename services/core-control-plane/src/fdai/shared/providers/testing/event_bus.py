"""In-memory :class:`EventBus` with Kafka-style consumer-group offsets.

Semantics that matter for the safety-core tests:

- **Per-partition ordering** - one implicit partition (partition=0) so
  ordering-by-key equals ordering-by-publish. Real brokers preserve order
  only per partition; the fake keeps that guarantee trivially.
- **Consumer-group offsets** - each ``group_id`` remembers where its last
  ``subscribe(...)`` yield ended. A second call resumes from that offset.
  New groups start at offset 0 (mirrors ``auto.offset.reset=earliest``).
- **At-least-once delivery** - the fake retains a bounded replay window
  (100,000 records per topic by default); a consumer MUST enforce
  idempotency on the event's ``idempotency_key`` just like on a real broker.
- **DLQ convention** - ``dead_letter`` publishes into ``<topic>.dlq``,
  matching the wire-level rule in ``csp-neutrality.md § Event Bus``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from copy import deepcopy
from threading import Lock
from typing import Any

from fdai.shared.providers.event_bus import (
    EventBus,
    EventEnvelope,
    PublishReceipt,
)


class InMemoryEventBus(EventBus):
    """Dict-of-lists event bus with consumer-group semantics."""

    def __init__(self, *, max_records_per_topic: int = 100_000) -> None:
        if max_records_per_topic < 1:
            raise ValueError("max_records_per_topic MUST be >= 1")
        self._records: dict[str, list[tuple[str, Mapping[str, Any]]]] = {}
        self._base_offsets: dict[str, int] = {}
        self._offsets: dict[tuple[str, str], int] = {}  # (topic, group_id) → next offset
        self._max_records_per_topic = max_records_per_topic
        self.compacted_records = 0
        self._lock = Lock()

    # ---- EventBus Protocol ---------------------------------------------------

    async def publish(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, Any],
    ) -> PublishReceipt:
        with self._lock:
            queue = self._records.setdefault(topic, [])
            offset = self._base_offsets.get(topic, 0) + len(queue)
            queue.append((key, _freeze_mapping(deepcopy(dict(payload)))))
            self._compact_locked(topic)
            return PublishReceipt(topic=topic, partition=0, offset=offset)

    def subscribe(self, topic: str, group_id: str) -> AsyncIterator[EventEnvelope]:
        return self._subscribe(topic, group_id)

    async def _subscribe(self, topic: str, group_id: str) -> AsyncIterator[EventEnvelope]:
        with self._lock:
            base = self._base_offsets.get(topic, 0)
            start = max(self._offsets.get((topic, group_id), base), base)
            end = base + len(self._records.get(topic, ()))

        for offset in range(start, end):
            with self._lock:
                base = self._base_offsets.get(topic, 0)
                if offset < base:
                    continue
                records = self._records.get(topic, ())
                index = offset - base
                if index >= len(records):
                    break
                key, payload = records[index]
            yield EventEnvelope(
                topic=topic,
                key=key,
                payload=dict(payload),
                offset=offset,
            )
            with self._lock:
                # Advance the group's committed offset after each successful
                # yield. Consumer failure between yields → the next
                # subscribe() call resumes from the *last committed* offset.
                self._offsets[(topic, group_id)] = offset + 1

    async def dead_letter(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, Any],
        reason: str,
    ) -> None:
        # Kafka has no native DLQ - enforce the <topic>.dlq convention.
        dlq_topic = f"{topic}.dlq"
        metadata: dict[str, Any] = {}
        original_payload = dict(payload)
        raw_metadata = original_payload.pop("__fdai_dlq_metadata__", None)
        if isinstance(raw_metadata, Mapping):
            metadata = dict(raw_metadata)
        dlq_payload: dict[str, Any] = {
            "original_topic": topic,
            **metadata,
            "reason": reason,
            "payload": _freeze_mapping(deepcopy(original_payload)),
        }
        with self._lock:
            queue = self._records.setdefault(dlq_topic, [])
            queue.append((key, _freeze_mapping(dlq_payload)))
            self._compact_locked(dlq_topic)

    def _compact_locked(self, topic: str) -> None:
        records = self._records.get(topic)
        if not records:
            return
        excess = len(records) - self._max_records_per_topic
        if excess <= 0:
            return
        del records[:excess]
        self._base_offsets[topic] = self._base_offsets.get(topic, 0) + excess
        self.compacted_records += excess


class _FrozenDict(dict[str, Any]):
    def __setitem__(self, _key: str, _value: Any) -> None:
        raise TypeError("frozen event payload is immutable")

    def __delitem__(self, _key: str) -> None:
        raise TypeError("frozen event payload is immutable")

    def clear(self) -> None:
        raise TypeError("frozen event payload is immutable")

    def pop(self, _key: str, _default: Any = None) -> Any:
        raise TypeError("frozen event payload is immutable")

    def popitem(self) -> tuple[str, Any]:
        raise TypeError("frozen event payload is immutable")

    def setdefault(self, _key: str, _default: Any = None) -> Any:
        raise TypeError("frozen event payload is immutable")

    def update(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise TypeError("frozen event payload is immutable")

    def __deepcopy__(self, memo: dict[int, Any]) -> _FrozenDict:
        del memo
        return self


class _FrozenList(list[Any]):
    def __readonly(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("frozen event payload is immutable")

    __setitem__ = __readonly
    __delitem__ = __readonly
    append = __readonly
    clear = __readonly
    extend = __readonly
    insert = __readonly
    pop = __readonly
    remove = __readonly
    reverse = __readonly
    sort = __readonly

    def __deepcopy__(self, memo: dict[int, Any]) -> _FrozenList:
        del memo
        return self


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    frozen = dict.__new__(_FrozenDict)
    dict.update(frozen, {str(key): _freeze(value_item) for key, value_item in value.items()})
    return frozen


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _freeze_mapping(value)
    if isinstance(value, list | tuple):
        frozen = list.__new__(_FrozenList)
        list.extend(frozen, (_freeze(item) for item in value))
        return frozen
    return value


__all__ = ["InMemoryEventBus"]
