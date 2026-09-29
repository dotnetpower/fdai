"""A parked category-only denial admits only the development Owner's attested self-approval.

The Operator route, the Slack and Teams callback service, and the decision transaction each refuse
any other approval, while any authorized approver may still reject the park.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from fdai_operator_service.families.iam.contracts import HilApprovalDecision
from fdai_operator_service.families.iam.hil_callback_authority import (
    HilCallbackActor,
    HilCallbackChannel,
)
from fdai_operator_service.families.iam.hil_callback_decision import (
    HilCallbackAttempt,
    HilCallbackDecisionService,
    HilCallbackSession,
    NormalizedHilDecision,
)
from fdai_operator_service.families.iam.hil_development_approval import (
    OWNER_ONLY_METADATA_FIELD,
    development_attestation,
    development_metadata,
)
from fdai_operator_service.postgres_family_store import PostgresFamilyStoreConfig
from fdai_operator_service.postgres_hil_decision import (
    PostgresHilDecisionPermissionError,
    PostgresHilDecisionStore,
    _validate_hil_decision_park,
)
from fdai_operator_service.projection_logic import caller_development_view, hil_item
from fdai_service_contracts import OperatorRole
from fdai_service_contracts.development_approval import development_owner_only

from .test_hil_development_approval import OWNER, _claims, _locked_park, _state
from .test_operator_iam_family import (
    RecordingHilAudit,
    RecordingHilOutbox,
    RecordingHilRegistry,
    _client,
)

APPROVER = "00000000-0000-0000-0000-00000000a002"


def _owner_only_state(parked_at: datetime, **block: object) -> dict[str, object]:
    return _state(parked_at, original_level="deny", owner_self_approval_only=True, **block)


def test_owner_only_marker_comes_from_the_core_block_and_fails_closed() -> None:
    parked_at = datetime.now(UTC)

    assert development_owner_only(_owner_only_state(parked_at)) is True
    assert development_owner_only(_state(parked_at, original_level="deny")) is True
    assert development_owner_only(_state(parked_at, owner_self_approval_only=False)) is True
    assert development_owner_only(_state(parked_at, original_level="hil")) is False
    assert development_owner_only({"development_authority": "malformed"}) is False
    assert development_owner_only({}) is False
    incomplete = development_metadata(_owner_only_state(parked_at, binding_digest=""))
    assert incomplete == {OWNER_ONLY_METADATA_FIELD: "true"}
    complete = development_metadata(_owner_only_state(parked_at))
    assert complete[OWNER_ONLY_METADATA_FIELD] == "true"
    assert OWNER_ONLY_METADATA_FIELD not in development_metadata(_state(parked_at))


def _owner_only_registry(parked_at: datetime) -> RecordingHilRegistry:
    registry = RecordingHilRegistry(submitter_oid=OWNER)
    metadata = {
        **registry.context.metadata,
        **development_metadata(_owner_only_state(parked_at)),
    }
    registry.context = replace(registry.context, metadata=metadata)
    return registry


def _console_decision(
    registry: RecordingHilRegistry,
    *,
    oid: str,
    role: OperatorRole,
    decision: str,
    claims: dict[str, object] | None = None,
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
            "x-test-oid": oid,
            "Idempotency-Key": f"console-owner-only-{oid}-{decision}",
            "authorization": "Bearer test-token",
        },
        json={"decision": decision, "justification": "Reviewed the exact development action."},
    )


@pytest.mark.parametrize("role", [OperatorRole.APPROVER, OperatorRole.OWNER])
def test_console_refuses_any_approval_but_the_owners_own(role: OperatorRole) -> None:
    parked_at = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=1)
    registry = _owner_only_registry(parked_at)

    refused = _console_decision(registry, oid=APPROVER, role=role, decision="approve")

    assert refused.status_code == 403
    assert "development_owner_only" in refused.text
    assert registry.command is None


def test_console_lets_any_authorized_approver_reject() -> None:
    parked_at = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=1)
    registry = _owner_only_registry(parked_at)

    rejected = _console_decision(
        registry, oid=APPROVER, role=OperatorRole.APPROVER, decision="reject"
    )

    assert rejected.status_code == 200
    assert registry.command is not None
    assert registry.command.decision is HilApprovalDecision.REJECT


def test_console_records_the_attested_owner_self_approval_of_a_category_park() -> None:
    parked_at = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=1)
    registry = _owner_only_registry(parked_at)

    admitted = _console_decision(
        registry,
        oid=OWNER,
        role=OperatorRole.OWNER,
        decision="approve",
        claims=_claims(parked_at + timedelta(seconds=20)),
    )

    assert admitted.status_code == 200
    assert registry.command is not None
    assert registry.command.development_attestation is not None


def test_console_refuses_the_owners_stale_or_unattested_category_approval() -> None:
    parked_at = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=1)

    for claims in (_claims(parked_at - timedelta(seconds=5)), None):
        registry = _owner_only_registry(parked_at)
        response = _console_decision(
            registry, oid=OWNER, role=OperatorRole.OWNER, decision="approve", claims=claims
        )
        assert response.status_code == 403
        assert "self_approval" in response.text
        assert registry.command is None


def test_console_lets_the_requesting_owner_reject_a_category_park() -> None:
    parked_at = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=1)

    for claims in (_claims(parked_at + timedelta(seconds=20)), None):
        registry = _owner_only_registry(parked_at)
        response = _console_decision(
            registry, oid=OWNER, role=OperatorRole.OWNER, decision="reject", claims=claims
        )
        assert response.status_code == 200
        assert registry.command is not None
        assert registry.command.decision is HilApprovalDecision.REJECT
        assert registry.command.development_attestation is None


class _ChannelAuthority:
    def __init__(self, oid: str = APPROVER, role: OperatorRole = OperatorRole.APPROVER) -> None:
        self.oid = oid
        self.role = role

    async def authenticate(self, **_: object) -> HilCallbackActor:
        return HilCallbackActor(
            oid=self.oid,
            identity_ref=f"actor:{self.oid}",
            roles=frozenset({self.role}),
            authority_basis="teams:entra_app_role",
        )


async def _channel_decision(
    registry: RecordingHilRegistry,
    authority: _ChannelAuthority,
    decision: HilApprovalDecision,
) -> Any:
    service = HilCallbackDecisionService(
        registry=registry,  # type: ignore[arg-type]
        outbox=RecordingHilOutbox(),  # type: ignore[arg-type]
        authority=authority,  # type: ignore[arg-type]
        audit=RecordingHilAudit(),  # type: ignore[arg-type]
        context_reader=registry,  # type: ignore[arg-type]
        clock=lambda: datetime.now(UTC),
    )
    session = await service.begin(
        HilCallbackAttempt(
            callback_id=f"teams-callback-{authority.oid}-{decision.value}",
            approval_id="approval-1",
            intent_digest="sha256:" + "d" * 64,
            channel_hint="teams",
            actor_hint=authority.oid,
        )
    )
    assert isinstance(session, HilCallbackSession)
    return await service.decide(
        session,
        approval_id="approval-1",
        payload=NormalizedHilDecision(
            decision=decision,
            justification="Decided from the channel card.",
            channel=HilCallbackChannel.TEAMS,
            provider_actor_id="provider-actor-1",
            audience="api://fdai",
            correlation_id=registry.context.correlation_id,
            idempotency_key=registry.context.idempotency_key,
            action_hash=registry.context.action_hash,
            decided_at=datetime.now(UTC),
            authorization="******",
        ),
    )


async def test_channel_callbacks_never_approve_a_category_park() -> None:
    parked_at = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=1)
    approver = _owner_only_registry(parked_at)
    owner = _owner_only_registry(parked_at)

    refused = await _channel_decision(approver, _ChannelAuthority(), HilApprovalDecision.APPROVE)
    unattested = await _channel_decision(
        owner, _ChannelAuthority(OWNER, OperatorRole.OWNER), HilApprovalDecision.APPROVE
    )

    assert refused.status_code == 403
    assert b"development_owner_only" in refused.body
    assert unattested.status_code == 403
    assert b"self_approval" in unattested.body
    assert approver.command is None and owner.command is None


async def test_channel_callbacks_let_the_owner_or_an_approver_reject_a_category_park() -> None:
    parked_at = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=1)

    for authority in (_ChannelAuthority(), _ChannelAuthority(OWNER, OperatorRole.OWNER)):
        registry = _owner_only_registry(parked_at)
        response = await _channel_decision(registry, authority, HilApprovalDecision.REJECT)
        assert response.status_code == 200
        assert registry.command is not None
        assert registry.command.decision is HilApprovalDecision.REJECT


def _owner_only_park(parked_at: datetime) -> dict[str, object]:
    parked = _locked_park(parked_at)
    block = parked["development_authority"]
    assert isinstance(block, dict)
    return {
        **parked,
        "development_authority": {
            **block,
            "original_level": "deny",
            "owner_self_approval_only": True,
        },
    }


def _validate(parked: dict[str, object], *, approver: str, **overrides: Any) -> None:
    parked_at = datetime.fromisoformat(str(parked["parked_at"]))
    arguments: dict[str, Any] = {
        "approval_id": "approval-1",
        "idempotency_key": "idem-1",
        "action_hash": "action-hash-1",
        "approver_oid": approver,
        "approver_roles": frozenset({OperatorRole.OWNER}),
        "database_now": parked_at + timedelta(minutes=2),
        "expected_expires_at": parked_at + timedelta(minutes=30),
        "expected_submitter_oid": OWNER,
        "expected_decision_route": "action",
        "expected_required_role": "",
    }
    arguments.update(overrides)
    _validate_hil_decision_park(parked, **arguments)


def test_decision_transaction_refuses_every_other_approval_of_a_category_park() -> None:
    parked_at = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=2)
    parked = _owner_only_park(parked_at)
    attested = development_attestation(
        claims=_claims(parked_at + timedelta(seconds=30)),
        actor_oid=OWNER,
        actor_roles=frozenset({OperatorRole.OWNER}),
        approval_id="approval-1",
        metadata=development_metadata(parked),
        now=parked_at + timedelta(minutes=1),
    )
    assert attested is not None
    record = attested.model_dump(mode="json")

    _validate(parked, approver=OWNER, decision="approve", development_attestation=record)
    _validate(parked, approver=APPROVER, decision="reject")
    for decision in ("approve", ""):
        with pytest.raises(PostgresHilDecisionPermissionError, match="development Owner"):
            _validate(parked, approver=APPROVER, decision=decision)
        with pytest.raises(PostgresHilDecisionPermissionError, match="development Owner"):
            _validate(
                parked,
                approver=APPROVER,
                decision=decision,
                development_attestation=record,
            )
    with pytest.raises(PostgresHilDecisionPermissionError):
        _validate(parked, approver=OWNER, decision="approve")
    # The Owner's attestation expires 10 minutes after the sign-in it proves.
    with pytest.raises(PostgresHilDecisionPermissionError, match="own request"):
        _validate(
            parked,
            approver=OWNER,
            decision="approve",
            development_attestation=record,
            database_now=parked_at + timedelta(minutes=11),
        )
    # The requesting Owner may reject the category park, with or without an attestation.
    _validate(parked, approver=OWNER, decision="reject")
    _validate(parked, approver=OWNER, decision="reject", development_attestation=record)
    # An ordinary development park keeps ordinary multi-operator approval and self-refusal.
    _validate(_locked_park(parked_at), approver=APPROVER, decision="approve")
    with pytest.raises(PostgresHilDecisionPermissionError, match="own request"):
        _validate(_locked_park(parked_at), approver=OWNER, decision="reject")


@pytest.mark.parametrize("decision", ["pending", "timeout", "", "APPROVE"])
async def test_decision_store_records_only_a_human_approve_or_reject(decision: str) -> None:
    now = datetime.now(UTC)
    store = PostgresHilDecisionStore(PostgresFamilyStoreConfig("postgresql://example.invalid/fdai"))

    # The refusal precedes any connection, so nothing reaches the receipt or the outbox.
    with pytest.raises(ValueError, match="approve or reject"):
        await store.append_hil_decision(
            approval_id="approval-1",
            idempotency_key="idem-1",
            action_hash="action-hash-1",
            decision=decision,
            approver_oid=APPROVER,
            approver_roles=frozenset({OperatorRole.APPROVER}),
            justification="Recorded decision.",
            decided_at=now,
            expected_expires_at=now + timedelta(minutes=30),
            expected_submitter_oid=OWNER,
            expected_decision_route="action",
            expected_required_role="",
        )


def test_queue_projection_marks_the_owner_only_park_for_every_caller() -> None:
    parked_at = datetime.now(UTC)
    event = {"action": {"event_id": "00000000-0000-0000-0000-000000000001"}}
    owner_only = hil_item(
        {"incident_available": False, "value": {**_owner_only_park(parked_at), **event}}
    )
    ordinary = hil_item(
        {"incident_available": False, "value": {**_locked_park(parked_at), **event}}
    )

    assert owner_only is not None and ordinary is not None
    assert (owner_only["development_owner_only"], ordinary["development_owner_only"]) == (
        True,
        False,
    )
    viewed = caller_development_view({"items": [owner_only]}, APPROVER)["items"]
    assert isinstance(viewed, list)
    assert viewed[0]["development_owner_only"] is True
    assert viewed[0]["development_self_approval_available"] is False
