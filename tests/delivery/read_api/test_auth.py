"""Read-API auth wire — Bearer extraction + verifier + RBAC glue."""

from __future__ import annotations

import base64
import json
from typing import Any

import pytest

from aiopspilot.core.rbac.enforcer import RoleEnforcer, RoleRequiredError
from aiopspilot.core.rbac.resolver import GroupMapping, RoleResolver
from aiopspilot.core.rbac.roles import Role
from aiopspilot.delivery.read_api.auth import (
    AuthenticationError,
    Authenticator,
    UnsafeClaimsExtractor,
    build_authenticator,
)


def _mapping() -> GroupMapping:
    return GroupMapping(
        reader_group_id="reader-group",
        contributor_group_id="contributor-group",
        approver_group_id="approver-group",
        owner_group_id="owner-group",
        break_glass_group_id="break-glass-group",
    )


def _resolver() -> RoleResolver:
    return RoleResolver(group_mapping=_mapping())


def _forge_token(claims: dict[str, Any]) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"RS256","typ":"JWT"}').rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode("utf-8")).rstrip(b"=").decode()
    sig = base64.urlsafe_b64encode(b"sig").rstrip(b"=").decode()
    return f"{header}.{payload}.{sig}"


class TestBearerExtraction:
    def test_missing_header_raises_authentication_error(self) -> None:
        auth = Authenticator(
            verifier=lambda t: {"oid": "u"},
            resolver=_resolver(),
            enforcer=RoleEnforcer(),
        )
        with pytest.raises(AuthenticationError, match="missing"):
            auth.authenticate(None)

    def test_empty_header_raises_authentication_error(self) -> None:
        auth = Authenticator(
            verifier=lambda t: {"oid": "u"},
            resolver=_resolver(),
            enforcer=RoleEnforcer(),
        )
        with pytest.raises(AuthenticationError, match="missing"):
            auth.authenticate("")

    def test_non_bearer_scheme_rejected(self) -> None:
        auth = Authenticator(
            verifier=lambda t: {"oid": "u"},
            resolver=_resolver(),
            enforcer=RoleEnforcer(),
        )
        with pytest.raises(AuthenticationError, match="Bearer scheme"):
            auth.authenticate("Basic abc==")

    def test_empty_bearer_token_rejected(self) -> None:
        auth = Authenticator(
            verifier=lambda t: {"oid": "u"},
            resolver=_resolver(),
            enforcer=RoleEnforcer(),
        )
        with pytest.raises(AuthenticationError, match="empty"):
            auth.authenticate("Bearer ")


class TestAuthenticateHappyPath:
    def test_returns_principal_from_verified_claims(self) -> None:
        auth = Authenticator(
            verifier=lambda t: {"oid": "user-1", "roles": ["Reader"]},
            resolver=_resolver(),
            enforcer=RoleEnforcer(),
        )
        p = auth.authenticate("Bearer any-token")
        assert p.oid == "user-1"
        assert Role.READER in p.roles

    def test_correlation_id_propagated(self) -> None:
        auth = Authenticator(
            verifier=lambda t: {"oid": "user-1"},
            resolver=_resolver(),
            enforcer=RoleEnforcer(),
        )
        p = auth.authenticate("Bearer x", correlation_id="corr-1")
        assert p.correlation_id == "corr-1"

    def test_empty_roles_still_returns_principal_deny_is_403_later(self) -> None:
        # Zero-role principal is authenticated but not authorized. The
        # read-API layer distinguishes 401 (auth) from 403 (rbac).
        auth = Authenticator(
            verifier=lambda t: {"oid": "user-1", "roles": []},
            resolver=_resolver(),
            enforcer=RoleEnforcer(),
        )
        p = auth.authenticate("Bearer x")
        assert p.roles == frozenset()


class TestAuthenticateFailurePaths:
    def test_verifier_authentication_error_bubbles(self) -> None:
        def verifier(_: str) -> dict[str, Any]:
            raise AuthenticationError("expired")

        auth = Authenticator(
            verifier=verifier,
            resolver=_resolver(),
            enforcer=RoleEnforcer(),
        )
        with pytest.raises(AuthenticationError, match="expired"):
            auth.authenticate("Bearer x")

    def test_verifier_arbitrary_exception_wrapped(self) -> None:
        def verifier(_: str) -> dict[str, Any]:
            raise RuntimeError("oops")

        auth = Authenticator(
            verifier=verifier,
            resolver=_resolver(),
            enforcer=RoleEnforcer(),
        )
        with pytest.raises(AuthenticationError, match="token verification failed"):
            auth.authenticate("Bearer x")

    def test_missing_oid_wrapped_as_authentication_error(self) -> None:
        # Resolver raises ValueError on missing oid; auth wraps it so the
        # read-API layer treats it as 401 (bad token) not 500.
        auth = Authenticator(
            verifier=lambda t: {"roles": ["Reader"]},
            resolver=_resolver(),
            enforcer=RoleEnforcer(),
        )
        with pytest.raises(AuthenticationError, match="invalid claims"):
            auth.authenticate("Bearer x")


class TestRequireRoles:
    def test_pass_when_role_present(self) -> None:
        auth = Authenticator(
            verifier=lambda t: {"oid": "u", "roles": ["Approver"]},
            resolver=_resolver(),
            enforcer=RoleEnforcer(),
        )
        p = auth.require_roles("Bearer x", required=(Role.APPROVER, Role.OWNER))
        assert Role.APPROVER in p.roles

    def test_deny_when_role_missing(self) -> None:
        auth = Authenticator(
            verifier=lambda t: {"oid": "u", "roles": ["Reader"]},
            resolver=_resolver(),
            enforcer=RoleEnforcer(),
        )
        with pytest.raises(RoleRequiredError):
            auth.require_roles("Bearer x", required=(Role.OWNER,))

    def test_missing_header_still_raises_authentication_error(self) -> None:
        auth = Authenticator(
            verifier=lambda t: {"oid": "u"},
            resolver=_resolver(),
            enforcer=RoleEnforcer(),
        )
        with pytest.raises(AuthenticationError):
            auth.require_roles(None, required=(Role.READER,))


class TestBuildAuthenticator:
    def test_returns_authenticator_with_default_enforcer(self) -> None:
        auth = build_authenticator(
            verifier=lambda t: {"oid": "u", "roles": ["Reader"]},
            resolver=_resolver(),
        )
        assert isinstance(auth, Authenticator)
        assert isinstance(auth.enforcer, RoleEnforcer)


class TestUnsafeClaimsExtractor:
    def test_extracts_claims_from_forged_token(self) -> None:
        extractor = UnsafeClaimsExtractor()
        token = _forge_token({"oid": "user-1", "roles": ["Reader"]})
        claims = extractor(token)
        assert claims["oid"] == "user-1"

    def test_malformed_token_maps_to_authentication_error(self) -> None:
        extractor = UnsafeClaimsExtractor()
        with pytest.raises(AuthenticationError):
            extractor("garbage")

    def test_dev_extractor_plugs_into_authenticator(self) -> None:
        # End-to-end: forged token → UnsafeClaimsExtractor → resolver → Principal.
        auth = build_authenticator(
            verifier=UnsafeClaimsExtractor(),
            resolver=_resolver(),
        )
        token = _forge_token({"oid": "user-42", "roles": ["Owner"]})
        p = auth.authenticate(f"Bearer {token}")
        assert p.oid == "user-42"
        assert Role.OWNER in p.roles
