"""Typed ingress publisher for post-merge human access apply requests."""

from __future__ import annotations

from dataclasses import dataclass

from fdai.delivery.identity import APPLY_HUMAN_ACCESS_ACTION
from fdai.shared.providers.event_bus import EventBus, PublishReceipt


@dataclass(frozen=True, slots=True)
class EventBusAssignmentApplyPublisher:
    event_bus: EventBus
    topic: str

    def __post_init__(self) -> None:
        if not self.topic.strip():
            raise ValueError("assignment apply event topic MUST be non-empty")

    async def publish(
        self,
        *,
        case_id: str,
        expected_revision: int,
        requester_ref: str,
    ) -> PublishReceipt:
        correlation_id = f"human-assignment:{case_id}"
        idempotency_key = f"human-access:{case_id}:{expected_revision}"
        resource_ref = f"human-assignment:{case_id}"
        return await self.event_bus.publish(
            self.topic,
            resource_ref,
            {
                "idempotency_key": idempotency_key,
                "correlation_id": correlation_id,
                "initiator_principal": requester_ref,
                "operator_initiated": True,
                "action_type": APPLY_HUMAN_ACCESS_ACTION,
                "resource_id": resource_ref,
                "resource_type": "human-assignment",
                "event_type": "operator_request",
                "origin_event_type": "human.assignment.iam_apply_requested",
                "params": {
                    "case_id": case_id,
                    "expected_revision": expected_revision,
                },
            },
        )


__all__ = ["EventBusAssignmentApplyPublisher"]
