"""Tests for the bounded local Azure CLI identity projection."""

from __future__ import annotations

import base64
import json

import pytest
from fdai_operator_service.local_auth import AzureCliIdentityError, resolve_azure_cli_identity
from fdai_service_contracts import OperatorPrincipalKind, OperatorRole


def _token(claims: dict[str, str]) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"RS256"}').rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    signature = base64.urlsafe_b64encode(b"signature").rstrip(b"=").decode()
    return f"{header}.{payload}.{signature}"


def _runner(
    *,
    tenant: str = "tenant-1",
    user_type: str = "user",
    claim_tenant: str = "tenant-1",
):
    responses = iter(
        (
            json.dumps(
                {
                    "state": "Enabled",
                    "tenantId": tenant,
                    "subscription": "must-not-be-projected",
                    "user": {"type": user_type, "name": "operator@example.com"},
                }
            ),
            json.dumps(
                {
                    "accessToken": _token(
                        {
                            "tid": claim_tenant,
                            "oid": "operator-oid",
                            "preferred_username": "operator@example.com",
                            "name": "Example Operator",
                        }
                    )
                }
            ),
        )
    )
    return lambda _: next(responses)


def test_resolves_browser_safe_contributor_identity() -> None:
    identity = resolve_azure_cli_identity(runner=_runner())

    assert identity.principal.subject_id == "operator-oid"
    assert identity.principal.roles == frozenset({OperatorRole.CONTRIBUTOR})
    assert identity.principal.principal_kind is OperatorPrincipalKind.HUMAN
    assert identity.to_dict() == {
        "oid": "operator-oid",
        "username": "operator@example.com",
        "name": "Example Operator",
        "roles": ["Contributor"],
        "source": "azure-cli",
    }


def test_rejects_service_principal_login() -> None:
    with pytest.raises(AzureCliIdentityError, match="interactive user"):
        resolve_azure_cli_identity(runner=_runner(user_type="servicePrincipal"))


def test_rejects_account_token_tenant_mismatch() -> None:
    with pytest.raises(AzureCliIdentityError, match="tenants do not match"):
        resolve_azure_cli_identity(runner=_runner(claim_tenant="tenant-2"))
