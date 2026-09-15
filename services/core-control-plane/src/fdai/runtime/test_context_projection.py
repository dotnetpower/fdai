"""Forward only Saga-audited context results to the non-privileged Operator read plane."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from fdai_service_contracts.semantic_turn import LOGICAL_TOPIC_FIELD
from fdai_service_contracts.test_context import TEST_CONTEXT_RESULT_TOPIC, TestContextApplication

from fdai.shared.providers.event_bus import EventBus


class TestContextApplicationPublisher:
    """Mechanical projection relay; never writes policy or supplies independent approval."""

    def __init__(self, bus: EventBus, *, physical_topic: str | None = None) -> None:
        self._bus = bus
        self._physical_topic = physical_topic

    async def handle(self, topic: str, payload: Mapping[str, Any]) -> None:
        """Ignore other audits and forward exact validated application metadata after audit."""
        if topic != "object.audit-entry" or payload.get("kind") != "test_context_application":
            return
        if (
            payload.get("producer_principal") != "Saga"
            or payload.get("audited_topic") != "object.policy"
            or payload.get("execution_authority") is not False
        ):
            raise ValueError("context application requires a Saga-owned policy audit")
        application = TestContextApplication.model_validate(payload.get("application"))
        if payload.get("correlation_id") != application.request_key:
            raise ValueError("context application projection correlation mismatch")
        async with asyncio.timeout(5):
            result = application.model_dump(mode="json")
            if self._physical_topic is not None:
                result[LOGICAL_TOPIC_FIELD] = TEST_CONTEXT_RESULT_TOPIC
            await self._bus.publish(
                self._physical_topic or TEST_CONTEXT_RESULT_TOPIC,
                application.command_digest,
                result,
            )
