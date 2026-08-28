"""Bridge Azure diagnostic Event Hub records into the governed ingest topic."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from fdai.delivery.azure.monitor_events import (
    AzureMonitorNormalizationError,
    DiagnosticNormalizerOptions,
    normalize_diagnostic_records,
)
from fdai.shared.providers.event_bus import EventBus, EventEnvelope, subscription


@dataclass(frozen=True, slots=True)
class DiagnosticEventIngestBridge:
    """Normalize one diagnostic stream and publish replay-stable Events."""

    source_bus: EventBus
    target_bus: EventBus
    source_topic: str
    target_topic: str
    consumer_group: str
    options: DiagnosticNormalizerOptions
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    def __post_init__(self) -> None:
        for field_name, value in (
            ("source_topic", self.source_topic),
            ("target_topic", self.target_topic),
            ("consumer_group", self.consumer_group),
        ):
            if not value.strip():
                raise ValueError(f"{field_name} MUST be non-empty")

    async def process(self, envelope: EventEnvelope) -> int:
        """Publish normalized Events or dead-letter one malformed source record."""

        if envelope.topic != self.source_topic:
            raise ValueError("diagnostic envelope arrived on an unexpected topic")
        try:
            events = normalize_diagnostic_records(
                envelope.payload,
                options=self.options,
                ingested_at=self.clock(),
            )
        except AzureMonitorNormalizationError as exc:
            await self.source_bus.dead_letter(
                self.source_topic,
                envelope.key,
                envelope.payload,
                type(exc).__name__,
            )
            return 0
        for event in events:
            await self.target_bus.publish(
                self.target_topic,
                event.resource_ref or event.idempotency_key,
                event.model_dump(mode="json"),
            )
        return len(events)

    async def run(self) -> None:
        """Consume until cancelled while preserving broker-managed replay."""

        async with subscription(
            self.source_bus,
            self.source_topic,
            self.consumer_group,
        ) as records:
            async for envelope in records:
                await self.process(envelope)


__all__ = ["DiagnosticEventIngestBridge"]
