#!/usr/bin/env python3
"""Plan, apply, and verify tenant-local FDAI Console Entra bindings."""

from __future__ import annotations

import json
import re
import subprocess
import uuid
from dataclasses import dataclass
from typing import Any

from fdai_deployment_cli.contracts import canonical_digest

_APP_NAMES = ("fdai-api", "fdai-console-spa")
_GROUPS = {
    "RBAC_READERS_GROUP_ID": ("aw-readers", "Reader"),
    "RBAC_CONTRIBUTORS_GROUP_ID": ("aw-contributors", "Contributor"),
    "RBAC_APPROVERS_GROUP_ID": ("aw-approvers", "Approver"),
    "RBAC_OWNERS_GROUP_ID": ("aw-owners", "Owner"),
    "RBAC_BREAK_GLASS_GROUP_ID": ("aw-break-glass", "BreakGlass"),
}
_GUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")


@dataclass(frozen=True, slots=True)
class EntraPlan:
    """Exact generic object operations needed in the current active tenant."""

    create_apps: tuple[str, ...]
    create_groups: tuple[str, ...]
    configure_roles: bool
    configure_runner_graph: bool
    digest: str

    def projection(self) -> dict[str, object]:
        """Return value-free operations suitable for exact human review."""

        return {
            "schema_version": "fdai.genesis-entra-plan.v1",
            "create_apps": list(self.create_apps),
            "create_groups": list(self.create_groups),
            "configure_api_roles_and_scope": self.configure_roles,
            "configure_runner_owned_spa_graph_permission": self.configure_runner_graph,
            "plan_digest": self.digest,
            "mutation_performed": False,
            "subscription_ready": False,
        }


def plan_entra() -> EntraPlan:
    """Inspect exact display names and block ambiguous or incompatible adoption."""

    apps = {name: _single_app(name) for name in _APP_NAMES}
    groups = {name: _single_group(name) for name, _role in _GROUPS.values()}
    for name, app in apps.items():
        if app is not None:
            _validate_app(name, app)
    body: dict[str, object] = {
        "schema_version": "fdai.genesis-entra-plan.v1",
        "create_apps": sorted(name for name, value in apps.items() if value is None),
        "create_groups": sorted(name for name, value in groups.items() if value is None),
        "configure_api_roles_and_scope": True,
        "configure_runner_owned_spa_graph_permission": True,
    }
    return EntraPlan(
        create_apps=tuple(body["create_apps"]),
        create_groups=tuple(body["create_groups"]),
        configure_roles=True,
        configure_runner_graph=True,
        digest=canonical_digest(body),
    )


def apply_entra(plan: EntraPlan, *, runner_principal_id: str) -> dict[str, str]:
    """Converge approved tenant-local objects and return repository-safe variable names."""

    if not _GUID.fullmatch(runner_principal_id):
        raise ValueError("runner principal identity is invalid")
    if plan_entra().digest != plan.digest:
        raise ValueError("Entra plan changed before apply")
    groups = {
        variable: _ensure_group(display_name) for variable, (display_name, _role) in _GROUPS.items()
    }
    api_app = _ensure_api_app()
    spa_app = _ensure_spa_app(api_app)
    api_sp = _ensure_service_principal(str(api_app["appId"]))
    _ensure_service_principal(str(spa_app["appId"]))
    _az(("ad", "app", "permission", "admin-consent", "--id", str(spa_app["appId"])))
    _assign_group_roles(api_app=api_app, api_sp=api_sp, groups=groups)
    _ensure_current_owner_membership(groups["RBAC_OWNERS_GROUP_ID"])
    _grant_runner_spa_ownership(str(spa_app["appId"]), runner_principal_id)
    _grant_runner_graph_permission(runner_principal_id)
    _verify_complete(api_app=api_app, spa_app=spa_app, groups=groups)
    return read_entra_bindings()


def read_entra_bindings() -> dict[str, str]:
    """Read and validate the exact tenant-local app and group bindings."""

    api_app = _single_app("fdai-api")
    spa_app = _single_app("fdai-console-spa")
    groups = {
        variable: _single_group(display_name) for variable, (display_name, _role) in _GROUPS.items()
    }
    if api_app is None or spa_app is None or any(value is None for value in groups.values()):
        raise ValueError("Entra binding readback is incomplete")
    _validate_app("fdai-api", api_app)
    _validate_app("fdai-console-spa", spa_app)
    scope = _scope(api_app)
    return {
        "ENTRA_CONSOLE_API_SCOPE": f"api://{api_app['appId']}/{scope['value']}",
        "ENTRA_CONSOLE_SPA_CLIENT_ID": str(spa_app["appId"]),
        "OPERATOR_API_AUDIENCE": f"api://{api_app['appId']}",
        **{variable: str(value["id"]) for variable, value in groups.items() if value is not None},
    }


def _ensure_api_app() -> dict[str, Any]:
    app = _single_app("fdai-api")
    if app is None:
        app_id = _az(
            (
                "ad",
                "app",
                "create",
                "--display-name",
                "fdai-api",
                "--sign-in-audience",
                "AzureADMyOrg",
                "--query",
                "appId",
                "--output",
                "tsv",
            )
        )
        app = _app(app_id)
    roles = app.get("appRoles")
    scope = _scope_or_none(app)
    if not _roles_valid(roles) or scope is None:
        role_values = {
            item.get("value"): item.get("id")
            for item in roles or []
            if isinstance(item, dict)
            and item.get("value") in {role for _name, role in _GROUPS.values()}
            and _GUID.fullmatch(str(item.get("id", "")))
        }
        role_payload = [
            {
                "allowedMemberTypes": ["User"],
                "description": f"FDAI {role} role",
                "displayName": role,
                "id": role_values.get(role, str(uuid.uuid4())),
                "isEnabled": True,
                "value": role,
            }
            for _name, role in _GROUPS.values()
        ]
        scope_id = str(scope["id"]) if scope is not None else str(uuid.uuid4())
        _az(
            (
                "ad",
                "app",
                "update",
                "--id",
                str(app["appId"]),
                "--app-roles",
                json.dumps(role_payload),
            )
        )
        _graph(
            "PATCH",
            f"applications/{app['id']}",
            {
                "identifierUris": [f"api://{app['appId']}"],
                "api": {
                    "requestedAccessTokenVersion": 2,
                    "oauth2PermissionScopes": [
                        {
                            "id": scope_id,
                            "adminConsentDescription": "Access the FDAI Operator API",
                            "adminConsentDisplayName": "Access the FDAI Operator API",
                            "userConsentDescription": "Access the FDAI Operator API",
                            "userConsentDisplayName": "Access the FDAI Operator API",
                            "isEnabled": True,
                            "type": "User",
                            "value": "access",
                        }
                    ],
                },
            },
        )
        app = _app(str(app["appId"]))
    return app


def _ensure_spa_app(api_app: dict[str, Any]) -> dict[str, Any]:
    app = _single_app("fdai-console-spa")
    if app is None:
        app_id = _az(
            (
                "ad",
                "app",
                "create",
                "--display-name",
                "fdai-console-spa",
                "--sign-in-audience",
                "AzureADMyOrg",
                "--query",
                "appId",
                "--output",
                "tsv",
            )
        )
        app = _app(app_id)
    scope = _scope(api_app)
    required = app.get("requiredResourceAccess")
    configured = any(
        isinstance(item, dict)
        and str(item.get("resourceAppId", "")).casefold() == str(api_app["appId"]).casefold()
        for item in required or []
    )
    if not configured:
        _graph(
            "PATCH",
            f"applications/{app['id']}",
            {
                "spa": {
                    "redirectUris": [
                        "http://localhost:5273",
                        "http://127.0.0.1:5273",
                    ]
                },
                "requiredResourceAccess": [
                    {
                        "resourceAppId": api_app["appId"],
                        "resourceAccess": [{"id": scope["id"], "type": "Scope"}],
                    }
                ],
            },
        )
        app = _app(str(app["appId"]))
    return app


def _ensure_group(display_name: str) -> str:
    group = _single_group(display_name)
    if group is None:
        value = _az(
            (
                "ad",
                "group",
                "create",
                "--display-name",
                display_name,
                "--mail-nickname",
                display_name,
                "--query",
                "id",
                "--output",
                "tsv",
            )
        )
        if not _GUID.fullmatch(value):
            raise ValueError("created Entra group identity is invalid")
        return value
    return str(group["id"])


def _ensure_service_principal(app_id: str) -> dict[str, Any]:
    values = _az_json(("ad", "sp", "list", "--filter", f"appId eq '{app_id}'"))
    if not isinstance(values, list) or len(values) > 1:
        raise ValueError("Entra service principal is ambiguous")
    if not values:
        _az(("ad", "sp", "create", "--id", app_id, "--output", "none"))
        values = _az_json(("ad", "sp", "list", "--filter", f"appId eq '{app_id}'"))
    if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], dict):
        raise ValueError("Entra service principal is unavailable")
    return values[0]


def _assign_group_roles(
    *, api_app: dict[str, Any], api_sp: dict[str, Any], groups: dict[str, str]
) -> None:
    roles = {
        str(item["value"]): str(item["id"])
        for item in api_app["appRoles"]
        if isinstance(item, dict) and item.get("isEnabled") is True
    }
    existing = _graph("GET", f"servicePrincipals/{api_sp['id']}/appRoleAssignedTo")
    rows = existing.get("value") if isinstance(existing, dict) else None
    if not isinstance(rows, list):
        raise ValueError("Entra App Role assignment inventory is invalid")
    pairs = {
        (str(row.get("principalId")), str(row.get("appRoleId")))
        for row in rows
        if isinstance(row, dict)
    }
    for variable, (_display_name, role) in _GROUPS.items():
        pair = (groups[variable], roles[role])
        if pair not in pairs:
            _graph(
                "POST",
                f"servicePrincipals/{api_sp['id']}/appRoleAssignedTo",
                {"principalId": pair[0], "resourceId": api_sp["id"], "appRoleId": pair[1]},
            )


def _ensure_current_owner_membership(group_id: str) -> None:
    user_id = _az(("ad", "signed-in-user", "show", "--query", "id", "--output", "tsv"))
    members = _az_json(("ad", "group", "member", "list", "--group", group_id))
    if not isinstance(members, list):
        raise ValueError("Entra group membership inventory is invalid")
    if not any(isinstance(item, dict) and item.get("id") == user_id for item in members):
        _az(("ad", "group", "member", "add", "--group", group_id, "--member-id", user_id))


def _grant_runner_spa_ownership(spa_app_id: str, runner_principal_id: str) -> None:
    owners = _az_json(("ad", "app", "owner", "list", "--id", spa_app_id))
    if not isinstance(owners, list):
        raise ValueError("Entra application owner inventory is invalid")
    if not any(isinstance(item, dict) and item.get("id") == runner_principal_id for item in owners):
        _az(
            (
                "ad",
                "app",
                "owner",
                "add",
                "--id",
                spa_app_id,
                "--owner-object-id",
                runner_principal_id,
            )
        )


def _grant_runner_graph_permission(runner_principal_id: str) -> None:
    graph = _az_json(("ad", "sp", "list", "--display-name", "Microsoft Graph"))
    matches = (
        [
            item
            for item in graph
            if isinstance(item, dict) and item.get("displayName") == "Microsoft Graph"
        ]
        if isinstance(graph, list)
        else []
    )
    if len(matches) != 1:
        raise ValueError("Microsoft Graph service principal is unavailable")
    roles = [
        item
        for item in matches[0].get("appRoles", [])
        if isinstance(item, dict)
        and item.get("value") == "Application.ReadWrite.OwnedBy"
        and "Application" in item.get("allowedMemberTypes", [])
    ]
    if len(roles) != 1:
        raise ValueError("Microsoft Graph owned-application permission is unavailable")
    assignments = _graph("GET", f"servicePrincipals/{runner_principal_id}/appRoleAssignments")
    rows = assignments.get("value") if isinstance(assignments, dict) else None
    pair = (str(matches[0]["id"]), str(roles[0]["id"]))
    if not isinstance(rows, list):
        raise ValueError("runner Graph assignment inventory is invalid")
    if not any(
        isinstance(row, dict) and (str(row.get("resourceId")), str(row.get("appRoleId"))) == pair
        for row in rows
    ):
        _graph(
            "POST",
            f"servicePrincipals/{runner_principal_id}/appRoleAssignments",
            {
                "principalId": runner_principal_id,
                "resourceId": pair[0],
                "appRoleId": pair[1],
            },
        )


def _verify_complete(
    *, api_app: dict[str, Any], spa_app: dict[str, Any], groups: dict[str, str]
) -> None:
    _validate_app("fdai-api", _app(str(api_app["appId"])))
    _validate_app("fdai-console-spa", _app(str(spa_app["appId"])))
    if any(_single_group(name) is None for name, _role in _GROUPS.values()) or any(
        not _GUID.fullmatch(value) for value in groups.values()
    ):
        raise ValueError("Entra binding readback is incomplete")


def _validate_app(name: str, app: dict[str, Any]) -> None:
    if (
        app.get("displayName") != name
        or app.get("signInAudience") != "AzureADMyOrg"
        or not _GUID.fullmatch(str(app.get("appId", "")))
    ):
        raise ValueError("existing Entra application conflicts with the FDAI contract")


def _single_app(name: str) -> dict[str, Any] | None:
    values = _az_json(("ad", "app", "list", "--display-name", name))
    exact = (
        [item for item in values if isinstance(item, dict) and item.get("displayName") == name]
        if isinstance(values, list)
        else []
    )
    if len(exact) > 1:
        raise ValueError("Entra application display name is ambiguous")
    return exact[0] if exact else None


def _single_group(name: str) -> dict[str, Any] | None:
    values = _az_json(("ad", "group", "list", "--display-name", name))
    exact = (
        [item for item in values if isinstance(item, dict) and item.get("displayName") == name]
        if isinstance(values, list)
        else []
    )
    if len(exact) > 1:
        raise ValueError("Entra group display name is ambiguous")
    return exact[0] if exact else None


def _app(app_id: str) -> dict[str, Any]:
    value = _az_json(("ad", "app", "show", "--id", app_id))
    if not isinstance(value, dict):
        raise ValueError("Entra application readback is invalid")
    return value


def _scope(app: dict[str, Any]) -> dict[str, Any]:
    value = _scope_or_none(app)
    if value is None:
        raise ValueError("FDAI API delegated scope is unavailable")
    return value


def _scope_or_none(app: dict[str, Any]) -> dict[str, Any] | None:
    api = app.get("api")
    scopes = api.get("oauth2PermissionScopes") if isinstance(api, dict) else None
    matches = [
        item
        for item in scopes or []
        if isinstance(item, dict)
        and item.get("value") == "access"
        and item.get("isEnabled") is True
    ]
    return (
        matches[0] if len(matches) == 1 and _GUID.fullmatch(str(matches[0].get("id", ""))) else None
    )


def _roles_valid(value: object) -> bool:
    roles = (
        {
            str(item.get("value"))
            for item in value
            if isinstance(item, dict) and item.get("isEnabled") is True
        }
        if isinstance(value, list)
        else set()
    )
    return roles == {role for _name, role in _GROUPS.values()}


def _az(arguments: tuple[str, ...]) -> str:
    completed = subprocess.run(
        ["az", *arguments, "--only-show-errors"],
        check=False,
        capture_output=True,
        text=True,
        timeout=90,
    )
    if completed.returncode != 0:
        raise ValueError("Entra command failed")
    return completed.stdout.strip()


def _az_json(arguments: tuple[str, ...]) -> Any:
    raw = _az((*arguments, "--output", "json"))
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("Entra response is invalid") from exc


def _graph(method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    arguments = [
        "rest",
        "--method",
        method,
        "--uri",
        f"https://graph.microsoft.com/v1.0/{path}",
        "--output",
        "json",
    ]
    if body is not None:
        arguments.extend(
            (
                "--headers",
                "Content-Type=application/json",
                "--body",
                json.dumps(body, separators=(",", ":")),
            )
        )
    raw = _az(tuple(arguments))
    if not raw:
        return {}
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Microsoft Graph response is invalid")
    return value
