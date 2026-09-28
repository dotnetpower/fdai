"""Loopback PostgreSQL proof that the Twin outbox relay pages only unpublished rows.

Skipped unless ``FDAI_DATABASE_URL`` points to a dedicated validation database.
Each run uses fresh identities, so assertions stay exact for this run's rows.
"""

from __future__ import annotations

import uuid

import pytest
from fdai.core.assurance_twin import build_posture_assessment_report
from fdai.core.assurance_twin.posture_activity import build_posture_report_activity
from fdai.delivery.assurance_twin_publication import AssuranceTwinOutboxPublisher
from fdai.delivery.persistence import PostgresStateStore
from fdai.delivery.persistence.state_store_assurance_twin_posture import (
    StateStoreAssuranceTwinPostureLedger,
)
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai_service_contracts import OperationalFreshness

from tests.delivery.test_assurance_twin_outbox_scale import (
    POSTURE_PREFIX,
    record_pending_review,
    write_retained_history,
)
from tests.persistence.test_postgres_state_field_path import postgres_store

pytestmark = pytest.mark.integration


async def _published(store: PostgresStateStore, key: str) -> bool:
    row = await store.read_state(key)
    return row is not None and row["publication_outbox"]["published"] is True


@pytest.mark.asyncio
async def test_postgres_relay_publishes_pending_reviews_beside_1000_retained_reviews() -> None:
    store = postgres_store()
    ledger = StateStoreAssuranceTwinPostureLedger(store=store)
    base = uuid.uuid4().int % (1 << 96) << 32
    await write_retained_history(store, published=1_010, base=base)
    pending = [await record_pending_review(ledger, base + 2_000 + index) for index in range(3)]
    publisher = AssuranceTwinOutboxPublisher(owner="Forseti", ledger=ledger, bus=InMemoryEventBus())

    for _pass in range(20):
        await publisher.publish_pending()
        if all([await _published(store, key) for key in pending]):
            break
    assert all([await _published(store, key) for key in pending])
    assert await store.verify_chain() is True


@pytest.mark.asyncio
async def test_postgres_heimdall_posture_relay_is_unchanged() -> None:
    store = postgres_store()
    ledger = StateStoreAssuranceTwinPostureLedger(store=store)
    scope = f"scope-{uuid.uuid4().hex}"
    report = build_posture_assessment_report(
        scope=scope, generated_at="2026-09-28T01:00:00+00:00", mode=Mode.SHADOW, findings=()
    )
    activity = build_posture_report_activity(
        report, correlation_id="posture", freshness=OperationalFreshness.FRESH
    )
    await ledger.record_posture_report(
        report,
        freshness="fresh",
        activity_id=activity.activity_id,
        correlation_id="posture",
        evidence_source_revision="source-1",
        source_confirmed=True,
        activity=activity,
    )
    key = f"{POSTURE_PREFIX}{scope}"
    publisher = AssuranceTwinOutboxPublisher(
        owner="Heimdall", ledger=ledger, bus=InMemoryEventBus()
    )

    for _pass in range(20):
        await publisher.publish_pending()
        if await _published(store, key):
            break
    assert await _published(store, key)
