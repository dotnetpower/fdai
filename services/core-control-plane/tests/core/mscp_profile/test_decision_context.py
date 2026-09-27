"""Fail-closed, immutable, restart-safe decision-context checks."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fdai.core.mscp_profile.decision_context import (
    DecisionSource,
    MscpDecisionContext,
    OwnerDecisionObservation,
    collect_decision_context,
    project_decision_context,
)
from fdai.core.mscp_profile.decision_context_store import (
    MscpDecisionContextConflictError,
    StateStoreMscpDecisionContext,
)
from fdai.core.mscp_profile.readiness import MscpCandidateKey
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_NOW = datetime(2026, 9, 27, 3, 0, tzinfo=UTC)
_CANDIDATE = MscpCandidateKey(
    action_type="example.restart",
    effect_metric="availability",
    environment="non-production",
    observer_version="observer-v1",
)
_SUBJECT = "sha256:" + "1" * 64


def _observation(source: DecisionSource, **changes: Any) -> OwnerDecisionObservation:
    record = OwnerDecisionObservation(
        source=source,
        decision_id="decision-one",
        subject_digest=_SUBJECT,
        revision=3,
        state="verified" if source is DecisionSource.AUDIT else "current",
        evidence_digest="sha256:" + hashlib.sha256(source.value.encode()).hexdigest(),
        observed_at=_NOW - timedelta(minutes=2),
        recorded_at=_NOW - timedelta(minutes=1),
        valid_until=_NOW + timedelta(minutes=5),
        complete=True,
        audit_chain_verified=source is DecisionSource.AUDIT,
    )
    return replace(record, **changes)


def _context(
    *observations: OwnerDecisionObservation,
    unavailable: tuple[DecisionSource, ...] = (),
    decision_id: str = "decision-one",
) -> MscpDecisionContext:
    return project_decision_context(
        candidate=_CANDIDATE,
        decision_id=decision_id,
        subject_digest=_SUBJECT,
        cutoff=_NOW,
        observations=observations,
        unavailable=unavailable,
    )


def _all() -> tuple[OwnerDecisionObservation, ...]:
    return tuple(_observation(source) for source in DecisionSource)


def test_complete_join_is_order_independent_and_carries_no_authority() -> None:
    records = _all()
    first = _context(*records)
    second = _context(*reversed(records))

    assert first == second
    assert first.disposition == "ready"
    assert first.reasons == ()
    assert first.execution_authority is False
    assert len(first.observations) == 4
    assert "secret" not in str(first.to_mapping())
    assert MscpDecisionContext.from_mapping(first.to_mapping()) == first


@pytest.mark.parametrize(
    ("changed", "reason"),
    [
        ({"decision_id": "another-decision"}, "conflicting_ontology"),
        ({"subject_digest": "sha256:" + "3" * 64}, "conflicting_ontology"),
        ({"complete": False}, "incomplete_ontology"),
        ({"recorded_at": _NOW + timedelta(seconds=1)}, "future_ontology"),
        ({"observed_at": _NOW + timedelta(seconds=1)}, "future_ontology"),
        ({"valid_until": _NOW}, "stale_ontology"),
    ],
)
def test_invalid_owner_facts_hold(changed: dict[str, Any], reason: str) -> None:
    records = list(_all())
    records[0] = replace(records[0], **changed)

    result = _context(*records)

    assert result.disposition == "hold"
    assert reason in result.reasons
    assert MscpDecisionContext.from_mapping(result.to_mapping()) == result


def test_missing_duplicate_and_unverified_audit_hold_without_silent_selection() -> None:
    records = _all()
    missing = _context(*records[1:])
    duplicate = _context(*records, _observation(DecisionSource.ONTOLOGY, revision=4))
    unverified = _context(*records[:3], replace(records[3], audit_chain_verified=False))

    assert missing.reasons == ("missing_ontology",)
    assert duplicate.reasons == ("conflicting_ontology",)
    assert unverified.reasons == ("unverified_audit",)
    assert all(item.disposition == "hold" for item in (missing, duplicate, unverified))


def test_swapped_owner_and_unrecorded_observation_hold() -> None:
    records = _all()
    swapped = _context(
        *records[:3],
        replace(records[3], source=DecisionSource.ONTOLOGY, audit_chain_verified=False),
    )
    unrecorded = _context(
        replace(records[0], observed_at=_NOW, recorded_at=_NOW - timedelta(minutes=1)),
        *records[1:],
    )

    assert swapped.disposition == "hold"
    assert "conflicting_ontology" in swapped.reasons
    assert "missing_audit" in swapped.reasons
    assert unrecorded.reasons == ("future_ontology",)


def test_one_source_lineage_cannot_attest_two_owners() -> None:
    records = _all()
    reused = _context(
        records[0],
        replace(records[1], evidence_digest=records[0].evidence_digest),
        *records[2:],
    )

    assert reused.disposition == "hold"
    assert reused.reasons == ("conflicting_source_lineage",)


class _Reader:
    def __init__(self, observation: OwnerDecisionObservation | None = None, *, fail: bool = False):
        self.observation = observation
        self.fail = fail
        self.calls = 0

    async def read(
        self, *, decision_id: str, subject_digest: str, cutoff: datetime
    ) -> OwnerDecisionObservation | None:
        assert decision_id == "decision-one"
        assert subject_digest == _SUBJECT
        assert cutoff == _NOW
        self.calls += 1
        if self.fail:
            raise RuntimeError("private owner error")
        return self.observation


async def test_owner_collection_holds_on_missing_reader_and_read_failure() -> None:
    records = _all()
    readers = {item.source: _Reader(item) for item in records}
    readers[DecisionSource.AUDIT] = _Reader(fail=True)
    del readers[DecisionSource.WORKFLOW]

    result = await collect_decision_context(
        candidate=_CANDIDATE,
        decision_id="decision-one",
        subject_digest=_SUBJECT,
        cutoff=_NOW,
        readers=readers,
    )

    assert result.disposition == "hold"
    assert set(result.reasons) == {"missing_workflow", "missing_audit", "unavailable_audit"}
    assert "private owner error" not in str(result.to_mapping())
    assert readers[DecisionSource.ONTOLOGY].calls == 1


@pytest.mark.parametrize(
    "bad",
    [
        {"revision": True},
        {"state": "raw source content"},
        {"subject_digest": "not-a-digest"},
        {"observed_at": datetime(2026, 9, 27)},
        {"audit_chain_verified": True},
    ],
)
def test_owner_boundary_rejects_unbounded_or_forged_fields(bad: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        _observation(DecisionSource.ONTOLOGY, **bad)


async def test_immutable_record_survives_restart_and_collapses_duplicate_audit() -> None:
    state = InMemoryStateStore()
    context = _context(*_all())

    await StateStoreMscpDecisionContext(state).record(context)
    replay = StateStoreMscpDecisionContext(state)
    assert await replay.get(_CANDIDATE, "decision-one") == context
    assert await replay.record(context) == context
    assert len(tuple(state.audit_entries)) == 1
    assert await state.verify_chain() is True
    entry = next(iter(state.audit_entries))
    assert entry["entry"]["context_digest"] == context.digest
    assert entry["entry"]["execution_authority"] is False
    assert "decision-one" not in str(entry)


async def test_conflicting_restart_and_concurrent_retry_cannot_rewrite_decision() -> None:
    state = InMemoryStateStore()
    store = StateStoreMscpDecisionContext(state)
    first = _context(*_all())
    changed = _context(*_all()[:-1], _observation(DecisionSource.AUDIT, revision=4))
    results = await asyncio.gather(
        store.record(first), store.record(changed), return_exceptions=True
    )

    assert sum(isinstance(item, MscpDecisionContextConflictError) for item in results) == 1
    assert (await StateStoreMscpDecisionContext(state).get(_CANDIDATE, "decision-one")) in (
        first,
        changed,
    )
    assert len(tuple(state.audit_entries)) == 1


async def test_stored_tamper_and_failed_audit_do_not_claim_a_decision() -> None:
    state = InMemoryStateStore()
    store = StateStoreMscpDecisionContext(state)
    context = _context(*_all())
    await store.record(context)
    key = next(iter(state._state))
    tampered = dict(state._state[key])
    tampered["execution_authority"] = True
    state._state[key] = tampered
    with pytest.raises(ValueError, match="execution authority"):
        await store.get(_CANDIDATE, "decision-one")

    class BrokenAuditStore(InMemoryStateStore):
        def _append_audit_locked(self, entry: Mapping[str, Any]) -> None:
            raise RuntimeError("audit unavailable")

    failed = BrokenAuditStore()
    with pytest.raises(RuntimeError, match="audit unavailable"):
        await StateStoreMscpDecisionContext(failed).record(context)
    assert not failed._state
    assert len(tuple(failed.audit_entries)) == 0


async def test_forged_ready_projection_cannot_enter_the_durable_record() -> None:
    state = InMemoryStateStore()
    forged = replace(_context(*_all()[:-1]), disposition="ready", reasons=())
    with pytest.raises(ValueError, match="immutable projection"):
        await StateStoreMscpDecisionContext(state).record(forged)
    assert not state._state
    assert len(tuple(state.audit_entries)) == 0
