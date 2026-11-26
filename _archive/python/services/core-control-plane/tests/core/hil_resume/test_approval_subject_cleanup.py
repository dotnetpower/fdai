"""Cleanup supersedes older duplicate pending approvals and keeps one open request per subject."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fdai.core.hil_resume import RequestOutcome
from fdai.core.hil_resume.subject_cleanup import (
    SUPERSEDED_STATUS,
    apply_duplicate_cleanup,
    plan_duplicate_cleanup,
)

from tests.core.hil_resume.test_coordinator import _SUBMITTER, _action, _coordinator, _rule

_T0 = datetime.now(UTC).replace(microsecond=0)


async def _legacy_park(coordinator, name: str, n: int, **changes):  # type: ignore[no-untyped-def]
    """Park the way the request path did before the subject index: one approval per event."""
    coordinator._request_clock = lambda: _T0 + timedelta(minutes=n)
    action = _action().model_copy(
        update={
            "event_id": UUID(int=0x1000 + n),
            "action_id": UUID(int=0x2000 + n),
            "idempotency_key": f"inventory-snapshot:generation-{n}",
            **changes,
        }
    )
    await coordinator.request_approval(
        action=action,
        rule=_rule(),
        submitter_oid=_SUBMITTER,
        correlation_id=f"corr-{n}",
        approval_id=name,
    )


async def test_plan_is_read_only_and_groups_by_subject() -> None:
    coordinator, _, store, _ = _coordinator()
    for n in range(4):
        await _legacy_park(coordinator, f"dup-{n}", n)
    await _legacy_park(coordinator, "other", 5, target_resource_ref="resource:example/rg/stg2")
    before = [dict(item) for item in await store.read_states("hil_park:", limit=50)]

    plan = await plan_duplicate_cleanup(store)

    assert (plan.open_total, plan.subject_total, plan.superseded_total) == (5, 2, 3)
    assert plan.groups[0].survivor_id == "dup-3"
    assert set(plan.groups[0].superseded_ids) == {"dup-0", "dup-1", "dup-2"}
    assert [dict(item) for item in await store.read_states("hil_park:", limit=50)] == before


async def test_apply_links_older_requests_keeps_history_and_seeds_the_index() -> None:
    coordinator, _, store, _ = _coordinator()
    for n in range(4):
        await _legacy_park(coordinator, f"dup-{n}", n)
    plan = await plan_duplicate_cleanup(store)

    result = await apply_duplicate_cleanup(store, plan, now=_T0 + timedelta(hours=1))

    assert (result.superseded, result.skipped_changed, result.subjects_seeded) == (3, 0, 1)
    survivor = await store.read_state("hil_park:dup-3")
    assert survivor is not None and survivor["status"] == "pending"
    for name in ("dup-0", "dup-1", "dup-2"):
        park = await store.read_state(f"hil_park:{name}")
        assert park is not None
        assert park["status"] == SUPERSEDED_STATUS
        assert park["superseded_by"] == "dup-3"
        assert park["action"]["event_id"]
    summary = (await store.read_states("hil_subject:", limit=5))[0]
    assert summary["approval_id"] == "dup-3"
    assert summary["observed_count"] == 4
    assert (await plan_duplicate_cleanup(store)).superseded_total == 0


async def test_a_new_proposal_after_cleanup_lands_on_the_survivor() -> None:
    coordinator, _, store, channel = _coordinator()
    for n in range(3):
        await _legacy_park(coordinator, f"dup-{n}", n)
    await apply_duplicate_cleanup(
        store, await plan_duplicate_cleanup(store), now=_T0 + timedelta(minutes=3)
    )
    sent = len(channel.sent)

    coordinator._request_clock = lambda: _T0 + timedelta(minutes=4)
    result = await coordinator.request_approval(
        action=_action().model_copy(
            update={
                "event_id": UUID(int=0x1999),
                "action_id": UUID(int=0x2999),
                "idempotency_key": "inventory-snapshot:generation-9",
            }
        ),
        rule=_rule(),
        submitter_oid=_SUBMITTER,
        correlation_id="corr-9",
    )

    assert result.outcome is RequestOutcome.ALREADY_OPEN
    assert result.approval_id == "dup-2"
    assert len(channel.sent) == sent


async def test_apply_skips_a_request_that_was_decided_in_the_meantime() -> None:
    coordinator, _, store, _ = _coordinator()
    for n in range(3):
        await _legacy_park(coordinator, f"dup-{n}", n)
    plan = await plan_duplicate_cleanup(store)
    coordinator._request_clock = lambda: _T0 + timedelta(minutes=5)
    await coordinator.resolve(
        approval_id="dup-0", decision="reject", approver_oid="alice@example.com"
    )

    result = await apply_duplicate_cleanup(store, plan, now=_T0 + timedelta(minutes=6))

    assert (result.superseded, result.skipped_changed) == (1, 1)
    decided = await store.read_state("hil_park:dup-0")
    assert decided is not None and decided["status"] == "resolved"


async def test_unreadable_parks_are_left_untouched_and_counted() -> None:
    coordinator, _, store, _ = _coordinator()
    await _legacy_park(coordinator, "ok", 0)
    await store.write_state("hil_park:legacy", {"status": "pending", "approval_id": "legacy"})

    plan = await plan_duplicate_cleanup(store)

    assert plan.unrecognized == 1
    assert plan.superseded_total == 0
