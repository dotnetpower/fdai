#!/usr/bin/env python3
"""Bootstrap the deployment-only Graph identity for Teams app installation."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from typing import Any

import httpx

_GRAPH = "https://graph.microsoft.com/v1.0"
_DISPLAY_NAME = "fdai-system-knowledge-installer"
_CREDENTIAL_NAME = "fdai-system-knowledge-dev"
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_REQUIRED_ROLES = {
    "AppCatalog.ReadWrite.All",
    "TeamsAppInstallation.ReadWriteForTeam.All",
}


class InstallerIdentityError(RuntimeError):
    """The deployment-only Graph identity could not be proven or created."""


def bootstrap(
    *,
    repository: str,
    environment: str,
    access_token: str,
    transport: httpx.Client,
) -> dict[str, str]:
    """Create or verify one app, service principal, OIDC credential, and role set."""

    if _REPOSITORY.fullmatch(repository) is None or environment != "dev":
        raise InstallerIdentityError("installer identity scope is outside the dev repository")
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    applications = _collection(
        transport.get(
            f"{_GRAPH}/applications",
            headers=headers,
            params={
                "$filter": f"displayName eq '{_DISPLAY_NAME}'",
                "$select": "id,appId,displayName",
            },
        ),
        operation="read installer applications",
    )
    if len(applications) > 1:
        raise InstallerIdentityError("more than one installer application exists")
    if applications:
        application = applications[0]
    else:
        response = transport.post(
            f"{_GRAPH}/applications",
            headers=headers,
            json={"displayName": _DISPLAY_NAME, "signInAudience": "AzureADMyOrg"},
        )
        application = _object(response, expected={201}, operation="create installer application")
    application_object_id = _string(application, "id", "installer application")
    client_id = _string(application, "appId", "installer application")

    service_principals = _collection(
        transport.get(
            f"{_GRAPH}/servicePrincipals",
            headers=headers,
            params={"$filter": f"appId eq '{client_id}'", "$select": "id,appId"},
        ),
        operation="read installer service principal",
    )
    if len(service_principals) > 1:
        raise InstallerIdentityError("more than one installer service principal exists")
    if service_principals:
        service_principal = service_principals[0]
    else:
        response = transport.post(
            f"{_GRAPH}/servicePrincipals",
            headers=headers,
            json={"appId": client_id},
        )
        service_principal = _object(
            response,
            expected={201},
            operation="create installer service principal",
        )
    service_principal_id = _string(
        service_principal,
        "id",
        "installer service principal",
    )

    subject = f"repo:{repository}:environment:{environment}"
    credentials = _collection(
        transport.get(
            f"{_GRAPH}/applications/{application_object_id}/federatedIdentityCredentials",
            headers=headers,
        ),
        operation="read installer federated credentials",
    )
    matching = [
        item
        for item in credentials
        if item.get("name") == _CREDENTIAL_NAME
        and item.get("issuer") == "https://token.actions.githubusercontent.com"
        and item.get("subject") == subject
        and item.get("audiences") == ["api://AzureADTokenExchange"]
    ]
    if len(matching) > 1:
        raise InstallerIdentityError("installer federated credential is duplicated")
    if not matching:
        response = transport.post(
            f"{_GRAPH}/applications/{application_object_id}/federatedIdentityCredentials",
            headers=headers,
            json={
                "name": _CREDENTIAL_NAME,
                "issuer": "https://token.actions.githubusercontent.com",
                "subject": subject,
                "audiences": ["api://AzureADTokenExchange"],
                "description": "FDAI dev System Knowledge Teams app installation",
            },
        )
        _object(response, expected={201}, operation="create federated credential")

    graph_principals = _collection(
        transport.get(
            f"{_GRAPH}/servicePrincipals",
            headers=headers,
            params={
                "$filter": "displayName eq 'Microsoft Graph'",
                "$select": "id,appRoles",
            },
        ),
        operation="read Microsoft Graph service principal",
    )
    if len(graph_principals) != 1:
        raise InstallerIdentityError("Microsoft Graph service principal is ambiguous")
    graph = graph_principals[0]
    graph_id = _string(graph, "id", "Microsoft Graph service principal")
    app_roles = graph.get("appRoles")
    if not isinstance(app_roles, list):
        raise InstallerIdentityError("Microsoft Graph application roles are unavailable")
    role_ids = {
        item.get("value"): item.get("id")
        for item in app_roles
        if isinstance(item, dict)
        and item.get("isEnabled") is True
        and item.get("value") in _REQUIRED_ROLES
        and "Application" in item.get("allowedMemberTypes", [])
    }
    if set(role_ids) != _REQUIRED_ROLES or any(
        not isinstance(value, str) for value in role_ids.values()
    ):
        raise InstallerIdentityError("required Microsoft Graph application roles are unavailable")
    assignments = _collection(
        transport.get(
            f"{_GRAPH}/servicePrincipals/{service_principal_id}/appRoleAssignments",
            headers=headers,
        ),
        operation="read installer Graph assignments",
    )
    assigned = {item.get("appRoleId") for item in assignments if item.get("resourceId") == graph_id}
    for role_name in sorted(_REQUIRED_ROLES):
        role_id = role_ids[role_name]
        if role_id in assigned:
            continue
        response = transport.post(
            f"{_GRAPH}/servicePrincipals/{service_principal_id}/appRoleAssignments",
            headers=headers,
            json={
                "principalId": service_principal_id,
                "resourceId": graph_id,
                "appRoleId": role_id,
            },
        )
        _object(response, expected={201}, operation=f"assign {role_name}")
    return {
        "application_object_id": application_object_id,
        "client_id": client_id,
        "service_principal_id": service_principal_id,
    }


def _graph_token() -> str:
    result = subprocess.run(  # noqa: S603 - fixed Azure CLI command and arguments
        [
            "az",
            "account",
            "get-access-token",
            "--resource",
            "https://graph.microsoft.com",
            "--query",
            "accessToken",
            "--output",
            "tsv",
            "--only-show-errors",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    token = result.stdout.strip()
    if result.returncode != 0 or token.count(".") != 2 or not token.isprintable():
        raise InstallerIdentityError("Azure CLI did not return a valid Microsoft Graph token")
    return token


def _collection(response: httpx.Response, *, operation: str) -> list[dict[str, Any]]:
    value = _object(response, expected={200}, operation=operation)
    items = value.get("value")
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        raise InstallerIdentityError(f"Microsoft Graph {operation} returned invalid items")
    return items


def _object(
    response: httpx.Response,
    *,
    expected: set[int],
    operation: str,
) -> dict[str, Any]:
    if response.status_code not in expected:
        try:
            code = response.json().get("error", {}).get("code", "unknown")
        except (AttributeError, ValueError):
            code = "invalid_response"
        raise InstallerIdentityError(
            f"Microsoft Graph {operation} failed with HTTP {response.status_code} ({code})"
        )
    try:
        value = response.json()
    except ValueError as exc:
        raise InstallerIdentityError(f"Microsoft Graph {operation} returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise InstallerIdentityError(f"Microsoft Graph {operation} returned a non-object")
    return value


def _string(value: dict[str, Any], key: str, label: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item or len(item) > 256:
        raise InstallerIdentityError(f"{label} has no bounded {key}")
    return item


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--environment", choices=("dev",), default="dev")
    arguments = parser.parse_args()
    token = _graph_token()
    try:
        with httpx.Client(
            timeout=httpx.Timeout(connect=5.0, read=30.0, write=30.0, pool=5.0),
            follow_redirects=False,
        ) as client:
            result = bootstrap(
                repository=arguments.repository,
                environment=arguments.environment,
                access_token=token,
                transport=client,
            )
    finally:
        token = ""
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
