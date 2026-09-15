"""Bounded, content-free assignment intake over independently packaged services."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fdai.core.human_assignment.request_intake import AssignmentRequestIntake
from fdai.shared.providers.event_bus import EventBus, subscription
from fdai_service_contracts.assignment_transport import (
    ASSIGNMENT_CONSUMER_GROUP,
    ASSIGNMENT_EVENT_TYPE,
    ASSIGNMENT_PROJECTION_TOPIC,
    ASSIGNMENT_REQUEST_TOPIC,
    AssignmentRequestNotice,
)


@dataclass(frozen=True, slots=True)
class AssignmentIntakeConsumer:
    """Publish an inert receipt disposition; agent review remains a separate boundary."""

    intake: AssignmentRequestIntake
    ingress: Callable[[dict[str, Any]], Awaitable[object]] | None = None
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    async def run(self, *, bus: EventBus, stop: asyncio.Event) -> None:
        async with subscription(bus, ASSIGNMENT_REQUEST_TOPIC, ASSIGNMENT_CONSUMER_GROUP) as stream:
            async for envelope in stream:
                if stop.is_set():
                    return
                try:
                    notice = AssignmentRequestNotice.model_validate(envelope.payload)
                    if envelope.key != notice.case_id:
                        raise ValueError("assignment request partition identity mismatch")
                except ValueError:
                    # Do not copy a malformed payload (potentially raw identity/prose) to a DLQ.
                    await bus.dead_letter(
                        ASSIGNMENT_REQUEST_TOPIC,
                        "invalid-assignment-notice",
                        {"reason": "invalid_assignment_notice", "execution_authority": False},
                        "invalid_assignment_notice",
                    )
                    continue
                try:
                    result = await self.intake.receive(notice, at=self.clock())
                except ValueError:
                    await bus.dead_letter(
                        ASSIGNMENT_REQUEST_TOPIC,
                        "conflicting-assignment-notice",
                        {"reason": "conflicting_assignment_notice", "execution_authority": False},
                        "conflicting_assignment_notice",
                    )
                    continue
                await bus.publish(
                    ASSIGNMENT_PROJECTION_TOPIC,
                    notice.proposal_id,
                    result.model_dump(mode="json"),
                )
                if result.status == "awaiting_agent_review" and self.ingress is not None:
                    await self.ingress(assignment_raw_event(notice))


def assignment_raw_event(notice: AssignmentRequestNotice) -> dict[str, Any]:
    """Preserve only the typed receipt notice through Huginn's bounded attributes."""
    attributes: Mapping[str, object] = {"assignment_notice": notice.model_dump(mode="json")}
    return {
        "event_type": ASSIGNMENT_EVENT_TYPE,
        "event_id": notice.proposal_id,
        "idempotency_key": f"assignment-request:{notice.proposal_id}",
        "correlation_id": notice.case_id,
        "source": "operator-assignment-receipt",
        "incident_correlation": "none",
        "attributes": dict(attributes),
    }


__all__ = ["AssignmentIntakeConsumer", "assignment_raw_event"]
