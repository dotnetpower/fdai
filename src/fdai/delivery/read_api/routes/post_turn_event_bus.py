"""Publish consent-filtered completed turns on Bragi's owned topic."""

from __future__ import annotations

from fdai.core.learning import PostTurnReviewInput, review_input_to_mapping
from fdai.shared.providers.event_bus import EventBus


class EventBusPostTurnReviewIntake:
    def __init__(self, *, bus: EventBus, topic: str = "object.post-turn-review") -> None:
        if topic != "object.post-turn-review":
            raise ValueError("post-turn review intake MUST publish object.post-turn-review")
        self._bus = bus
        self._topic = topic

    async def submit(self, review_input: PostTurnReviewInput) -> None:
        await self._bus.publish(
            self._topic,
            review_input.principal_scope,
            {
                "producer_principal": "Bragi",
                "id": review_input.review_id,
                "correlation_id": review_input.assistant_turn_id,
                "idempotency_key": f"post-turn-review:{review_input.review_id}",
                "kind": "post_turn_review",
                "principal_scope": review_input.principal_scope,
                "review": review_input_to_mapping(review_input),
            },
        )


__all__ = ["EventBusPostTurnReviewIntake"]
