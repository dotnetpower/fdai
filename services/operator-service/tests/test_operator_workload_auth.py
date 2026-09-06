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


@pytest.mark.parametrize(
    "roles",
    [[], ["Contributor"], ["Approver"], ["Owner"], ["BreakGlass"], ["Reader", "Owner"]],
)
def test_workload_principal_cannot_claim_a_higher_role(roles: list[str]) -> None:
    with pytest.raises(AuthenticationError, match="Reader App Role"):
        _authenticator(
            {
                "oid": "workload-object-id",
                "idtyp": "app",
                "roles": roles,
                "scp": "access_as_user",
            }
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


@pytest.mark.parametrize("scope", [None, "", "  ", [], ["access_as_user"], True])
def test_missing_principal_type_without_delegated_scope_is_rejected(scope: object) -> None:
    with pytest.raises(AuthenticationError, match="missing principal type"):
        _authenticator(
            {
                "oid": "operator-a",
                "roles": ["Contributor"],
                "groups": ["group:responders"],
                "scp": scope,
            }
        ).authenticate("Bearer test-token")


@pytest.mark.parametrize("role", ["Reader", "Contributor", "Approver", "Owner"])
def test_delegated_human_without_idtyp_preserves_verified_roles_and_groups(role: str) -> None:
    identity = _authenticator(
        {
            "oid": "operator-a",
            "scp": "access_as_user",
            "roles": [role],
            "groups": ["group:responders"],
            "azp": "console-client",
        }
    ).authenticate_identity("Bearer test-token")

    assert identity.principal.principal_kind is OperatorPrincipalKind.HUMAN
    assert identity.principal.subject_id == "operator-a"
    assert identity.principal.roles == frozenset({OperatorRole(role)})
    assert identity.principal.groups == frozenset({"group:responders"})
    assert identity.authorized_party == "console-client"


async def test_delegated_reader_without_idtyp_keeps_human_role_gate() -> None:
    authorizer = OperatorFamilyAuthorizer(
        _authenticator({"oid": "operator-a", "scp": "access_as_user", "roles": ["Reader"]})
    )
    scope = await authorizer.authorize(_request(), operation="chat.health")

    assert scope.principal_kind is OperatorPrincipalKind.HUMAN
    assert scope.roles == frozenset({"Reader"})
    with pytest.raises(AuthorizationError, match="principal lacks required role"):
        await authorizer.authorize(_request(), operation="chat.stream")


def test_delegated_scope_without_roles_cannot_grant_reader_access() -> None:
    authenticator = _authenticator({"oid": "operator-a", "scp": "access_as_user"})
    with pytest.raises(AuthorizationError, match="principal lacks required role"):
        authenticator.require_any("Bearer test-token", frozenset({OperatorRole.READER}))


def test_delegated_human_without_idtyp_keeps_server_owned_group_role_resolution() -> None:
    authenticator = OperatorAuthenticator(
        verifier=lambda _: {
            "oid": "operator-a",
            "scp": "access_as_user",
            "groups": ["group:responders"],
        },
        group_ids={OperatorRole.READER: "group:responders"},
    )
    principal = authenticator.require_any("Bearer test-token", frozenset({OperatorRole.READER}))
    assert principal.principal_kind is OperatorPrincipalKind.HUMAN
    assert principal.roles == frozenset({OperatorRole.READER})


@pytest.mark.parametrize("identity_type", ["unknown", "", True, ["user"]])
def test_delegated_scope_does_not_override_invalid_explicit_principal_type(
    identity_type: object,
) -> None:
    with pytest.raises(AuthenticationError, match="unsupported principal type"):
        _authenticator(
            {
                "oid": "operator-a",
                "idtyp": identity_type,
                "scp": "access_as_user",
                "roles": ["Owner"],
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

    with pytest.raises(AuthenticationError) as raised:
        OperatorAuthenticator(verifier=unavailable, group_ids={}).authenticate("Bearer token")
    assert str(raised.value) == "token verification failed: RuntimeError"
    assert "provider detail" not in str(raised.value)
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
