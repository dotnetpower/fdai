"""Policy-admin App Role stays outside ordinary Operator role hierarchy."""

from __future__ import annotations

import pytest
from fdai_operator_service.auth import AuthorizationError, OperatorAuthenticator
from fdai_operator_service.families.conversation.semantic_turn import _highest_ordinary_role
from fdai_service_contracts import OperatorRole


def test_policy_admin_raw_app_role_does_not_break_ordinary_role_ranking() -> None:
    authenticator = OperatorAuthenticator(
        verifier=lambda _: {
            "oid": "operator-1",
            "roles": ["Owner", "policy-admin"],
            "idtyp": "user",
        },
        group_ids={},
    )

    identity = authenticator.authenticate_identity("Bearer token")

    assert identity.principal.roles == frozenset({OperatorRole.OWNER})
    assert identity.app_roles == frozenset({"Owner", "policy-admin"})
    assert _highest_ordinary_role(tuple(identity.principal.roles)) == "owner"


def test_policy_admin_only_principal_is_refused_by_ordinary_read_gate() -> None:
    authenticator = OperatorAuthenticator(
        verifier=lambda _: {
            "oid": "operator-1",
            "roles": ["policy-admin"],
            "idtyp": "user",
        },
        group_ids={},
    )

    with pytest.raises(AuthorizationError):
        authenticator.require_any(
            "Bearer token",
            frozenset(
                {
                    OperatorRole.READER,
                    OperatorRole.CONTRIBUTOR,
                    OperatorRole.APPROVER,
                    OperatorRole.OWNER,
                }
            ),
        )


def test_break_glass_only_principal_remains_admitted_by_full_read_gate() -> None:
    authenticator = OperatorAuthenticator(
        verifier=lambda _: {
            "oid": "operator-1",
            "roles": ["BreakGlass"],
            "idtyp": "user",
        },
        group_ids={},
    )

    principal = authenticator.require_any("Bearer token", frozenset(OperatorRole))

    assert principal.roles == frozenset({OperatorRole.BREAK_GLASS})
