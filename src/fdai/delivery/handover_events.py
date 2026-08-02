"""Content-free session availability events for proactive handover goals."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol

from fdai.shared.providers.event_bus import EventBus, PublishReceipt


class HandoverAvailabilityPublisher(Protocol):
    async def publish(self, *, subject_ref: str, session_id: str) -> PublishReceipt: ...


@dataclass(frozen=True, slots=True)
class EventBusHandoverAvailabilityPublisher:
    event_bus: EventBus
    topic: str

    def __post_init__(self) -> None:
        if not self.topic.strip():
            raise ValueError("handover availability topic MUST be non-empty")

    async def publish(self, *, subject_ref: str, session_id: str) -> PublishReceipt:
        subject_hash = _digest(subject_ref)
        session_hash = _digest(session_id)
        key = f"handover-availability:{subject_hash}:{session_hash}"
        return await self.event_bus.publish(
            self.topic,
            subject_hash,
            {
                "event_type": "handover.session.available",
                "idempotency_key": key,
                "correlation_id": f"handover-session:{session_hash}",
                "subject_hash": subject_hash,
                "session_hash": session_hash,
                "content_included": False,
            },
        )


def _digest(value: str) -> str:
    if not value.strip() or len(value) > 256:
        raise ValueError("handover availability reference MUST be non-empty and bounded")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__ = ["EventBusHandoverAvailabilityPublisher", "HandoverAvailabilityPublisher"]
