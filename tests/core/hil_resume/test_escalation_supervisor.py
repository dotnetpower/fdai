from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from fdai.core.hil_resume.escalation_supervisor import (
    EscalationDuty,
    EscalationPolicy,
    EscalationRung,
    HumanNonResponseSupervisor,
)
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.hil_channel import (
    HilApprovalReceipt,
    HilApprovalRequest,
    HilChannelError,
)
from fdai.shared.providers.testing.hil_channel import InMemoryHilChannel
from fdai.shared.providers.testing.state_store import InMemoryStateStore


class PrimaryIneligible:
    async def is_eligible(self, *, subject_ref: str, minimum_role: str) -> bool:
        return subject_ref != "primary-1"


class BlockingSendChannel(InMemoryHilChannel):
    def __init__(self) -> None:
        super().__init__()
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def send(self, request: HilApprovalRequest) -> HilApprovalReceipt:
        self.entered.set()
        await self.release.wait()
        return await super().send(request)


def _park(now: datetime) -> dict[str, object]:
    return {
        "status": "pending",
        "approval_id": "approval-1",
        "revision": 0,
        "action": {
            "action_id": "action-1",
            "action_type": "ops.restart-service",
            "target_resource_ref": "resource-1",
            "citing_rules": ["rule-1"],
        },
        "action_type": "ops.restart-service",
        "submitter_oid": "requester-1",
        "assignee_oid": None,
        "correlation_id": "correlation-1",
        "idempotency_key": "action-1",
        "request_fingerprint": "fingerprint-1",
        "approval_context": {
            "reasons": [],
            "blast_radius_summary": "one resource",
            "ttl_seconds": 1800,
            "expires_at": (now + timedelta(minutes=30)).isoformat(),
        },
    }


def _rungs() -> tuple[EscalationRung, ...]:
    return (
        EscalationRung("primary-1", EscalationDuty.PRIMARY),
        EscalationRung("backup-1", EscalationDuty.BACKUP),
        EscalationRung("maintainer-1", EscalationDuty.MAINTAINER, "Owner"),
    )


async def _supervisor(
    now: datetime,
    *,
    channel: InMemoryHilChannel | None = None,
) -> tuple[HumanNonResponseSupervisor, InMemoryStateStore, InMemoryHilChannel]:
    store = InMemoryStateStore()
    resolved_channel = channel or InMemoryHilChannel()
    supervisor = HumanNonResponseSupervisor(
        state_store=store,
        channel=resolved_channel,
        policy=EscalationPolicy(
            decision_timeout_seconds=60,
            overall_timeout_seconds=300,
            delivery_retry_seconds=10,
            scan_limit=20,
            mode=Mode.ENFORCE,
        ),
        clock=lambda: now,
    )
    parked = supervisor.attach(_park(now), rungs=_rungs(), now=now)
    await store.write_state("hil_park:approval-1", parked)
    return supervisor, store, resolved_channel


async def test_delivery_then_non_response_advances_once_under_concurrent_ticks() -> None:
    now = datetime(2026, 8, 1, tzinfo=UTC)
    supervisor, store, channel = await _supervisor(now)
    first = await supervisor.tick(at=now)
    assert first.delivered == 1
    assert len(channel.sent) == 1

    due = now + timedelta(seconds=61)
    results = await asyncio.gather(supervisor.tick(at=due), supervisor.tick(at=due))
    parked = await store.read_state("hil_park:approval-1")
    assert sum(item.advanced for item in results) == 1
    assert parked is not None
    assert parked["assignee_oid"] == "backup-1"
    assert parked["action"] == _park(now)["action"]


async def test_concurrent_initial_ticks_send_one_request() -> None:
    now = datetime(2026, 8, 1, tzinfo=UTC)
    channel = BlockingSendChannel()
    supervisor, _, _ = await _supervisor(now, channel=channel)

    first = asyncio.create_task(supervisor.tick(at=now))
    await channel.entered.wait()
    second = asyncio.create_task(supervisor.tick(at=now))
    await asyncio.sleep(0)
    channel.release.set()

    results = await asyncio.gather(first, second)
    assert len(channel.sent) == 1
    assert sum(item.delivered for item in results) == 1


async def test_delivery_failure_does_not_advance_human_rung() -> None:
    now = datetime(2026, 8, 1, tzinfo=UTC)
    channel = InMemoryHilChannel(
        send_error=HilChannelError("unavailable", approval_id="approval-1")
    )
    supervisor, store, _ = await _supervisor(now, channel=channel)

    result = await supervisor.tick(at=now)

    parked = await store.read_state("hil_park:approval-1")
    assert result.delivery_failed == 1
    assert result.advanced == 0
    assert parked is not None
    assert parked["assignee_oid"] == "primary-1"


async def test_overall_deadline_exhausts_to_audited_noop() -> None:
    now = datetime(2026, 8, 1, tzinfo=UTC)
    supervisor, store, channel = await _supervisor(now)

    result = await supervisor.tick(at=now + timedelta(seconds=301))

    parked = await store.read_state("hil_park:approval-1")
    assert result.exhausted == 1
    assert channel.sent == []
    assert parked is not None
    assert parked["status"] == "resolved"
    assert parked["decision"] == "timeout"
    assert any(entry["entry"].get("terminal_noop") is True for entry in store.audit_entries)


async def test_resolved_rejection_is_terminal_across_restart() -> None:
    now = datetime(2026, 8, 1, tzinfo=UTC)
    supervisor, store, channel = await _supervisor(now)
    parked = dict((await store.read_state("hil_park:approval-1")) or {})
    parked.update({"status": "resolved", "decision": "reject", "revision": 1})
    await store.write_state("hil_park:approval-1", parked)
    restarted = HumanNonResponseSupervisor(
        state_store=store,
        channel=channel,
        policy=supervisor.policy,
    )

    result = await restarted.tick(at=now + timedelta(hours=1))

    assert result.delivered == result.advanced == result.exhausted == 0
    assert channel.sent == []


async def test_role_loss_skips_to_backup_without_counting_human_silence() -> None:
    now = datetime(2026, 8, 1, tzinfo=UTC)
    store = InMemoryStateStore()
    channel = InMemoryHilChannel()
    supervisor = HumanNonResponseSupervisor(
        state_store=store,
        channel=channel,
        eligibility=PrimaryIneligible(),
        policy=EscalationPolicy(mode=Mode.ENFORCE),
        clock=lambda: now,
    )
    await store.write_state(
        "hil_park:approval-1",
        supervisor.attach(_park(now), rungs=_rungs(), now=now),
    )

    result = await supervisor.tick(at=now)

    parked = await store.read_state("hil_park:approval-1")
    assert result.advanced == 1
    assert parked is not None
    assert parked["assignee_oid"] == "backup-1"
    assert channel.sent == []


async def test_action_tamper_exhausts_without_dispatch() -> None:
    now = datetime(2026, 8, 1, tzinfo=UTC)
    supervisor, store, channel = await _supervisor(now)
    parked = dict((await store.read_state("hil_park:approval-1")) or {})
    parked["action"] = {**dict(parked["action"]), "target_resource_ref": "other-resource"}
    await store.write_state("hil_park:approval-1", parked)

    result = await supervisor.tick(at=now)

    held = await store.read_state("hil_park:approval-1")
    assert result.exhausted == 1
    assert channel.sent == []
    assert held is not None
    assert held["status"] == "resolved"


async def test_shadow_due_records_observation_without_rung_change() -> None:
    now = datetime(2026, 8, 1, tzinfo=UTC)
    store = InMemoryStateStore()
    channel = InMemoryHilChannel()
    supervisor = HumanNonResponseSupervisor(
        state_store=store,
        channel=channel,
        policy=EscalationPolicy(decision_timeout_seconds=60),
    )
    await store.write_state(
        "hil_park:approval-1",
        supervisor.attach(_park(now), rungs=_rungs(), now=now),
    )
    await supervisor.mark_delivered("approval-1", at=now)

    result = await supervisor.tick(at=now + timedelta(seconds=61))

    parked = await store.read_state("hil_park:approval-1")
    assert result.observed == 1
    assert result.advanced == 0
    assert parked is not None
    assert parked["assignee_oid"] == "primary-1"
    assert parked["status"] == "pending"
    assert channel.sent == []


async def test_shadow_pending_delivery_never_sends() -> None:
    now = datetime(2026, 8, 1, tzinfo=UTC)
    store = InMemoryStateStore()
    channel = InMemoryHilChannel()
    supervisor = HumanNonResponseSupervisor(state_store=store, channel=channel)
    await store.write_state(
        "hil_park:approval-1",
        supervisor.attach(_park(now), rungs=_rungs(), now=now),
    )

    result = await supervisor.tick(at=now)

    assert result.delivered == result.delivery_failed == 0
    assert channel.sent == []
