"""Huginn authenticated operator-request ingress tests."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.huginn_operator_receipt import OperatorRequestReceiptGate
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.huginn import Huginn, HuginnIngressRejected
from fdai.delivery.operator_request_receipt import core_operator_request_receipt_issuer_from_env
from fdai.runtime.bootstrap_pantheon import _operator_request_receipt_gate
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.operator_request_receipt import (
    OperatorRequestReceipt,
    operator_request_public_key_from_seed,
    operator_request_receipt_body_from_event,
    operator_request_receipt_signing_bytes,
    sign_operator_request_receipt,
)


class _Verifier:
    def __init__(self, *, accepted: bytes | None = None) -> None:
        self.accepted = accepted
        self.calls: list[bytes] = []

    def verify_operator_request_receipt(
        self,
        *,
        receipt: OperatorRequestReceipt,
        signing_bytes: bytes,
    ) -> bool:
        del receipt
        self.calls.append(signing_bytes)
        return self.accepted is None or signing_bytes == self.accepted


class _FailFirstPublishBus(InMemoryBus):
    def __init__(self) -> None:
        super().__init__(load_pantheon())
        self.failures_remaining = 1

    async def publish(self, principal: str, topic: str, payload: dict[str, Any]) -> None:
        if self.failures_remaining:
            self.failures_remaining -= 1
            raise RuntimeError("transient broker failure before durable publish")
        await super().publish(principal, topic, payload)


class _ReserveExpiredGate:
    async def verify(self, raw: Mapping[str, Any]) -> object:
        receipt = OperatorRequestReceipt.model_validate(raw["operator_request_receipt"])
        return type("Verified", (), {"receipt": receipt, "replay_key": "replay-key"})()

    async def reserve(self, _verified: object) -> object:
        raise ValueError("expired")


_CORE_SEED = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
_OPERATOR_SEED = "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE"


def _request(now: datetime) -> dict[str, Any]:
    return {
        "idempotency_key": "operator-request:one",
        "correlation_id": "conversation-one",
        "initiator_principal": "operator-one",
        "operator_initiated": True,
        "action_type": "ops.scale-out",
        "resource_id": "resource:service/api",
        "event_type": "operator_request",
        "params": {"replicas": 3},
        "source": "operator-service",
        "operator_request_receipt": _receipt(
            {
                "idempotency_key": "operator-request:one",
                "correlation_id": "conversation-one",
                "initiator_principal": "operator-one",
                "action_type": "ops.scale-out",
                "resource_id": "resource:service/api",
                "params": {"replicas": 3},
            },
            now=now,
        ).model_dump(mode="json"),
    }


def _receipt(
    event: Mapping[str, Any],
    *,
    now: datetime,
) -> OperatorRequestReceipt:
    body = operator_request_receipt_body_from_event(
        event,
        producer_service_identity="operator-service",
        issued_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    return OperatorRequestReceipt.create(body=body, signature=b"test-signature")


def _gate(now: datetime, verifier: _Verifier | None = None) -> OperatorRequestReceiptGate:
    return OperatorRequestReceiptGate(
        verifier=verifier or _Verifier(),
        state_store=InMemoryStateStore(),
        clock=lambda: now,
    )


async def test_huginn_accepts_only_authenticated_ingress_receipt_before_publish() -> None:
    now = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
    request = _request(now)
    body = operator_request_receipt_body_from_event(
        request,
        producer_service_identity="operator-service",
        issued_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    verifier = _Verifier(accepted=operator_request_receipt_signing_bytes(body))
    bus = InMemoryBus(load_pantheon())
    huginn = Huginn(bus=bus, operator_request_receipt_gate=_gate(now, verifier))

    normalized = await huginn.ingest(request)

    assert normalized is not None
    assert normalized["operator_request_channel"] == "ingress"
    assert normalized["initiator_principal"] == "operator-one"
    assert len(bus.messages_on("object.event")) == 1
    assert verifier.calls == [operator_request_receipt_signing_bytes(body)]


async def test_core_bootstrap_derives_trusted_producer_keys_from_configured_seeds() -> None:
    now = datetime.now(UTC)
    gate = _operator_request_receipt_gate(
        {
            "FDAI_OPERATOR_REQUEST_CORE_SIGNING_SEED": _CORE_SEED,
            "FDAI_OPERATOR_REQUEST_OPERATOR_TRUST_SEED": _OPERATOR_SEED,
            "FDAI_OPERATOR_REQUEST_CORE_PRODUCER_ID": "core-control-plane",
            "FDAI_OPERATOR_REQUEST_OPERATOR_PRODUCER_ID": "operator-service",
        },
        InMemoryStateStore(),
    )

    assert gate is not None
    assert gate.trusted_producer_public_keys == {
        "core-control-plane": operator_request_public_key_from_seed(_CORE_SEED),
        "operator-service": operator_request_public_key_from_seed(_OPERATOR_SEED),
    }

    request = _request(now)
    request["operator_request_receipt"] = sign_operator_request_receipt(
        request,
        producer_service_identity="operator-service",
        private_key_seed=_OPERATOR_SEED,
        issued_at=now,
        expires_at=now + timedelta(minutes=5),
    ).model_dump(mode="json")
    assert await Huginn(operator_request_receipt_gate=gate, clock=lambda: now).ingest(request)


def test_core_signer_refuses_non_core_producer_identity() -> None:
    with pytest.raises(RuntimeError, match="MUST sign as core-control-plane"):
        core_operator_request_receipt_issuer_from_env(
            {
                "FDAI_OPERATOR_REQUEST_CORE_SIGNING_SEED": _CORE_SEED,
                "FDAI_OPERATOR_REQUEST_CORE_PRODUCER_ID": "operator-service",
            }
        )


async def test_huginn_rejects_unbound_ingress_receipt_before_publication() -> None:
    bus = InMemoryBus(load_pantheon())
    huginn = Huginn(bus=bus)

    with pytest.raises(HuginnIngressRejected) as exc:
        await huginn.ingest(_request(datetime(2026, 10, 1, 0, 0, tzinfo=UTC)))

    assert exc.value.reason_code == "operator_request_receipt_unbound"
    assert bus.messages_on("object.event") == []


async def test_huginn_rejects_mismatched_expired_unverifiable_and_replayed_receipts() -> None:
    now = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
    mismatched = _request(now)
    mismatched["resource_id"] = "resource:service/other"
    with pytest.raises(HuginnIngressRejected) as mismatch:
        await Huginn(operator_request_receipt_gate=_gate(now)).ingest(mismatched)
    assert mismatch.value.reason_code == "operator_request_receipt_mismatch"

    expired_now = now + timedelta(minutes=6)
    with pytest.raises(HuginnIngressRejected) as expired:
        await Huginn(operator_request_receipt_gate=_gate(expired_now)).ingest(_request(now))
    assert expired.value.reason_code == "operator_request_receipt_expired"

    with pytest.raises(HuginnIngressRejected) as unverifiable:
        await Huginn(operator_request_receipt_gate=_gate(now, _Verifier(accepted=b"other"))).ingest(
            _request(now)
        )
    assert unverifiable.value.reason_code == "operator_request_receipt_unverifiable"

    gate = _gate(now)
    huginn = Huginn(operator_request_receipt_gate=gate)
    assert await huginn.ingest(_request(now)) is not None
    with pytest.raises(HuginnIngressRejected) as replayed:
        await huginn.ingest(_request(now))
    assert replayed.value.reason_code == "operator_request_receipt_replayed"


async def test_huginn_retries_receipt_when_publish_fails_before_durable_checkpoint() -> None:
    now = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
    gate = _gate(now)
    bus = _FailFirstPublishBus()
    huginn = Huginn(bus=bus, operator_request_receipt_gate=gate, clock=lambda: now)

    with pytest.raises(RuntimeError, match="transient broker failure"):
        await huginn.ingest(_request(now))

    normalized = await huginn.ingest(_request(now))

    assert normalized is not None
    assert len(bus.messages_on("object.event")) == 1


async def test_huginn_rejects_operator_request_when_receipt_reservation_fails_before_publish() -> (
    None
):
    now = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
    bus = InMemoryBus(load_pantheon())
    huginn = Huginn(
        bus=bus,
        operator_request_receipt_gate=_ReserveExpiredGate(),  # type: ignore[arg-type]
        clock=lambda: now,
    )

    with pytest.raises(HuginnIngressRejected) as exc:
        await huginn.ingest(_request(now))

    assert exc.value.reason_code == "operator_request_receipt_expired"
    assert bus.messages_on("object.event") == []


async def test_huginn_rejects_mutated_workflow_action_lineage() -> None:
    now = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
    request = _request(now)
    request["workflow_action"] = {
        "process_id": "process-one",
        "step_id": "restart",
        "proposal_ref": "process-one:step:restart:attempt:1",
        "attempt": 1,
    }
    request["operator_request_receipt"] = _receipt(request, now=now).model_dump(mode="json")
    mutated = dict(request)
    mutated["workflow_action"] = {
        "process_id": "evil",
        "step_id": "restart",
        "proposal_ref": "evil-ref",
        "attempt": 99,
    }

    assert await Huginn(operator_request_receipt_gate=_gate(now), clock=lambda: now).ingest(request)
    with pytest.raises(HuginnIngressRejected) as exc:
        await Huginn(operator_request_receipt_gate=_gate(now), clock=lambda: now).ingest(mutated)

    assert exc.value.reason_code == "operator_request_receipt_mismatch"


async def test_huginn_rejects_absent_to_empty_workflow_action_mutation() -> None:
    now = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
    request = _request(now)
    mutated = dict(request)
    mutated["workflow_action"] = {}

    with pytest.raises(HuginnIngressRejected) as exc:
        await Huginn(operator_request_receipt_gate=_gate(now), clock=lambda: now).ingest(mutated)

    assert exc.value.reason_code == "operator_request_receipt_mismatch"


async def test_receipt_replay_cleanup_expires_rows_and_retains_summary() -> None:
    current = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
    store = InMemoryStateStore()

    def clock() -> datetime:
        return current

    gate = OperatorRequestReceiptGate(
        verifier=_Verifier(),
        state_store=store,
        clock=clock,
        cleanup_limit=10,
    )
    replayed_request: dict[str, Any] | None = None
    for index in range(3):
        request = _request(current)
        request["idempotency_key"] = f"operator-request:{index}"
        request["operator_request_receipt"] = _receipt(request, now=current).model_dump(mode="json")
        await gate.commit(await gate.verify(request))
        if index == 1:
            replayed_request = request

    with pytest.raises(ValueError, match="replayed"):
        assert replayed_request is not None
        await gate.verify(replayed_request)

    current = current + timedelta(minutes=8)
    assert await gate.cleanup_expired() == 3
    assert await store.read_states("pantheon/huginn/operator-request-receipts/", limit=10) == ()
    summary = await store.read_state("pantheon/huginn/operator-request-receipt-summary")
    assert summary is not None
    assert summary["expired_rows"] == 3


async def test_schema_learning_publishes_inert_idempotent_evidence_without_normalizing_change() -> (
    None
):
    now = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
    store = InMemoryStateStore()
    bus = InMemoryBus(load_pantheon())
    raw = {
        "idempotency_key": "event-one",
        "correlation_id": "corr-one",
        "event_type": "inventory.resource_changed",
        "source": "provider",
        "resource_id": "resource-one",
        "attributes": {"status": "ready"},
    }
    disabled = await Huginn(clock=lambda: now).ingest(dict(raw))
    enabled = await Huginn(
        state_store=InMemoryStateStore(),
        schema_learning_enabled=True,
        clock=lambda: now,
    ).ingest(dict(raw))

    assert enabled == disabled

    learner = Huginn(bus=bus, state_store=store, schema_learning_enabled=True, clock=lambda: now)
    assert await learner.ingest(dict(raw)) == enabled
    await learner.maintenance_tick()
    evidence = [
        message.payload
        for message in bus.messages_on("object.event")
        if message.payload.get("event_type") == "schema_cluster.evidence"
    ]
    assert len(evidence) == 1
    assert evidence[0]["event_type"] == "schema_cluster.evidence"
    assert evidence[0]["authority"] == "inert_evidence_only"
    assert evidence[0]["normalization_changed"] is False

    restarted = Huginn(bus=bus, state_store=store, schema_learning_enabled=True, clock=lambda: now)
    replay_schema = dict(raw)
    replay_schema["idempotency_key"] = "event-two"
    replay_schema["resource_id"] = "resource-two"
    assert await restarted.ingest(replay_schema) is not None
    await restarted.maintenance_tick()
    assert [
        message.payload
        for message in bus.messages_on("object.event")
        if message.payload.get("event_type") == "schema_cluster.evidence"
    ] == evidence


async def test_schema_learning_ignores_rejected_operator_request_shapes() -> None:
    now = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
    bus = InMemoryBus(load_pantheon())
    huginn = Huginn(
        bus=bus,
        state_store=InMemoryStateStore(),
        schema_learning_enabled=True,
        operator_request_receipt_gate=_gate(now, _Verifier(accepted=b"other")),
        clock=lambda: now,
    )
    rejected = _request(now)
    rejected["attacker_controlled_schema_probe"] = {"nested": True}

    with pytest.raises(HuginnIngressRejected) as exc:
        await huginn.ingest(rejected)
    await huginn.maintenance_tick()

    assert exc.value.reason_code == "operator_request_receipt_unverifiable"
    assert [
        message.payload
        for message in bus.messages_on("object.event")
        if message.payload.get("event_type") == "schema_cluster.evidence"
    ] == []
    assert huginn.health()["schema_learning"]["pending_fingerprints"] == 0


async def test_schema_learning_state_stays_bounded_under_adversarial_inputs() -> None:
    learner = Huginn(state_store=InMemoryStateStore(), schema_learning_enabled=True)
    for index in range(200):
        await learner.ingest(
            {
                "idempotency_key": f"event-{index}",
                "event_type": "generic",
                "source": "provider",
                "resource_id": f"resource-{index}",
                "attributes": {"index": index},
                f"field_{index}": "value",
            }
        )

    assert learner.health()["schema_learning"]["pending_fingerprints"] == 128
