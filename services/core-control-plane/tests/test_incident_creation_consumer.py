"""Focused Core consumption checks for confirmed Incident creation requests."""

from __future__ import annotations

import asyncio
import base64
import logging
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import NAMESPACE_URL, uuid5

import pytest
from fdai.agents import OperatorRequestReceiptGate
from fdai.core.incident import IncidentLifecycleWorkflow, IncidentRegistry
from fdai.shared.providers.event_bus import EventEnvelope
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_core_service.incident_creation_consumer import consume_incident_creations
from fdai_service_contracts.incident_creation import (
    INCIDENT_CREATION_CONSUMER_GROUP,
    INCIDENT_CREATION_REQUEST_TOPIC,
    IncidentCreationArguments,
    IncidentCreationRequest,
    attach_incident_creation_receipt,
    build_incident_creation_request,
    incident_creation_receipt_event,
)
from fdai_service_contracts.operator import OperatorRole
from fdai_service_contracts.operator_request_receipt import (
    operator_request_public_key_from_seed,
    sign_operator_request_receipt,
)

NOW = datetime(2026, 9, 16, 2, 5, tzinfo=UTC)
DIGEST = "sha256:" + "a" * 64
SOURCE_REQUEST_ID = str(uuid5(NAMESPACE_URL, "fdai.test.incident-creation.request"))
SOURCE_PROJECTION_ID = str(uuid5(NAMESPACE_URL, "fdai.test.incident-creation.projection"))
SEED = base64.urlsafe_b64encode(bytes(range(32))).decode("ascii").rstrip("=")


class _Stream:
    def __init__(self, events: list[EventEnvelope]) -> None:
        self._events = iter(events)
        self.closed = False

    def __aiter__(self) -> _Stream:
        return self

    async def __anext__(self) -> EventEnvelope:
        try:
            return next(self._events)
        except StopIteration as exc:
            raise StopAsyncIteration from exc

    async def aclose(self) -> None:
        self.closed = True


class _Bus:
    def __init__(self, events: list[EventEnvelope]) -> None:
        self.stream = _Stream(events)
        self.dead_letters: list[tuple[str, str]] = []

    def subscribe(self, topic: str, group_id: str) -> _Stream:
        assert topic == INCIDENT_CREATION_REQUEST_TOPIC
        assert group_id == INCIDENT_CREATION_CONSUMER_GROUP
        return self.stream

    async def dead_letter(
        self,
        topic: str,
        key: str,
        payload: object,
        reason: str,
    ) -> None:
        del topic, payload
        self.dead_letters.append((key, reason))


def _request_payload(
    *,
    source_request_id: str = SOURCE_REQUEST_ID,
    source_projection_id: str = SOURCE_PROJECTION_ID,
    idempotency_key: str = "draft-one",
) -> dict[str, object]:
    return build_incident_creation_request(
        request_id=source_request_id,
        source_request_id=source_request_id,
        source_projection_id=source_projection_id,
        principal_id="operator-one",
        principal_roles=(OperatorRole.CONTRIBUTOR,),
        idempotency_key=idempotency_key,
        session_id="session-one",
        arguments=IncidentCreationArguments(severity="sev2", target="service-api"),
        source_input_digest=DIGEST,
        draft_digest="sha256:" + "b" * 64,
        draft_expires_at=datetime(2026, 9, 16, 2, 10, tzinfo=UTC),
        confirmed_at=NOW,
    ).model_dump(mode="json")


def _request(
    *,
    source_request_id: str = SOURCE_REQUEST_ID,
    source_projection_id: str = SOURCE_PROJECTION_ID,
    principal_roles: tuple[OperatorRole, ...] = (OperatorRole.CONTRIBUTOR,),
    idempotency_key: str = "draft-one",
) -> IncidentCreationRequest:
    return build_incident_creation_request(
        request_id=source_request_id,
        source_request_id=source_request_id,
        source_projection_id=source_projection_id,
        principal_id="operator-one",
        principal_roles=principal_roles,
        idempotency_key=idempotency_key,
        session_id="session-one",
        arguments=IncidentCreationArguments(severity="sev2", target="service-api"),
        source_input_digest=DIGEST,
        draft_digest="sha256:" + "b" * 64,
        draft_expires_at=datetime(2026, 9, 16, 2, 10, tzinfo=UTC),
        confirmed_at=NOW,
    )


def _signed_payload(
    request: IncidentCreationRequest | None = None,
    *,
    issued_at: datetime = NOW,
    expires_at: datetime = NOW + timedelta(minutes=5),
) -> dict[str, object]:
    unsigned = request or _request()
    receipt = sign_operator_request_receipt(
        incident_creation_receipt_event(unsigned),
        producer_service_identity="operator-service",
        private_key_seed=SEED,
        issued_at=issued_at,
        expires_at=expires_at,
    )
    return attach_incident_creation_receipt(unsigned, receipt).model_dump(mode="json")


def _receipt_gate(
    state_store: InMemoryStateStore, *, now: datetime = NOW
) -> OperatorRequestReceiptGate:
    return OperatorRequestReceiptGate(
        verifier=_Verifier(),
        state_store=state_store,
        clock=lambda: now,
        trusted_producer_public_keys={
            "operator-service": operator_request_public_key_from_seed(SEED)
        },
    )


class _Verifier:
    def verify_operator_request_receipt(self, *, receipt: object, signing_bytes: bytes) -> bool:
        del receipt, signing_bytes
        return False


class _FinalizeFailsOnceGate:
    def __init__(self) -> None:
        self.finalize_calls = 0
        self.release_calls = 0

    async def verify_or_committed(self, event: object) -> object:
        del event
        return object()

    async def reserve(self, verified: object) -> object:
        return verified

    async def finalize(self, reserved: object) -> object:
        del reserved
        self.finalize_calls += 1
        if self.finalize_calls == 1:
            raise ValueError("expired")
        return object()

    async def release(self, reserved: object) -> bool:
        del reserved
        self.release_calls += 1
        return True


async def test_consumer_opens_one_incident_for_redelivered_request() -> None:
    payload = _signed_payload()
    target_ref = str(payload["target_ref"])
    envelope = EventEnvelope(INCIDENT_CREATION_REQUEST_TOPIC, target_ref, payload, 1)
    bus = _Bus([envelope, envelope])
    state_store = InMemoryStateStore()
    registry = IncidentRegistry(state_store=state_store)

    await consume_incident_creations(
        bus=bus,  # type: ignore[arg-type]
        topic=INCIDENT_CREATION_REQUEST_TOPIC,
        group_id=INCIDENT_CREATION_CONSUMER_GROUP,
        workflow=IncidentLifecycleWorkflow(registry=registry),
        receipt_gate=_receipt_gate(state_store),
        stop=asyncio.Event(),
    )

    incidents = tuple(registry.snapshot().values())
    assert len(incidents) == 1
    assert incidents[0].severity.value == "sev2"
    assert bus.dead_letters == []
    assert bus.stream.closed is True
    opens = [
        item for item in state_store.audit_entries if item["entry"].get("kind") == "incident.open"
    ]
    assert len(opens) == 1


async def test_consumer_acknowledges_applied_incident_when_finalize_fails_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    payload = _signed_payload()
    target_ref = str(payload["target_ref"])
    envelope = EventEnvelope(INCIDENT_CREATION_REQUEST_TOPIC, target_ref, payload, 1)
    bus = _Bus([envelope, envelope])
    registry_store = InMemoryStateStore()
    registry = IncidentRegistry(state_store=registry_store)
    gate = _FinalizeFailsOnceGate()

    with caplog.at_level(logging.WARNING):
        await consume_incident_creations(
            bus=bus,  # type: ignore[arg-type]
            topic=INCIDENT_CREATION_REQUEST_TOPIC,
            group_id=INCIDENT_CREATION_CONSUMER_GROUP,
            workflow=IncidentLifecycleWorkflow(registry=registry),
            receipt_gate=cast(OperatorRequestReceiptGate, gate),
            stop=asyncio.Event(),
        )

    incidents = tuple(registry.snapshot().values())
    assert len(incidents) == 1
    assert bus.dead_letters == []
    assert gate.finalize_calls == 2
    assert gate.release_calls == 0
    opens = [
        item
        for item in registry_store.audit_entries
        if item["entry"].get("kind") == "incident.open"
    ]
    assert len(opens) == 1
    assert "incident_creation_applied_but_receipt_fence_unfinalized" in caplog.text


async def test_consumer_dead_letters_a_partition_mismatch() -> None:
    payload = _signed_payload()
    state_store = InMemoryStateStore()
    bus = _Bus(
        [
            EventEnvelope(
                INCIDENT_CREATION_REQUEST_TOPIC,
                "sha256:" + "0" * 64,
                payload,
                1,
            )
        ]
    )
    registry = IncidentRegistry(state_store=InMemoryStateStore())

    await consume_incident_creations(
        bus=bus,  # type: ignore[arg-type]
        topic=INCIDENT_CREATION_REQUEST_TOPIC,
        group_id=INCIDENT_CREATION_CONSUMER_GROUP,
        workflow=IncidentLifecycleWorkflow(registry=registry),
        receipt_gate=_receipt_gate(state_store),
        stop=asyncio.Event(),
    )

    assert registry.snapshot() == {}
    assert bus.dead_letters == [("sha256:" + "0" * 64, "incident_creation_request_rejected")]


async def test_distinct_confirmed_requests_for_one_target_open_distinct_incidents() -> None:
    first = _signed_payload()
    second = _signed_payload(
        _request(
            source_request_id=str(
                uuid5(NAMESPACE_URL, "fdai.test.incident-creation.request.second")
            ),
            source_projection_id=str(
                uuid5(NAMESPACE_URL, "fdai.test.incident-creation.projection.second")
            ),
            idempotency_key="draft-two",
        )
    )
    target_ref = str(first["target_ref"])
    state_store = InMemoryStateStore()
    bus = _Bus(
        [
            EventEnvelope(INCIDENT_CREATION_REQUEST_TOPIC, target_ref, first, 1),
            EventEnvelope(INCIDENT_CREATION_REQUEST_TOPIC, target_ref, second, 2),
        ]
    )
    registry = IncidentRegistry(state_store=InMemoryStateStore())

    await consume_incident_creations(
        bus=bus,  # type: ignore[arg-type]
        topic=INCIDENT_CREATION_REQUEST_TOPIC,
        group_id=INCIDENT_CREATION_CONSUMER_GROUP,
        workflow=IncidentLifecycleWorkflow(registry=registry),
        receipt_gate=_receipt_gate(state_store),
        stop=asyncio.Event(),
    )

    assert len(registry.snapshot()) == 2
    assert bus.dead_letters == []


async def test_consumer_dead_letters_unsigned_request_before_opening_incident() -> None:
    payload = _request_payload()
    target_ref = str(payload["target_ref"])
    bus = _Bus([EventEnvelope(INCIDENT_CREATION_REQUEST_TOPIC, target_ref, payload, 1)])
    state_store = InMemoryStateStore()
    registry = IncidentRegistry(state_store=state_store)

    await consume_incident_creations(
        bus=bus,  # type: ignore[arg-type]
        topic=INCIDENT_CREATION_REQUEST_TOPIC,
        group_id=INCIDENT_CREATION_CONSUMER_GROUP,
        workflow=IncidentLifecycleWorkflow(registry=registry),
        receipt_gate=_receipt_gate(state_store),
        stop=asyncio.Event(),
    )

    assert registry.snapshot() == {}
    assert bus.dead_letters == [(target_ref, "incident_creation_receipt_missing")]


async def test_consumer_dead_letters_when_receipt_gate_is_unconfigured() -> None:
    payload = _signed_payload()
    target_ref = str(payload["target_ref"])
    bus = _Bus([EventEnvelope(INCIDENT_CREATION_REQUEST_TOPIC, target_ref, payload, 1)])
    registry = IncidentRegistry(state_store=InMemoryStateStore())

    await consume_incident_creations(
        bus=bus,  # type: ignore[arg-type]
        topic=INCIDENT_CREATION_REQUEST_TOPIC,
        group_id=INCIDENT_CREATION_CONSUMER_GROUP,
        workflow=IncidentLifecycleWorkflow(registry=registry),
        stop=asyncio.Event(),
    )

    assert registry.snapshot() == {}
    assert bus.dead_letters == [(target_ref, "incident_creation_receipt_gate_unconfigured")]


async def test_consumer_dead_letters_tampered_roles_bound_outside_receipt() -> None:
    signed = IncidentCreationRequest.model_validate(_signed_payload())
    receipt = signed.operator_request_receipt
    assert receipt is not None
    tampered = attach_incident_creation_receipt(
        _request(principal_roles=(OperatorRole.CONTRIBUTOR, OperatorRole.OWNER)),
        receipt,
    ).model_dump(mode="json")
    target_ref = str(tampered["target_ref"])
    bus = _Bus([EventEnvelope(INCIDENT_CREATION_REQUEST_TOPIC, target_ref, tampered, 1)])
    state_store = InMemoryStateStore()
    registry = IncidentRegistry(state_store=state_store)

    await consume_incident_creations(
        bus=bus,  # type: ignore[arg-type]
        topic=INCIDENT_CREATION_REQUEST_TOPIC,
        group_id=INCIDENT_CREATION_CONSUMER_GROUP,
        workflow=IncidentLifecycleWorkflow(registry=registry),
        receipt_gate=_receipt_gate(state_store),
        stop=asyncio.Event(),
    )

    assert registry.snapshot() == {}
    assert bus.dead_letters == [(target_ref, "incident_creation_receipt_mismatch")]


async def test_consumer_dead_letters_expired_receipt_before_opening_incident() -> None:
    payload = _signed_payload(
        issued_at=NOW - timedelta(minutes=10),
        expires_at=NOW - timedelta(minutes=1),
    )
    target_ref = str(payload["target_ref"])
    bus = _Bus([EventEnvelope(INCIDENT_CREATION_REQUEST_TOPIC, target_ref, payload, 1)])
    state_store = InMemoryStateStore()
    registry = IncidentRegistry(state_store=state_store)

    await consume_incident_creations(
        bus=bus,  # type: ignore[arg-type]
        topic=INCIDENT_CREATION_REQUEST_TOPIC,
        group_id=INCIDENT_CREATION_CONSUMER_GROUP,
        workflow=IncidentLifecycleWorkflow(registry=registry),
        receipt_gate=_receipt_gate(state_store),
        stop=asyncio.Event(),
    )

    assert registry.snapshot() == {}
    assert bus.dead_letters == [(target_ref, "incident_creation_receipt_expired")]
