"""External incident platform synchronization into event ingest."""

from __future__ import annotations

from datetime import UTC, datetime

from fdai.core.incident.platform_sync import IncidentPlatformSync
from fdai.shared.providers.event_bus import PublishReceipt
from fdai.shared.providers.incident_platform import (
    ExternalIncident,
    ExternalIncidentStatus,
)

_NOW = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)


class _Provider:
    async def list_active(self, *, limit: int = 100):
        assert limit == 20
        return (
            ExternalIncident(
                platform="example",
                incident_ref="inc-1",
                title="API latency",
                severity="high",
                status=ExternalIncidentStatus.TRIGGERED,
                created_at=_NOW,
                updated_at=_NOW,
                service_ref="service-api",
            ),
        )

    async def acknowledge(self, incident_ref: str):  # pragma: no cover - sync is read-only
        raise NotImplementedError


class _RecordingBus:
    def __init__(self) -> None:
        self.published: list[tuple[str, str, dict[str, object]]] = []

    async def publish(self, topic: str, key: str, payload: dict[str, object]) -> PublishReceipt:
        self.published.append((topic, key, payload))
        return PublishReceipt(topic=topic, partition=0, offset=len(self.published))

    def subscribe(self, topic: str, group_id: str):  # pragma: no cover - unused
        raise NotImplementedError

    async def dead_letter(self, topic, key, payload, reason):  # pragma: no cover - unused
        raise NotImplementedError

    async def resolve(self, incident_ref: str):  # pragma: no cover - sync is read-only
        raise NotImplementedError

    async def add_note(self, incident_ref: str, note: str):  # pragma: no cover
        raise NotImplementedError


async def test_sync_publishes_stable_bounded_event() -> None:
    bus = _RecordingBus()
    sync = IncidentPlatformSync(
        provider=_Provider(),
        event_bus=bus,
        topic="aw.incidents",
        limit=20,
    )

    first = await sync.run_once()
    second = await sync.run_once()

    assert first.observed == first.published == 1
    assert second.published == 1
    assert len(bus.published) == 2
    first_payload = bus.published[0][2]
    second_payload = bus.published[1][2]
    assert first_payload["idempotency_key"] == second_payload["idempotency_key"]
    assert first_payload["event_type"] == "incident.platform.updated"
    assert first_payload["payload"]["incident_ref"] == "inc-1"  # type: ignore[index]
