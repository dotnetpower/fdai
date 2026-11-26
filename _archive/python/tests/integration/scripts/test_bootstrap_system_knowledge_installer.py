from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/deployment/system_knowledge/bootstrap_installer_identity.py"
APP_ID = "00000000-0000-0000-0000-000000000001"
APP_OBJECT_ID = "00000000-0000-0000-0000-000000000002"
SP_ID = "00000000-0000-0000-0000-000000000003"
GRAPH_ID = "00000000-0000-0000-0000-000000000004"


def _module():
    spec = importlib.util.spec_from_file_location("bootstrap_installer_identity", SCRIPT)
    assert spec is not None and spec.loader is not None
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def test_bootstrap_creates_oidc_identity_and_exact_graph_roles() -> None:
    module = _module()
    assignments: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "GET" and path.endswith("/applications"):
            return httpx.Response(
                200,
                json={"value": [{"id": APP_OBJECT_ID, "appId": APP_ID}]},
            )
        if request.method == "GET" and path.endswith("/federatedIdentityCredentials"):
            return httpx.Response(200, json={"value": []})
        if request.method == "POST" and path.endswith("/federatedIdentityCredentials"):
            return httpx.Response(201, json={"id": "credential"})
        if request.method == "GET" and path.endswith("/servicePrincipals"):
            if request.url.params.get("$select") == "id,appRoles":
                return httpx.Response(
                    200,
                    json={
                        "value": [
                            {
                                "id": GRAPH_ID,
                                "appRoles": [
                                    {
                                        "id": "role-catalog",
                                        "value": "AppCatalog.ReadWrite.All",
                                        "isEnabled": True,
                                        "allowedMemberTypes": ["Application"],
                                    },
                                    {
                                        "id": "role-install",
                                        "value": ("TeamsAppInstallation.ReadWriteForTeam.All"),
                                        "isEnabled": True,
                                        "allowedMemberTypes": ["Application"],
                                    },
                                ],
                            }
                        ]
                    },
                )
            return httpx.Response(200, json={"value": [{"id": SP_ID, "appId": APP_ID}]})
        if request.method == "GET" and path.endswith("/appRoleAssignments"):
            return httpx.Response(200, json={"value": []})
        if request.method == "POST" and path.endswith("/appRoleAssignments"):
            assignments.append(json.loads(request.content)["appRoleId"])
            return httpx.Response(201, json={"id": "assignment"})
        raise AssertionError((request.method, path, request.url))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = module.bootstrap(
            repository="dotnetpower/fdai",
            environment="dev",
            access_token="header.payload.signature",
            transport=client,
        )

    assert result["client_id"] == APP_ID
    assert assignments == ["role-catalog", "role-install"]
