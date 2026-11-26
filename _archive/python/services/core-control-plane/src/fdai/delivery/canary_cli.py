"""One-shot canary publisher bound to an explicit slot or a platform execution identity."""

from __future__ import annotations

import asyncio
import logging
import os
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx

from fdai.core.control_loop._canary import CANARY_EVENT_TYPE, CANARY_SOURCE
from fdai.delivery.azure.event_bus import EventHubsKafkaBus, EventHubsKafkaBusConfig
from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity
from fdai.shared.contracts.models import Event, Mode

_LOGGER = logging.getLogger("fdai.canary")
_ACA_EXECUTION_NAME = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,84}[a-z0-9])?")


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


def _execution_slot(environment: Mapping[str, str]) -> str:
    """Preserve explicit slots; otherwise require exactly one platform execution identity."""
    explicit = environment.get("FDAI_CANARY_SLOT", "").strip()
    if explicit:
        return explicit
    if "FDAI_CANARY_JOB_UID" in environment and "CONTAINER_APP_JOB_EXECUTION_NAME" in environment:
        raise RuntimeError("canary execution identity is ambiguous across platform bindings")
    if "CONTAINER_APP_JOB_EXECUTION_NAME" in environment:
        execution = environment["CONTAINER_APP_JOB_EXECUTION_NAME"]
        if _ACA_EXECUTION_NAME.fullmatch(execution) is None:
            raise RuntimeError("Container Apps canary execution name is malformed or out of bounds")
        return f"aca-execution:{execution}"
    uid = environment.get("FDAI_CANARY_JOB_UID", "")
    if len(uid) != 36:
        raise RuntimeError(
            "canary execution identity requires an explicit slot or one valid platform execution"
        )
    try:
        parsed = UUID(uid)
    except ValueError as exc:
        raise RuntimeError(
            "canary execution identity requires an explicit slot or one valid platform execution"
        ) from exc
    if str(parsed) != uid or parsed.int == 0:
        raise RuntimeError("FDAI_CANARY_JOB_UID must be a canonical nonzero controller Job UID")
    return f"aks-job:{uid}"


async def _run() -> int:
    topic = os.environ.get("FDAI_CANARY_TOPIC", "").strip()
    bootstrap_servers = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "").strip()
    if not topic or not bootstrap_servers:
        raise RuntimeError("FDAI_CANARY_TOPIC and KAFKA_BOOTSTRAP_SERVERS are required")
    now = datetime.now(tz=UTC)
    slot = _execution_slot(os.environ)
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
