"""Admitted inventory delivery resumes across instances using real PostgreSQL fences."""

from datetime import UTC, datetime, timedelta

import pytest
from fdai.agents import InMemoryBus, load_pantheon
from fdai.agents.huginn import Huginn
from fdai.delivery.persistence import PostgresStateStore, PostgresStateStoreConfig

from tests.agents.test_huginn_discovery import _canonical_event
from tests.persistence.test_postgres_state_store import saga_database as saga_database

pytestmark = pytest.mark.integration


async def _project(_payload):
    return None


async def test_admitted_inventory_recovers_without_raw_input_on_postgres(saga_database):
    store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=saga_database))
    now = [datetime(2026, 9, 20, tzinfo=UTC)]
    try:
        writer = Huginn(
            state_store=store,
            discovery_projector=_project,
            clock=lambda: now[0],
            dedup_clock=lambda: now[0],
        )
        original = await writer.ingest(_canonical_event())
        assert original is not None
        now[0] += timedelta(minutes=2)
        bus = InMemoryBus(load_pantheon())
        restarted = Huginn(
            bus=bus,
            state_store=store,
            discovery_projector=_project,
            clock=lambda: now[0],
            dedup_clock=lambda: now[0],
        )
        await restarted.maintenance_tick()
        assert len(bus.messages_on("object.event")) == 1
        assert bus.messages_on("object.event")[0].payload["ingested_at"] == original["ingested_at"]
        assert await restarted.recover_pending_inventory() == 0
        completed = await store.read_states("pantheon/huginn/ingress-dedup/terminal/", limit=8)
        assert len(completed) == 1
        assert completed[0]["status"] == "published"
        assert await store.verify_chain()
    finally:
        await store.aclose()
