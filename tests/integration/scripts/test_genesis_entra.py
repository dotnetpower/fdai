"""Tenant-local Entra planning regressions for one-command Genesis."""

from __future__ import annotations

import sys
from pathlib import Path

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


def test_read_entra_bindings_returns_only_validated_repository_values(monkeypatch) -> None:
    api = {
        "displayName": "fdai-api",
        "signInAudience": "AzureADMyOrg",
        "appId": GUID,
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
