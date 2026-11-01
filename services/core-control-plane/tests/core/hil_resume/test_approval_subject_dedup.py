"""A subject has at most one open approval; repeated observations update a summary instead."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from fdai.core.hil_resume import RequestOutcome
from fdai.core.hil_resume.subject_index import subject_state_key
from fdai.shared.providers.hil_channel import HilDecision

from tests.core.hil_resume.test_coordinator import (
    _APPROVER,
    _SUBMITTER,
    _action,
    _audit_kinds,
    _coordinator,
    _rule,
)

# Resolution reads the real clock, so the scenario is anchored to it.
_T0 = datetime.now(UTC).replace(microsecond=0)


def _observation(n: int, **changes: Any):  # type: ignore[no-untyped-def]
    """The same condition seen again: only per-event values differ."""
    update = {
        "event_id": UUID(int=0x1000 + n),
        "action_id": UUID(int=0x2000 + n),
        "idempotency_key": f"inventory-snapshot:generation-{n}",
        "created_at": _T0 + timedelta(minutes=n),
        **changes,
    }
    return _action().model_copy(update=update)


async def _propose(coordinator, n: int, **action_changes: Any):  # type: ignore[no-untyped-def]
    return await coordinator.request_approval(
        action=_observation(n, **action_changes),
        rule=_rule(),
        submitter_oid=_SUBMITTER,
        correlation_id=f"corr-{n}",
        ttl_seconds=1800,
    )


def _at(coordinator, moment: datetime) -> None:  # type: ignore[no-untyped-def]
    coordinator._request_clock = lambda: moment


async def _parks(store) -> list[dict[str, Any]]:  # type: ignore[no-untyped-def]
    return [dict(item) for item in await store.read_states("hil_park:", limit=100)]


async def _subject(store) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    records = await store.read_states("hil_subject:", limit=10)
    assert len(records) == 1
    return dict(records[0])


async def test_repeated_observations_share_one_open_request_and_one_notification() -> None:
    coordinator, _, store, channel = _coordinator()
    _at(coordinator, _T0)
    first = await _propose(coordinator, 0)

    results = []
    for n in range(1, 9):
        _at(coordinator, _T0 + timedelta(minutes=n))
        results.append(await _propose(coordinator, n))

    assert first.outcome is RequestOutcome.PARKED
    assert {result.outcome for result in results} == {RequestOutcome.ALREADY_OPEN}
    assert {result.approval_id for result in results} == {first.approval_id}
    assert len(await _parks(store)) == 1
    assert len(channel.sent) == 1
    summary = await _subject(store)
    assert summary["observed_count"] == 9
    assert summary["approval_id"] == first.approval_id
    assert len(summary["recent_events"]) == 5
    assert summary["recent_events"][-1]["event_id"] == str(UUID(int=0x1008))


async def test_concurrent_proposals_open_exactly_one_request() -> None:
    coordinator, _, store, channel = _coordinator()
    _at(coordinator, _T0)

    results = await asyncio.gather(*(_propose(coordinator, n) for n in range(12)))

    outcomes = [result.outcome for result in results]
    assert outcomes.count(RequestOutcome.PARKED) == 1
    assert outcomes.count(RequestOutcome.ALREADY_OPEN) == 11
    assert len(await _parks(store)) == 1
    assert len(channel.sent) == 1


async def test_a_different_target_or_content_is_a_different_subject() -> None:
    coordinator, _, store, _ = _coordinator()
    _at(coordinator, _T0)

    base = await _propose(coordinator, 0)
    other_target = await _propose(coordinator, 1, target_resource_ref="resource:example/rg/stg2")
    other_params = await _propose(coordinator, 2, params={"tag_value": "team-b"})

    assert {base.outcome, other_target.outcome, other_params.outcome} == {RequestOutcome.PARKED}
    assert len({base.approval_id, other_target.approval_id, other_params.approval_id}) == 3
    assert len(await _parks(store)) == 3


async def test_an_expired_unanswered_request_reopens_as_the_next_lineage_revision() -> None:
    coordinator, _, store, channel = _coordinator()
    _at(coordinator, _T0)
    first = await _propose(coordinator, 0)

    _at(coordinator, _T0 + timedelta(minutes=45))
    reopened = await _propose(coordinator, 1)

    assert reopened.outcome is RequestOutcome.PARKED
    assert reopened.approval_id != first.approval_id
    parked = await store.read_state(f"hil_park:{reopened.approval_id}")
    assert parked is not None
    assert parked["lineage"] == 2
    assert parked["previous_approval_id"] == first.approval_id
    summary = await _subject(store)
    assert summary["approval_id"] == reopened.approval_id
    assert summary["lineage"] == 2
    assert summary["lineage_refs"][0]["approval_id"] == first.approval_id
    assert summary["lineage_refs"][0]["ended"] == "expired"
    assert len(channel.sent) == 2
    assert await store.read_state(f"hil_park:{first.approval_id}") is not None


async def test_a_timed_out_request_reopens_and_records_why_it_ended() -> None:
    coordinator, _, store, _ = _coordinator()
    _at(coordinator, _T0)
    first = await _propose(coordinator, 0)
    await coordinator.resolve(
        approval_id=first.approval_id, decision=HilDecision.TIMEOUT, approver_oid="system"
    )

    _at(coordinator, _T0 + timedelta(minutes=2))
    reopened = await _propose(coordinator, 1)

    assert reopened.outcome is RequestOutcome.PARKED
    assert (await _subject(store))["lineage_refs"][0]["ended"] == "timeout"


async def test_a_rejected_subject_stays_closed_and_is_audited_once() -> None:
    coordinator, _, store, channel = _coordinator()
    _at(coordinator, _T0)
    first = await _propose(coordinator, 0)
    await coordinator.resolve(
        approval_id=first.approval_id, decision=HilDecision.REJECT, approver_oid=_APPROVER
    )

    outcomes = []
    for n in range(1, 5):
        _at(coordinator, _T0 + timedelta(hours=n))
        outcomes.append((await _propose(coordinator, n)).outcome)

    assert set(outcomes) == {RequestOutcome.REJECTED_SUBJECT}
    assert len(await _parks(store)) == 1
    assert len(channel.sent) == 1
    suppressed = [
        kind for kind in _audit_kinds(store) if kind == "hil.request.suppressed_after_rejection"
    ]
    assert len(suppressed) == 1
    assert (await _subject(store))["observed_count"] == 5


async def test_an_approved_subject_that_recurs_gets_a_new_linked_request() -> None:
    coordinator, _, store, _ = _coordinator()
    _at(coordinator, _T0)
    first = await _propose(coordinator, 0)
    await coordinator.resolve(
        approval_id=first.approval_id, decision=HilDecision.APPROVE, approver_oid=_APPROVER
    )

    _at(coordinator, _T0 + timedelta(minutes=10))
    again = await _propose(coordinator, 1)

    assert again.outcome is RequestOutcome.PARKED
    parked = await store.read_state(f"hil_park:{again.approval_id}")
    assert parked is not None
    assert parked["previous_approval_id"] == first.approval_id
    assert (await _subject(store))["lineage_refs"][0]["ended"] == "approve"


async def test_an_in_flight_claim_is_honoured_and_a_stale_one_is_taken_over() -> None:
    coordinator, _, store, _ = _coordinator()
    _at(coordinator, _T0)
    first = await _propose(coordinator, 0)
    # Simulate a crash between the claim and the park write.
    await store.delete_state(f"hil_park:{first.approval_id}")

    _at(coordinator, _T0 + timedelta(seconds=20))
    in_flight = await _propose(coordinator, 1)
    _at(coordinator, _T0 + timedelta(minutes=5))
    recovered = await _propose(coordinator, 2)

    assert in_flight.outcome is RequestOutcome.ALREADY_OPEN
    assert recovered.outcome is RequestOutcome.PARKED
    assert (await _subject(store))["lineage_refs"][0]["ended"] == "never_parked"


async def test_an_explicit_approval_id_is_not_deduplicated() -> None:
    coordinator, _, store, _ = _coordinator()
    _at(coordinator, _T0)

    first = await coordinator.request_approval(
        action=_observation(0),
        rule=_rule(),
        submitter_oid=_SUBMITTER,
        correlation_id="corr-0",
        approval_id="named-1",
    )
    second = await coordinator.request_approval(
        action=_observation(1),
        rule=_rule(),
        submitter_oid=_SUBMITTER,
        correlation_id="corr-1",
        approval_id="named-2",
    )

    assert {first.outcome, second.outcome} == {RequestOutcome.PARKED}
    assert await store.read_state(subject_state_key("unused")) is None
    assert len(await _parks(store)) == 2


@pytest.mark.parametrize("field", ["event_id", "action_id", "idempotency_key", "created_at"])
async def test_per_event_values_never_split_a_subject(field: str) -> None:
    coordinator, _, store, _ = _coordinator()
    _at(coordinator, _T0)
    await _propose(coordinator, 0)

    result = await _propose(coordinator, 1)

    assert field in _observation(1).model_dump()
    assert result.outcome is RequestOutcome.ALREADY_OPEN
    assert len(await _parks(store)) == 1


async def test_baseline_sweep_does_not_reopen_expired_or_timed_out_subject() -> None:
    coordinator, _, store, channel = _coordinator()
    _at(coordinator, _T0)
    first = await coordinator.request_approval(
        action=_observation(0),
        rule=_rule(),
        submitter_oid=_SUBMITTER,
        correlation_id="corr-0",
        ttl_seconds=1800,
        reopen_on_expiry=False,
    )
    assert first.outcome is RequestOutcome.PARKED

    _at(coordinator, _T0 + timedelta(minutes=45))
    expired_repeat = await coordinator.request_approval(
        action=_observation(1),
        rule=_rule(),
        submitter_oid=_SUBMITTER,
        correlation_id="corr-1",
        ttl_seconds=1800,
        reopen_on_expiry=False,
    )
    assert expired_repeat.outcome is RequestOutcome.ALREADY_OPEN
    assert expired_repeat.approval_id == first.approval_id

    await coordinator.resolve(
        approval_id=first.approval_id, decision=HilDecision.TIMEOUT, approver_oid="system"
    )
    _at(coordinator, _T0 + timedelta(minutes=47))
    timed_out_repeat = await coordinator.request_approval(
        action=_observation(2),
        rule=_rule(),
        submitter_oid=_SUBMITTER,
        correlation_id="corr-2",
        ttl_seconds=1800,
        reopen_on_expiry=False,
    )
    assert timed_out_repeat.outcome is RequestOutcome.ALREADY_OPEN
    assert timed_out_repeat.approval_id == first.approval_id
    assert len(await _parks(store)) == 1
    assert len(channel.sent) == 1
