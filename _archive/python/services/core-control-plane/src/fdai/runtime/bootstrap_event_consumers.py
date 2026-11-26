"""Schedule independent typed event consumers under shared readiness and shutdown."""

from __future__ import annotations

import asyncio
from typing import Any

from fdai.runtime.readiness import StartupReadinessRuntime
from fdai.shared.providers.event_bus import EventBus


def _schedule(
    *,
    binding: Any,
    readiness: StartupReadinessRuntime,
    bus: EventBus,
    stop: asyncio.Event,
    name: str,
) -> asyncio.Task[None] | None:
    if binding is None:
        return None
    return asyncio.create_task(
        readiness.run_when_ready(stop, lambda: binding.run(bus=bus, stop=stop)),
        name=name,
    )


def schedule_incident_creation_consumer(
    *,
    binding: Any,
    readiness: StartupReadinessRuntime,
    bus: EventBus,
    stop: asyncio.Event,
) -> asyncio.Task[None] | None:
    return _schedule(
        binding=binding,
        readiness=readiness,
        bus=bus,
        stop=stop,
        name="incident-creation-consumer",
    )


def schedule_document_intent_ingress(
    *,
    binding: Any,
    readiness: StartupReadinessRuntime,
    bus: EventBus,
    stop: asyncio.Event,
) -> asyncio.Task[None] | None:
    return _schedule(
        binding=binding,
        readiness=readiness,
        bus=bus,
        stop=stop,
        name="document-intent-ready-consumer",
    )


__all__ = ["schedule_document_intent_ingress", "schedule_incident_creation_consumer"]
