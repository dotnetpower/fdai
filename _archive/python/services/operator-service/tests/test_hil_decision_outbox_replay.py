"""Focused proof for lease-fenced replay of durable HIL decision records.

A recorded human decision is persisted as an ``iam`` /
``hil.decision.enqueue`` proposal before any broker call. If the broker call
fails - or the replica crashes between the durable write and the publish - the
decision MUST still reach the bus without a second HTTP callback, and it MUST
be marked delivered only after the broker accepted it.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

import pytest
from fdai_operator_service.families.iam.contracts import (
    HilApprovalDecision,
    HilDecisionOutboxRequest,
    HilDecisionReceipt,
)
from fdai_operator_service.families.iam.hil_decision_outbox import (
    DurableHilDecisionOutboxPublisher,
    HilDecisionOutboxBridge,
    HilDecisionOutboxDrainer,
    hil_decision_delivery_key,
    hil_decision_payload,
    outbox_payload,
    receipt_from_outbox_payload,
)

_NOW = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
_TOPIC = "fdai.hil.decisions"


def _receipt(**overrides: Any) -> HilDecisionReceipt:
    values: dict[str, Any] = {
        "approval_id": "approval-1",
        "idempotency_key": "hil-key-1",
        "decision": HilApprovalDecision.APPROVE,
        "approver_oid": "approver-1",
        "decided_at": _NOW,
        "receipt_ref": "receipt-1",
        "justification": "Verified rollback and blast radius.",
    }
    values.update(overrides)
    return HilDecisionReceipt(**values)


@dataclass(frozen=True, slots=True)
class _Claim:
    key: str
    claim_id: str
    payload: Mapping[str, object]


class _Store:
    """In-process durable outbox with the PostgreSQL claim/release semantics."""

    def __init__(self) -> None:
        self.records: dict[str, dict[str, Any]] = {}
        self.claims = 0

    async def enqueue(self, request: HilDecisionOutboxRequest) -> None:
        key = hil_decision_delivery_key(request.receipt.idempotency_key)
        self.records.setdefault(
            key,
            {
                "key": key,
                "dispatch_status": "pending",
                "claim_id": None,
                "attempt": 0,
                "payload": outbox_payload(request.receipt),
            },
        )

    async def claim_hil_decision_proposal(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
    ) -> _Claim | None:
        del worker_id, lease_seconds
        for record in self.records.values():
            if record["dispatch_status"] != "pending":
                continue
            self.claims += 1
            record["dispatch_status"] = "claimed"
            record["claim_id"] = str(uuid.uuid4())
            record["attempt"] += 1
            return _Claim(
                key=str(record["key"]),
                claim_id=str(record["claim_id"]),
                payload=dict(record["payload"]),
            )
        return None

    async def mark_proposal_published(self, *, key: str, claim_id: str) -> bool:
        record = self.records.get(key)
        if record is None or record["claim_id"] != claim_id:
            return False
        record["dispatch_status"] = "published"
        return True

    async def mark_proposal_rejected(
        self,
        *,
        key: str,
        claim_id: str,
        reason_code: str,
    ) -> bool:
        record = self.records.get(key)
        if record is None or record["claim_id"] != claim_id:
            return False
        record["dispatch_status"] = "rejected"
        record["rejection_reason"] = reason_code
        return True

    async def release_proposal_claim(self, *, key: str, claim_id: str) -> bool:
        record = self.records.get(key)
        if record is None or record["claim_id"] != claim_id:
            return False
        record["dispatch_status"] = "pending"
        record["claim_id"] = None
        return True

    async def mark_decision_published(self, idempotency_key: str) -> bool:
        record = self.records.get(hil_decision_delivery_key(idempotency_key))
        if record is None or record["dispatch_status"] != "pending":
            return False
        record["dispatch_status"] = "published"
        return True


class _Registry:
    def __init__(self, receipt: HilDecisionReceipt | None = None) -> None:
        self.receipts: dict[str, HilDecisionReceipt] = (
            {receipt.approval_id: receipt} if receipt is not None else {}
        )
        self.delivered_calls = 0

    async def get_decision_by_approval_id(
        self,
        approval_id: str,
    ) -> HilDecisionReceipt | None:
        return self.receipts.get(approval_id)

    async def mark_delivered(self, receipt: HilDecisionReceipt) -> HilDecisionReceipt:
        self.delivered_calls += 1
        stored = self.receipts.get(receipt.approval_id, receipt)
        if stored.delivered:
            return stored
        delivered = replace(stored, delivered=True)
        self.receipts[receipt.approval_id] = delivered
        return delivered


class _Publisher:
    def __init__(self, *, failures: int = 0) -> None:
        self.published: list[tuple[str, str, dict[str, object]]] = []
        self._failures = failures

    async def publish(self, topic: str, key: str, payload: dict[str, object]) -> object:
        if self._failures > 0:
            self._failures -= 1
            raise RuntimeError("synthetic broker outage")
        self.published.append((topic, key, payload))
        return object()


def _drainer(store: _Store, registry: _Registry, publisher: _Publisher) -> HilDecisionOutboxDrainer:
    return HilDecisionOutboxDrainer(
        store=store,
        registry=registry,
        publisher=publisher,
        topic=_TOPIC,
    )


def test_delivery_key_bounds_maximum_callback_identity() -> None:
    key = hil_decision_delivery_key("x" * 256)

    assert len(key) <= 256
    assert key != hil_decision_delivery_key("y" * 256)


@pytest.mark.asyncio
async def test_broker_failure_after_durable_write_is_redriven_without_a_new_callback() -> None:
    store = _Store()
    registry = _Registry(_receipt())
    failing = _Publisher(failures=1)
    outbox = DurableHilDecisionOutboxPublisher(
        durable=store,
        publisher=failing,
        topic=_TOPIC,
        ledger=store,
    )

    with pytest.raises(RuntimeError, match="synthetic broker outage"):
        await outbox.enqueue(HilDecisionOutboxRequest(receipt=_receipt()))

    key = hil_decision_delivery_key("hil-key-1")
    assert store.records[key]["dispatch_status"] == "pending"
    assert registry.receipts["approval-1"].delivered is False

    publisher = _Publisher()
    assert await _drainer(store, registry, publisher).run_once() is True

    assert store.records[key]["dispatch_status"] == "published"
    assert registry.receipts["approval-1"].delivered is True
    assert publisher.published == [(_TOPIC, "approval-1", hil_decision_payload(_receipt()))]


@pytest.mark.asyncio
async def test_crash_after_durable_write_is_redriven_on_restart() -> None:
    """Simulate a replica that persisted the record and then died."""
    store = _Store()
    registry = _Registry(_receipt())
    await store.enqueue(HilDecisionOutboxRequest(receipt=_receipt()))

    publisher = _Publisher()
    assert await _drainer(store, registry, publisher).run_once() is True
    assert await _drainer(store, registry, publisher).run_once() is False

    assert len(publisher.published) == 1
    assert registry.receipts["approval-1"].delivered is True


@pytest.mark.asyncio
async def test_delivery_is_marked_only_after_broker_acceptance() -> None:
    store = _Store()
    registry = _Registry(_receipt())
    await store.enqueue(HilDecisionOutboxRequest(receipt=_receipt()))
    failing = _Publisher(failures=1)

    assert await _drainer(store, registry, failing).run_once() is False

    assert registry.delivered_calls == 0
    assert registry.receipts["approval-1"].delivered is False
    assert store.records[hil_decision_delivery_key("hil-key-1")]["dispatch_status"] == "pending"
    assert store.records[hil_decision_delivery_key("hil-key-1")]["attempt"] == 1


@pytest.mark.asyncio
async def test_replay_never_republishes_an_already_delivered_decision() -> None:
    store = _Store()
    registry = _Registry(_receipt(delivered=True))
    await store.enqueue(HilDecisionOutboxRequest(receipt=_receipt()))
    publisher = _Publisher()

    assert await _drainer(store, registry, publisher).run_once() is True

    assert publisher.published == []
    assert registry.delivered_calls == 0
    assert store.records[hil_decision_delivery_key("hil-key-1")]["dispatch_status"] == "published"


@pytest.mark.asyncio
async def test_immediate_path_and_worker_publish_identical_payloads() -> None:
    store = _Store()
    registry = _Registry(_receipt())
    immediate = _Publisher()
    outbox = DurableHilDecisionOutboxPublisher(
        durable=store,
        publisher=immediate,
        topic=_TOPIC,
        ledger=store,
    )
    await outbox.enqueue(HilDecisionOutboxRequest(receipt=_receipt()))

    # The immediate path closed the record, so the worker finds nothing.
    replay = _Publisher()
    assert await _drainer(store, registry, replay).run_once() is False
    assert replay.published == []

    # Reopen the record the way an interrupted ledger close would leave it.
    store.records[hil_decision_delivery_key("hil-key-1")]["dispatch_status"] = "pending"
    assert await _drainer(store, registry, replay).run_once() is True

    assert replay.published[0] == immediate.published[0]


@pytest.mark.asyncio
async def test_replay_rejects_a_conflicting_authoritative_receipt() -> None:
    store = _Store()
    stale = _receipt(justification="Stale copy.", receipt_ref="stale-ref")
    await store.enqueue(HilDecisionOutboxRequest(receipt=stale))
    registry = _Registry(_receipt())
    publisher = _Publisher()

    assert await _drainer(store, registry, publisher).run_once() is False
    record = store.records[hil_decision_delivery_key("hil-key-1")]
    assert record["dispatch_status"] == "rejected"
    assert record["rejection_reason"] == "conflicting_hil_decision_outbox_record"
    assert publisher.published == []


@pytest.mark.asyncio
async def test_malformed_durable_record_is_closed_without_transport_retry() -> None:
    store = _Store()
    key = hil_decision_delivery_key("hil-key-1")
    store.records[key] = {
        "key": key,
        "dispatch_status": "pending",
        "claim_id": None,
        "attempt": 0,
        "payload": {"receipt": {"approval_id": "approval-1"}},
    }
    publisher = _Publisher()

    assert await _drainer(store, _Registry(), publisher).run_once() is False

    assert store.records[key]["dispatch_status"] == "rejected"
    assert store.records[key]["rejection_reason"] == "malformed_hil_decision_outbox_record"
    assert publisher.published == []


@pytest.mark.asyncio
async def test_outbox_payload_round_trips_the_exact_receipt() -> None:
    receipt = _receipt()

    assert receipt_from_outbox_payload(outbox_payload(receipt)) == receipt

    with pytest.raises(ValueError, match="malformed"):
        receipt_from_outbox_payload({"receipt": "not-an-object"})
    with pytest.raises(ValueError, match="timezone-aware"):
        receipt_from_outbox_payload(
            {
                "receipt": {
                    **hil_decision_payload(receipt),
                    "decided_at": _NOW.replace(tzinfo=None).isoformat(),
                }
            }
        )


@pytest.mark.asyncio
async def test_replay_bridge_starts_and_closes_exactly_once() -> None:
    store = _Store()
    registry = _Registry(_receipt())
    await store.enqueue(HilDecisionOutboxRequest(receipt=_receipt()))
    bridge = HilDecisionOutboxBridge(
        store=store,
        registry=registry,
        publisher=_Publisher(),
        topic=_TOPIC,
        retry_seconds=0.01,
    )

    assert bridge.workers_ready() is False
    await bridge.start()
    await bridge.start()
    assert bridge.workers_ready() is True
    await bridge.aclose()
    assert bridge.workers_ready() is False
    await bridge.aclose()


def test_replay_bounds_are_validated() -> None:
    with pytest.raises(ValueError, match="topic MUST be non-empty"):
        HilDecisionOutboxDrainer(
            store=_Store(),
            registry=_Registry(),
            publisher=_Publisher(),
            topic="  ",
        )
    with pytest.raises(ValueError, match=r"lease_seconds MUST be in \[1, 300\]"):
        HilDecisionOutboxDrainer(
            store=_Store(),
            registry=_Registry(),
            publisher=_Publisher(),
            topic=_TOPIC,
            lease_seconds=0,
        )
    with pytest.raises(ValueError, match="retry_seconds MUST be positive"):
        HilDecisionOutboxBridge(
            store=_Store(),
            registry=_Registry(),
            publisher=_Publisher(),
            topic=_TOPIC,
            retry_seconds=0,
        )


async def test_store_claim_targets_only_iam_hil_decision_enqueue_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fdai_operator_service.postgres_family_store import (
        PostgresFamilyStore,
        PostgresFamilyStoreConfig,
    )

    statements: list[str] = []
    parameters_seen: list[Mapping[str, object]] = []

    async def fetch_all(
        self: PostgresFamilyStore,
        statement: str,
        parameters: Mapping[str, object],
    ) -> list[dict[str, object]]:
        del self
        statements.append(statement)
        parameters_seen.append(parameters)
        return [
            {
                "key": "operator-proposal:iam:one",
                "value": {"payload": outbox_payload(_receipt()), "attempt": 1},
            }
        ]

    monkeypatch.setattr(PostgresFamilyStore, "_fetch_all", fetch_all)
    store = PostgresFamilyStore(PostgresFamilyStoreConfig("postgresql://example.invalid/fdai"))

    claim = await store.claim_hil_decision_proposal(worker_id="worker-one", lease_seconds=30)

    assert claim is not None
    assert receipt_from_outbox_payload(claim.payload) == _receipt()
    assert "value ->> 'family' = 'iam'" in statements[0]
    assert "value ->> 'operation' = 'hil.decision.enqueue'" in statements[0]
    assert "value ->> 'dispatch_status' = 'pending'" in statements[0]
    assert "(value ->> 'claim_expires_at')::timestamptz <= NOW()" in statements[0]
    assert "FOR UPDATE SKIP LOCKED" in statements[0]
    assert "'claim_worker_id', %(worker_id)s::text" in statements[0]
    assert parameters_seen[0]["proposal_prefix"] == "operator-proposal:%"


async def test_store_close_only_advances_a_pending_durable_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fdai_operator_service.postgres_family_store import (
        PostgresFamilyStore,
        PostgresFamilyStoreConfig,
    )

    statements: list[str] = []

    async def fetch_all(
        self: PostgresFamilyStore,
        statement: str,
        parameters: Mapping[str, object],
    ) -> list[dict[str, object]]:
        del self, parameters
        statements.append(statement)
        return []

    monkeypatch.setattr(PostgresFamilyStore, "_fetch_all", fetch_all)
    store = PostgresFamilyStore(PostgresFamilyStoreConfig("postgresql://example.invalid/fdai"))

    assert await store.mark_hil_decision_published(idempotency_key="hil-key-1:delivery") is False
    assert "value ->> 'dispatch_status' = 'pending'" in statements[0]
    assert "'dispatch_status', 'published'" in statements[0]
    with pytest.raises(ValueError, match="idempotency_key MUST be"):
        await store.mark_hil_decision_published(idempotency_key="  ")
