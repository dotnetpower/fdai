"""Tests for the local Azure CLI identity projection."""

from __future__ import annotations

import base64
import json

import pytest

from fdai.core.rbac.roles import Role
from fdai.delivery.read_api.dev.azure_cli_identity import (
    AzureCliIdentityError,
    resolve_azure_cli_identity,
)


def _token(claims: dict[str, str]) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"RS256"}').rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    return f"{header}.{payload}.signature"


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

    assert identity.principal.oid == "operator-oid"
    assert identity.principal.roles == frozenset({Role.CONTRIBUTOR})
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