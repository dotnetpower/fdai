"""Content-free Operator authentication receipts retained beside test-context commands."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest
from fdai_operator_service.auth import OperatorAuthenticator
from fdai_operator_service.authentication_receipt import live_authentication_receipt
from fdai_operator_service.conversation_family_adapters import PostgresConversationAdapters
from fdai_operator_service.families.conversation.contracts import (
    ConversationProposal,
    ConversationReceiptAuthorizer,
    PrincipalScope,
)
from fdai_operator_service.family_authorization import OperatorFamilyAuthorizer
from fdai_operator_service.postgres_family_store import (
    PostgresFamilyStore,
    PostgresFamilyStoreConfig,
    StoredProposal,
)
from fdai_service_contracts import OperatorPrincipal, OperatorRole
from fdai_service_contracts.operator_authentication import (
    OperatorAuthenticationEvidenceClass,
    OperatorAuthenticationReceipt,
)
from starlette.requests import Request

_ISSUED = int(datetime(2026, 9, 28, 5, 0, tzinfo=UTC).timestamp())
_HEADER = "Bearer example-opaque-value"
_CLAIMS: dict[str, object] = {
    "oid": "00000000-0000-0000-0000-000000000011",
    "idtyp": "user",
    "iss": "https://issuer.example.invalid/v2.0",
    "aud": "api://fdai-operator.example.invalid",
    "tid": "00000000-0000-0000-0000-000000000000",
    "uti": "token-identifier-claim",
    "iat": _ISSUED,
    "exp": _ISSUED + 3600,
    "groups": ["00000000-0000-0000-0000-000000000002"],
}
_GROUPS = {OperatorRole.APPROVER: "00000000-0000-0000-0000-000000000002"}


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/test-context/review",
            "headers": [(b"authorization", _HEADER.encode())],
        }
    )


def test_verified_claims_yield_a_receipt_with_exact_groups_and_no_token() -> None:
    identity = OperatorAuthenticator(
        verifier=lambda _: _CLAIMS, group_ids=_GROUPS
    ).authenticate_identity(_HEADER)
    receipt = identity.authentication_receipt
    assert receipt is not None
    assert receipt.evidence_class is OperatorAuthenticationEvidenceClass.LIVE
    assert receipt.subject_id == _CLAIMS["oid"]
    assert receipt.groups == ("00000000-0000-0000-0000-000000000002",)
    assert receipt.roles == ("Approver",)
    assert receipt.group_overage is False and receipt.token_retained is False
    serialized = receipt.model_dump_json()
    for secret in ("example-opaque-value", "token-identifier-claim", str(_CLAIMS["tid"])):
        assert secret not in serialized


@pytest.mark.parametrize("missing", ["tid", "uti", "iat", "exp", "iss"])
def test_missing_identifying_claim_yields_no_receipt(missing: str) -> None:
    claims = {key: value for key, value in _CLAIMS.items() if key != missing}
    principal = OperatorPrincipal(
        subject_id=str(_CLAIMS["oid"]), roles=frozenset({OperatorRole.APPROVER})
    )
    assert live_authentication_receipt(claims, principal=principal, group_ids=_GROUPS) is None


def test_local_cli_session_receipt_is_loopback_class() -> None:
    principal = OperatorPrincipal(
        subject_id="local-operator", roles=frozenset({OperatorRole.OWNER})
    )
    identity = OperatorAuthenticator(
        verifier=lambda _: {},
        group_ids={},
        local_principal=principal,
        local_session_token="local-session-value",
    ).authenticate_identity("Bearer local-session-value")
    receipt = identity.authentication_receipt
    assert receipt is not None
    assert receipt.evidence_class is OperatorAuthenticationEvidenceClass.LOCAL_LOOPBACK
    assert "local-session-value" not in receipt.model_dump_json()


async def test_authorizer_returns_the_receipt_of_its_single_verification() -> None:
    authorizer = OperatorFamilyAuthorizer(
        OperatorAuthenticator(verifier=lambda _: _CLAIMS, group_ids=_GROUPS)
    )
    assert isinstance(authorizer, ConversationReceiptAuthorizer)
    scope, receipt = await authorizer.authorize_with_receipt(
        _request(), operation="test-context.review"
    )
    assert scope.subject_id == _CLAIMS["oid"]
    assert receipt is not None and receipt.subject_id == scope.subject_id
    assert await authorizer.authorize(_request(), operation="test-context.review") == scope


class _RecordingStore:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def append_proposal(self, **kwargs: Any) -> StoredProposal:
        self.calls.append(kwargs)
        return StoredProposal(
            proposal_id="operator-proposal",
            accepted_at="2026-09-28T05:00:00+00:00",
            duplicate=False,
            record={},
        )


async def test_receipt_is_retained_beside_the_idempotent_request_payload() -> None:
    receipt = (
        OperatorAuthenticator(verifier=lambda _: _CLAIMS, group_ids=_GROUPS)
        .authenticate_identity(_HEADER)
        .authentication_receipt
    )
    assert isinstance(receipt, OperatorAuthenticationReceipt)
    store = _RecordingStore()
    adapters = PostgresConversationAdapters(store)  # type: ignore[arg-type]
    proposal = ConversationProposal(
        operation="test-context.review",
        scope=PrincipalScope(subject_id=str(_CLAIMS["oid"]), roles=frozenset({"Approver"})),
        idempotency_key="context-review-key",
        body={"operation": "review"},
        authentication_receipt=receipt.model_dump(mode="json"),
    )
    await adapters.append(proposal)
    await adapters.append(replace(proposal, operation="chat.exchange"))
    retained, ordinary = store.calls
    assert retained["authentication_receipt"]["receipt_digest"] == receipt.receipt_digest
    assert "authentication_receipt" not in retained["payload"]
    assert "authentication_receipt" not in ordinary
    assert "authentication_receipt" not in ordinary["payload"]


async def test_outbox_record_digest_excludes_the_receipt(monkeypatch: pytest.MonkeyPatch) -> None:
    store = PostgresFamilyStore(PostgresFamilyStoreConfig("postgresql://unused.invalid/fdai"))
    captured: list[dict[str, object]] = []

    async def insert(*, key: str, value: dict[str, object]) -> tuple[bool, dict[str, object]]:
        captured.append(value)
        return True, value

    monkeypatch.setattr(store, "_insert_if_absent", insert)
    arguments: dict[str, Any] = {
        "family": "conversation",
        "operation": "test-context.review",
        "principal_id": "principal",
        "idempotency_key": "context-review-key",
        "payload": {"body": {}},
    }
    await store.append_proposal(**arguments)
    await store.append_proposal(**arguments, authentication_receipt={"receipt_digest": "x"})
    plain, retained = captured
    assert plain["request_digest"] == retained["request_digest"]
    assert "authentication_receipt" not in plain
    assert retained["authentication_receipt"] == {"receipt_digest": "x"}
