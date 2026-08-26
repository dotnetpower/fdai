"""Consume Core read-investigation completions into the Operator-owned inbox."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Protocol

from fdai_service_contracts.read_investigation import (
    READ_INVESTIGATION_COMPLETION_CONSUMER_GROUP,
    READ_INVESTIGATION_COMPLETION_TOPIC,
    ReadInvestigationCompletion,
)

from fdai_operator_service.postgres_read_investigation_completion import (
    ReadInvestigationCompletionConflictError,
    StoredReadInvestigationCompletion,
)

_LOGGER = logging.getLogger(__name__)
_MAX_UNMATCHED_ATTEMPTS = 5
_MAX_TRACKED_CONFLICTS = 256
_COMPLETION_ID_PATTERN = re.compile(r"^read-completion-[a-f0-9]{32}$")


class ReadInvestigationCompletionStore(Protocol):
    """Persist one completion without exposing execution capabilities."""

    async def project_read_investigation_completion(
        self,
        completion: ReadInvestigationCompletion,
    ) -> StoredReadInvestigationCompletion: ...


class ReadInvestigationCompletionSource(Protocol):
    """Open the configured completion stream with commit-after-processing semantics."""

    def subscribe(
        self,
        topic: str,
        group_id: str,
    ) -> AsyncIterator[Mapping[str, object]]: ...


class ReadInvestigationCompletionPublisher(Protocol):
    """Publish a bounded poison-record reference to the sibling DLQ."""

    async def publish(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, object],
    ) -> object: ...


@dataclass(frozen=True, slots=True)
class ReadInvestigationCompletionConsumer:
    """Validate one authority-free completion and persist it exactly once."""

    store: ReadInvestigationCompletionStore

    async def consume(
        self,
        payload: Mapping[str, object],
    ) -> StoredReadInvestigationCompletion:
        """Reject malformed wire data before touching durable state."""

        completion = ReadInvestigationCompletion.model_validate(payload)
        return await self.store.project_read_investigation_completion(completion)


class ReadInvestigationCompletionBridge:
    """Own one supervised completion consumer for the Operator lifecycle."""

    def __init__(
        self,
        *,
        store: ReadInvestigationCompletionStore,
        source: ReadInvestigationCompletionSource,
        publisher: ReadInvestigationCompletionPublisher,
        topic: str = READ_INVESTIGATION_COMPLETION_TOPIC,
        group_id: str = READ_INVESTIGATION_COMPLETION_CONSUMER_GROUP,
        retry_seconds: float = 1.0,
    ) -> None:
        if not topic.strip() or not group_id.strip():
            raise ValueError("completion topic and consumer group MUST be non-empty")
        if retry_seconds <= 0:
            raise ValueError("completion retry_seconds MUST be positive")
        self._source = source
        self._publisher = publisher
        self._consumer = ReadInvestigationCompletionConsumer(store)
        self._topic = topic
        self._group_id = group_id
        self._retry_seconds = retry_seconds
        self._task: asyncio.Task[None] | None = None

    def workers_ready(self) -> bool:
        """Report whether the configured completion consumer remains active."""

        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        """Start the single completion consumer once."""

        if self._task is None:
            self._task = asyncio.create_task(
                self._run(),
                name="operator-read-investigation-completions",
            )

    async def aclose(self) -> None:
        """Cancel and join the completion consumer."""

        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _run(self) -> None:
        conflicts: dict[str, int] = {}
        while True:
            try:
                async for payload in self._source.subscribe(self._topic, self._group_id):
                    quarantine_key = _quarantine_key(payload)
                    if conflicts.get(quarantine_key, 0) >= _MAX_UNMATCHED_ATTEMPTS:
                        await self._quarantine(quarantine_key, "unmatched_or_conflicting")
                        conflicts.pop(quarantine_key, None)
                        continue
                    try:
                        await self._consumer.consume(payload)
                    except ValueError:
                        await self._quarantine(quarantine_key, "invalid_completion")
                    except ReadInvestigationCompletionConflictError:
                        attempts = conflicts.get(quarantine_key, 0) + 1
                        if attempts < _MAX_UNMATCHED_ATTEMPTS:
                            if (
                                quarantine_key not in conflicts
                                and len(conflicts) >= _MAX_TRACKED_CONFLICTS
                            ):
                                await self._quarantine(
                                    quarantine_key,
                                    "conflict_tracking_capacity",
                                )
                                continue
                            conflicts[quarantine_key] = attempts
                            raise
                        conflicts[quarantine_key] = attempts
                        await self._quarantine(quarantine_key, "unmatched_or_conflicting")
                        conflicts.pop(quarantine_key, None)
                    else:
                        conflicts.pop(quarantine_key, None)
            except Exception:  # noqa: BLE001 - keep the source offset uncommitted for retry
                _LOGGER.warning("read_investigation_completion_consumer_retrying", exc_info=True)
            await asyncio.sleep(self._retry_seconds)

    async def _quarantine(self, key: str, reason: str) -> None:
        await self._publisher.publish(
            f"{self._topic}.dlq",
            key,
            {
                "original_topic": self._topic,
                "completion_ref": key,
                "reason": reason,
            },
        )


def _quarantine_key(payload: Mapping[str, object]) -> str:
    completion_id = payload.get("completion_id")
    if isinstance(completion_id, str) and _COMPLETION_ID_PATTERN.fullmatch(completion_id):
        return completion_id
    encoded = json.dumps(
        dict(payload),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"invalid-completion-{hashlib.sha256(encoded).hexdigest()[:32]}"


__all__ = [
    "ReadInvestigationCompletionBridge",
    "ReadInvestigationCompletionConsumer",
    "ReadInvestigationCompletionPublisher",
    "ReadInvestigationCompletionSource",
    "ReadInvestigationCompletionStore",
]
