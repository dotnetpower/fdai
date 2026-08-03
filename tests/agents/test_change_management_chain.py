from __future__ import annotations

from datetime import UTC, datetime

import pytest

from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.huginn import Huginn
from fdai.agents.muninn import Muninn


async def test_huginn_publishes_change_and_muninn_keeps_revision() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    huginn = Huginn(bus=bus)
    muninn = Muninn()
    bus.subscribe("object.change", "Muninn", muninn.on_typed_message)

    await huginn.ingest(
        {
            "idempotency_key": "plan-1",
            "event_id": "event-1",
            "correlation_id": "correlation-1",
            "event_type": "iac.plan",
            "source": "gitops",
            "resource_id": "resource-1",
            "occurred_at": datetime(2026, 8, 4, tzinfo=UTC).isoformat(),
            "change": {
                "id": "change-1",
                "change_kind": "infrastructure",
                "intent_kind": "planned",
                "actor_ref": "pipeline-principal",
                "status": "planned",
                "desired_state_digest": "sha256:desired",
                "plan_receipt_ref": "plan:1",
            },
        }
    )

    changes = bus.messages_on("object.change")
    assert len(changes) == 1
    assert changes[0].principal == "Huginn"
    stored = muninn.get_context("changes", "change-1")
    assert stored is not None
    assert stored["change"]["desired_state_digest"] == "sha256:desired"
    assert len(muninn.state_store.data["change_revisions"]) == 1


async def test_non_change_event_does_not_publish_change() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    await Huginn(bus=bus).ingest(
        {
            "id": "event-1",
            "event_type": "health.sample",
            "resource_id": "resource-1",
        }
    )
    assert bus.messages_on("object.change") == []


async def test_change_without_authoritative_time_fails_before_publish() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    with pytest.raises(ValueError, match="occurred_at"):
        await Huginn(bus=bus).ingest(
            {
                "id": "event-1",
                "event_type": "iac.plan",
                "source": "gitops",
                "resource_id": "resource-1",
            }
        )
    assert bus.messages_on("object.event") == []
    assert bus.messages_on("object.change") == []


async def test_muninn_preserves_distinct_change_revisions() -> None:
    muninn = Muninn()
    baseline = {
        "producer_principal": "Huginn",
        "id": "change-1",
        "status": "planned",
    }
    await muninn.on_typed_message("object.change", baseline)
    await muninn.on_typed_message("object.change", {**baseline, "status": "completed"})
    await muninn.on_typed_message("object.change", {**baseline, "status": "completed"})

    assert len(muninn.state_store.data["change_revisions"]) == 2
    latest = muninn.get_context("changes", "change-1")
    assert latest is not None
    assert latest["change"]["status"] == "completed"
