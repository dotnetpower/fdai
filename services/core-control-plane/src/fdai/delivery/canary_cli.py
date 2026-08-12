"""One-shot synthetic canary publisher for a Container Apps scheduled Job."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

import httpx

from fdai.core.control_loop._canary import CANARY_EVENT_TYPE, CANARY_SOURCE
from fdai.delivery.azure.event_bus import EventHubsKafkaBus, EventHubsKafkaBusConfig
from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity
from fdai.shared.contracts.models import Event, Mode

_LOGGER = logging.getLogger("fdai.canary")


def build_canary_event(*, slot: str, now: datetime) -> Event:
    """Build the deterministic event for one scheduled canary slot."""
    normalized_slot = slot.strip()
    if not normalized_slot or len(normalized_slot) > 100:
        raise ValueError("canary slot MUST contain 1 to 100 characters")
    if now.tzinfo is None:
        raise ValueError("canary timestamp MUST be timezone-aware")
    observed_at = now.astimezone(UTC)
    event_id = uuid5(NAMESPACE_URL, f"fdai.canary://{normalized_slot}")
    return Event(
        schema_version="1.0.0",
        event_id=event_id,
        idempotency_key=f"canary:{normalized_slot}",
        correlation_id=f"canary:{normalized_slot}",
        source=CANARY_SOURCE,
        event_type=CANARY_EVENT_TYPE,
        payload={"slot": normalized_slot},
        detected_at=observed_at,
        ingested_at=observed_at,
        mode=Mode.SHADOW,
    )


async def _run() -> int:
    topic = os.environ.get("FDAI_CANARY_TOPIC", "").strip()
    bootstrap_servers = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "").strip()
    if not topic or not bootstrap_servers:
        raise RuntimeError("FDAI_CANARY_TOPIC and KAFKA_BOOTSTRAP_SERVERS are required")
    now = datetime.now(tz=UTC)
    slot = os.environ.get("FDAI_CANARY_SLOT", "").strip() or now.strftime("%Y%m%dT%H%MZ")
    event = build_canary_event(slot=slot, now=now)
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=5.0, read=15.0, write=15.0, pool=5.0)
    ) as http_client:
        identity = ManagedIdentityWorkloadIdentity.from_env(http_client=http_client)
        bus = EventHubsKafkaBus(
            identity=identity,
            config=EventHubsKafkaBusConfig(bootstrap_servers=bootstrap_servers),
        )
        try:
            await bus.publish(
                topic,
                event.idempotency_key,
                event.model_dump(mode="json"),
            )
        finally:
            await bus.close()
    _LOGGER.info(
        "canary_published",
        extra={"topic": topic, "event_id": str(event.event_id), "slot": slot},
    )
    return 0


def main() -> int:
    """Publish one canary and map provider failures to a non-zero job exit."""
    logging.basicConfig(level=logging.INFO)
    try:
        return asyncio.run(_run())
    except Exception:
        _LOGGER.exception("canary_publish_failed")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_canary_event", "main"]
