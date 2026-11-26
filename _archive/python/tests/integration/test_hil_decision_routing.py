"""Cross-service proof that workflow HIL decisions reach the quorum owner.

The Operator service records a human approval, persists it, and publishes it on
``fdai.hil.decisions``. Core consumes that record. A ``decision_route=workflow``
park is one quorum slot owned by
:class:`~fdai.delivery.persistence.state_store_hil_registry.StateStoreHilApprovalRegistry`;
routing it to :meth:`HilResumeCoordinator.resolve` would bypass quorum
accounting, duplicate-approver refusal, and self-approval refusal, and would
also be the only path that can reach an executor.

Every case here drives the real Operator publisher payload shape, the real Core
consumer, and the real registry against an in-memory bus and state store. The
Operator writes its durable decision receipt before it publishes, so each case
records that receipt in the shared store unless it proves what happens without one.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fdai.delivery.persistence.state_store_hil_registry import (
    StateStoreHilApprovalRegistry,
)
from fdai.delivery.persistence.workflow_approval import (
    StateStoreWorkflowApprovalProvider,
)
from fdai.runtime import consumers as consumers_module
from fdai.runtime.consumers import _consume_hil_decisions
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_operator_service.families.iam.contracts import (
    HilApprovalDecision as OperatorDecision,
)
from fdai_operator_service.families.iam.contracts import (
    HilDecisionReceipt as OperatorReceipt,
)
from fdai_operator_service.families.iam.hil_decision_outbox import hil_decision_payload

_NOW = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
_TOPIC = "fdai.hil.decisions"


class _ReceiptReadingCoordinator:
    """Read Operator receipts from the shared store exactly as the real coordinator does."""

    def __init__(self, store: InMemoryStateStore) -> None:
        self.store = store
        self.calls: list[dict[str, Any]] = []

    async def read_operator_decision_receipt(self, approval_id: str) -> Any:
        return await self.store.read_state(f"operator-hil-decision:{approval_id}")


class _RefusingCoordinator(_ReceiptReadingCoordinator):
    """Fail loudly if a workflow slot ever reaches the executor-capable path."""

    async def resolve(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        raise AssertionError("workflow approval slots MUST NOT resume through the coordinator")


class _RecordingCoordinator(_ReceiptReadingCoordinator):
    async def resolve(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return None


class _UnreadableReceiptCoordinator(_RecordingCoordinator):
    async def read_operator_decision_receipt(self, approval_id: str) -> Any:
        raise RuntimeError("state store unavailable")


async def _record_receipt(store: InMemoryStateStore, payload: dict[str, object]) -> None:
    """Persist the durable receipt the Operator writes before it publishes ``payload``."""
    await store.write_state(
        f"operator-hil-decision:{payload['approval_id']}",
        {**payload, "already_recorded": False, "delivered": True},
    )


async def _publish_recorded(
    bus: InMemoryEventBus,
    store: InMemoryStateStore,
    payload: dict[str, object],
) -> None:
    await _record_receipt(store, payload)
    await bus.publish(_TOPIC, str(payload["approval_id"]), payload)


async def _request_workflow_approval(
    store: InMemoryStateStore,
    *,
    quorum: int = 2,
    requester_principal: str = "requester-1",
) -> Any:
    provider = StateStoreWorkflowApprovalProvider(store=store)
    return await provider.ensure_requested(
        process_id="process-1",
        step_id="board_approval",
        correlation_id="correlation-1",
        target_resource_id="resource-1",
        requester_principal=requester_principal,
        required_role="approver",
        quorum=quorum,
        no_self_approval=True,
        timeout_seconds=3_600,
        requested_at=_NOW,
    )


def _operator_decision_payload(
    *,
    approval_id: str,
    idempotency_key: str,
    approver_oid: str,
    decision: OperatorDecision = OperatorDecision.APPROVE,
    justification: str = "Independent review complete.",
) -> dict[str, object]:
    """Build the exact payload the Operator durable outbox publishes."""
    return hil_decision_payload(
        OperatorReceipt(
            approval_id=approval_id,
            idempotency_key=idempotency_key,
            decision=decision,
            approver_oid=approver_oid,
            decided_at=_NOW,
            receipt_ref=f"operator-receipt:{approval_id}",
            justification=justification,
        )
    )


async def _drain(
    bus: InMemoryEventBus,
    coordinator: Any,
    registry: StateStoreHilApprovalRegistry | None,
) -> None:
    await _consume_hil_decisions(
        bus=bus,
        topic=_TOPIC,
        coordinator=coordinator,
        stop=asyncio.Event(),
        workflow_registry=registry,
    )


async def _dead_letters(bus: InMemoryEventBus) -> list[dict[str, Any]]:
    return [dict(item.payload) async for item in bus.subscribe(f"{_TOPIC}.dlq", "reader")]


@pytest.mark.asyncio
async def test_two_distinct_approvals_fill_quorum_without_touching_the_executor_path() -> None:
    store = InMemoryStateStore()
    registry = StateStoreHilApprovalRegistry(store=store, clock=lambda: _NOW)
    coordinator = _RefusingCoordinator(store)
    await _request_workflow_approval(store)
    slots = [
        await registry.get_pending_by_approval_id(str(slot["approval_id"]))
        for slot in _slots(store)
    ]
    assert all(item is not None for item in slots)

    bus = InMemoryEventBus()
    for pending, approver in zip(slots, ("approver-a", "approver-b"), strict=True):
        assert pending is not None
        await _publish_recorded(
            bus,
            store,
            _operator_decision_payload(
                approval_id=pending.approval_id,
                idempotency_key=pending.idempotency_key,
                approver_oid=approver,
            ),
        )
    await _drain(bus, coordinator, registry)

    record = await store.read_state(_workflow_state_key(store))
    assert record is not None
    claims = record["decision_claims"]
    assert len(claims) == 2
    assert {claim["principal"] for claim in claims.values()} == {"approver-a", "approver-b"}
    assert {claim["decision"] for claim in claims.values()} == {"approved"}
    assert {claim["justification"] for claim in claims.values()} == {"Independent review complete."}
    assert {claim["decided_at"] for claim in claims.values()} == {_NOW.isoformat()}
    assert coordinator.calls == []
    assert await _dead_letters(bus) == []


@pytest.mark.asyncio
async def test_requester_self_approval_is_refused_by_the_quorum_owner() -> None:
    store = InMemoryStateStore()
    registry = StateStoreHilApprovalRegistry(store=store, clock=lambda: _NOW)
    coordinator = _RefusingCoordinator(store)
    await _request_workflow_approval(store, requester_principal="requester-1")
    pending = await registry.get_pending_by_approval_id(str(_slots(store)[0]["approval_id"]))
    assert pending is not None

    bus = InMemoryEventBus()
    await _publish_recorded(
        bus,
        store,
        _operator_decision_payload(
            approval_id=pending.approval_id,
            idempotency_key=pending.idempotency_key,
            approver_oid="Requester-1",
        ),
    )
    await _drain(bus, coordinator, registry)

    record = await store.read_state(_workflow_state_key(store))
    assert record is not None
    assert record.get("decision_claims", {}) == {}
    assert coordinator.calls == []
    dead_letters = await _dead_letters(bus)
    assert dead_letters[0]["reason"] == ("hil_decision_consume_error:HilSelfApprovalForbiddenError")


@pytest.mark.asyncio
async def test_duplicate_workflow_decision_delivery_is_idempotent() -> None:
    store = InMemoryStateStore()
    registry = StateStoreHilApprovalRegistry(store=store, clock=lambda: _NOW)
    coordinator = _RefusingCoordinator(store)
    await _request_workflow_approval(store)
    pending = await registry.get_pending_by_approval_id(str(_slots(store)[0]["approval_id"]))
    assert pending is not None
    payload = _operator_decision_payload(
        approval_id=pending.approval_id,
        idempotency_key=pending.idempotency_key,
        approver_oid="approver-a",
    )

    bus = InMemoryEventBus()
    await _publish_recorded(bus, store, payload)
    await bus.publish(_TOPIC, pending.approval_id, dict(payload))
    await _drain(bus, coordinator, registry)

    record = await store.read_state(_workflow_state_key(store))
    assert record is not None
    assert len(record["decision_claims"]) == 1
    assert record["revision"] == 2
    assert coordinator.calls == []
    assert await _dead_letters(bus) == []


@pytest.mark.asyncio
async def test_conflicting_workflow_decision_is_dead_lettered() -> None:
    store = InMemoryStateStore()
    registry = StateStoreHilApprovalRegistry(store=store, clock=lambda: _NOW)
    coordinator = _RefusingCoordinator(store)
    await _request_workflow_approval(store)
    pending = await registry.get_pending_by_approval_id(str(_slots(store)[0]["approval_id"]))
    assert pending is not None

    bus = InMemoryEventBus()
    await _publish_recorded(
        bus,
        store,
        _operator_decision_payload(
            approval_id=pending.approval_id,
            idempotency_key=pending.idempotency_key,
            approver_oid="approver-a",
        ),
    )
    # The Operator refuses to record a second, conflicting decision, so only the
    # first one has a receipt; the unrecorded reject is transport without authority.
    await bus.publish(
        _TOPIC,
        pending.approval_id,
        _operator_decision_payload(
            approval_id=pending.approval_id,
            idempotency_key=pending.idempotency_key,
            approver_oid="approver-a",
            decision=OperatorDecision.REJECT,
        ),
    )
    await _drain(bus, coordinator, registry)

    dead_letters = await _dead_letters(bus)
    assert dead_letters[0]["reason"] == "hil_decision_receipt_refused:decision_mismatch"
    record = await store.read_state(_workflow_state_key(store))
    assert record is not None
    assert [claim["decision"] for claim in record["decision_claims"].values()] == ["approved"]
    assert coordinator.calls == []


@pytest.mark.asyncio
async def test_one_principal_cannot_occupy_two_quorum_slots() -> None:
    store = InMemoryStateStore()
    registry = StateStoreHilApprovalRegistry(store=store, clock=lambda: _NOW)
    coordinator = _RefusingCoordinator(store)
    await _request_workflow_approval(store)
    slots = _slots(store)

    bus = InMemoryEventBus()
    for slot in slots:
        pending = await registry.get_pending_by_approval_id(str(slot["approval_id"]))
        assert pending is not None
        await _publish_recorded(
            bus,
            store,
            _operator_decision_payload(
                approval_id=pending.approval_id,
                idempotency_key=pending.idempotency_key,
                approver_oid="approver-a",
            ),
        )
    await _drain(bus, coordinator, registry)

    record = await store.read_state(_workflow_state_key(store))
    assert record is not None
    assert len(record["decision_claims"]) == 1
    dead_letters = await _dead_letters(bus)
    assert dead_letters[0]["reason"] == "hil_decision_consume_error:HilDuplicateApproverError"


@pytest.mark.asyncio
async def test_action_parks_still_resume_through_the_coordinator() -> None:
    store = InMemoryStateStore()
    registry = StateStoreHilApprovalRegistry(store=store, clock=lambda: _NOW)
    coordinator = _RecordingCoordinator(store)
    await store.write_state(
        "hil_park:action-approval-1",
        {
            "status": "pending",
            "approval_id": "action-approval-1",
            "idempotency_key": "action-key-1",
            "submitter_oid": "submitter-1",
            "correlation_id": "correlation-2",
            "metadata": {"decision_route": "action"},
            "approval_context": {
                "expires_at": (_NOW + timedelta(minutes=30)).isoformat(),
            },
        },
    )

    bus = InMemoryEventBus()
    await _publish_recorded(
        bus,
        store,
        _operator_decision_payload(
            approval_id="action-approval-1",
            idempotency_key="action-key-1",
            approver_oid="approver-a",
        ),
    )
    await _drain(bus, coordinator, registry)

    assert len(coordinator.calls) == 1
    assert coordinator.calls[0]["approval_id"] == "action-approval-1"
    assert coordinator.calls[0]["reason"] == "Independent review complete."
    assert await _dead_letters(bus) == []


@pytest.mark.asyncio
async def test_unknown_approval_never_routes_to_the_quorum_owner() -> None:
    """An approval with no durable park keeps the audited coordinator outcome."""
    store = InMemoryStateStore()
    registry = StateStoreHilApprovalRegistry(store=store, clock=lambda: _NOW)
    coordinator = _RecordingCoordinator(store)

    bus = InMemoryEventBus()
    await _publish_recorded(
        bus,
        store,
        _operator_decision_payload(
            approval_id="missing-approval",
            idempotency_key="missing-key",
            approver_oid="approver-a",
        ),
    )
    await _drain(bus, coordinator, registry)

    assert await registry.get_decision_route("missing-approval") == ""
    assert len(coordinator.calls) == 1


async def _park_action(store: InMemoryStateStore, approval_id: str = "action-approval-1") -> None:
    await store.write_state(
        f"hil_park:{approval_id}",
        {
            "status": "pending",
            "approval_id": approval_id,
            "idempotency_key": "action-key-1",
            "submitter_oid": "submitter-1",
            "correlation_id": "correlation-2",
            "metadata": {"decision_route": "action"},
            "approval_context": {
                "expires_at": (_NOW + timedelta(minutes=30)).isoformat(),
            },
        },
    )


@pytest.mark.asyncio
async def test_approval_without_a_durable_receipt_is_refused_before_dispatch() -> None:
    store = InMemoryStateStore()
    registry = StateStoreHilApprovalRegistry(store=store, clock=lambda: _NOW)
    coordinator = _RecordingCoordinator(store)
    await _park_action(store)

    bus = InMemoryEventBus()
    await bus.publish(
        _TOPIC,
        "action-approval-1",
        _operator_decision_payload(
            approval_id="action-approval-1",
            idempotency_key="action-key-1",
            approver_oid="approver-a",
        ),
    )
    await _drain(bus, coordinator, registry)

    assert coordinator.calls == []
    parked = await store.read_state("hil_park:action-approval-1")
    assert parked is not None and parked["status"] == "pending"
    dead_letters = await _dead_letters(bus)
    assert [item["reason"] for item in dead_letters] == [
        "hil_decision_receipt_refused:receipt_missing"
    ]


@pytest.mark.parametrize(
    ("published", "reason"),
    [
        ({"approver_oid": "approver-b"}, "approver_mismatch"),
        ({"decision": "approve", "recorded_decision": "reject"}, "decision_mismatch"),
        ({"idempotency_key": "other-key"}, "identity_mismatch"),
        ({"receipt_ref": "operator-receipt:forged"}, "identity_mismatch"),
        ({"justification": "Forged reason."}, "justification_mismatch"),
        ({"decided_at": "2026-08-31T12:05:00+00:00"}, "decided_at_mismatch"),
        ({"development_attestation": {"approval_id": "action-approval-1"}}, "attestation_mismatch"),
    ],
)
@pytest.mark.asyncio
async def test_published_decision_that_diverges_from_its_receipt_is_refused(
    published: dict[str, object],
    reason: str,
) -> None:
    store = InMemoryStateStore()
    registry = StateStoreHilApprovalRegistry(store=store, clock=lambda: _NOW)
    coordinator = _RecordingCoordinator(store)
    await _park_action(store)
    recorded_decision = published.pop("recorded_decision", None)
    recorded = _operator_decision_payload(
        approval_id="action-approval-1",
        idempotency_key="action-key-1",
        approver_oid="approver-a",
        decision=(
            OperatorDecision(str(recorded_decision))
            if recorded_decision is not None
            else OperatorDecision.APPROVE
        ),
    )
    await _record_receipt(store, recorded)

    bus = InMemoryEventBus()
    await bus.publish(_TOPIC, "action-approval-1", {**recorded, **published})
    await _drain(bus, coordinator, registry)

    assert coordinator.calls == []
    dead_letters = await _dead_letters(bus)
    assert [item["reason"] for item in dead_letters] == [f"hil_decision_receipt_refused:{reason}"]


class _FlakyReceiptCoordinator(_RecordingCoordinator):
    def __init__(self, store: InMemoryStateStore, failures: int) -> None:
        super().__init__(store)
        self.failures = failures
        self.reads = 0

    async def read_operator_decision_receipt(self, approval_id: str) -> Any:
        self.reads += 1
        if self.reads <= self.failures:
            raise RuntimeError("state store unavailable")
        return await super().read_operator_decision_receipt(approval_id)


@pytest.mark.asyncio
async def test_unreadable_receipt_is_never_acknowledged_or_routed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(consumers_module, "_RECEIPT_READ_BACKOFF_SECONDS", 0.0)
    store = InMemoryStateStore()
    registry = StateStoreHilApprovalRegistry(store=store, clock=lambda: _NOW)
    coordinator = _UnreadableReceiptCoordinator(store)
    await _park_action(store)

    bus = InMemoryEventBus()
    await _publish_recorded(
        bus,
        store,
        _operator_decision_payload(
            approval_id="action-approval-1",
            idempotency_key="action-key-1",
            approver_oid="approver-a",
        ),
    )
    with pytest.raises(consumers_module.HilDecisionReceiptUnavailableError):
        await _drain(bus, coordinator, registry)

    assert coordinator.calls == []
    assert await _dead_letters(bus) == []


@pytest.mark.asyncio
async def test_transient_receipt_failure_is_retried_before_routing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(consumers_module, "_RECEIPT_READ_BACKOFF_SECONDS", 0.0)
    store = InMemoryStateStore()
    registry = StateStoreHilApprovalRegistry(store=store, clock=lambda: _NOW)
    coordinator = _FlakyReceiptCoordinator(store, failures=2)
    await _park_action(store)

    bus = InMemoryEventBus()
    await _publish_recorded(
        bus,
        store,
        _operator_decision_payload(
            approval_id="action-approval-1",
            idempotency_key="action-key-1",
            approver_oid="approver-a",
        ),
    )
    await _drain(bus, coordinator, registry)

    assert coordinator.reads == 3
    assert [call["approval_id"] for call in coordinator.calls] == ["action-approval-1"]
    assert await _dead_letters(bus) == []


@pytest.mark.asyncio
async def test_unrecorded_workflow_approval_never_fills_a_quorum_slot() -> None:
    store = InMemoryStateStore()
    registry = StateStoreHilApprovalRegistry(store=store, clock=lambda: _NOW)
    coordinator = _RefusingCoordinator(store)
    await _request_workflow_approval(store)
    pending = await registry.get_pending_by_approval_id(str(_slots(store)[0]["approval_id"]))
    assert pending is not None

    bus = InMemoryEventBus()
    await bus.publish(
        _TOPIC,
        pending.approval_id,
        _operator_decision_payload(
            approval_id=pending.approval_id,
            idempotency_key=pending.idempotency_key,
            approver_oid="approver-a",
        ),
    )
    await _drain(bus, coordinator, registry)

    record = await store.read_state(_workflow_state_key(store))
    assert record is not None
    assert record.get("decision_claims", {}) == {}
    assert coordinator.calls == []
    dead_letters = await _dead_letters(bus)
    assert [item["reason"] for item in dead_letters] == [
        "hil_decision_receipt_refused:receipt_missing"
    ]


def _slots(store: InMemoryStateStore) -> list[dict[str, Any]]:
    for key, value in _state_items(store):
        if key.startswith("workflow:approval:"):
            return [dict(slot) for slot in value["slots"]]
    raise AssertionError("workflow approval record was not persisted")


def _workflow_state_key(store: InMemoryStateStore) -> str:
    for key, _value in _state_items(store):
        if key.startswith("workflow:approval:"):
            return key
    raise AssertionError("workflow approval record was not persisted")


def _state_items(store: InMemoryStateStore) -> list[tuple[str, Any]]:
    values = getattr(store, "_state", None)
    if values is None:  # pragma: no cover - in-memory store contract
        raise AssertionError("in-memory state store does not expose its records")
    return list(values.items())
