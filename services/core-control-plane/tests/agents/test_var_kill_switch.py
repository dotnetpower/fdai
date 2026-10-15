from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.agents import (
    KillSwitchRequestRejectedError,
    OperatorRequestReceiptGate,
    PantheonRuntime,
    VarKillSwitchRequestHandler,
)
from fdai.core.rbac.kill_switch_command import KillSwitchCommandService
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai.shared.resilience.kill_switch import KILL_SWITCH_STATE_KEY
from fdai_service_contracts.kill_switch import (
    KILL_SWITCH_REQUEST_TOPIC,
    KillSwitchRequestBody,
    KillSwitchRequestEvent,
)
from fdai_service_contracts.operator_authentication import (
    OperatorAuthenticationEvidenceClass,
    OperatorAuthenticationReceipt,
)
from fdai_service_contracts.operator_request_receipt import sign_operator_request_receipt

NOW = datetime(2026, 10, 16, 9, 0, tzinfo=UTC)
SEED = "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA"


class _Verifier:
    def verify_operator_request_receipt(self, *, receipt: object, signing_bytes: bytes) -> bool:
        return bool(receipt and signing_bytes)


def _authentication_receipt(role: str) -> OperatorAuthenticationReceipt:
    return OperatorAuthenticationReceipt.create(
        evidence_class=OperatorAuthenticationEvidenceClass.LIVE,
        issuer="https://login.example.com/issuer",
        audience="api://example",
        tenant_digest="sha256:" + "a" * 64,
        subject_id="owner@example.com",
        principal_kind="human",
        groups=(),
        token_id_digest="sha256:" + "b" * 64,
        issued_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=9),
        roles=(role,),
        role_mapping_revision="sha256:" + "c" * 64,
    )


def _request(role: str = "Owner") -> KillSwitchRequestEvent:
    body = KillSwitchRequestBody(
        engaged=True,
        reason="Bounded development containment drill.",
    )
    correlation_id = "kill-switch:request-1"
    receipt_input = KillSwitchRequestEvent.operator_receipt_event(
        body=body,
        correlation_id=correlation_id,
        idempotency_key="stop-1",
        initiator_principal="owner@example.com",
        requested_at=NOW,
        authenticated_at=NOW,
        principal_roles=frozenset({role}),
    )
    receipt = sign_operator_request_receipt(
        receipt_input,
        producer_service_identity="operator-service:test",
        private_key_seed=SEED,
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
    )
    return KillSwitchRequestEvent.create(
        body=body,
        request_id="request-1",
        correlation_id=correlation_id,
        idempotency_key="stop-1",
        initiator_principal="owner@example.com",
        requested_at=NOW,
        authentication_receipt=_authentication_receipt(role),
        operator_request_receipt=receipt,
    )


def _handler(store: InMemoryStateStore) -> VarKillSwitchRequestHandler:
    return VarKillSwitchRequestHandler(
        service=KillSwitchCommandService(store),
        receipt_gate=OperatorRequestReceiptGate(
            verifier=_Verifier(),
            state_store=store,
            clock=lambda: NOW,
        ),
        operator_producer_service_identity="operator-service:test",
        clock=lambda: NOW,
    )


async def test_var_applies_and_deduplicates_signed_kill_switch_request() -> None:
    store = InMemoryStateStore()
    handler = _handler(store)
    request = _request()

    state = await handler.handle(request.model_dump(mode="json"))
    duplicate = await handler.handle(request.model_dump(mode="json"))

    assert state is not None and state.engaged is True and state.revision == 1
    assert duplicate is None
    persisted = await store.read_state(KILL_SWITCH_STATE_KEY)
    assert persisted is not None
    assert persisted["engaged"] is True
    assert persisted["revision"] == 1


async def test_var_rejects_kill_switch_request_without_owner_or_break_glass_role() -> None:
    store = InMemoryStateStore()

    with pytest.raises(KillSwitchRequestRejectedError, match="operator_role_missing"):
        await _handler(store).handle(_request("Reader").model_dump(mode="json"))

    assert await store.read_state(KILL_SWITCH_STATE_KEY) is None


def test_runtime_subscribes_var_only_when_kill_switch_handler_is_bound() -> None:
    store = InMemoryStateStore()
    unbound = PantheonRuntime.build(
        provider=InMemoryEventBus(),
        raw_event_topic="raw.events",
    )
    bound = PantheonRuntime.build(
        provider=InMemoryEventBus(),
        raw_event_topic="raw.events",
        var_kill_switch_request_handler=_handler(store),
    )

    assert KILL_SWITCH_REQUEST_TOPIC not in unbound.bridge._subs
    assert {name for name, _ in bound.bridge._subs[KILL_SWITCH_REQUEST_TOPIC]} == {"Var"}
