"""Synthetic inter-service transport checks with independent stores and no live provider."""

from __future__ import annotations

import asyncio
import hashlib
from copy import deepcopy
from datetime import UTC, datetime

import pytest
from fdai.core.human_assignment.request_intake import AssignmentRequestIntake
from fdai.shared.providers.event_bus import EventEnvelope, PublishReceipt
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_core_service.assignment_intake_consumer import AssignmentIntakeConsumer
from fdai_operator_service.assignment_notice import assignment_notice_from_record
from fdai_operator_service.assignment_outbox import AssignmentNoticeDrainer, AssignmentProposalClaim
from fdai_operator_service.postgres_assignment_outbox import PostgresAssignmentOutbox
from fdai_operator_service.postgres_family_store import PostgresFamilyStoreConfig
from fdai_service_contracts.assignment_transport import (
    ASSIGNMENT_PROJECTION_TOPIC,
    ASSIGNMENT_REQUEST_TOPIC,
    assignment_content_digest,
)


def _source():
    request = {
        "family": "iam",
        "operation": "assignments.create",
        "principal_id": "human:owner",
        "idempotency_key": "handover:test:1",
        "payload": {"principal": {"oid": "human:owner", "roles": ["Owner"]}},
    }
    digest = assignment_content_digest(request)
    record = {
        **request,
        "kind": "operator.proposal",
        "mode": "shadow",
        "proposal_id": f"operator-{digest[:32]}",
        "request_digest": digest,
        "accepted_at": datetime.now(UTC).isoformat(),
    }
    key = "operator-proposal:iam:" + hashlib.sha256(b"handover:test:1").hexdigest()
    return AssignmentProposalClaim(key, "claim-1", record)


class Outbox:
    def __init__(self, claim):
        self.pending = claim
        self.finished = []
        self.released = []

    async def claim(self):
        return self.pending

    async def finish(self, claim, *, rejected=False):
        self.finished.append((claim, rejected))
        self.pending = None
        return True

    async def release(self, claim):
        self.released.append(claim)


class Bus:
    def __init__(self):
        self.records = []
        self.dead_letters = []
        self.failure = None
        self.closed = False

    async def publish(self, topic, key, payload):
        if self.failure is not None:
            raise self.failure
        self.records.append(EventEnvelope(topic, key, dict(payload), len(self.records)))
        return PublishReceipt(topic, 0, len(self.records))

    async def subscribe(self, topic, group_id):
        del group_id
        try:
            for record in list(self.records):
                if record.topic == topic:
                    yield record
        finally:
            self.closed = True

    async def dead_letter(self, topic, key, payload, reason):
        self.dead_letters.append((topic, key, payload, reason))


async def test_operator_notice_reaches_core_without_sharing_workflow_state():
    claim = _source()
    bus = Bus()
    outbox = Outbox(claim)
    operator_receipts = InMemoryStateStore()
    core_state = InMemoryStateStore()
    await operator_receipts.write_state(claim.key, claim.record)
    assert await AssignmentNoticeDrainer(outbox, bus).run_once()
    assert bus.records[0].topic == ASSIGNMENT_REQUEST_TOPIC
    assert "human:owner" not in str(bus.records[0].payload)
    consumer = AssignmentIntakeConsumer(
        AssignmentRequestIntake(receipts=operator_receipts, store=core_state)
    )
    await consumer.run(bus=bus, stop=asyncio.Event())
    projected = [item for item in bus.records if item.topic == ASSIGNMENT_PROJECTION_TOPIC]
    assert len(projected) == 1
    assert projected[0].payload["status"] == "awaiting_agent_review"
    assert projected[0].payload["execution_authority"] is False
    assert not await core_state.read_states("human_assignment:case:", limit=5)
    assert not await operator_receipts.read_states("human_assignment:intake:", limit=5)
    assert bus.closed


@pytest.mark.parametrize("failure", [OSError("test network"), TimeoutError("test timeout")])
async def test_unacknowledged_notice_remains_retryable_with_same_identity(failure):
    claim = _source()
    bus = Bus()
    bus.failure = failure
    outbox = Outbox(claim)
    drainer = AssignmentNoticeDrainer(outbox, bus)
    assert not await drainer.run_once()
    assert outbox.released == [claim]
    assert not outbox.finished
    bus.failure = None
    assert await drainer.run_once()
    assert bus.records[0].key == claim.record["proposal_id"]


async def test_malformed_proposal_is_rejected_before_transport():
    original = _source()
    bad = AssignmentProposalClaim(
        original.key, original.claim_id, {**original.record, "mode": "enforce"}
    )
    outbox, bus = Outbox(bad), Bus()
    assert not await AssignmentNoticeDrainer(outbox, bus).run_once()
    assert outbox.finished == [(bad, True)]
    assert not bus.records


async def test_consumer_redacts_malformed_notice_before_dead_letter():
    bus = Bus()
    await bus.publish(ASSIGNMENT_REQUEST_TOPIC, "private-user", {"raw": "private-prose"})
    state = InMemoryStateStore()
    consumer = AssignmentIntakeConsumer(AssignmentRequestIntake(receipts=state, store=state))
    await consumer.run(bus=bus, stop=asyncio.Event())
    assert len(bus.dead_letters) == 1
    assert "private" not in str(bus.dead_letters)
    assert bus.closed


async def test_consumer_rejects_wrong_partition_key():
    notice = assignment_notice_from_record(_source().record)
    bus = Bus()
    await bus.publish(ASSIGNMENT_REQUEST_TOPIC, "wrong", notice.model_dump(mode="json"))
    state = InMemoryStateStore()
    consumer = AssignmentIntakeConsumer(AssignmentRequestIntake(receipts=state, store=state))
    await consumer.run(bus=bus, stop=asyncio.Event())
    assert len(bus.dead_letters) == 1
    assert not tuple(state.audit_entries)


async def test_failed_notice_does_not_preempt_valid_notice():
    claim = _source()
    notice = assignment_notice_from_record(claim.record)
    state = InMemoryStateStore()
    source = InMemoryStateStore()
    await source.write_state(claim.key, claim.record)
    intake = AssignmentRequestIntake(receipts=source, store=state)
    altered = notice.model_validate({**notice.model_dump(), "operation": "assignments.review"})
    assert (await intake.receive(altered, at=datetime.now(UTC))).status == "held"
    assert (await intake.receive(notice, at=datetime.now(UTC))).status == "awaiting_agent_review"


async def test_postgres_claim_and_closure_are_operation_scoped_and_lease_fenced(monkeypatch):
    claim = _source()
    calls = []

    async def query(_self, sql, parameters):
        calls.append((sql, parameters))
        return [{"key": claim.key, "value": dict(claim.record)}]

    monkeypatch.setattr(PostgresAssignmentOutbox, "_query", query)
    outbox = PostgresAssignmentOutbox(
        PostgresFamilyStoreConfig(dsn="postgresql://localhost/example")
    )
    claimed = await outbox.claim()
    assert claimed is not None
    assert "FOR UPDATE OF request SKIP LOCKED" in calls[0][0]
    assert "assignments.create" in calls[0][0]
    assert "transport_attempt" in calls[0][0]
    assert await outbox.finish(claimed)
    assert "value ->> 'claim_id' = %(claim_id)s" in calls[1][0]
    assert calls[1][1]["state"] == "published"
    assert "human_assignment:case" not in calls[1][0]


def test_notice_never_accepts_mutable_presentational_state_as_a_request():
    record = deepcopy(_source().record)
    record["kind"] = "assignment.projection"
    with pytest.raises(ValueError):
        assignment_notice_from_record(record)
