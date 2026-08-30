from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.heimdall import Heimdall
from fdai.agents.muninn import Muninn
from fdai.core.ontology_platform.evidence_conflict import EvidenceConflictStatus
from fdai.delivery.evidence_conflict import StateStoreEvidenceConflictProjection
from fdai.shared.providers.testing.state_store import InMemoryStateStore

NOW = datetime(2026, 8, 30, 2, tzinfo=UTC)


def _lineage(
    *,
    authority: str,
    source: str,
    claim_digest: str,
) -> dict[str, object]:
    return {
        "source_identity": source,
        "source_revision": "revision-1",
        "claim_digest": claim_digest,
        "authority": authority,
        "evidence_cutoff": (NOW - timedelta(seconds=30)).isoformat(),
        "recorded_at": NOW.isoformat(),
        "freshness_ceiling_seconds": 300,
        "evidence_refs": [f"evidence:{source}"],
    }


def _candidate(
    *,
    status: str,
    supersedes_revision_ref: str | None = None,
) -> dict[str, object]:
    attributes: dict[str, object] = {
        "status": status,
        "target_ref": "resource:example-vm",
        "scope_ref": "scope:example",
        "generation_ref": "inventory-generation:one",
        "semantic_refs": ["runtime.vm.power_state"],
        "conflicting_fields": ["power_state"] if status == "active" else [],
        "source_a": _lineage(
            authority="provider",
            source="provider-inventory",
            claim_digest="sha256:" + "a" * 64,
        ),
        "source_b": _lineage(
            authority="telemetry",
            source="telemetry-query",
            claim_digest=("sha256:" + ("a" if status == "resolved" else "b") * 64),
        ),
    }
    if supersedes_revision_ref is not None:
        attributes["supersedes_revision_ref"] = supersedes_revision_ref
    return {
        "producer_principal": "Huginn",
        "correlation_id": "evidence-conflict:one",
        "idempotency_key": f"evidence-conflict:{status}",
        "event_id": f"event:evidence-conflict:{status}",
        "event_type": "evidence.conflict.candidate.v1",
        "detected_at": NOW.isoformat(),
        "resource_id": "resource:example-vm",
        "attributes": attributes,
    }


async def test_heimdall_publishes_and_muninn_advances_immutable_conflict_revisions() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    state_store = InMemoryStateStore()
    projection = StateStoreEvidenceConflictProjection(state_store)
    heimdall = Heimdall(bus=bus)
    muninn = Muninn(evidence_conflict_sink=projection)
    muninn.bind_bus(bus)
    bus.subscribe("object.event", "Heimdall", heimdall.on_typed_message)
    bus.subscribe("object.evidence-conflict", "Muninn", muninn.on_typed_message)

    await bus.publish("Huginn", "object.event", _candidate(status="active"))

    messages = bus.messages_on("object.evidence-conflict")
    assert len(messages) == 1
    active_payload = messages[0].payload
    assert active_payload["producer_principal"] == "Heimdall"
    assert active_payload["status"] == "active"
    active = await projection.current(str(active_payload["slot_ref"]))
    assert active is not None
    assert active.status is EvidenceConflictStatus.ACTIVE

    await bus.publish(
        "Huginn",
        "object.event",
        _candidate(
            status="resolved",
            supersedes_revision_ref=active.revision_ref,
        ),
    )

    current = await projection.current(active.slot_ref)
    assert current is not None
    assert current.status is EvidenceConflictStatus.RESOLVED
    assert current.supersedes_revision_ref == active.revision_ref
    assert heimdall.behavior_snapshot()["evidence_conflict:active"] == 1
    assert heimdall.behavior_snapshot()["evidence_conflict:resolved"] == 1
    assert muninn.behavior_snapshot()["evidence_conflict:stored"] == 2


async def test_heimdall_rejects_candidate_from_another_principal() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    heimdall = Heimdall(bus=bus)
    payload = _candidate(status="active")
    payload["producer_principal"] = "Other"

    await heimdall.on_typed_message("object.event", payload)

    assert bus.messages_on("object.evidence-conflict") == []
    assert heimdall.behavior_snapshot()["evidence_conflict:invalid_candidate"] == 1
