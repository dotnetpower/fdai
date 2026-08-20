from __future__ import annotations

import hashlib

import pytest
from fdai_operator_service.auth import (
    AuthenticationError,
    AuthorizationError,
    OperatorAuthenticator,
)
from fdai_operator_service.families.conversation.contracts import (
    ConversationProposal,
    PrincipalScope,
)
from fdai_operator_service.families.conversation.semantic_turn import SemanticTurnEnvelopeBuilder
from fdai_operator_service.family_authorization import OperatorFamilyAuthorizer
from fdai_service_contracts import OperatorPrincipalKind, OperatorRole
from starlette.requests import Request


def _authenticator(claims: dict[str, object]) -> OperatorAuthenticator:
    return OperatorAuthenticator(verifier=lambda _: claims, group_ids={})


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/chat/stream",
            "headers": [(b"authorization", b"Bearer verified-token")],
        }
    )


def test_workload_reader_is_digest_scoped() -> None:
    principal = _authenticator(
        {"oid": "workload-object-id", "idtyp": "app", "roles": ["Reader"]}
    ).authenticate("Bearer verified-token")

    expected = hashlib.sha256(b"workload-object-id").hexdigest()
    assert principal.subject_id == f"sha256:{expected}"
    assert principal.roles == frozenset({OperatorRole.READER})
    assert principal.principal_kind is OperatorPrincipalKind.WORKLOAD


def test_workload_principal_cannot_claim_a_higher_role() -> None:
    with pytest.raises(AuthenticationError, match="Reader App Role"):
        _authenticator(
            {"oid": "workload-object-id", "idtyp": "app", "roles": ["Contributor"]}
        ).authenticate("Bearer verified-token")


async def test_workload_reader_can_submit_only_semantic_streams() -> None:
    authorizer = OperatorFamilyAuthorizer(
        _authenticator({"oid": "workload-object-id", "idtyp": "app", "roles": ["Reader"]})
    )

    scope = await authorizer.authorize(_request(), operation="chat.stream")

    assert scope.roles == frozenset({"Reader"})
    assert scope.principal_kind is OperatorPrincipalKind.WORKLOAD
    with pytest.raises(AuthorizationError, match="only Reader-scoped semantic turns"):
        await authorizer.authorize(_request(), operation="chat.exchange")


def test_workload_kind_reaches_the_semantic_envelope() -> None:
    envelope = SemanticTurnEnvelopeBuilder().build(
        ConversationProposal(
            operation="chat.stream",
            scope=PrincipalScope(
                subject_id="sha256:" + "a" * 64,
                roles=frozenset({"Reader"}),
                principal_kind=OperatorPrincipalKind.WORKLOAD,
            ),
            idempotency_key="question-campaign-case",
            body={"prompt": "Inspect bounded evidence."},
        )
    )

    semantic_turn = envelope["semantic_turn"]
    assert isinstance(semantic_turn, dict)
    assert semantic_turn["principal"]["principal_kind"] == "workload"
