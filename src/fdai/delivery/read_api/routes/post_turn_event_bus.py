"""Publish consent-filtered completed turns on Bragi's owned topic."""

from __future__ import annotations

from fdai.core.learning import PostTurnReviewInput, review_input_to_mapping
from fdai.shared.providers.event_bus import EventBus


class EventBusPostTurnReviewIntake:
    def __init__(self, *, bus: EventBus, topic: str = "object.turn") -> None:
        if topic != "object.turn":
            raise ValueError("post-turn review intake MUST publish object.turn")
        self._bus = bus
        self._topic = topic

    async def submit(self, review_input: PostTurnReviewInput) -> None:
        await self._bus.publish(
            self._topic,
            review_input.principal_scope,
            {
                "producer_principal": "Bragi",
                "kind": "post_turn_review",
                "review": review_input_to_mapping(review_input),
            },
        )


__all__ = ["EventBusPostTurnReviewIntake"]
