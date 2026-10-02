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
import genesis_entra_readback  # noqa: E402

GUID = "00000000-0000-0000-0000-000000000000"
ROLE_GROUPS = {
    "readers": "00000000-0000-0000-0000-000000000011",
    "contributors": "00000000-0000-0000-0000-000000000012",
    "approvers": "00000000-0000-0000-0000-000000000013",
    "owners": "00000000-0000-0000-0000-000000000014",
    "break_glass": "00000000-0000-0000-0000-000000000015",
}


def test_entra_plan_lists_only_missing_generic_objects(monkeypatch) -> None:
    monkeypatch.setattr(genesis_entra, "_single_app", lambda name: None)
    monkeypatch.setattr(genesis_entra, "_single_group", lambda name: None)

    plan = genesis_entra.plan_entra()

    assert plan.create_apps == ("fdai-api", "fdai-approval-bot", "fdai-console-spa")
    assert plan.create_groups == (
        "aw-approvers",
        "aw-break-glass",
        "aw-contributors",
        "aw-owners",
        "aw-readers",
    )
    assert plan.projection()["subscription_ready"] is False
    assert plan.projection()["provider_admin_consent"] is False
    assert len(plan.digest) == 64


def test_entra_plan_reads_independent_directory_objects_concurrently(monkeypatch) -> None:
    barrier = threading.Barrier(8)

    def read_app(_name: str):
        barrier.wait(timeout=1)
        return None

    def read_group(_name: str):
        barrier.wait(timeout=1)
        return None

    monkeypatch.setattr(genesis_entra, "_single_app", read_app)
    monkeypatch.setattr(genesis_entra, "_single_group", read_group)

    plan = genesis_entra.plan_entra()

    assert len(plan.create_apps) == 3
    assert len(plan.create_groups) == 5


def test_unique_display_name_preflight_reports_ambiguous_application(monkeypatch) -> None:
    def directory(command):
        if command[:3] == ("ad", "app", "list") and command[-1] == "fdai-api":
            return [{"displayName": "fdai-api"}, {"displayName": "fdai-api"}]
        if command[:3] == ("ad", "app", "list"):
            return [{"displayName": command[-1]}]
        if command[:3] == ("ad", "group", "list"):
            return [{"displayName": command[-1]}]
        raise AssertionError(command)

    monkeypatch.setattr(genesis_entra, "_az_json", directory)

    with pytest.raises(
        ValueError,
        match="enterprise_identity_governance_entra_display_name_ambiguous: applications=fdai-api",
    ):
        genesis_entra.check_unique_display_names()


def test_unique_display_name_preflight_reports_ambiguous_group(monkeypatch) -> None:
    def directory(command):
        if command[:3] == ("ad", "app", "list"):
            return [{"displayName": command[-1]}]
        if command[:3] == ("ad", "group", "list") and command[-1] == "aw-approvers":
            return [{"displayName": "aw-approvers"}, {"displayName": "aw-approvers"}]
        if command[:3] == ("ad", "group", "list"):
            return [{"displayName": command[-1]}]
        raise AssertionError(command)

    monkeypatch.setattr(genesis_entra, "_az_json", directory)

    with pytest.raises(
        ValueError,
        match=(
            "enterprise_identity_governance_entra_display_name_ambiguous: "
            "applications=none; groups=aw-approvers"
        ),
    ):
        genesis_entra.check_unique_display_names()


def test_unique_display_name_preflight_accepts_unique_tenant(monkeypatch) -> None:
    calls = []

    def directory(command):
        calls.append(command)
        return [{"displayName": command[-1]}]

    monkeypatch.setattr(genesis_entra, "_az_json", directory)

    result = genesis_entra.check_unique_display_names()

    assert result["state"] == "unique"
    assert result["mutation_performed"] is False
    assert len(calls) == 8


def test_bounded_plan_requires_existing_groups_and_never_proposes_group_creation(
    monkeypatch,
) -> None:
    monkeypatch.setattr(genesis_entra, "_single_app", lambda _name: None)
    slot_by_name = {
        display_name: slot
        for slot, (_variable, display_name, _role) in genesis_entra._GROUP_SLOTS.items()
    }
    monkeypatch.setattr(
        genesis_entra,
        "_single_group",
        lambda name: {"id": ROLE_GROUPS[slot_by_name[name]], "displayName": name},
    )

    plan = genesis_entra.plan_entra(
        bounded=True,
        approved_role_groups=ROLE_GROUPS,
    )

    assert plan.create_apps == ("fdai-api", "fdai-approval-bot", "fdai-console-spa")
    assert plan.create_groups == ()
    assert plan.projection()["create_groups"] == []
    assert plan.projection()["require_existing_role_groups"] is True
    assert isinstance(plan.projection()["role_group_binding_digest"], str)
    assert plan.projection()["configure_runner_owned_spa_graph_permission"] is False


def test_apply_entra_does_not_grant_provider_consent(monkeypatch) -> None:
    plan = genesis_entra.EntraPlan((), (), True, True, "a" * 64)
    app = {"appId": GUID}
    authority_calls = []

    monkeypatch.setattr(genesis_entra, "plan_entra", lambda: plan)
    monkeypatch.setattr(genesis_entra, "_ensure_group", lambda _name: GUID)
    monkeypatch.setattr(genesis_entra, "_ensure_api_app", lambda: app)
    monkeypatch.setattr(genesis_entra, "_ensure_spa_app", lambda _api: app)
    monkeypatch.setattr(genesis_entra, "_ensure_approval_bot_app", lambda _api: app)
    monkeypatch.setattr(genesis_entra, "_ensure_service_principal", lambda _app_id: {"id": GUID})
    monkeypatch.setattr(genesis_entra, "_assign_group_roles", lambda **_kwargs: None)
    monkeypatch.setattr(
        genesis_entra,
        "_ensure_current_owner_membership",
        lambda _group_id: authority_calls.append("owner-membership"),
    )
    monkeypatch.setattr(
        genesis_entra,
        "_grant_runner_spa_ownership",
        lambda *_args: authority_calls.append("spa-owner"),
    )
    monkeypatch.setattr(
        genesis_entra,
        "_grant_runner_graph_permission",
        lambda _runner_id: authority_calls.append("graph-role"),
    )
    monkeypatch.setattr(genesis_entra, "_verify_complete", lambda **_kwargs: None)
    monkeypatch.setattr(genesis_entra, "read_entra_bindings", lambda: {})
    monkeypatch.setattr(
        genesis_entra,
        "_az",
        lambda *_args: pytest.fail("provider consent must remain a separate approved operation"),
    )

    assert genesis_entra.apply_entra(plan, runner_principal_id=GUID) == {}
    assert authority_calls == ["owner-membership", "spa-owner", "graph-role"]


def test_bounded_apply_never_grants_runner_directory_authority(monkeypatch) -> None:
    plan = genesis_entra.EntraPlan(
        (),
        (),
        True,
        False,
        "a" * 64,
        tuple(sorted(ROLE_GROUPS.items())),
    )
    app = {"appId": GUID}
    monkeypatch.setattr(genesis_entra, "plan_entra", lambda **_kwargs: plan)
    monkeypatch.setattr(
        genesis_entra,
        "_ensure_group",
        lambda _name: pytest.fail("bounded apply attempted group creation"),
    )
    monkeypatch.setattr(
        genesis_entra,
        "_require_existing_group",
        lambda _name, expected: expected,
    )
    monkeypatch.setattr(genesis_entra, "_ensure_api_app", lambda: app)
    monkeypatch.setattr(genesis_entra, "_ensure_spa_app", lambda _api: app)
    monkeypatch.setattr(genesis_entra, "_ensure_approval_bot_app", lambda _api: app)
    monkeypatch.setattr(genesis_entra, "_ensure_service_principal", lambda _app_id: {"id": GUID})
    monkeypatch.setattr(genesis_entra, "_assign_group_roles", lambda **_kwargs: None)
    monkeypatch.setattr(
        genesis_entra,
        "_ensure_owner_membership",
        lambda *_args: pytest.fail("bounded apply changed owner membership"),
    )
    monkeypatch.setattr(
        genesis_entra,
        "_ensure_current_owner_membership",
        lambda *_args: pytest.fail("bounded apply changed current owner membership"),
    )
    monkeypatch.setattr(genesis_entra, "_verify_complete", lambda **_kwargs: None)
    monkeypatch.setattr(
        genesis_entra,
        "_grant_runner_spa_ownership",
        lambda *_args: pytest.fail("bounded apply granted SPA ownership"),
    )
    monkeypatch.setattr(
        genesis_entra,
        "_grant_runner_graph_permission",
        lambda *_args: pytest.fail("bounded apply granted Graph authority"),
    )

    assert genesis_entra.apply_entra_bounded(plan) is None


def test_bounded_apply_rejects_same_name_group_recreated_with_new_id_before_writes(
    monkeypatch,
) -> None:
    plan = genesis_entra.EntraPlan(
        (),
        (),
        True,
        False,
        "a" * 64,
        tuple(sorted(ROLE_GROUPS.items())),
    )
    slot_by_name = {
        display_name: slot
        for slot, (_variable, display_name, _role) in genesis_entra._GROUP_SLOTS.items()
    }
    replacement = "00000000-0000-0000-0000-000000000099"
    monkeypatch.setattr(genesis_entra, "plan_entra", lambda **_kwargs: plan)
    monkeypatch.setattr(
        genesis_entra,
        "_single_group",
        lambda name: {
            "id": (replacement if name == "aw-owners" else ROLE_GROUPS[slot_by_name[name]]),
            "displayName": name,
        },
    )
    monkeypatch.setattr(
        genesis_entra,
        "_ensure_api_app",
        lambda: pytest.fail("changed group binding reached first application write"),
    )

    with pytest.raises(ValueError, match="binding changed"):
        genesis_entra.apply_entra_bounded(plan)


@pytest.mark.parametrize(
    ("effect", "target_name"),
    [
        ("role-scope-definitions", "_ensure_api_app"),
        ("service-principals", "_ensure_service_principal"),
        ("group-role-assignments", "_assign_group_roles"),
    ],
)
def test_bounded_apply_stops_on_crash_before_each_effect(
    monkeypatch, effect: str, target_name: str
) -> None:
    plan = genesis_entra.EntraPlan(
        (),
        (),
        True,
        False,
        "a" * 64,
        tuple(sorted(ROLE_GROUPS.items())),
    )
    app = {"appId": GUID}
    monkeypatch.setattr(genesis_entra, "plan_entra", lambda **_kwargs: plan)
    monkeypatch.setattr(
        genesis_entra,
        "_ensure_group",
        lambda _name: pytest.fail("bounded apply attempted group creation"),
    )
    monkeypatch.setattr(
        genesis_entra,
        "_require_existing_group",
        lambda _name, expected: expected,
    )
    monkeypatch.setattr(genesis_entra, "_ensure_api_app", lambda: app)
    monkeypatch.setattr(genesis_entra, "_ensure_spa_app", lambda _api: app)
    monkeypatch.setattr(genesis_entra, "_ensure_approval_bot_app", lambda _api: app)
    monkeypatch.setattr(genesis_entra, "_ensure_service_principal", lambda _app_id: {"id": GUID})
    monkeypatch.setattr(genesis_entra, "_assign_group_roles", lambda **_kwargs: None)
    monkeypatch.setattr(
        genesis_entra,
        "_ensure_owner_membership",
        lambda *_args: pytest.fail("bounded apply changed owner membership"),
    )
    monkeypatch.setattr(genesis_entra, "_verify_complete", lambda **_kwargs: None)
    monkeypatch.setattr(
        genesis_entra,
        "_grant_runner_spa_ownership",
        lambda *_args: pytest.fail("crashed bounded apply reached SPA ownership"),
    )
    monkeypatch.setattr(
        genesis_entra,
        "_grant_runner_graph_permission",
        lambda *_args: pytest.fail("crashed bounded apply reached Graph authority"),
    )

    def crash(*_args, **_kwargs):
        raise RuntimeError(f"crash-before-{effect}")

    monkeypatch.setattr(genesis_entra, target_name, crash)

    with pytest.raises(RuntimeError, match=effect):
        genesis_entra.apply_entra_bounded(plan)


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
        "requiredResourceAccess": [
            {
                "resourceAppId": GUID,
                "resourceAccess": [{"id": GUID, "type": "Scope"}],
            }
        ],
    }
    approval_bot = {
        "displayName": "fdai-approval-bot",
        "signInAudience": "AzureADMyOrg",
        "appId": GUID,
        "requiredResourceAccess": [
            {
                "resourceAppId": GUID,
                "resourceAccess": [{"id": GUID, "type": "Scope"}],
            }
        ],
    }
    monkeypatch.setattr(
        genesis_entra,
        "_single_app",
        lambda name: (
            api if name == "fdai-api" else approval_bot if name == "fdai-approval-bot" else spa
        ),
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
        "FDAI_TEAMS_APPLICATION_ID",
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
        "requiredResourceAccess": [
            {
                "resourceAppId": GUID,
                "resourceAccess": [{"id": GUID, "type": "Scope"}],
            }
        ],
    }
    approval_bot = {
        "displayName": "fdai-approval-bot",
        "signInAudience": "AzureADMyOrg",
        "appId": GUID,
        "requiredResourceAccess": [
            {
                "resourceAppId": GUID,
                "resourceAccess": [{"id": GUID, "type": "Scope"}],
            }
        ],
    }
    monkeypatch.setattr(
        genesis_entra,
        "_single_app",
        lambda name: (
            api if name == "fdai-api" else approval_bot if name == "fdai-approval-bot" else spa
        ),
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


def test_complete_bounded_readback_requires_all_five_existing_group_assignments(
    monkeypatch,
) -> None:
    plan = genesis_entra.EntraPlan(
        (),
        (),
        True,
        False,
        "a" * 64,
        tuple(sorted(ROLE_GROUPS.items())),
    )
    roles = [role for _name, role in genesis_entra._GROUPS.values()]
    role_ids = {
        role: f"00000000-0000-0000-0000-{index:012d}" for index, role in enumerate(roles, start=101)
    }
    api = {
        "appId": "00000000-0000-0000-0000-000000000201",
        "appRoles": [
            {"value": role, "id": role_id, "isEnabled": True} for role, role_id in role_ids.items()
        ],
    }
    spa = {"appId": "00000000-0000-0000-0000-000000000202"}
    bot = {"appId": "00000000-0000-0000-0000-000000000203"}
    slot_by_name = {
        display_name: slot
        for slot, (_variable, display_name, _role) in genesis_entra._GROUP_SLOTS.items()
    }
    groups = {
        name: {"id": ROLE_GROUPS[slot_by_name[name]], "displayName": name}
        for name, _role in genesis_entra._GROUPS.values()
    }
    api_sp = "00000000-0000-0000-0000-000000000401"
    assignments = [
        {
            "principalId": groups[name]["id"],
            "resourceId": api_sp,
            "appRoleId": role_ids[role],
            "principalType": "Group",
        }
        for name, role in genesis_entra._GROUPS.values()
    ]
    monkeypatch.setattr(genesis_entra_readback, "plan_entra", lambda **_kwargs: plan)
    monkeypatch.setattr(genesis_entra_readback, "read_entra_bindings", lambda: {})
    monkeypatch.setattr(
        genesis_entra_readback,
        "_directory_inventory",
        lambda: (
            {
                "fdai-api": api,
                "fdai-console-spa": spa,
                "fdai-approval-bot": bot,
            },
            groups,
        ),
    )
    monkeypatch.setattr(
        genesis_entra_readback,
        "_read_service_principal",
        lambda app_id: {
            "id": {
                api["appId"]: api_sp,
                spa["appId"]: "00000000-0000-0000-0000-000000000402",
                bot["appId"]: "00000000-0000-0000-0000-000000000403",
            }[app_id],
            "appId": app_id,
        },
    )
    monkeypatch.setattr(
        genesis_entra_readback,
        "_graph",
        lambda *_args: {"value": assignments},
    )
    result = genesis_entra_readback.read_entra_effects(
        plan=plan,
    )

    assert result.projection()["group_role_assignments_verified"] is True
    assert result.projection()["owner_membership_changed_by_operation"] is False

    owners_id = groups["aw-owners"]["id"]
    approvers_id = groups["aw-approvers"]["id"]
    groups["aw-owners"]["id"] = approvers_id
    groups["aw-approvers"]["id"] = owners_id
    with pytest.raises(ValueError, match="binding changed"):
        genesis_entra_readback.read_entra_effects(plan=plan)
    groups["aw-owners"]["id"] = owners_id
    groups["aw-approvers"]["id"] = approvers_id

    assignments.pop()
    with pytest.raises(ValueError, match="assignment readback"):
        genesis_entra_readback.read_entra_effects(
            plan=plan,
        )
