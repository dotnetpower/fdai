from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai_service_contracts.kill_switch import (
    KillSwitchRequestBody,
    KillSwitchRequestEvent,
)
from fdai_service_contracts.operator_authentication import (
    OperatorAuthenticationEvidenceClass,
    OperatorAuthenticationReceipt,
)
from pydantic import ValidationError


def _authentication_receipt(now: datetime) -> OperatorAuthenticationReceipt:
    return OperatorAuthenticationReceipt.create(
        evidence_class=OperatorAuthenticationEvidenceClass.LIVE,
        issuer="https://login.example.com/issuer",
        audience="api://example",
        tenant_digest="sha256:" + "a" * 64,
        subject_id="owner@example.com",
        principal_kind="human",
        groups=(),
        token_id_digest="sha256:" + "b" * 64,
        issued_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(minutes=9),
        roles=("Owner",),
        role_mapping_revision="sha256:" + "c" * 64,
    )


def test_kill_switch_request_binds_identity_state_and_digest() -> None:
    now = datetime(2026, 10, 16, 9, 0, tzinfo=UTC)
    body = KillSwitchRequestBody(
        engaged=True,
        reason="Bounded development containment drill.",
    )
    event = KillSwitchRequestEvent.create(
        body=body,
        request_id="request-1",
        correlation_id="kill-switch:request-1",
        idempotency_key="request-1",
        initiator_principal="owner@example.com",
        requested_at=now,
        authentication_receipt=_authentication_receipt(now),
        operator_request_receipt=None,
    )

    assert event.accountable_agent == "Var"
    assert event.execution_authority is False
    assert event.authentication_receipt_ref == event.authentication_receipt.receipt_digest
    assert event.request_digest.startswith("sha256:")
    assert (
        event.operator_receipt_event(
            body=body,
            correlation_id=event.correlation_id,
            idempotency_key=event.idempotency_key,
            initiator_principal=event.initiator_principal,
            requested_at=event.requested_at,
            authenticated_at=now,
            principal_roles=frozenset({"Owner"}),
        )["action_type"]
        == "system.kill-switch.set-state"
    )


def test_kill_switch_request_rejects_digest_tampering() -> None:
    now = datetime(2026, 10, 16, 9, 0, tzinfo=UTC)
    event = KillSwitchRequestEvent.create(
        body=KillSwitchRequestBody(
            engaged=True,
            reason="Bounded development containment drill.",
        ),
        request_id="request-1",
        correlation_id="kill-switch:request-1",
        idempotency_key="request-1",
        initiator_principal="owner@example.com",
        requested_at=now,
        authentication_receipt=_authentication_receipt(now),
        operator_request_receipt=None,
    )
    payload = event.model_dump(mode="json")
    payload["engaged"] = False

    with pytest.raises(ValidationError, match="request digest mismatched"):
        KillSwitchRequestEvent.model_validate(payload)
