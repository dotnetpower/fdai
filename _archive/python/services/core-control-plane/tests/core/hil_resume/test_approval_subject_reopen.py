"""An operator can reopen a rejected subject; the rejection itself is never edited."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from fdai.core.hil_resume import RequestOutcome
from fdai.core.hil_resume.subject_index import ReopenOutcome, reopen_rejected_subject
from fdai.shared.providers.hil_channel import HilDecision

from tests.core.hil_resume.test_coordinator import (
    _APPROVER,
    _SUBMITTER,
    _action,
    _audit_kinds,
    _coordinator,
    _rule,
)

_T0 = datetime.now(UTC).replace(microsecond=0)


async def _propose(coordinator, n: int):  # type: ignore[no-untyped-def]
    coordinator._request_clock = lambda: _T0 + timedelta(minutes=n)
    action = _action().model_copy(
        update={
            "event_id": UUID(int=0x1000 + n),
            "action_id": UUID(int=0x2000 + n),
            "idempotency_key": f"inventory-snapshot:generation-{n}",
        }
    )
    return await coordinator.request_approval(
        action=action, rule=_rule(), submitter_oid=_SUBMITTER, correlation_id=f"corr-{n}"
    )


async def _rejected(coordinator):  # type: ignore[no-untyped-def]
    first = await _propose(coordinator, 0)
    await coordinator.resolve(
        approval_id=first.approval_id, decision=HilDecision.REJECT, approver_oid=_APPROVER
    )
    return first.approval_id


async def test_reopen_lets_the_next_proposal_park_a_linked_revision() -> None:
    coordinator, _, store, channel = _coordinator()
    rejected_id = await _rejected(coordinator)
    assert (await _propose(coordinator, 1)).outcome is RequestOutcome.REJECTED_SUBJECT
    before = await store.read_state(f"hil_park:{rejected_id}")

    outcome = await reopen_rejected_subject(
        store, approval_id=rejected_id, actor="operator@example.com", now=_T0
    )
    reopened = await _propose(coordinator, 2)

    assert outcome is ReopenOutcome.REOPENED
    assert reopened.outcome is RequestOutcome.PARKED
    parked: Any = await store.read_state(f"hil_park:{reopened.approval_id}")
    assert parked["previous_approval_id"] == rejected_id
    assert parked["lineage"] == 2
    assert await store.read_state(f"hil_park:{rejected_id}") == before
    assert "hil.subject.reopened" in _audit_kinds(store)
    assert len(channel.sent) == 2


async def test_reopen_is_one_shot_and_a_new_rejection_closes_the_subject_again() -> None:
    coordinator, _, store, _ = _coordinator()
    rejected_id = await _rejected(coordinator)
    await reopen_rejected_subject(store, approval_id=rejected_id, actor="op", now=_T0)

    again = await reopen_rejected_subject(store, approval_id=rejected_id, actor="op", now=_T0)
    second = await _propose(coordinator, 2)
    after_park = await reopen_rejected_subject(store, approval_id=rejected_id, actor="op", now=_T0)
    await coordinator.resolve(
        approval_id=second.approval_id, decision=HilDecision.REJECT, approver_oid=_APPROVER
    )

    assert again is ReopenOutcome.ALREADY_REOPENED
    assert after_park is ReopenOutcome.STALE
    assert (await _propose(coordinator, 3)).outcome is RequestOutcome.REJECTED_SUBJECT


async def test_reopen_refuses_what_is_not_a_current_rejection() -> None:
    coordinator, _, store, _ = _coordinator()
    open_request = await _propose(coordinator, 0)

    assert (
        await reopen_rejected_subject(store, approval_id="missing", actor="op", now=_T0)
        is ReopenOutcome.NOT_FOUND
    )
    assert (
        await reopen_rejected_subject(
            store, approval_id=open_request.approval_id, actor="op", now=_T0
        )
        is ReopenOutcome.NOT_REJECTED
    )
    with pytest.raises(ValueError, match="actor"):
        await reopen_rejected_subject(
            store, approval_id=open_request.approval_id, actor=" ", now=_T0
        )


async def test_dry_run_reports_without_writing() -> None:
    coordinator, _, store, _ = _coordinator()
    rejected_id = await _rejected(coordinator)

    outcome = await reopen_rejected_subject(
        store, approval_id=rejected_id, actor="op", now=_T0, apply=False
    )

    assert outcome is ReopenOutcome.REOPENED
    assert "hil.subject.reopened" not in _audit_kinds(store)
    assert (await _propose(coordinator, 1)).outcome is RequestOutcome.REJECTED_SUBJECT
