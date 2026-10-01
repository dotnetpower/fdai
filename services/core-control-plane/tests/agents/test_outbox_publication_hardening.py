from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.outbox_publication import (
    PublicationClaim,
    await_bounded_publication,
    publish_claimed_outbox,
)
from fdai.agents._framework.registry import load_pantheon
from fdai.agents._framework.runtime_operational_agents import rehydrate_operational_agents
from fdai.agents._framework.var_final_approval import (
    claim_approval_publication,
    mark_approval_published,
)
from fdai.agents.heimdall import Heimdall
from fdai.agents.mimir import Mimir
from fdai.agents.muninn import Muninn
from fdai.agents.saga import Saga, _audit_outbox_key
from fdai.agents.var import Var
from fdai.shared.providers.testing.state_store import InMemoryStateStore


def _bus() -> InMemoryBus:
    return InMemoryBus(registry=load_pantheon(), handler_timeout=None)


def _rule_payload(index: int) -> dict[str, Any]:
    return {
        "producer_principal": "Mimir",
        "kind": "rule_promotion",
        "correlation_id": f"rule-corr-{index}",
        "idempotency_key": f"rule-publication:{index}",
        "rule_id": f"rule.test.{index}",
        "state": "shadow",
        "source": "manual",
        "updated_at": "2032-01-01T00:00:00+00:00",
        "grants_execution_authority": False,
    }


class _BlockingPublisher:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.cancelled = asyncio.Event()
        self.records: list[tuple[str, str, dict[str, Any]]] = []

    async def publish(self, principal: str, topic: str, payload: Mapping[str, Any]) -> None:
        self.started.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        self.records.append((principal, topic, dict(payload)))


class _FailingBus(InMemoryBus):
    def __init__(self, failing_keys: set[str]) -> None:
        super().__init__(registry=load_pantheon(), handler_timeout=None)
        self.failing_keys = set(failing_keys)

    async def publish(self, principal: str, topic: str, payload: dict[str, Any]) -> None:
        idempotency_key = str(payload.get("idempotency_key") or "")
        if idempotency_key in self.failing_keys:
            self.failing_keys.remove(idempotency_key)
            raise RuntimeError("transient publication failure")
        await super().publish(principal, topic, payload)


async def test_bounded_publication_awaits_cancelled_task_before_release() -> None:
    cleanup_complete = asyncio.Event()
    release_observed_cleanup = False

    async def publish() -> None:
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cleanup_complete.set()
            raise

    async def mark_published(_claim: PublicationClaim) -> bool:
        raise AssertionError("timed out publication must not be marked")

    async def release(_claim: PublicationClaim) -> None:
        nonlocal release_observed_cleanup
        release_observed_cleanup = cleanup_complete.is_set()

    with pytest.raises(TimeoutError):
        await publish_claimed_outbox(
            PublicationClaim(owner="test-claim", claimed_at="2032-01-01T00:00:00+00:00"),
            publish=publish,
            mark_published=mark_published,
            release=release,
            lease=timedelta(milliseconds=2),
        )

    assert release_observed_cleanup


async def test_bounded_publication_cancels_inner_publish_when_outer_cancelled() -> None:
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def publish() -> None:
        started.set()
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    task = asyncio.create_task(await_bounded_publication(publish(), lease=timedelta(hours=1)))
    await started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert cancelled.is_set()


async def test_var_late_publisher_cannot_mark_after_claim_reclaimed() -> None:
    now = datetime(2032, 1, 1, tzinfo=UTC)
    store = InMemoryStateStore()
    var = Var(state_store=store, clock=lambda: now)
    approval = {
        "producer_principal": "Var",
        "correlation_id": "approval-late",
        "idempotency_key": "approval-late:key",
        "state": "approved",
    }
    await var._checkpoint_final_approval(approval)  # noqa: SLF001
    first_claim = await claim_approval_publication(
        store=store,
        approval=approval,
        published_cache=set(),
        owner="Var:first",
        now=now,
    )
    assert first_claim is not None

    now += timedelta(minutes=6)
    second_cache: set[tuple[str, str]] = set()
    second_claim = await claim_approval_publication(
        store=store,
        approval=approval,
        published_cache=second_cache,
        owner="Var:second",
        now=now,
    )
    assert second_claim is not None

    assert await mark_approval_published(
        store=store,
        published_cache=second_cache,
        approval=approval,
        claim=second_claim,
    )
    assert not await mark_approval_published(
        store=store,
        published_cache=set(),
        approval=approval,
        claim=first_claim,
    )


async def test_saga_late_publisher_cannot_mark_after_claim_reclaimed() -> None:
    now = datetime(2032, 1, 1, tzinfo=UTC)
    store = InMemoryStateStore()
    saga = Saga(durable_state_store=store, clock=lambda: now)
    payload = {
        "producer_principal": "Saga",
        "correlation_id": "audit-late",
        "idempotency_key": "audit-late:key",
        "audited_topic": "object.action-run",
        "result": "success",
    }
    await saga._checkpoint_audit_outbox(payload)  # noqa: SLF001
    first_claim = await saga._claim_audit_outbox_publication(payload)  # noqa: SLF001
    assert first_claim is not None

    now += timedelta(minutes=6)
    second_claim = await saga._claim_audit_outbox_publication(payload)  # noqa: SLF001
    assert second_claim is not None

    assert await saga._mark_audit_outbox_published(payload, second_claim) is True  # noqa: SLF001
    assert await saga._mark_audit_outbox_published(payload, first_claim) is False  # noqa: SLF001
    assert (await store.read_state(_audit_outbox_key(payload)))["status"] == "published"


async def test_heimdall_runtime_startup_recovers_pending_publications() -> None:
    store = InMemoryStateStore()
    payload = {
        "producer_principal": "Heimdall",
        "kind": "recovery_effect_observation",
        "correlation_id": "heimdall-recovery",
        "idempotency_key": "heimdall-recovery:1",
    }
    checkpoint = Heimdall(state_store=store)
    assert await checkpoint._publish_once("object.recovery-effect-observation", payload) is False

    bus = _bus()
    restarted = Heimdall(bus=bus, state_store=store)
    await rehydrate_operational_agents({"Heimdall": restarted})

    messages = bus.messages_on("object.recovery-effect-observation")
    assert [message.payload["idempotency_key"] for message in messages] == ["heimdall-recovery:1"]


async def test_heimdall_concurrent_replicas_publish_one_row() -> None:
    store = InMemoryStateStore()
    bus = _BlockingPublisher()
    payload = {
        "producer_principal": "Heimdall",
        "kind": "recovery_effect_observation",
        "correlation_id": "heimdall-concurrent",
        "idempotency_key": "heimdall-concurrent:1",
    }
    first = Heimdall(bus=bus, state_store=store)  # type: ignore[arg-type]
    second = Heimdall(bus=bus, state_store=store)  # type: ignore[arg-type]

    first_publish = asyncio.create_task(
        first._publish_once("object.recovery-effect-observation", dict(payload))  # noqa: SLF001
    )
    await bus.started.wait()

    assert not await second._publish_once(  # noqa: SLF001
        "object.recovery-effect-observation",
        dict(payload),
    )
    bus.release.set()
    assert await first_publish
    assert bus.records == [("Heimdall", "object.recovery-effect-observation", payload)]


async def test_heimdall_publication_recovery_drains_multiple_pages() -> None:
    store = InMemoryStateStore()
    checkpoint = Heimdall(state_store=store)
    for index in range(101):
        payload = {
            "producer_principal": "Heimdall",
            "kind": "recovery_effect_observation",
            "correlation_id": f"heimdall-recovery-page-{index}",
            "idempotency_key": f"heimdall-recovery-page:{index}",
        }
        assert not await checkpoint._publish_once(  # noqa: SLF001
            "object.recovery-effect-observation",
            payload,
        )

    bus = _bus()
    recovered = Heimdall(bus=bus, state_store=store)

    assert await recovered.recover_publications() == 101
    assert len(bus.messages_on("object.recovery-effect-observation")) == 101


async def test_heimdall_recovery_failure_defers_row_and_continues() -> None:
    store = InMemoryStateStore()
    checkpoint = Heimdall(state_store=store)
    failed_payload = {
        "producer_principal": "Heimdall",
        "kind": "recovery_effect_observation",
        "correlation_id": "heimdall-failed",
        "idempotency_key": "heimdall-failed:1",
    }
    good_payload = {
        "producer_principal": "Heimdall",
        "kind": "recovery_effect_observation",
        "correlation_id": "heimdall-good",
        "idempotency_key": "heimdall-good:1",
    }
    assert not await checkpoint._publish_once(  # noqa: SLF001
        "object.recovery-effect-observation", failed_payload
    )
    assert not await checkpoint._publish_once(  # noqa: SLF001
        "object.recovery-effect-observation", good_payload
    )

    recovered = Heimdall(
        bus=_FailingBus({"heimdall-failed:1"}),
        state_store=store,
    )

    assert await recovered.recover_publications() == 1
    messages = recovered.bus.messages_on("object.recovery-effect-observation")
    assert [message.payload["idempotency_key"] for message in messages] == ["heimdall-good:1"]
    failed_digest = hashlib.sha256(
        b"object.recovery-effect-observation:heimdall-failed:1"
    ).hexdigest()
    failed_row = await store.read_state(f"pantheon/heimdall/publications/{failed_digest}")
    assert failed_row is not None
    assert failed_row["state"] == "pending"
    assert failed_row["idempotency_key"] == "heimdall-failed:1"
    assert recovered.behavior_snapshot()["publication:recovery_publish_failed"] == 1


async def test_heimdall_malformed_recovery_row_is_retained_and_skipped() -> None:
    store = InMemoryStateStore()
    await store.write_state(
        "pantheon/heimdall/publications/malformed",
        {
            "schema_version": "1.0.0",
            "revision": 1,
            "state": "pending",
            "topic": "object.bad",
            "idempotency_key": "heimdall-bad:1",
            "payload": {"idempotency_key": "heimdall-bad:1"},
        },
    )
    heimdall = Heimdall(bus=_bus(), state_store=store)

    assert await heimdall.recover_publications() == 0
    assert (await store.read_state("pantheon/heimdall/publications/malformed")) is not None
    assert heimdall.behavior_snapshot()["publication:recovery_invalid_row"] == 1


async def test_mimir_rule_publication_recovery_drains_multiple_pages() -> None:
    store = InMemoryStateStore()
    bus = _bus()
    mimir = Mimir(governance_state_store=store)
    mimir.bind_bus(bus)
    for index in range(129):
        payload = _rule_payload(index)
        assert await mimir._checkpoint_rule_publication(  # noqa: SLF001
            topic="object.rule",
            payload=payload,
            idempotency_key=str(payload["idempotency_key"]),
        )

    assert await mimir.recover_governance_state() == 129
    assert len(bus.messages_on("object.rule")) == 129
    _rows, pending = await store.read_state_page(
        "pantheon/mimir/governance/rule-publications/",
        limit=200,
        field="status",
        value="pending",
    )
    assert pending == 0


async def test_mimir_recovery_failure_defers_row_and_continues() -> None:
    store = InMemoryStateStore()
    mimir = Mimir(governance_state_store=store)
    failed_payload = _rule_payload(10)
    good_payload = _rule_payload(11)
    assert await mimir._checkpoint_rule_publication(  # noqa: SLF001
        topic="object.rule",
        payload=failed_payload,
        idempotency_key=str(failed_payload["idempotency_key"]),
    )
    assert await mimir._checkpoint_rule_publication(  # noqa: SLF001
        topic="object.rule",
        payload=good_payload,
        idempotency_key=str(good_payload["idempotency_key"]),
    )
    mimir.bind_bus(_FailingBus({str(failed_payload["idempotency_key"])}))

    assert await mimir._recover_rule_publications(store) == 1  # noqa: SLF001
    messages = mimir.bus.messages_on("object.rule")
    assert [message.payload["idempotency_key"] for message in messages] == [
        good_payload["idempotency_key"]
    ]
    failed_row = await store.read_state(
        f"pantheon/mimir/governance/rule-publications/{failed_payload['idempotency_key']}"
    )
    assert failed_row is not None
    assert failed_row["status"] == "pending"
    assert failed_row["idempotency_key"] == failed_payload["idempotency_key"]
    assert mimir.behavior_snapshot()["promotion:publication_recovery_failed"] == 1


async def test_mimir_malformed_recovery_row_is_retained_and_skipped() -> None:
    store = InMemoryStateStore()
    await store.write_state(
        "pantheon/mimir/governance/rule-publications/malformed",
        {
            "kind": "mimir_rule_publication",
            "revision": 1,
            "status": "pending",
            "topic": "object.bad",
            "idempotency_key": "mimir-bad:1",
            "payload": {"idempotency_key": "mimir-bad:1"},
        },
    )
    mimir = Mimir(governance_state_store=store)
    mimir.bind_bus(_bus())

    assert await mimir._recover_rule_publications(store) == 0  # noqa: SLF001
    assert (
        await store.read_state("pantheon/mimir/governance/rule-publications/malformed")
    ) is not None
    assert mimir.behavior_snapshot()["promotion:publication_recovery_invalid_row"] == 1


async def test_muninn_operational_publication_recovery_drains_multiple_pages() -> None:
    old_now = datetime(2032, 1, 1, tzinfo=UTC)
    new_now = old_now + timedelta(minutes=6)
    store = InMemoryStateStore()
    first = Muninn(durable_state_store=store, case_history_clock=lambda: old_now)
    for index in range(101):
        payload = {
            "producer_principal": "Muninn",
            "kind": "context_index",
            "correlation_id": f"muninn-recovery-{index}",
            "idempotency_key": f"muninn-recovery:{index}",
        }
        key_digest = hashlib.sha256(str(payload["idempotency_key"]).encode()).hexdigest()
        claim = await first._claim_publication(  # noqa: SLF001
            f"pantheon/muninn/operational-outbox/test/{key_digest}",
            "object.context-index",
            payload,
        )
        assert claim is not None

    bus = _bus()
    restarted = Muninn(durable_state_store=store, case_history_clock=lambda: new_now)
    restarted.bind_bus(bus)

    assert await restarted.recover_operational_publications() == 101
    assert len(bus.messages_on("object.context-index")) == 101


async def test_muninn_concurrent_replicas_publish_one_row() -> None:
    store = InMemoryStateStore()
    bus = _BlockingPublisher()
    payload = {
        "producer_principal": "Muninn",
        "kind": "context_index",
        "correlation_id": "muninn-concurrent",
        "idempotency_key": "muninn-concurrent:1",
    }
    key_digest = hashlib.sha256(str(payload["idempotency_key"]).encode()).hexdigest()
    outbox_key = f"pantheon/muninn/operational-outbox/test/{key_digest}"
    first = Muninn(durable_state_store=store)
    first.bind_bus(bus)  # type: ignore[arg-type]
    second = Muninn(durable_state_store=store)
    second.bind_bus(bus)  # type: ignore[arg-type]

    first_publish = asyncio.create_task(
        first._publish_with_outbox(outbox_key, "object.context-index", dict(payload))  # noqa: SLF001
    )
    await bus.started.wait()

    assert not await second._publish_with_outbox(  # noqa: SLF001
        outbox_key,
        "object.context-index",
        dict(payload),
    )
    bus.release.set()
    assert await first_publish
    assert bus.records == [("Muninn", "object.context-index", payload)]


async def test_heimdall_maintenance_redrives_deferred_publication() -> None:
    store = InMemoryStateStore()
    checkpoint = Heimdall(state_store=store)
    payload = {
        "producer_principal": "Heimdall",
        "kind": "recovery_effect_observation",
        "correlation_id": "heimdall-maintenance",
        "idempotency_key": "heimdall-maintenance:1",
    }
    assert not await checkpoint._publish_once("object.recovery-effect-observation", payload)  # noqa: SLF001
    checkpoint.bind_bus(_bus())

    await checkpoint.maintenance_tick()

    assert len(checkpoint.bus.messages_on("object.recovery-effect-observation")) == 1


async def test_saga_maintenance_redrives_deferred_audit_publication() -> None:
    store = InMemoryStateStore()
    saga = Saga(durable_state_store=store)
    payload = {
        "producer_principal": "Saga",
        "correlation_id": "saga-maintenance",
        "idempotency_key": "saga-maintenance:1",
        "audited_topic": "object.action-run",
        "result": "success",
    }
    await saga._checkpoint_audit_outbox(payload)  # noqa: SLF001
    assert await saga.recover_audit_outbox() == 0
    saga.bind_bus(_bus())

    await saga.maintenance_tick()

    assert len(saga.bus.messages_on("object.audit-entry")) == 1


async def test_muninn_maintenance_redrives_deferred_operational_publication() -> None:
    store = InMemoryStateStore()
    muninn = Muninn(durable_state_store=store)
    payload = {
        "producer_principal": "Muninn",
        "kind": "context_index",
        "correlation_id": "muninn-maintenance",
        "idempotency_key": "muninn-maintenance:1",
    }
    outbox_key = "pantheon/muninn/operational-outbox/test/muninn-maintenance"
    claim = await muninn._claim_publication(  # noqa: SLF001
        outbox_key,
        "object.context-index",
        payload,
    )
    assert claim is not None
    await muninn._release_publication_claim(outbox_key, payload, claim)  # noqa: SLF001
    muninn.bind_bus(_bus())

    await muninn.maintenance_tick()

    assert len(muninn.bus.messages_on("object.context-index")) == 1


async def test_mimir_maintenance_redrives_deferred_rule_publication() -> None:
    store = InMemoryStateStore()
    mimir = Mimir(governance_state_store=store)
    payload = _rule_payload(200)
    assert await mimir._checkpoint_rule_publication(  # noqa: SLF001
        topic="object.rule",
        payload=payload,
        idempotency_key=str(payload["idempotency_key"]),
    )
    mimir.bind_bus(_bus())

    await mimir.maintenance_tick()

    assert len(mimir.bus.messages_on("object.rule")) == 1


async def test_var_maintenance_redrives_deferred_final_approval() -> None:
    store = InMemoryStateStore()
    var = Var(state_store=store)
    approval = {
        "producer_principal": "Var",
        "correlation_id": "var-maintenance",
        "idempotency_key": "var-maintenance:1",
        "state": "approved",
    }
    await var._checkpoint_final_approval(approval)  # noqa: SLF001
    assert await var.recover_approvals() == (0, 0)
    var.bind_bus(_bus())

    await var.maintenance_tick()

    assert len(var.bus.messages_on("object.approval")) == 1
