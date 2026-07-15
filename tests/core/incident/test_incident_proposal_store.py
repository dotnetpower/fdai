"""Atomic pending incident proposal store tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from fdai.core.incident.intent import IncidentCreationProposal
from fdai.core.incident.proposal_store import (
    InMemoryIncidentProposalStore,
    proposal_from_record,
    proposal_to_record,
)
from fdai.shared.contracts.models import IncidentSeverity


def _proposal(now: datetime) -> IncidentCreationProposal:
    return IncidentCreationProposal(
        requested_by="operator@example.com",
        correlation_keys=("resource:example-1",),
        severity=IncidentSeverity.SEV2,
        source_text="Open a SEV2 incident for target example-1",
        requested_at=now,
        expires_at=now + timedelta(minutes=10),
    )


async def test_take_is_atomic_under_concurrent_confirmation() -> None:
    now = datetime(2026, 7, 15, tzinfo=UTC)
    store = InMemoryIncidentProposalStore()
    await store.save(operator_id="operator@example.com", session_id="s1", proposal=_proposal(now))

    results = await asyncio.gather(
        *(
            store.take(operator_id="operator@example.com", session_id="s1", now=now)
            for _ in range(8)
        )
    )

    assert [result.status for result in results].count("found") == 1
    assert [result.status for result in results].count("missing") == 7


async def test_take_consumes_expired_proposal() -> None:
    now = datetime(2026, 7, 15, tzinfo=UTC)
    store = InMemoryIncidentProposalStore()
    await store.save(operator_id="operator@example.com", session_id="s1", proposal=_proposal(now))

    expired = await store.take(
        operator_id="operator@example.com",
        session_id="s1",
        now=now + timedelta(minutes=11),
    )
    replayed = await store.take(
        operator_id="operator@example.com",
        session_id="s1",
        now=now + timedelta(minutes=11),
    )

    assert expired.status == "expired"
    assert replayed.status == "missing"


async def test_capacity_evicts_earliest_expiry() -> None:
    now = datetime(2026, 7, 15, tzinfo=UTC)
    store = InMemoryIncidentProposalStore(capacity=1)
    first = _proposal(now)
    second = IncidentCreationProposal(
        requested_by="operator@example.com",
        correlation_keys=("resource:example-2",),
        severity=IncidentSeverity.SEV3,
        source_text="Open a SEV3 incident for target example-2",
        requested_at=now,
        expires_at=now + timedelta(minutes=20),
    )
    await store.save(operator_id="operator@example.com", session_id="s1", proposal=first)
    await store.save(operator_id="operator@example.com", session_id="s2", proposal=second)

    evicted = await store.take(operator_id="operator@example.com", session_id="s1", now=now)
    retained = await store.take(operator_id="operator@example.com", session_id="s2", now=now)

    assert evicted.status == "missing"
    assert retained.proposal == second


async def test_store_rejects_requester_mismatch_and_naive_now() -> None:
    aware_now = datetime(2026, 7, 15, tzinfo=UTC)
    store = InMemoryIncidentProposalStore()

    with pytest.raises(ValueError, match="requester MUST match"):
        await store.save(
            operator_id="other@example.com",
            session_id="s1",
            proposal=_proposal(aware_now),
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        await store.take(
            operator_id="operator@example.com",
            session_id="s1",
            now=datetime(2026, 7, 15),
        )


def test_proposal_record_round_trip() -> None:
    proposal = _proposal(datetime(2026, 7, 15, tzinfo=UTC))

    record = proposal_to_record(proposal)
    restored = proposal_from_record(record)

    assert "source_text" not in record
    assert record["source_sha256"] != proposal.source_text
    assert restored.source_text == ""
    assert restored.requested_by == proposal.requested_by
    assert restored.correlation_keys == proposal.correlation_keys
    assert restored.severity is proposal.severity
    assert restored.requested_at == proposal.requested_at
    assert restored.expires_at == proposal.expires_at


@pytest.mark.parametrize(
    "update",
    [
        {"schema_version": "2.0.0"},
        {"requested_by": ""},
        {"source_sha256": "not-a-digest"},
        {"correlation_keys": []},
        {"severity": "unknown"},
        {"expires_at": "2026-07-15T00:00:00"},
    ],
)
def test_proposal_record_rejects_malformed_persistence(update: dict[str, object]) -> None:
    record = proposal_to_record(_proposal(datetime(2026, 7, 15, tzinfo=UTC)))
    record.update(update)

    with pytest.raises(ValueError, match="invalid incident proposal record"):
        proposal_from_record(record)