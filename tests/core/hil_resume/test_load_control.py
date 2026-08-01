"""Approval load grouping, quiet-hour, fatigue, and reminder invariants."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from fdai.core.hil_resume.load_control import (
    ApprovalDispatchMode,
    ApprovalLoadController,
    ApprovalLoadPolicy,
    ApprovalReminderDispatcher,
)
from fdai.shared.providers.hil_channel import HilChannelError
from fdai.shared.providers.testing.hil_channel import InMemoryHilChannel
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_BASE = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)


def _policy(**overrides: object) -> ApprovalLoadPolicy:
    value: dict[str, object] = {
        "schema_version": "1.0.0",
        "group_window_seconds": 300,
        "max_pending_per_assignee": 3,
        "reminder_offsets_seconds": [600, 1200],
        "quiet_hours_utc": {"start": "22:00", "end": "06:00"},
        "urgent_severities": ["critical"],
        "scan_limit": 1000,
        "worker_interval_seconds": 30,
    }
    value.update(overrides)
    return ApprovalLoadPolicy.from_mapping(value)


def _park(
    approval_id: str,
    *,
    at: datetime,
    action_type: str = "ops.restart-service",
    assignee: str = "approver-one",
    ttl_seconds: int = 7200,
) -> dict[str, object]:
    return {
        "status": "pending",
        "approval_id": approval_id,
        "action_type": action_type,
        "assignee_oid": assignee,
        "submitter_oid": "submitter-one",
        "correlation_id": f"corr-{approval_id}",
        "idempotency_key": f"idem-{approval_id}",
        "parked_at": at.isoformat(),
        "action": {
            "action_id": f"action-{approval_id}",
            "target_resource_ref": f"resource:{approval_id}",
            "citing_rules": ["rule-one"],
        },
        "approval_context": {
            "reasons": ["risk gate requires approval"],
            "blast_radius_summary": "one resource",
            "ttl_seconds": ttl_seconds,
            "expires_at": (at + timedelta(seconds=ttl_seconds)).isoformat(),
        },
    }


async def _store_park(store: InMemoryStateStore, park: dict[str, object]) -> None:
    await store.write_state(f"hil_park:{park['approval_id']}", park)


def test_policy_rejects_unbounded_or_noncritical_configuration() -> None:
    with pytest.raises(ValueError, match="at most 4"):
        _policy(reminder_offsets_seconds=[1, 2, 3, 4, 5])
    with pytest.raises(ValueError, match="include critical"):
        _policy(urgent_severities=["high"])
    with pytest.raises(ValueError, match="unknown"):
        _policy(unknown=True)


def test_quiet_hours_wrap_midnight() -> None:
    policy = _policy()

    assert policy.in_quiet_hours(datetime(2026, 7, 25, 23, 0, tzinfo=UTC))
    assert policy.in_quiet_hours(datetime(2026, 7, 26, 5, 59, tzinfo=UTC))
    assert not policy.in_quiet_hours(datetime(2026, 7, 26, 6, 0, tzinfo=UTC))


async def test_critical_always_sends_during_quiet_hours() -> None:
    now = datetime(2026, 7, 25, 23, 0, tzinfo=UTC)
    store = InMemoryStateStore()
    parked = _park("critical-one", at=now)
    await _store_park(store, parked)
    controller = ApprovalLoadController(state_store=store, policy=_policy(), clock=lambda: now)

    plan = await controller.plan(parked, severity="critical")

    assert plan.mode is ApprovalDispatchMode.SEND_NOW
    assert len(plan.due_at) == 2


async def test_quiet_grouping_and_fatigue_never_remove_parks() -> None:
    now = datetime(2026, 7, 25, 23, 0, tzinfo=UTC)
    store = InMemoryStateStore()
    controller = ApprovalLoadController(state_store=store, policy=_policy(), clock=lambda: now)
    modes = []
    for index in range(6):
        parked = _park(f"quiet-{index}", at=now)
        await _store_park(store, parked)
        modes.append((await controller.plan(parked, severity="medium")).mode)

    assert modes[0] is ApprovalDispatchMode.DEFERRED
    assert modes.count(ApprovalDispatchMode.DEFERRED) == 2
    assert modes.count(ApprovalDispatchMode.GROUPED) == 4
    parks = await store.read_states("hil_park:", limit=100)
    plans = await store.read_states("hil_load_plan:", limit=100)
    assert len(parks) == 6
    assert len(plans) == 6
    assert any(item.get("overloaded") is True for item in plans)


async def test_policy_simulation_never_drops_or_defers_critical() -> None:
    now = datetime(2026, 7, 25, 23, 30, tzinfo=UTC)
    store = InMemoryStateStore()
    controller = ApprovalLoadController(state_store=store, policy=_policy(), clock=lambda: now)
    critical_ids = set()
    for index in range(100):
        approval_id = f"simulation-{index}"
        severity = "critical" if index % 10 == 0 else "low"
        if severity == "critical":
            critical_ids.add(approval_id)
        parked = _park(approval_id, at=now, action_type=f"ops.action-{index % 4}")
        await _store_park(store, parked)
        plan = await controller.plan(parked, severity=severity)
        if severity == "critical":
            assert plan.mode is ApprovalDispatchMode.SEND_NOW

    parks = await store.read_states("hil_park:", limit=200)
    plans = await store.read_states("hil_load_plan:", limit=200)
    assert len(parks) == 100
    assert len(plans) == 100
    urgent_plans = {item["approval_id"] for item in plans if item["severity"] == "critical"}
    assert urgent_plans == critical_ids
    snapshot = await controller.snapshot()
    assert snapshot.total_plans == 100
    assert snapshot.urgent_plans == 10


async def test_due_reminders_are_attempted_once_across_repeated_drains() -> None:
    now = _BASE
    current = now
    store = InMemoryStateStore()
    channel = InMemoryHilChannel()
    policy = _policy()
    parked = _park("reminder-one", at=now)
    await _store_park(store, parked)
    controller = ApprovalLoadController(state_store=store, policy=policy, clock=lambda: current)
    plan = await controller.plan(parked, severity="high")
    assert plan.mode is ApprovalDispatchMode.SEND_NOW
    dispatcher = ApprovalReminderDispatcher(
        state_store=store,
        channel=channel,
        policy=policy,
        clock=lambda: current,
    )

    current = now + timedelta(seconds=1300)
    assert await dispatcher.drain_due() == 2
    assert await dispatcher.drain_due() == 0
    assert len(channel.sent) == 2
    assert {item.metadata["approval_reminder_index"] for item in channel.sent} == {"0", "1"}


async def test_deferred_initial_dispatch_waits_until_quiet_end() -> None:
    now = datetime(2026, 7, 25, 23, 0, tzinfo=UTC)
    current = now
    store = InMemoryStateStore()
    channel = InMemoryHilChannel()
    policy = _policy()
    parked = _park("deferred-one", at=now, ttl_seconds=30_000)
    await _store_park(store, parked)
    controller = ApprovalLoadController(state_store=store, policy=policy, clock=lambda: current)
    plan = await controller.plan(parked, severity="medium")
    deliveries: list[tuple[str, datetime]] = []

    async def observe_delivery(approval_id: str, delivered_at: datetime) -> None:
        deliveries.append((approval_id, delivered_at))

    dispatcher = ApprovalReminderDispatcher(
        state_store=store,
        channel=channel,
        policy=policy,
        clock=lambda: current,
        delivery_observer=observe_delivery,
    )

    assert plan.mode is ApprovalDispatchMode.DEFERRED
    assert await dispatcher.drain_due() == 0
    current = datetime(2026, 7, 26, 6, 0, tzinfo=UTC)
    assert await dispatcher.drain_due() == 1
    assert channel.sent[0].metadata["approval_load_mode"] == "deferred_initial"
    assert deliveries == [("deferred-one", current)]


async def test_grouped_approvals_emit_one_anchor_digest_after_window() -> None:
    current = _BASE
    store = InMemoryStateStore()
    channel = InMemoryHilChannel()
    policy = _policy(max_pending_per_assignee=10)
    controller = ApprovalLoadController(state_store=store, policy=policy, clock=lambda: current)
    plans = []
    for index in range(3):
        parked = _park(f"grouped-{index}", at=current)
        await _store_park(store, parked)
        plans.append(await controller.plan(parked, severity="medium"))
    dispatcher = ApprovalReminderDispatcher(
        state_store=store,
        channel=channel,
        policy=policy,
        clock=lambda: current,
    )

    assert [plan.mode for plan in plans] == [
        ApprovalDispatchMode.SEND_NOW,
        ApprovalDispatchMode.GROUPED,
        ApprovalDispatchMode.GROUPED,
    ]
    assert all(len(plan.due_at) == 1 for plan in plans[1:])
    assert await dispatcher.drain_due() == 0

    current = _BASE + timedelta(seconds=policy.group_window_seconds)
    assert await dispatcher.drain_due() == 1
    assert await dispatcher.drain_due() == 0
    assert len(channel.sent) == 1
    assert channel.sent[0].approval_id == "grouped-0"
    assert channel.sent[0].metadata["approval_load_mode"] == "grouped_digest"
    assert channel.sent[0].metadata["approval_group_size"] == "3"
    assert len(await store.read_states("hil_park:", limit=10)) == 3


async def test_quiet_group_uses_one_dispatch_for_deferred_anchor_and_members() -> None:
    current = datetime(2026, 7, 25, 23, 0, tzinfo=UTC)
    store = InMemoryStateStore()
    channel = InMemoryHilChannel()
    policy = _policy(max_pending_per_assignee=10)
    controller = ApprovalLoadController(state_store=store, policy=policy, clock=lambda: current)
    for index in range(3):
        parked = _park(f"quiet-group-{index}", at=current, ttl_seconds=30_000)
        await _store_park(store, parked)
        await controller.plan(parked, severity="medium")
    dispatcher = ApprovalReminderDispatcher(
        state_store=store,
        channel=channel,
        policy=policy,
        clock=lambda: current,
    )

    current = datetime(2026, 7, 26, 6, 0, tzinfo=UTC)
    assert await dispatcher.drain_due() == 1
    assert len(channel.sent) == 1
    assert channel.sent[0].approval_id == "quiet-group-0"
    assert channel.sent[0].metadata["approval_load_mode"] == "grouped_digest"
    assert channel.sent[0].metadata["approval_group_size"] == "3"


async def test_failed_reminder_does_not_retry_or_remove_pending() -> None:
    now = _BASE
    current = now
    store = InMemoryStateStore()
    error = HilChannelError("unavailable", approval_id="failure-one")
    channel = InMemoryHilChannel(send_error=error)
    policy = _policy(reminder_offsets_seconds=[1])
    parked = _park("failure-one", at=now)
    await _store_park(store, parked)
    controller = ApprovalLoadController(state_store=store, policy=policy, clock=lambda: current)
    await controller.plan(parked, severity="high")
    dispatcher = ApprovalReminderDispatcher(
        state_store=store,
        channel=channel,
        policy=policy,
        clock=lambda: current,
    )

    current = now + timedelta(seconds=2)
    assert await dispatcher.drain_due() == 1
    assert await dispatcher.drain_due() == 0
    assert await store.read_state("hil_park:failure-one") is not None
    assert channel.sent == []


async def test_expired_park_is_atomically_reaped_once_across_workers() -> None:
    current = _BASE + timedelta(seconds=10)
    store = InMemoryStateStore()
    policy = _policy()
    parked = _park("expired-one", at=_BASE, ttl_seconds=5)
    await _store_park(store, parked)
    first = ApprovalReminderDispatcher(
        state_store=store,
        channel=InMemoryHilChannel(),
        policy=policy,
        clock=lambda: current,
    )
    second = ApprovalReminderDispatcher(
        state_store=store,
        channel=InMemoryHilChannel(),
        policy=policy,
        clock=lambda: current,
    )

    results = await asyncio.gather(first.expire_due(), second.expire_due())

    assert sum(results) == 1
    reaped = await store.read_state("hil_park:expired-one")
    assert reaped is not None
    assert reaped["status"] == "resolved"
    assert reaped["decision"] == "timeout"
    assert reaped["approver_oid"] == "system:approval-expiry"
    assert reaped["revision"] == 1
    timeout_audits = [
        item for item in store.audit_entries if item["entry"].get("action_kind") == "hil.timeout"
    ]
    assert len(timeout_audits) == 1


async def test_malformed_expiry_fails_closed_to_timeout() -> None:
    current = _BASE
    store = InMemoryStateStore()
    parked = _park("malformed-expiry", at=current)
    parked["approval_context"] = {
        **parked["approval_context"],  # type: ignore[dict-item]
        "expires_at": "not-a-timestamp",
    }
    await _store_park(store, parked)
    dispatcher = ApprovalReminderDispatcher(
        state_store=store,
        channel=InMemoryHilChannel(),
        policy=_policy(),
        clock=lambda: current,
    )

    assert await dispatcher.expire_due() == 1
    reaped = await store.read_state("hil_park:malformed-expiry")
    assert reaped is not None
    assert reaped["decision"] == "timeout"
