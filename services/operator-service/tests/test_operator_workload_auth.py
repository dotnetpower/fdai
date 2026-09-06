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
from fdai_service_contracts import OperatorPrincipal, OperatorPrincipalKind, OperatorRole
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


def test_workload_group_claims_are_rejected() -> None:
    with pytest.raises(AuthenticationError, match="MUST NOT carry group claims"):
        _authenticator(
            {
                "oid": "workload-object-id",
                "idtyp": "app",
                "roles": ["Reader"],
                "groups": ["group:responders"],
            }
        ).authenticate("Bearer test-token")


def test_human_group_overage_is_rejected_even_with_an_app_role() -> None:
    with pytest.raises(AuthenticationError, match="group overage"):
        _authenticator(
            {
                "oid": "operator-a",
                "idtyp": "user",
                "roles": ["Contributor"],
                "hasgroups": True,
            }
        ).authenticate("Bearer test-token")


def test_oversized_inline_group_claims_are_rejected_as_invalid_authentication() -> None:
    with pytest.raises(AuthenticationError, match="groups exceed"):
        _authenticator(
            {
                "oid": "operator-a",
                "idtyp": "user",
                "roles": ["Contributor"],
                "groups": [f"group:{index}" for index in range(65)],
            }
        ).authenticate("Bearer test-token")


def test_missing_principal_type_is_rejected() -> None:
    with pytest.raises(AuthenticationError, match="missing principal type"):
        _authenticator(
            {
                "oid": "operator-a",
                "roles": ["Contributor"],
                "groups": ["group:responders"],
            }
        ).authenticate("Bearer test-token")


def test_blank_group_claim_is_rejected_as_invalid_authentication() -> None:
    with pytest.raises(AuthenticationError, match="malformed value"):
        _authenticator(
            {
                "oid": "operator-a",
                "idtyp": "user",
                "roles": ["Contributor"],
                "groups": ["   "],
            }
        ).authenticate("Bearer test-token")


@pytest.mark.parametrize(
    "groups",
    (
        "group:responders",
        ["group:responders", "group:responders"],
        ["x" * 257],
        [1],
    ),
)
def test_malformed_group_claim_shapes_are_rejected(groups: object) -> None:
    with pytest.raises(AuthenticationError, match="groups"):
        _authenticator(
            {
                "oid": "operator-a",
                "idtyp": "user",
                "roles": ["Contributor"],
                "groups": groups,
            }
        ).authenticate("Bearer test-token")


def test_group_mapping_grants_only_the_configured_fallback_role() -> None:
    authenticator = OperatorAuthenticator(
        verifier=lambda _: {
            "oid": "operator-a",
            "idtyp": "user",
            "groups": ["group:readers"],
        },
        group_ids={OperatorRole.READER: "group:readers"},
    )

    principal = authenticator.authenticate("Bearer test-token")

    assert principal.roles == frozenset({OperatorRole.READER})


def test_local_session_requires_its_exact_token() -> None:
    local = OperatorPrincipal(
        subject_id="local-operator",
        roles=frozenset({OperatorRole.CONTRIBUTOR}),
    )
    authenticator = OperatorAuthenticator(
        verifier=lambda _: {},
        group_ids={},
        local_principal=local,
        local_session_token="local-token",
    )

    assert authenticator.authenticate("Bearer local-token") is local
    with pytest.raises(AuthenticationError, match="local Azure CLI"):
        authenticator.authenticate("Bearer wrong-token")


@pytest.mark.parametrize("header", (None, "Basic token", "Bearer "))
def test_bearer_header_failures_are_typed(header: str | None) -> None:
    with pytest.raises(AuthenticationError, match="Authorization|Bearer"):
        _authenticator({"oid": "operator-a", "idtyp": "user", "roles": ["Reader"]}).authenticate(
            header
        )


def test_verifier_and_claim_failures_are_sanitized() -> None:
    def unavailable(_token: str) -> dict[str, object]:
        raise RuntimeError("provider detail")

    with pytest.raises(AuthenticationError, match="RuntimeError"):
        OperatorAuthenticator(verifier=unavailable, group_ids={}).authenticate("Bearer token")
    with pytest.raises(AuthenticationError, match="missing non-empty oid"):
        _authenticator({"idtyp": "user", "roles": ["Reader"]}).authenticate("Bearer token")
    with pytest.raises(AuthenticationError, match="authorized party"):
        _authenticator(
            {
                "oid": "operator-a",
                "idtyp": "user",
                "roles": ["Reader"],
                "azp": 1,
            }
        ).authenticate("Bearer token")


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


async def test_human_group_claims_reach_the_semantic_envelope() -> None:
    authorizer = OperatorFamilyAuthorizer(
        _authenticator(
            {
                "oid": "operator-a",
                "idtyp": "user",
                "roles": ["Contributor"],
                "groups": ["group:responders"],
            }
        )
    )
    scope = await authorizer.authorize(_request(), operation="chat.stream")

    envelope = SemanticTurnEnvelopeBuilder().build(
        ConversationProposal(
            operation="chat.stream",
            scope=scope,
            idempotency_key="group-scoped-question",
            body={"prompt": "What does the recovery runbook require?"},
        )
    )

    semantic_turn = envelope["semantic_turn"]
    assert isinstance(semantic_turn, dict)
    assert semantic_turn["principal"]["groups"] == ["group:responders"]
