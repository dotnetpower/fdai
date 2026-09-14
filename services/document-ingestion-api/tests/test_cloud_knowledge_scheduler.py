"""Durable-scheduler protocol tests use an explicit in-memory test store only."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fdai_ingestion_api_service.cloud_knowledge.collector import (
    CloudDocumentCollector,
    SourceResponse,
    SourceState,
)
from fdai_ingestion_api_service.cloud_knowledge.scheduler import CloudKnowledgeScheduler
from fdai_ingestion_api_service.cloud_knowledge.store import SourceCheckpoint
from fdai_service_contracts.cloud_knowledge import (
    Applicability,
    CloudKnowledgeSource,
    SourceRegistryRevision,
)

NOW = datetime(2026, 9, 14, tzinfo=UTC)


class MemoryCheckpoints:
    def __init__(self) -> None:
        self.items: dict[str, SourceCheckpoint] = {}
        self.claims: dict[str, UUID] = {}
        self.history: list[SourceState] = []

    async def get(self, registry_digest: str, source_id: str) -> SourceCheckpoint:
        return self.items.get(source_id, SourceCheckpoint(0, SourceState()))

    async def claim(self, registry_digest: str, source_id: str, revision: int) -> UUID | None:
        if source_id in self.claims:
            return None
        claim = uuid4()
        self.claims[source_id] = claim
        return claim

    async def finish(
        self,
        registry_digest: str,
        source_id: str,
        checkpoint: SourceCheckpoint,
        claim: UUID,
        state: SourceState,
    ) -> None:
        assert self.claims.pop(source_id) == claim
        self.items[source_id] = SourceCheckpoint(checkpoint.revision + 1, state)
        self.history.append(state)


class ScriptedTransport:
    def __init__(self, statuses: list[int]) -> None:
        self.statuses = statuses
        self.calls: list[str] = []

    async def fetch(self, source: CloudKnowledgeSource, *, etag: str | None) -> SourceResponse:
        self.calls.append(source.source_id)
        return SourceResponse(status=self.statuses.pop(0), content=b"Reference body")


def registry() -> SourceRegistryRevision:
    return SourceRegistryRevision(
        revision=1,
        approved_by="reviewer",
        valid_until=NOW + timedelta(days=60),
        sources=tuple(
            CloudKnowledgeSource(
                source_id=f"source-{number}",
                collection_id="cloud",
                title="Source",
                url=f"https://example.com/source-{number}",
                mode="online",
                enabled=True,
                storage_allowed=True,
                license_ref="fixture",
                applicability=Applicability(resource_type="network", service_generation="v1"),
            )
            for number in range(3)
        ),
    )


async def test_restart_does_not_repeat_successful_checkpoints() -> None:
    store = MemoryCheckpoints()
    transport = ScriptedTransport([200, 200, 200])
    collector = CloudDocumentCollector(transport, collector_id="test")
    first = CloudKnowledgeScheduler(
        registry=registry(),
        store=store,
        collector=collector,
        clock=lambda: NOW,
    )
    assert (await first.tick())["checked"] == 3
    restarted = CloudKnowledgeScheduler(
        registry=registry(),
        store=store,
        collector=collector,
        clock=lambda: NOW + timedelta(days=1),
    )
    assert (await restarted.tick())["checked"] == 0
    assert len(transport.calls) == 3 and len(store.history) == 3


async def test_provider_pressure_stops_without_claiming_complete_coverage() -> None:
    store = MemoryCheckpoints()
    transport = ScriptedTransport([200, 429, 200])
    scheduler = CloudKnowledgeScheduler(
        registry=registry(),
        store=store,
        collector=CloudDocumentCollector(transport, collector_id="test"),
        clock=lambda: NOW,
    )
    result = await scheduler.tick()
    assert result == {"checked": 2, "failed": 1, "status": "partial"}
    assert transport.calls == ["source-0", "source-1"]
    assert "source-2" not in store.items


async def test_active_lease_and_expired_registry_never_fetch() -> None:
    store = MemoryCheckpoints()
    store.claims = {f"source-{number}": uuid4() for number in range(3)}
    transport = ScriptedTransport([])
    scheduler = CloudKnowledgeScheduler(
        registry=registry(),
        store=store,
        collector=CloudDocumentCollector(transport, collector_id="test"),
        clock=lambda: NOW,
    )
    assert (await scheduler.tick())["checked"] == 0
    expired = CloudKnowledgeScheduler(
        registry=registry(),
        store=store,
        collector=CloudDocumentCollector(transport, collector_id="test"),
        clock=lambda: NOW + timedelta(days=60),
    )
    assert (await expired.tick())["status"] == "registry_expired"
    assert transport.calls == []
