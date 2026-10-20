"""Admitted inventory delivery resumes across instances using real PostgreSQL fences."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fdai.agents import InMemoryBus, load_pantheon
from fdai.agents.heimdall import Heimdall
from fdai.agents.huginn import Huginn
from fdai.core.incident import (
    IncidentAutoOpenPolicy,
    IncidentLifecycleWorkflow,
    IncidentRegistry,
    open_detected_incident_candidate,
)
from fdai.delivery.persistence import PostgresStateStore, PostgresStateStoreConfig
from fdai.shared.contracts.models import IncidentSeverity

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


async def test_grounded_detection_creates_one_durable_incident_and_survives_restart(saga_database):
    store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=saga_database))
    now = datetime(2026, 10, 21, tzinfo=UTC)
    candidates = []
    try:
        registry = IncidentRegistry(state_store=store)
        workflow = IncidentLifecycleWorkflow(
            registry=registry,
            allowed_agent_principals={"Heimdall"},
        )

        async def open_candidate(candidate):
            candidates.append(candidate)
            result = await open_detected_incident_candidate(
                workflow=workflow,
                candidate=candidate,
                policy=IncidentAutoOpenPolicy(),
            )
            return result is not None

        bus = InMemoryBus(load_pantheon(), isolate_handlers=False)
        heimdall = Heimdall(
            bus=bus,
            rate_threshold=2,
            incident_candidate_hook=open_candidate,
            clock=lambda: now.timestamp(),
        )
        bus.subscribe("object.event", "Heimdall", heimdall.on_typed_message)
        huginn = Huginn(bus=bus, state_store=store, clock=lambda: now)
        events = [
            {
                "resource_id": "test-resource",
                "resource_type": "compute.vm",
                "event_type": "availability.failed",
                "source": "synthetic-validation",
                "correlation_id": "test-episode",
                "idempotency_key": f"evidence-{index}",
                "event_id": str(UUID(int=index + 1)),
                "occurred_at": now.isoformat(),
                "severity": "high",
            }
            for index in range(2)
        ]
        for event in events:
            await huginn.ingest(event)
        assert await huginn.ingest(events[0]) is None
        assert len(candidates) == 1
        assert len(registry.snapshot()) == 1
        incident = next(iter(registry.snapshot().values()))
        assert incident.severity is IncidentSeverity.SEV2
        assert len(incident.member_event_ids) == 2
        restarted = IncidentRegistry(state_store=store)
        transitions = await store.read_incident_transitions()
        restarted.rehydrate(transitions)
        replay = await open_detected_incident_candidate(
            workflow=IncidentLifecycleWorkflow(
                registry=restarted,
                allowed_agent_principals={"Heimdall"},
            ),
            candidate=candidates[0],
            policy=IncidentAutoOpenPolicy(),
        )
        assert replay is not None and not replay.created
        assert replay.incident.incident_id == incident.incident_id
        assert len(await store.read_incident_transitions()) == len(transitions)
        assert await store.verify_chain()
    finally:
        await store.aclose()
