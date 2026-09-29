"""Core ingress for Operator post-turn review publication requests."""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Protocol, cast

from fdai_service_contracts.post_turn_review import (
    POST_TURN_REVIEW_REQUEST_CONSUMER_GROUP,
    POST_TURN_REVIEW_REQUEST_TOPIC,
    OperatorPostTurnReviewRequestEnvelope,
)

from fdai.core.learning import review_input_from_mapping
from fdai.shared.providers.event_bus import EventBus, EventEnvelope, subscription

_LOGGER = logging.getLogger(__name__)
_SEEN_LIMIT = 4096


class BragiPostTurnPublisher(Protocol):
    async def publish_post_turn_review(self, review: object) -> bool: ...


@dataclass(slots=True)
class PostTurnReviewRequestConsumer:
    """Validate Operator requests and re-publish them only through Bragi."""

    runtime: Any | None
    group_id: str = POST_TURN_REVIEW_REQUEST_CONSUMER_GROUP
    _seen: set[str] = field(default_factory=set)
    _order: deque[str] = field(default_factory=deque)

    async def run(self, *, bus: EventBus, stop: asyncio.Event) -> None:
        async with subscription(bus, POST_TURN_REVIEW_REQUEST_TOPIC, self.group_id) as stream:
            async for envelope in stream:
                if stop.is_set():
                    return
                await self.handle(bus=bus, envelope=envelope)

    async def handle(self, *, bus: EventBus, envelope: EventEnvelope) -> bool:
        try:
            request = OperatorPostTurnReviewRequestEnvelope.model_validate(envelope.payload)
            if envelope.key != request.idempotency_key:
                raise ValueError("post-turn review request key mismatch")
            if request.idempotency_key in self._seen:
                return True
            bragi = self._bragi()
            if bragi is None:
                _LOGGER.warning(
                    "post_turn_review_bragi_unavailable",
                    extra={"idempotency_key": request.idempotency_key},
                )
                return False
            review_input = review_input_from_mapping(request.review.to_wire_mapping())
            published = await bragi.publish_post_turn_review(review_input)
            if not published:
                _LOGGER.warning(
                    "post_turn_review_bragi_publish_unavailable",
                    extra={"idempotency_key": request.idempotency_key},
                )
                return False
            self._remember(request.idempotency_key)
            return True
        except ValueError:
            await bus.dead_letter(
                POST_TURN_REVIEW_REQUEST_TOPIC,
                envelope.key,
                {"reason": "invalid_post_turn_review_request", "execution_authority": False},
                "invalid_post_turn_review_request",
            )
            return False

    def _bragi(self) -> BragiPostTurnPublisher | None:
        if self.runtime is None:
            return None
        candidate = self.runtime.agents.get("Bragi")
        publisher = getattr(candidate, "publish_post_turn_review", None)
        if publisher is None:
            return None
        return cast(BragiPostTurnPublisher, candidate)

    def _remember(self, key: str) -> None:
        self._seen.add(key)
        self._order.append(key)
        while len(self._order) > _SEEN_LIMIT:
            self._seen.discard(self._order.popleft())


__all__ = ["PostTurnReviewRequestConsumer"]
