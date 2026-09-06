"""Offline exact-wire and reconciliation tests; no credential files or live Graph."""

from __future__ import annotations

import copy
import json
import re
import ssl
from dataclasses import replace
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import pytest

from fdai_deployment_cli import entra_graph
from fdai_deployment_cli.entra_bootstrap import (
    ROLES,
    EntraDesired,
    apply_entra_bootstrap,
    plan_entra_bootstrap,
    readback_entra_bootstrap,
)
from fdai_deployment_cli.entra_graph import EntraBootstrapError, GraphResponse, GraphToken

TENANT, OWNER = str(UUID(int=1)), str(UUID(int=2))
TOKEN = "synthetic-in-memory-graph-token"


def desired(**changes: Any) -> EntraDesired:
    return replace(
        EntraDesired(
            TENANT, "example-binding", OWNER, "https://console.example.com", "example-fdai"
        ),
        **changes,
    )


def token(tenant: str) -> GraphToken:
    assert tenant == TENANT
    return GraphToken(TENANT, TOKEN)


class FakeGraph:
    """Small Graph double with independently stored writes and subsequent GETs."""

    def __init__(self) -> None:
        self.rows: dict[str, list[dict[str, Any]]] = {
            name: []
            for name in (
                "applications",
                "servicePrincipals",
                "groups",
                "oauth2PermissionGrants",
                "assignments",
            )
        }
        self.members: dict[str, list[dict[str, Any]]] = {}
        self.requests: list[tuple[str, str, dict[str, Any]]] = []
        self.intercept: Any = None
        self.tenant, self.owner = TENANT, OWNER

    def request(
        self, method: str, target: str, headers: Any, body: bytes, *, deadline: float
    ) -> GraphResponse:
        assert headers == {
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        assert deadline > 0 and target.startswith("/v1.0/")
        data = json.loads(body) if body else {}
        self.requests.append((method, target, copy.deepcopy(data)))
        parts = urlsplit(target)
        path = parts.path.removeprefix("/v1.0/")
        if self.intercept:
            intercepted = self.intercept(method, path, data)
            if intercepted is not None:
                return intercepted
        query = parse_qs(parts.query)
        segments = path.split("/")
        kind = segments[0]
        if method == "GET":
            if kind == "organization":
                assert query == {"$select": ["id"]}
                return self.response({"value": [{"id": self.tenant}]})
            if kind == "users":
                assert query == {"$select": ["id,accountEnabled"]}
                return (
                    self.response({"id": self.owner, "accountEnabled": True})
                    if segments[1] == self.owner
                    else GraphResponse(404)
                )
            if segments[-1] == "members":
                return self.response({"value": self.members.get(segments[1], [])})
            if segments[-1] == "appRoleAssignedTo":
                return self.response({"value": self.rows["assignments"]})
            if len(segments) == 2:
                rows = [row for row in self.rows[kind] if row["id"] == segments[1]]
                if not rows:
                    return GraphResponse(404)
                row = copy.deepcopy(rows[0])
                if kind == "servicePrincipals":
                    app = next(
                        app for app in self.rows["applications"] if app["appId"] == row["appId"]
                    )
                    row["appRoles"] = [
                        {**role, "origin": "Application"} for role in app["appRoles"]
                    ]
                    row["oauth2PermissionScopes"] = app["api"].get("oauth2PermissionScopes", [])
                return self.response(row)
            assert query["$top"] == ["100"]
            predicate = query.get("$filter", [""])[0]
            tag = re.fullmatch(r"tags/any\(t:t eq '([^']+)'\)", predicate)
            field = re.fullmatch(
                r"(displayName|mailNickname|appId|clientId) eq '([^']+)'", predicate
            )
            assert tag or field
            selected = [
                row
                for row in self.rows[kind]
                if (
                    tag.group(1) in row.get("tags", [])
                    if tag
                    else row.get(field.group(1)) == field.group(2)
                )
            ]
            return self.response({"value": selected})
        if method == "PATCH":
            row = next(row for row in self.rows[kind] if row["id"] == segments[1])
            row.update(copy.deepcopy(data))
            return GraphResponse(204)
        assert method == "POST"
        if segments[-1] == "$ref":
            assert kind == "groups" and segments[-2] == "members"
            assert data == {"@odata.id": f"https://graph.microsoft.com/v1.0/users/{OWNER}"}
            self.members.setdefault(segments[1], []).append({"id": OWNER})
            return GraphResponse(204)
        object_id = str(UUID(int=100 + sum(len(rows) for rows in self.rows.values())))
        row = {"id": object_id, **copy.deepcopy(data)}
        if kind == "applications":
            row = {
                "appId": str(UUID(int=1000 + len(self.rows[kind]))),
                "appRoles": [],
                "identifierUris": [],
                "api": {},
                "spa": {"redirectUris": []},
                "requiredResourceAccess": [],
                **row,
            }
        if kind == "groups":
            assert "isAssignableToRole" not in data
            row.update(isAssignableToRole=False, onPremisesSyncEnabled=None)
        if kind == "servicePrincipals" and segments[-1] != "appRoleAssignedTo":
            row.update(appOwnerOrganizationId=TENANT, servicePrincipalType="Application")
        if segments[-1] == "appRoleAssignedTo":
            kind = "assignments"
            row["principalType"] = "Group"
        self.rows[kind].append(row)
        return self.response({"id": object_id}, 201)

    @staticmethod
    def response(value: Any, status: int = 200) -> GraphResponse:
        return GraphResponse(status, json.dumps(value).encode())

    def writes(self) -> list[tuple[str, str, dict[str, Any]]]:
        return [row for row in self.requests if row[0] != "GET"]


def apply(fake: FakeGraph, **changes: Any) -> Any:
    return apply_entra_bootstrap(
        plan_entra_bootstrap(desired(**changes)), token_provider=token, transport=fake
    )


def test_fresh_exact_requests_and_private_result() -> None:
    fake = FakeGraph()
    result = apply(fake)
    plan = plan_entra_bootstrap(desired())
    posts = [(target, body) for method, target, body in fake.writes() if method == "POST"]
    assert len(posts) == 15  # two apps, two SPs, five groups, five assignments, one member
    api = fake.rows["applications"][0]
    assert api["appRoles"] == [
        {
            "id": role_id,
            "value": role,
            "displayName": role,
            "description": f"FDAI {role} human role",
            "allowedMemberTypes": ["User"],
            "isEnabled": True,
        }
        for role, role_id in zip(ROLES, plan.role_ids, strict=True)
    ]
    assert api["identifierUris"] == [f"api://{api['appId']}"]
    assert api["signInAudience"] == "AzureADMyOrg"
    assert api["api"]["requestedAccessTokenVersion"] == 2
    assert api["api"]["oauth2PermissionScopes"][0]["type"] == "User"
    assert api["api"]["oauth2PermissionScopes"][0]["value"] == "access"
    spa = fake.rows["applications"][1]
    assert spa["spa"] == {"redirectUris": [desired().console_origin]}
    assert spa["requiredResourceAccess"] == [
        {"resourceAppId": api["appId"], "resourceAccess": [{"id": plan.scope_id, "type": "Scope"}]}
    ]
    assert not fake.rows["oauth2PermissionGrants"]
    assert set(fake.members) == {dict(result.references.groups)["owners"]}
    for index, group in enumerate(fake.rows["groups"]):
        assert group["description"].startswith(plan.marker + ":")
        assert group["securityEnabled"] and not group["mailEnabled"] and not group["groupTypes"]
        assignment = fake.rows["assignments"][index]
        assert assignment["principalId"] == group["id"]
        assert assignment["appRoleId"] == plan.role_ids[index]
    assert all("/v1.0/me" not in path for _, path, _ in fake.requests)
    for private in (
        TENANT,
        OWNER,
        TOKEN,
        result.references.api_client_id,
        desired().console_origin,
    ):
        assert private not in repr(result) + repr(plan) + repr(token(TENANT))
    assert len(result.evidence_digest) == 64


def test_owned_repeat_and_independent_readback_are_get_only() -> None:
    fake = FakeGraph()
    result = apply(fake)
    fake.requests.clear()
    assert apply(fake) == result
    assert not fake.writes()
    fake.requests.clear()
    assert (
        readback_entra_bootstrap(
            plan_entra_bootstrap(desired()), result.references, token_provider=token, transport=fake
        )
        == result
    )
    assert not fake.writes()
    with pytest.raises(EntraBootstrapError, match="reference-mismatch"):
        readback_entra_bootstrap(
            plan_entra_bootstrap(desired()),
            replace(result.references, api_object_id=OWNER),
            token_provider=token,
            transport=fake,
        )


def test_preserves_unrelated_redirects_roles_scopes_permissions_and_assignments() -> None:
    fake = FakeGraph()
    result = apply(fake)
    api, spa = fake.rows["applications"]
    unrelated = {"id": str(UUID(int=8000)), "value": "Unrelated", "isEnabled": True}
    api["appRoles"].append(unrelated)
    api["api"]["oauth2PermissionScopes"].append(unrelated)
    permission = {"resourceAppId": str(UUID(int=8001)), "resourceAccess": []}
    spa["requiredResourceAccess"].append(permission)
    fake.rows["assignments"].append(
        {
            "principalId": str(UUID(int=8002)),
            "appRoleId": OWNER,
            "principalType": "User",
            "resourceId": result.references.api_service_principal_id,
        }
    )
    fake.requests.clear()
    apply(fake, console_origin="https://new-console.example.com")
    assert spa["spa"]["redirectUris"] == [
        desired().console_origin,
        "https://new-console.example.com",
    ]
    assert unrelated in api["appRoles"] and unrelated in api["api"]["oauth2PermissionScopes"]
    assert permission in spa["requiredResourceAccess"]
    assert len(fake.rows["assignments"]) == 6
    assert len(fake.members[dict(result.references.groups)["owners"]]) == 1


@pytest.mark.parametrize(
    "kind,ambiguous",
    [("applications", False), ("applications", True), ("groups", False), ("groups", True)],
)
def test_foreign_and_ambiguous_ownership_refuse_before_writes(kind: str, ambiguous: bool) -> None:
    fake = FakeGraph()
    apply(fake)
    row = fake.rows[kind][0]
    if ambiguous:
        fake.rows[kind].append({**row, "id": str(UUID(int=9000))})
    elif kind == "groups":
        row["description"] = "foreign-marker"
    else:
        row["tags"] = ["foreign-marker"]
    fake.requests.clear()
    with pytest.raises(EntraBootstrapError, match="ownership"):
        apply(fake)
    assert not fake.writes()


@pytest.mark.parametrize("mode", ["provider-tenant", "graph-tenant", "absent-owner"])
def test_wrong_tenant_and_absent_explicit_user_stop_before_writes(mode: str) -> None:
    fake = FakeGraph()
    provider = token
    if mode == "provider-tenant":

        def provider(_: str) -> GraphToken:
            return GraphToken(OWNER, TOKEN)
    elif mode == "graph-tenant":
        fake.tenant = OWNER
    else:
        fake.owner = str(UUID(int=3))
    with pytest.raises(EntraBootstrapError):
        apply_entra_bootstrap(
            plan_entra_bootstrap(desired()), token_provider=provider, transport=fake
        )
    assert not fake.writes()
    assert len(fake.requests) == {"provider-tenant": 0, "graph-tenant": 1, "absent-owner": 2}[mode]
    with pytest.raises(EntraBootstrapError):
        desired(initial_owner_user_id="")


def test_unexpected_provider_and_transport_defects_are_not_hidden() -> None:
    fake = FakeGraph()

    def broken_provider(_: str) -> GraphToken:
        raise AssertionError("provider defect")

    with pytest.raises(AssertionError, match="provider defect"):
        apply_entra_bootstrap(
            plan_entra_bootstrap(desired()),
            token_provider=broken_provider,
            transport=fake,
        )

    def broken_transport(method: str, path: str, data: Any) -> GraphResponse | None:
        raise AssertionError("transport defect")

    fake.intercept = broken_transport
    with pytest.raises(AssertionError, match="transport defect"):
        apply(fake)


@pytest.mark.parametrize("change", ["role-id", "role-flags", "scope-id", "scope-type"])
def test_role_or_scope_contract_conflicts_are_not_overwritten(change: str) -> None:
    fake = FakeGraph()
    apply(fake)
    api = fake.rows["applications"][0]
    row = (
        api["appRoles"][0] if change.startswith("role") else api["api"]["oauth2PermissionScopes"][0]
    )
    key = (
        "id"
        if change.endswith("id")
        else "allowedMemberTypes"
        if change == "role-flags"
        else "type"
    )
    row[key] = ["User", "Application"] if key == "allowedMemberTypes" else "conflicting-value"
    fake.requests.clear()
    with pytest.raises(EntraBootstrapError, match="role-or-scope-conflict"):
        apply(fake)
    assert not fake.writes()


@pytest.mark.parametrize("stage", ["redirect", "assignment", "owner", "consent"])
def test_http_acceptance_without_independent_effect_is_not_success(stage: str) -> None:
    fake = FakeGraph()
    if stage == "redirect":
        apply(fake)

    def intercept(method: str, path: str, data: Any) -> GraphResponse | None:
        if stage == "redirect" and method == "PATCH":
            return GraphResponse(204)
        suffix = {
            "assignment": "appRoleAssignedTo",
            "owner": "$ref",
            "consent": "oauth2PermissionGrants",
        }.get(stage)
        if method == "POST" and suffix and path.endswith(suffix):
            return fake.response({"id": str(UUID(int=9500))}, 201)
        return None

    fake.intercept = intercept
    with pytest.raises(EntraBootstrapError, match="readback"):
        apply(
            fake,
            console_origin="https://new-console.example.com",
            consent="initial-owner" if stage == "consent" else "none",
        )


def test_consent_is_only_owner_principal_and_custom_scope() -> None:
    fake = FakeGraph()
    result = apply(fake, consent="initial-owner")
    grant = fake.rows["oauth2PermissionGrants"][0]
    assert {key: value for key, value in grant.items() if key != "id"} == {
        "clientId": result.references.spa_service_principal_id,
        "resourceId": result.references.api_service_principal_id,
        "consentType": "Principal",
        "principalId": OWNER,
        "scope": "access",
    }
    fake.requests.clear()
    apply(fake, consent="initial-owner")
    assert not fake.writes()


@pytest.mark.parametrize("status", [302, 403, 404, 429, 503])
def test_sanitized_http_failure_never_retries(status: int) -> None:
    fake = FakeGraph()
    fake.intercept = lambda *_: GraphResponse(status, f"{TOKEN} {OWNER}".encode())
    with pytest.raises(EntraBootstrapError) as caught:
        apply(fake)
    assert caught.value.http_status == status
    assert TOKEN not in str(caught.value) and OWNER not in str(caught.value)
    assert len(fake.requests) == 1


@pytest.mark.parametrize("failure", ["timeout", "pagination", "unknown"])
def test_timeout_or_incomplete_collection_is_not_absence(failure: str) -> None:
    fake = FakeGraph()

    def intercept(*_: Any) -> GraphResponse:
        if failure == "timeout":
            raise TimeoutError(TOKEN)
        return fake.response(
            {"value": [], "@odata.nextLink": "https://foreign.example.com"}
            if failure == "pagination"
            else {}
        )

    fake.intercept = intercept
    with pytest.raises(EntraBootstrapError) as caught:
        apply(fake)
    assert TOKEN not in str(caught.value) and len(fake.requests) == 1


@pytest.mark.parametrize(
    "origin",
    [
        "http://console.example.com",
        "https://user@example.com",
        "https://example.com/path",
        "https://example.com?code=x",
    ],
)
def test_invalid_console_origins_are_rejected_without_io(origin: str) -> None:
    with pytest.raises(EntraBootstrapError, match="invalid-console-origin"):
        desired(console_origin=origin)


def test_response_and_request_budgets_stop_without_mutation(monkeypatch: Any) -> None:
    fake = FakeGraph()
    fake.intercept = lambda *_: GraphResponse(200, b"x" * (entra_graph.MAX_BYTES + 1))
    with pytest.raises(EntraBootstrapError, match="response-limit"):
        apply(fake)
    assert len(fake.requests) == 1 and not fake.writes()
    fake.intercept = None
    fake.requests.clear()
    monkeypatch.setattr(entra_graph, "MAX_REQUESTS", 1)
    with pytest.raises(EntraBootstrapError, match="request-limit"):
        apply(fake)
    assert len(fake.requests) == 1 and not fake.writes()


def test_unknown_application_fields_do_not_become_empty_collections() -> None:
    fake = FakeGraph()
    apply(fake)
    del fake.rows["applications"][0]["appRoles"]
    fake.requests.clear()
    with pytest.raises(EntraBootstrapError, match="incomplete-application"):
        apply(fake)
    assert not fake.writes()


def test_stdlib_transport_pins_tls_host_and_does_not_follow_redirect(monkeypatch: Any) -> None:
    observed: dict[str, Any] = {}

    class Socket:
        def settimeout(self, timeout: float) -> None:
            assert 0 < timeout <= 10

        def connect(self, address: Any) -> None:
            observed["address"] = address

        def close(self) -> None:
            pass

    class Context:
        def wrap_socket(self, sock: Any, *, server_hostname: str) -> Any:
            observed["sni"] = server_hostname
            return sock

    class Connection:
        def __init__(self, host: str, *, context: Any) -> None:
            observed["host"] = host
            self.sock: Any = None

        def request(self, method: str, target: str, **kwargs: Any) -> None:
            observed["request"] = method, target

        def getresponse(self) -> Any:
            return type("Response", (), {"status": 302})()

        def close(self) -> None:
            pass

    real_context = ssl.create_default_context

    def context() -> Context:
        tls = real_context()
        assert tls.verify_mode == ssl.CERT_REQUIRED and tls.check_hostname
        return Context()

    monkeypatch.setattr(entra_graph.ssl, "create_default_context", context)
    monkeypatch.setattr(entra_graph.http.client, "HTTPSConnection", Connection)
    monkeypatch.setattr(
        entra_graph.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("192.0.2.1", 443))]
    )
    monkeypatch.setattr(entra_graph.socket, "socket", lambda *a: Socket())
    with pytest.raises(EntraBootstrapError) as caught:
        apply_entra_bootstrap(plan_entra_bootstrap(desired()), token_provider=token)
    assert caught.value.http_status == 302
    assert observed["host"] == observed["sni"] == "graph.microsoft.com"
    assert observed["request"][0] == "GET"
