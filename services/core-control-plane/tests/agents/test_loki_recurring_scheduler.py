"""Loki recurring chaos scheduler regressions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.loki_scheduling import ChaosScheduleConfig
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.loki import _MAX_HELD_PROPOSALS, _SCHEDULED_PREFIX, ChaosProposal, Loki
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_NOW = datetime(2026, 10, 1, 2, 0, tzinfo=UTC)


def _complete_schedule(*, schedule_id: str = "weekly-dr") -> ChaosScheduleConfig:
    return ChaosScheduleConfig(
        schedule_id=schedule_id,
        cadence=timedelta(hours=1),
        targets=("resource-chaos",),
        causal_hypothesis_ref="hypothesis:latency-cascade",
        refutation_query_ref="query:no-cascade",
        impact_envelope_id="impact:bounded",
        recovery_plan_id="recovery:ready",
        dry_run_receipt="dry-run:ok",
        start_at=_NOW - timedelta(hours=2),
    )


async def test_loki_recurring_scheduler_publishes_one_always_hil_window() -> None:
    bus = InMemoryBus(registry=load_pantheon(), isolate_handlers=False)
    store = InMemoryStateStore()
    loki = Loki(
        bus=bus,
        state_store=store,
        clock=lambda: _NOW,
        recurring_schedule=_complete_schedule(),
    )

    await loki.maintenance_tick()
    await loki.maintenance_tick()

    (proposal,) = (message.payload for message in bus.messages_on("object.chaos-experiment"))
    assert proposal["action_type"] == "tool.run-chaos-experiment"
    assert proposal["targets"] == ["resource-chaos"]
    assert proposal["human_approval_required"] is True
    assert proposal["dry_run_receipt"] == "dry-run:ok"
    assert loki.behavior_snapshot()["chaos_scheduler:published"] == 1
    assert loki.behavior_snapshot()["chaos_scheduler:duplicate_window"] == 1


class _FailOnceAfterWindowClaimLoki(Loki):
    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.failed_once = False

    async def propose_experiment(
        self,
        *,
        experiment_id: str,
        action_type: str,
        targets: tuple[str, ...],
        correlation_id: str = "",
        causal_hypothesis_ref: str = "",
        refutation_query_ref: str = "",
        impact_envelope_id: str = "",
        recovery_plan_id: str = "",
        dry_run_receipt: str = "",
    ) -> ChaosProposal:
        if not self.failed_once:
            self.failed_once = True
            raise RuntimeError("synthetic publish-path failure")
        return await super().propose_experiment(
            experiment_id=experiment_id,
            action_type=action_type,
            targets=targets,
            correlation_id=correlation_id,
            causal_hypothesis_ref=causal_hypothesis_ref,
            refutation_query_ref=refutation_query_ref,
            impact_envelope_id=impact_envelope_id,
            recovery_plan_id=recovery_plan_id,
            dry_run_receipt=dry_run_receipt,
        )


async def test_loki_recurring_scheduler_resumes_claimed_window_after_exception() -> None:
    bus = InMemoryBus(registry=load_pantheon(), isolate_handlers=False)
    loki = _FailOnceAfterWindowClaimLoki(
        bus=bus,
        state_store=InMemoryStateStore(),
        clock=lambda: _NOW,
        recurring_schedule=_complete_schedule(schedule_id="recover-claimed"),
    )

    try:
        await loki.maintenance_tick()
    except RuntimeError as exc:
        assert str(exc) == "synthetic publish-path failure"

    await loki.maintenance_tick()

    (proposal,) = (message.payload for message in bus.messages_on("object.chaos-experiment"))
    assert proposal["targets"] == ["resource-chaos"]
    assert loki.behavior_snapshot()["chaos_scheduler:claimed_window_resumed"] == 1
    assert loki.behavior_snapshot()["chaos_scheduler:published"] == 1


async def test_loki_recurring_scheduler_holds_expired_claimed_window_after_exception() -> None:
    bus = InMemoryBus(registry=load_pantheon(), isolate_handlers=False)
    current = _NOW
    loki = _FailOnceAfterWindowClaimLoki(
        bus=bus,
        state_store=InMemoryStateStore(),
        clock=lambda: current,
        reservation_ttl=timedelta(minutes=5),
        recurring_schedule=_complete_schedule(schedule_id="expire-claimed"),
    )

    try:
        await loki.maintenance_tick()
    except RuntimeError as exc:
        assert str(exc) == "synthetic publish-path failure"
    current = _NOW + timedelta(minutes=6)

    await loki.maintenance_tick()

    assert bus.messages_on("object.chaos-experiment") == []
    assert loki.behavior_snapshot()["chaos_scheduler:claimed_window_expired"] == 1
    assert loki.behavior_snapshot()["chaos_scheduler:duplicate_window"] == 1


async def test_loki_recurring_scheduler_holds_incomplete_or_unbound_state() -> None:
    loki = Loki(clock=lambda: _NOW)

    await loki.maintenance_tick()

    assert loki.behavior_snapshot()["chaos_scheduler:unbound"] == 1
    health = loki.health()
    assert health["ingress"]["recurring_scheduler"] == "disabled"

    bus = InMemoryBus(registry=load_pantheon(), isolate_handlers=False)
    incomplete = Loki(
        bus=bus,
        state_store=InMemoryStateStore(),
        clock=lambda: _NOW,
        recurring_schedule=ChaosScheduleConfig(
            schedule_id="incomplete",
            cadence=timedelta(hours=1),
            targets=("resource-chaos",),
            start_at=_NOW - timedelta(hours=1),
        ),
    )

    await incomplete.maintenance_tick()

    assert bus.messages_on("object.chaos-experiment") == []
    assert incomplete.behavior_snapshot()["chaos_scheduler:incomplete_evidence"] == 1


async def test_loki_recurring_scheduler_records_hold_when_blast_radius_is_full() -> None:
    bus = InMemoryBus(registry=load_pantheon(), isolate_handlers=False)
    loki = Loki(
        bus=bus,
        blast_radius_cap=1,
        state_store=InMemoryStateStore(),
        clock=lambda: _NOW,
        recurring_schedule=_complete_schedule(schedule_id="blocked-window"),
    )
    first = await loki.propose_experiment(
        experiment_id="already-running",
        action_type="tool.run-chaos-experiment",
        targets=("resource-chaos",),
        correlation_id="already-running",
        causal_hypothesis_ref="hypothesis:existing",
        refutation_query_ref="query:existing",
        impact_envelope_id="impact:existing",
        recovery_plan_id="recovery:existing",
        dry_run_receipt="dry-run:existing",
    )
    assert first.accepted

    await loki.maintenance_tick()

    assert len(bus.messages_on("object.chaos-experiment")) == 1
    assert loki.behavior_snapshot()["chaos_scheduler:blast_radius_full"] == 1


async def test_loki_recurring_scheduler_compacts_durable_window_rows() -> None:
    bus = InMemoryBus(registry=load_pantheon(), isolate_handlers=False)
    store = InMemoryStateStore()
    current = _NOW
    loki = Loki(
        bus=bus,
        state_store=store,
        clock=lambda: current,
        recurring_schedule=_complete_schedule(schedule_id="retained-windows"),
    )

    for _index in range(_MAX_HELD_PROPOSALS + 4):
        await loki.maintenance_tick()
        current += timedelta(hours=1)

    rows, total = await store.read_state_page(
        _SCHEDULED_PREFIX,
        limit=_MAX_HELD_PROPOSALS + 10,
    )
    assert total == _MAX_HELD_PROPOSALS
    assert len(rows) == _MAX_HELD_PROPOSALS
