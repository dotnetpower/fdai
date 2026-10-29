"""Saga aggregates only bounded, actionless no-rule-match verdict deliveries."""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Any

import pytest
from fdai.agents import Saga, StateStoreAuditChainAdapter
from fdai.agents._framework.audit_chain_rehydrate import AuditAppendDeferredError
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents._framework.saga_verdict_aggregation import (
    _VERDICT_AGGREGATE_KEY,
    _aggregate_digests,
)
from fdai.shared.providers.testing import InMemoryStateStore


class FailedPairWriteStore(InMemoryStateStore):
    fail_pair_write = False

    async def compare_and_set_state_pair_with_audit(
        self,
        key: str,
        value: Mapping[str, Any],
        *,
        expected_revision: int,
        second_key: str,
        second_value: Mapping[str, Any],
        expected_second_revision: int,
        audit_entry: Mapping[str, Any],
    ) -> bool:
        if self.fail_pair_write:
            return False
        return await super().compare_and_set_state_pair_with_audit(
            key,
            value,
            expected_revision=expected_revision,
            second_key=second_key,
            second_value=second_value,
            expected_second_revision=expected_second_revision,
            audit_entry=audit_entry,
        )


class FailingStageWriteStore(InMemoryStateStore):
    fail_stage_write = False

    async def compare_and_set_state(
        self,
        key: str,
        value: Mapping[str, Any],
        *,
        expected_revision: int,
    ) -> bool:
        if self.fail_stage_write and key == _VERDICT_AGGREGATE_KEY:
            raise RuntimeError("aggregate ledger write failed")
        return await super().compare_and_set_state(
            key,
            value,
            expected_revision=expected_revision,
        )


class InterleavingPairWriteStore(InMemoryStateStore):
    before_pair_write: Callable[[], Awaitable[None]] | None = None

    async def compare_and_set_state_pair_with_audit(
        self,
        key: str,
        value: Mapping[str, Any],
        *,
        expected_revision: int,
        second_key: str,
        second_value: Mapping[str, Any],
        expected_second_revision: int,
        audit_entry: Mapping[str, Any],
    ) -> bool:
        callback = self.before_pair_write
        self.before_pair_write = None
        if callback is not None:
            await callback()
        return await super().compare_and_set_state_pair_with_audit(
            key,
            value,
            expected_revision=expected_revision,
            second_key=second_key,
            second_value=second_value,
            expected_second_revision=expected_second_revision,
            audit_entry=audit_entry,
        )


class FailingLedgerReadStore(InMemoryStateStore):
    fail_ledger_read = False

    async def read_state(self, key: str) -> Mapping[str, Any] | None:
        if self.fail_ledger_read and key == _VERDICT_AGGREGATE_KEY:
            raise RuntimeError("aggregate ledger read failed")
        return await super().read_state(key)


def verdict(
    resource_id: str = "resource-a",
    correlation_id: str = "correlation-a",
    *,
    variant: str = "base",
    risk_verdict: str = "hil",
    action_id: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "producer_principal": "Forseti",
        "reason": "no_rule_match",
        "risk_verdict": risk_verdict,
        "action_type": "",
        "resolved_autonomy_ceiling": "shadow_only",
        "resource_id": resource_id,
        "correlation_id": correlation_id,
        "idempotency_key": f"verdict:{correlation_id}",
        "source_variant": variant,
    }
    if action_id is not None:
        payload["action_id"] = action_id
    return payload


def saga_for(
    store: InMemoryStateStore,
    *,
    clock=lambda: datetime.now(UTC),
) -> tuple[Saga, InMemoryBus]:
    bus = InMemoryBus(registry=load_pantheon())
    saga = Saga(
        audit_chain=StateStoreAuditChainAdapter(store),
        durable_state_store=store,
        clock=clock,
    )
    saga.bind_bus(bus)
    return saga, bus


async def test_repeated_delivery_survives_restart_and_seals_without_source_identity() -> None:
    store = InMemoryStateStore()
    saga, _ = saga_for(store)
    await saga.recover_audit_outbox()
    first = verdict(correlation_id="source-correlation-1")
    second = verdict(correlation_id="source-correlation-2")
    second["idempotency_key"] = first["idempotency_key"]

    await saga.on_typed_message("object.verdict", first)
    await saga.on_typed_message("object.verdict", second)

    ledger = await store.read_state(_VERDICT_AGGREGATE_KEY)
    assert ledger is not None
    assert len(ledger["groups"]) == 1
    group_digest, group = next(iter(ledger["groups"].items()))
    assert group["count"] == 2
    assert saga.audit_chain.entries == []
    assert saga.health()["audit_completeness"]["status"] == "incomplete"

    restarted, _ = saga_for(store)
    await restarted.recover_audit_outbox()
    assert restarted.health()["pending_verdict_aggregates"] == 1
    await restarted.maintenance_tick()

    assert len(restarted.audit_chain.entries) == 1
    restarted.audit_chain.verify()
    entry = restarted.audit_chain.entries[0]
    assert entry.correlation_id == f"aggregate:{group_digest}:{entry.seq}"
    assert restarted.audit_chain.entries_for_correlation(first["correlation_id"]) == []
    assert restarted.audit_chain.entries_for_correlation(second["correlation_id"]) == []
    assert restarted.audit_chain.entries_for_correlation(entry.correlation_id) == [entry]
    records, truncated = await store.read_audit_chain_entries(limit=10)
    assert not truncated
    aggregate = records[-1]
    assert aggregate["payload"] == {
        "schema_version": "1.0.0",
        "aggregate_type": "forseti.no_rule_match",
        "subject_digest": hashlib.sha256(first["resource_id"].encode("utf-8")).hexdigest(),
        "source_digest": group["source_digest"],
        "count": 2,
        "first_seen_at": group["first_seen_at"],
        "last_seen_at": group["last_seen_at"],
    }
    assert first["resource_id"] not in str(aggregate["payload"])
    assert first["correlation_id"] not in str(aggregate["payload"])
    assert restarted.health()["audit_completeness"]["status"] == "complete"


async def test_subject_order_seals_changed_and_nonmatching_verdicts_individually() -> None:
    store = InMemoryStateStore()
    saga, _ = saga_for(store)
    await saga.recover_audit_outbox()

    await saga.on_typed_message(
        "object.verdict",
        verdict(correlation_id="correlation-a", variant="first"),
    )
    await saga.on_typed_message(
        "object.verdict",
        verdict(correlation_id="correlation-b", variant="second"),
    )
    assert len(saga.audit_chain.entries) == 1

    individual = verdict(
        correlation_id="correlation-c",
        variant="not-a-noop",
        risk_verdict="deny",
        action_id="action-1",
    )
    await saga.on_typed_message("object.verdict", individual)

    records, _ = await store.read_audit_chain_entries(limit=10)
    assert [record["payload"].get("aggregate_type") for record in records] == [
        "forseti.no_rule_match",
        "forseti.no_rule_match",
        None,
    ]
    assert records[-1]["payload"]["risk_verdict"] == "deny"
    assert records[-1]["payload"]["action_id"] == "action-1"
    assert records[-1]["correlation_id"] == individual["correlation_id"]
    ledger = await store.read_state(_VERDICT_AGGREGATE_KEY)
    assert ledger is not None and ledger["groups"] == {}


async def test_ledger_caps_groups_and_seals_oldest_before_admitting_another() -> None:
    store = InMemoryStateStore()
    saga, _ = saga_for(store)
    await saga.recover_audit_outbox()

    for index in range(65):
        await saga.on_typed_message(
            "object.verdict",
            verdict(resource_id=f"resource-{index}", correlation_id=f"correlation-{index}"),
        )

    ledger = await store.read_state(_VERDICT_AGGREGATE_KEY)
    assert ledger is not None
    assert len(ledger["groups"]) == 64
    assert len(saga.audit_chain.entries) == 1
    assert saga.health()["pending_verdict_aggregates"] == 64
    records, _ = await store.read_audit_chain_entries(limit=10)
    assert records[0]["payload"]["subject_digest"] == hashlib.sha256(b"resource-0").hexdigest()


async def test_failed_seal_defers_following_message_and_recovers_in_order() -> None:
    store = FailedPairWriteStore()
    saga, _ = saga_for(store)
    await saga.recover_audit_outbox()
    await saga.on_typed_message("object.verdict", verdict())
    store.fail_pair_write = True

    following = verdict(
        correlation_id="correlation-following",
        variant="individual",
        risk_verdict="deny",
    )
    await saga.on_typed_message("object.verdict", following)

    assert saga.audit_chain.entries == []
    assert saga.health()["pending_audit_inbox"] == 1
    assert saga.health()["audit_completeness"]["status"] == "incomplete"
    pending = await store.read_state(_VERDICT_AGGREGATE_KEY)
    assert pending is not None and len(pending["groups"]) == 1

    store.fail_pair_write = False
    await saga.recover_audit_outbox()

    records, _ = await store.read_audit_chain_entries(limit=10)
    assert [record["payload"].get("aggregate_type") for record in records] == [
        "forseti.no_rule_match",
        None,
    ]
    assert records[-1]["correlation_id"] == following["correlation_id"]
    assert saga.health()["pending_audit_inbox"] == 0
    assert saga.health()["audit_completeness"]["status"] == "complete"


async def test_failed_stage_write_defers_delivery_and_marks_health_incomplete() -> None:
    store = FailingStageWriteStore()
    saga, _ = saga_for(store)
    await saga.recover_audit_outbox()
    store.fail_stage_write = True

    await saga.on_typed_message("object.verdict", verdict())

    health = saga.health()
    assert health["pending_audit_inbox"] == 1
    assert health["pending_verdict_aggregate_readable"] is False
    assert health["audit_completeness"]["status"] == "incomplete"

    store.fail_stage_write = False
    await saga.recover_audit_outbox()
    ledger = await store.read_state(_VERDICT_AGGREGATE_KEY)
    assert ledger is not None and len(ledger["groups"]) == 1
    assert saga.health()["pending_audit_inbox"] == 0


async def test_concurrent_stage_is_sealed_before_ordered_subject_append() -> None:
    store = InterleavingPairWriteStore()
    saga, _ = saga_for(store)
    racing_saga, _ = saga_for(store)
    await saga.recover_audit_outbox()
    await racing_saga.recover_audit_outbox()

    async def stage_racing_verdict() -> None:
        await racing_saga.on_typed_message(
            "object.verdict",
            verdict(correlation_id="racing-correlation"),
        )

    store.before_pair_write = stage_racing_verdict
    await saga._append_audit(
        principal="Operator",
        topic="object.approval",
        correlation_id="normal-correlation",
        payload={"resource_id": "resource-a", "decision": "approved"},
    )

    records, _ = await store.read_audit_chain_entries(limit=10)
    assert [record["payload"].get("aggregate_type") for record in records] == [
        "forseti.no_rule_match",
        None,
    ]
    assert records[-1]["correlation_id"] == "normal-correlation"
    assert records[-1]["payload"]["decision"] == "approved"


async def test_failed_health_refresh_cannot_reuse_a_previous_complete_snapshot() -> None:
    store = FailingLedgerReadStore()
    saga, _ = saga_for(store)
    await saga.recover_audit_outbox()
    assert saga.health()["audit_completeness"]["status"] == "complete"

    store.fail_ledger_read = True
    with pytest.raises(AuditAppendDeferredError, match="aggregate ledger read failed"):
        await saga._no_rule_match_aggregator.refresh()

    health = saga.health()
    assert health["pending_verdict_aggregate_readable"] is False
    assert health["audit_completeness"]["status"] == "incomplete"


async def test_pair_writer_conflict_changes_neither_state_row_nor_audit() -> None:
    store = InMemoryStateStore()
    await store.write_state("saga:aggregate:pending", {"revision": 1})
    await store.write_state("saga:audit:checkpoint", {"revision": 1})

    committed = await store.compare_and_set_state_pair_with_audit(
        "saga:aggregate:pending",
        {"revision": 2},
        expected_revision=1,
        second_key="saga:audit:checkpoint",
        second_value={"revision": 2},
        expected_second_revision=0,
        audit_entry={"actor": "Saga", "action_kind": "audit.aggregate"},
    )

    assert not committed
    assert await store.read_state("saga:aggregate:pending") == {"revision": 1}
    assert await store.read_state("saga:audit:checkpoint") == {"revision": 1}
    records, _ = await store.read_audit_entries(limit=10)
    assert records == ()


def test_group_identity_excludes_only_source_correlation_and_delivery_key() -> None:
    first = verdict(correlation_id="correlation-first")
    second = verdict(correlation_id="correlation-second")

    assert _aggregate_digests(first) == _aggregate_digests(second)
