"""The Operator admits an Owner's development self-approval only after a fresh sign-in."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from fdai_operator_service.families.iam.contracts import HilApprovalDecision, HilDecisionReceipt
from fdai_operator_service.families.iam.hil_decision_outbox import (
    hil_decision_payload,
    outbox_payload,
    receipt_from_outbox_payload,
)
from fdai_operator_service.families.iam.hil_development_approval import (
    development_attestation,
    development_metadata,
    development_self_approval_admitted,
)
from fdai_operator_service.postgres_hil_decision import (
    PostgresHilDecisionPermissionError,
    _validate_hil_decision_park,
)
from fdai_operator_service.projection_logic import caller_development_view, hil_item
from fdai_service_contracts import OperatorRole

from .test_operator_iam_family import (
    RecordingHilAudit,
    RecordingHilOutbox,
    RecordingHilRegistry,
    _client,
)

OWNER = "00000000-0000-0000-0000-00000000a001"
BLOCK = {
    "owner_principal": OWNER,
    "block_digest": "sha256:" + "a" * 64,
    "binding_digest": "sha256:" + "b" * 64,
    "profile_digest": "sha256:" + "c" * 64,
}


def _state(parked_at: datetime, **block: object) -> dict[str, object]:
    return {
        "approval_id": "approval-1",
        "parked_at": parked_at.isoformat(),
        "development_authority": {
            **BLOCK,
            "expires_at": (parked_at + timedelta(minutes=30)).isoformat(),
            **block,
        },
    }


def _claims(auth_time: datetime, **overrides: object) -> dict[str, object]:
    return {"oid": OWNER, "auth_time": int(auth_time.timestamp()), "uti": "token-1", **overrides}


def test_metadata_flattens_only_a_complete_core_block() -> None:
    parked_at = datetime.now(UTC)

    metadata = development_metadata(_state(parked_at))

    assert metadata["development_owner_principal"] == OWNER
    assert metadata["development_block_digest"] == BLOCK["block_digest"]
    assert metadata["parked_at"] == parked_at.isoformat()
    assert development_metadata(_state(parked_at, binding_digest="")) == {}
    assert development_metadata({"development_authority": BLOCK}) == {}
    assert development_metadata({}) == {}


def test_attestation_requires_the_owner_and_a_sign_in_after_the_park() -> None:
    parked_at = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=2)
    now = parked_at + timedelta(minutes=2)
    metadata = development_metadata(_state(parked_at))
    fresh = _claims(parked_at + timedelta(seconds=30))
    owner_roles = frozenset({OperatorRole.OWNER})

    def attest(claims: dict[str, object], **overrides: Any) -> object:
        arguments: dict[str, Any] = {
            "claims": claims,
            "actor_oid": OWNER,
            "actor_roles": owner_roles,
            "approval_id": "approval-1",
            "metadata": metadata,
            "now": now,
        }
        arguments.update(overrides)
        return development_attestation(**arguments)

    attested = attest(fresh)

    assert attested is not None
    assert attested.block_digest == BLOCK["block_digest"]  # type: ignore[attr-defined]
    assert attested.authenticated_at == parked_at + timedelta(seconds=30)  # type: ignore[attr-defined]
    assert attest(_claims(parked_at)) is None
    assert attest(_claims(parked_at - timedelta(minutes=1))) is None
    assert attest(fresh, now=parked_at + timedelta(minutes=15)) is None
    assert attest(fresh, actor_roles=frozenset({OperatorRole.APPROVER})) is None
    assert attest(fresh, actor_oid="00000000-0000-0000-0000-00000000a002") is None
    assert attest({**fresh, "oid": "00000000-0000-0000-0000-00000000a002"}) is None
    assert attest({**fresh, "auth_time": str(fresh["auth_time"])}) is None
    assert attest({key: value for key, value in fresh.items() if key != "uti"}) is None
    assert attest(fresh, metadata={}) is None
    expired = development_metadata(_state(parked_at - timedelta(minutes=31)))
    assert attest(fresh, metadata=expired) is None


def test_decision_transaction_revalidates_against_the_locked_park_row() -> None:
    parked_at = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=2)
    now = parked_at + timedelta(minutes=2)
    state = _state(parked_at)
    attested = development_attestation(
        claims=_claims(parked_at + timedelta(seconds=30)),
        actor_oid=OWNER,
        actor_roles=frozenset({OperatorRole.OWNER}),
        approval_id="approval-1",
        metadata=development_metadata(state),
        now=now,
    )
    assert attested is not None
    record = attested.model_dump(mode="json")

    def admitted(**overrides: Any) -> bool:
        arguments: dict[str, Any] = {
            "approver_oid": OWNER,
            "approver_roles": frozenset({OperatorRole.OWNER}),
            "decision": "approve",
            "attestation": record,
            "now": now,
        }
        arguments.update(overrides)
        return development_self_approval_admitted(state, **arguments)

    assert admitted() is True
    assert admitted(decision="reject") is False
    assert admitted(attestation=None) is False
    assert admitted(attestation={"schema_version": "1.0.0"}) is False
    assert admitted(approver_roles=frozenset({OperatorRole.APPROVER})) is False
    assert admitted(now=parked_at + timedelta(minutes=40)) is False
    assert admitted(attestation={**record, "block_digest": "sha256:" + "f" * 64}) is False
    other = _state(parked_at, owner_principal="00000000-0000-0000-0000-00000000a002")
    assert (
        development_self_approval_admitted(
            other,
            approver_oid=OWNER,
            approver_roles=frozenset({OperatorRole.OWNER}),
            decision="approve",
            attestation=record,
            now=now,
        )
        is False
    )


def _owner_registry(parked_at: datetime) -> RecordingHilRegistry:
    registry = RecordingHilRegistry(submitter_oid=OWNER)
    metadata = {**registry.context.metadata, **development_metadata(_state(parked_at))}
    registry.context = replace(registry.context, metadata=metadata)
    return registry


def _decide(
    registry: RecordingHilRegistry,
    *,
    claims: dict[str, object] | None,
    role: OperatorRole = OperatorRole.OWNER,
    decision: str = "approve",
) -> Any:
    authenticator = SimpleNamespace(verifier=lambda _token: claims) if claims else None
    client = _client(
        hil_registry=registry,
        hil_outbox=RecordingHilOutbox(),
        hil_audit=RecordingHilAudit(),
        hil_context=registry,
        slack_authenticator=authenticator,
    )
    return client.post(
        "/hil/approval-1/operator-decision",
        headers={
            "x-test-role": role.value,
            "x-test-oid": OWNER,
            "Idempotency-Key": "console-development-decision-1",
            "authorization": "Bearer test-token",
        },
        json={"decision": decision, "justification": "Verified the exact development action."},
    )


def test_console_records_an_attested_owner_self_approval() -> None:
    parked_at = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=1)
    registry = _owner_registry(parked_at)

    response = _decide(registry, claims=_claims(parked_at + timedelta(seconds=20)))

    assert response.status_code == 200
    assert registry.command is not None
    assert registry.command.approver_oid == OWNER
    attestation = registry.command.development_attestation
    assert attestation is not None
    assert attestation["block_digest"] == BLOCK["block_digest"]
    assert attestation["authenticated_principal"] == OWNER


def test_console_keeps_refusing_unattested_owner_self_decisions() -> None:
    parked_at = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=1)
    fresh = _claims(parked_at + timedelta(seconds=20))

    unbound = _decide(_owner_registry(parked_at), claims=None)
    stale = _decide(_owner_registry(parked_at), claims=_claims(parked_at - timedelta(seconds=5)))
    approver = _decide(_owner_registry(parked_at), claims=fresh, role=OperatorRole.APPROVER)
    rejected = _decide(_owner_registry(parked_at), claims=fresh, decision="reject")
    ordinary = RecordingHilRegistry(submitter_oid=OWNER)
    unmarked = _decide(ordinary, claims=fresh)

    for response in (unbound, stale, approver, rejected, unmarked):
        assert response.status_code == 403
        assert "self_approval" in response.text
    assert ordinary.command is None


def _locked_park(parked_at: datetime) -> dict[str, object]:
    return {
        **_state(parked_at),
        "status": "pending",
        "idempotency_key": "idem-1",
        "submitter_oid": OWNER,
        "request_fingerprint": "action-hash-1",
        "approval_context": {"expires_at": (parked_at + timedelta(minutes=30)).isoformat()},
    }


def test_decision_store_admits_only_an_attested_owner_self_approval() -> None:
    parked_at = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=2)
    parked = _locked_park(parked_at)
    attested = development_attestation(
        claims=_claims(parked_at + timedelta(seconds=30)),
        actor_oid=OWNER,
        actor_roles=frozenset({OperatorRole.OWNER}),
        approval_id="approval-1",
        metadata=development_metadata(parked),
        now=parked_at + timedelta(minutes=1),
    )
    assert attested is not None
    common: dict[str, Any] = {
        "approval_id": "approval-1",
        "idempotency_key": "idem-1",
        "action_hash": "action-hash-1",
        "approver_oid": OWNER,
        "approver_roles": frozenset({OperatorRole.OWNER}),
        "database_now": parked_at + timedelta(minutes=2),
        "expected_expires_at": parked_at + timedelta(minutes=30),
        "expected_submitter_oid": OWNER,
        "expected_decision_route": "action",
        "expected_required_role": "",
    }

    _validate_hil_decision_park(
        parked,
        decision="approve",
        development_attestation=attested.model_dump(mode="json"),
        **common,
    )
    with pytest.raises(PostgresHilDecisionPermissionError):
        _validate_hil_decision_park(parked, decision="approve", **common)
    with pytest.raises(PostgresHilDecisionPermissionError):
        _validate_hil_decision_park(
            parked,
            decision="reject",
            development_attestation=attested.model_dump(mode="json"),
            **common,
        )


def test_outbox_round_trip_carries_the_attestation_to_core() -> None:
    receipt = HilDecisionReceipt(
        approval_id="approval-1",
        idempotency_key="idem-1",
        decision=HilApprovalDecision.APPROVE,
        approver_oid=OWNER,
        decided_at=datetime.now(UTC),
        receipt_ref="receipt-1",
        development_attestation={"block_digest": BLOCK["block_digest"]},
    )
    legacy = replace(receipt, development_attestation=None)

    payload = hil_decision_payload(receipt)

    assert payload["development_attestation"] == {"block_digest": BLOCK["block_digest"]}
    assert "development_attestation" not in hil_decision_payload(legacy)
    assert receipt_from_outbox_payload(outbox_payload(receipt)) == receipt
    assert receipt_from_outbox_payload(outbox_payload(legacy)) == legacy
    with pytest.raises(ValueError, match="malformed"):
        receipt_from_outbox_payload({"receipt": {**payload, "development_attestation": "x"}})


def test_queue_projection_names_only_the_core_selected_owner() -> None:
    parked_at = datetime.now(UTC)
    row = {
        "incident_available": False,
        "value": {
            **_locked_park(parked_at),
            "action": {"event_id": "00000000-0000-0000-0000-000000000001"},
        },
    }

    bound = {
        "target_revision": "sha256:" + "1" * 64,
        "dry_run_digest": "sha256:" + "2" * 64,
        "scope_digest": "sha256:" + "3" * 64,
    }
    value = row["value"]
    assert isinstance(value, dict)
    value["development_authority"] = {**value["development_authority"], **bound}
    projected = hil_item(row)
    plain = hil_item({**row, "value": {**row["value"], "development_authority": None}})

    assert projected is not None and plain is not None
    assert projected["development_self_approval_owner"] == OWNER
    assert plain["development_self_approval_owner"] is None
    owner_view = caller_development_view({"items": [projected, plain]}, OWNER.upper())
    other_view = caller_development_view(
        {"items": [projected]}, "00000000-0000-0000-0000-00000000a002"
    )
    owner_items = owner_view["items"]
    assert isinstance(owner_items, list)
    assert [item["development_self_approval_available"] for item in owner_items] == [True, False]
    assert all("development_self_approval_owner" not in item for item in owner_items)
    assert owner_items[0]["development_binding"] == {
        "binding_digest": BLOCK["binding_digest"],
        **bound,
    }
    assert owner_items[1]["development_binding"] is None
    assert other_view["items"][0]["development_self_approval_available"] is False  # type: ignore[index]
    assert other_view["items"][0]["development_binding"] is None  # type: ignore[index]
    assert caller_development_view({"total": 1}, OWNER) == {"total": 1}
