"""Tenant-local Entra planning regressions for one-command Genesis."""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT_DIR = ROOT / "scripts/deployment/azure"
sys.path.insert(0, str(SCRIPT_DIR))

import genesis_entra  # noqa: E402

GUID = "00000000-0000-0000-0000-000000000000"


def test_entra_plan_lists_only_missing_generic_objects(monkeypatch) -> None:
    monkeypatch.setattr(genesis_entra, "_single_app", lambda name: None)
    monkeypatch.setattr(genesis_entra, "_single_group", lambda name: None)

    plan = genesis_entra.plan_entra()

    assert plan.create_apps == ("fdai-api", "fdai-console-spa")
    assert plan.create_groups == (
        "aw-approvers",
        "aw-break-glass",
        "aw-contributors",
        "aw-owners",
        "aw-readers",
    )
    assert plan.projection()["subscription_ready"] is False
    assert len(plan.digest) == 64


def test_entra_plan_reads_independent_directory_objects_concurrently(monkeypatch) -> None:
    barrier = threading.Barrier(7)

    def read_app(_name: str):
        barrier.wait(timeout=1)
        return None

    def read_group(_name: str):
        barrier.wait(timeout=1)
        return None

    monkeypatch.setattr(genesis_entra, "_single_app", read_app)
    monkeypatch.setattr(genesis_entra, "_single_group", read_group)

    plan = genesis_entra.plan_entra()

    assert len(plan.create_apps) == 2
    assert len(plan.create_groups) == 5


def test_read_entra_bindings_returns_only_validated_repository_values(monkeypatch) -> None:
    api = {
        "displayName": "fdai-api",
        "signInAudience": "AzureADMyOrg",
        "appId": GUID,
        "appRoles": [
            {
                "value": role,
                "isEnabled": True,
                "allowedMemberTypes": list(member_types),
            }
            for role, member_types in genesis_entra._ROLE_MEMBER_TYPES.items()
        ],
        "api": {"oauth2PermissionScopes": [{"id": GUID, "value": "access", "isEnabled": True}]},
    }
    spa = {
        "displayName": "fdai-console-spa",
        "signInAudience": "AzureADMyOrg",
        "appId": GUID,
    }
    monkeypatch.setattr(
        genesis_entra,
        "_single_app",
        lambda name: api if name == "fdai-api" else spa,
    )
    monkeypatch.setattr(
        genesis_entra,
        "_single_group",
        lambda name: {"id": GUID, "displayName": name},
    )

    result = genesis_entra.read_entra_bindings()

    assert result["ENTRA_CONSOLE_API_SCOPE"] == f"api://{GUID}/access"
    assert result["OPERATOR_API_AUDIENCE"] == f"api://{GUID}"
    assert set(result) == {
        "ENTRA_CONSOLE_API_SCOPE",
        "ENTRA_CONSOLE_SPA_CLIENT_ID",
        "OPERATOR_API_AUDIENCE",
        "RBAC_APPROVERS_GROUP_ID",
        "RBAC_BREAK_GLASS_GROUP_ID",
        "RBAC_CONTRIBUTORS_GROUP_ID",
        "RBAC_OWNERS_GROUP_ID",
        "RBAC_READERS_GROUP_ID",
    }


def test_api_roles_require_human_roles_and_application_only_attachment_role() -> None:
    roles = [
        {
            "value": role,
            "isEnabled": True,
            "allowedMemberTypes": list(member_types),
        }
        for role, member_types in genesis_entra._ROLE_MEMBER_TYPES.items()
    ]

    assert genesis_entra._roles_valid(roles) is True
    assert genesis_entra._roles_valid(roles[:-1]) is False
    roles[-1]["allowedMemberTypes"] = ["User"]
    assert genesis_entra._roles_valid(roles) is False


def test_read_entra_bindings_rejects_missing_attachment_role(monkeypatch) -> None:
    api = {
        "displayName": "fdai-api",
        "signInAudience": "AzureADMyOrg",
        "appId": GUID,
        "appRoles": [
            {
                "value": role,
                "isEnabled": True,
                "allowedMemberTypes": list(member_types),
            }
            for role, member_types in list(genesis_entra._ROLE_MEMBER_TYPES.items())[:-1]
        ],
        "api": {"oauth2PermissionScopes": [{"id": GUID, "value": "access", "isEnabled": True}]},
    }
    spa = {
        "displayName": "fdai-console-spa",
        "signInAudience": "AzureADMyOrg",
        "appId": GUID,
    }
    monkeypatch.setattr(
        genesis_entra,
        "_single_app",
        lambda name: api if name == "fdai-api" else spa,
    )
    monkeypatch.setattr(
        genesis_entra,
        "_single_group",
        lambda name: {"id": GUID, "displayName": name},
    )

    with pytest.raises(ValueError, match="App Role readback"):
        genesis_entra.read_entra_bindings()


def test_console_spa_redirect_preserves_existing_values_and_verifies(monkeypatch) -> None:
    client_id = "00000000-0000-0000-0000-000000000001"
    object_id = "00000000-0000-0000-0000-000000000002"
    origin = "https://calm-field-012345678.3.azurestaticapps.net"
    app = {
        "id": object_id,
        "appId": client_id,
        "displayName": "fdai-console-spa",
        "signInAudience": "AzureADMyOrg",
        "spa": {"redirectUris": ["http://localhost:5273"]},
    }
    writes = []

    monkeypatch.setattr(genesis_entra, "_app", lambda _client_id: app)

    def graph(method, path, body):
        writes.append((method, path, body))
        app.update(body)
        return {}

    monkeypatch.setattr(genesis_entra, "_graph", graph)

    assert genesis_entra.ensure_console_spa_redirect(client_id, origin) is True
    assert writes == [
        (
            "PATCH",
            f"applications/{object_id}",
            {"spa": {"redirectUris": ["http://localhost:5273", origin]}},
        )
    ]
    assert genesis_entra.ensure_console_spa_redirect(client_id, origin) is False
    assert len(writes) == 1


@pytest.mark.parametrize(
    ("client_id", "origin"),
    [
        ("not-a-guid", "https://calm-field.azurestaticapps.net"),
        ("00000000-0000-0000-0000-000000000001", "https://console.example.com"),
    ],
)
def test_console_spa_redirect_rejects_unbound_values(
    monkeypatch, client_id: str, origin: str
) -> None:
    monkeypatch.setattr(
        genesis_entra,
        "_app",
        lambda *_args: pytest.fail("invalid binding must fail before Graph readback"),
    )

    with pytest.raises(ValueError, match="redirect binding"):
        genesis_entra.ensure_console_spa_redirect(client_id, origin)
