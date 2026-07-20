"""Idempotent external incident ingestion into the canonical event bus."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5

from fdai.shared.contracts.models import Event, Mode
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.incident_platform import IncidentPlatform

_EVENT_TYPE = "incident.platform.updated"
_SOURCE = "fdai.incident-platform-sync"


@dataclass(frozen=True, slots=True)
class IncidentPlatformSyncReport:
    observed: int
    published: int


class IncidentPlatformSync:
    """Publish bounded platform incidents with stable idempotency keys."""

    def __init__(
        self,
        *,
        provider: IncidentPlatform,
        event_bus: EventBus,
        topic: str,
        limit: int = 100,
    ) -> None:
        if not topic.strip():
            raise ValueError("incident platform sync topic MUST be non-empty")
        if not 1 <= limit <= 500:
            raise ValueError("incident platform sync limit MUST be in [1, 500]")
        self._provider = provider
        self._bus = event_bus
        self._topic = topic
        self._limit = limit

    async def run_once(self) -> IncidentPlatformSyncReport:
        incidents = tuple(await self._provider.list_active(limit=self._limit))
        published = 0
        for incident in incidents:
            idempotency_key = _idempotency_key(
                incident.platform,
                incident.incident_ref,
                incident.status.value,
                incident.updated_at.isoformat(),
            )
            event = Event(
                schema_version="1.0.0",
                event_id=uuid5(NAMESPACE_URL, idempotency_key),
                idempotency_key=idempotency_key,
                source=f"incident-platform:{incident.platform}",
                event_type=_EVENT_TYPE,
                payload={
                    "platform": incident.platform,
                    "incident_ref": incident.incident_ref,
                    "title": incident.title,
                    "severity": incident.severity,
                    "status": incident.status.value,
                    "created_at": incident.created_at.isoformat(),
                    "updated_at": incident.updated_at.isoformat(),
                    "service_ref": incident.service_ref,
                },
                detected_at=incident.updated_at,
                ingested_at=incident.updated_at,
                mode=Mode.SHADOW,
            )
            await self._bus.publish(
                self._topic,
                incident.service_ref or incident.incident_ref,
                event.model_dump(mode="json"),
            )
            published += 1
        return IncidentPlatformSyncReport(observed=len(incidents), published=published)


def _idempotency_key(*parts: str) -> str:
    digest = hashlib.sha256("\0".join(parts).encode()).hexdigest()
    return f"incident-platform:{digest}"


__all__ = ["IncidentPlatformSync", "IncidentPlatformSyncReport"]
