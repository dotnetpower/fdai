from __future__ import annotations

import base64
import json
from typing import Any

from starlette.testclient import TestClient

from fdai.core.rbac.access_request import AccessRequestService
from fdai.core.rbac.resolver import GroupMapping, RoleResolver
from fdai.delivery.operator_api.auth import UnsafeClaimsExtractor, build_authenticator
from fdai.delivery.operator_api.main import OperatorApiConfig, build_app
from fdai.delivery.operator_api.read_model import InMemoryConsoleReadModel
from fdai.shared.providers.human_identity import (
    HumanIdentity,
    IdentityRosterEntry,
    StaticHumanIdentityDirectory,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore


def forge_token(claims: dict[str, Any]) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"RS256","typ":"JWT"}').rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    signature = base64.urlsafe_b64encode(b"sig").rstrip(b"=").decode()
    return f"{header}.{payload}.{signature}"


def client(*, with_directory: bool = False) -> TestClient:
    mapping = GroupMapping(
        reader_group_id="reader-group",
        contributor_group_id="contributor-group",
        approver_group_id="approver-group",
        owner_group_id="owner-group",
        break_glass_group_id="break-glass-group",
    )
    authenticator = build_authenticator(
        verifier=UnsafeClaimsExtractor(),
        resolver=RoleResolver(group_mapping=mapping),
    )
    app = build_app(
        authenticator=authenticator,
        read_model=InMemoryConsoleReadModel(),
        config=OperatorApiConfig(
            iam_access=AccessRequestService(store=InMemoryStateStore()),
            iam_directory=(
                StaticHumanIdentityDirectory(
                    (
                        HumanIdentity(
                            provider="entra",
                            subject_id="directory-user-1",
                            username="alex@example.com",
                            display_name="Alex Kim",
                        ),
                    ),
                    roster=(
                        IdentityRosterEntry(
                            provider="entra",
                            subject_id="group-reader",
                            display_name="fdai-readers",
                            principal_type="group",
                            roles=("Reader",),
                        ),
                        IdentityRosterEntry(
                            provider="entra",
                            subject_id="directory-user-1",
                            display_name="Alex Kim",
                            principal_type="person",
                            roles=("Reader",),
                            username="alex@example.com",
                        ),
                    ),
                )
                if with_directory
                else None
            ),
            iam_role_group_ids={"Reader": "group-reader"},
        ),
    )
    return TestClient(app)


def headers(oid: str, role: str) -> dict[str, str]:
    return {"authorization": f"Bearer {forge_token({'oid': oid, 'roles': [role]})}"}


def unassigned_headers(oid: str = "unassigned-1") -> dict[str, str]:
    claims = {"oid": oid, "upn": "new-user@example.com", "roles": []}
    return {"authorization": f"Bearer {forge_token(claims)}"}


def request_payload(**overrides: str) -> dict[str, str]:
    return {
        "idempotency_key": "iam-request-1",
        "target_oid": "target-1",
        "target_username": "user@example.com",
        "operation": "grant",
        "role": "Reader",
        "justification": "Required for the on-call support rotation.",
        **overrides,
    }


def test_iam_projection_uses_server_verified_roles() -> None:
    response = client().get("/iam", headers=headers("reader-1", "Reader"))

    assert response.status_code == 200
    assert response.json()["principal"] == {
        "oid": "reader-1",
        "roles": ["Reader"],
        "capabilities": ["view-console"],
    }
    assert [role["value"] for role in response.json()["roles"]] == [
        "Reader",
        "Contributor",
        "Approver",
        "Owner",
        "BreakGlass",
    ]
    assert response.json()["roles"][-1]["routine_assignment"] is False


def test_contributor_submits_and_replays_access_request() -> None:
    api = client()
    actor_headers = headers("contributor-1", "Contributor")

    first = api.post("/iam/access-requests", headers=actor_headers, json=request_payload())
    second = api.post("/iam/access-requests", headers=actor_headers, json=request_payload())
    denied_list = api.get("/iam/access-requests", headers=actor_headers)
    listed = api.get("/iam/access-requests", headers=headers("owner-1", "Owner"))

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["request_id"] == first.json()["request_id"]
    assert denied_list.status_code == 403
    assert listed.status_code == 200
    assert [item["request_id"] for item in listed.json()["items"]] == [first.json()["request_id"]]


def test_reader_cannot_submit_and_break_glass_is_not_routine() -> None:
    api = client()

    denied = api.post(
        "/iam/access-requests",
        headers=headers("reader-1", "Reader"),
        json=request_payload(),
    )
    break_glass = api.post(
        "/iam/access-requests",
        headers=headers("contributor-1", "Contributor"),
        json=request_payload(role="BreakGlass"),
    )

    assert denied.status_code == 403
    assert break_glass.status_code == 400
    assert "routine access requests" in break_glass.json()["error"]["message"]


def test_idempotency_conflict_returns_409() -> None:
    api = client()
    actor_headers = headers("contributor-1", "Contributor")
    assert (
        api.post(
            "/iam/access-requests",
            headers=actor_headers,
            json=request_payload(),
        ).status_code
        == 201
    )

    conflict = api.post(
        "/iam/access-requests",
        headers=actor_headers,
        json=request_payload(role="Owner"),
    )

    assert conflict.status_code == 409


def test_unassigned_user_can_request_reader_for_self() -> None:
    api = client()
    actor_headers = unassigned_headers()

    assert api.get("/iam", headers=actor_headers).status_code == 403
    before = api.get("/iam/self", headers=actor_headers)
    created = api.post(
        "/iam/access-requests/self",
        headers=actor_headers,
        json={"idempotency_key": "first-login-request"},
    )
    after = api.get("/iam/self", headers=actor_headers)

    assert before.status_code == 200
    assert before.json()["can_access_console"] is False
    assert before.json()["request"] is None
    assert created.status_code == 201
    assert created.json()["identity_provider"] == "entra"
    assert created.json()["target_subject_id"] == "unassigned-1"
    assert created.json()["role"] == "Reader"
    assert after.json()["request"]["request_id"] == created.json()["request_id"]


def test_only_owner_can_search_the_configured_identity_directory() -> None:
    api = client(with_directory=True)

    denied = api.get(
        "/iam/directory/users?q=alex",
        headers=headers("contributor-1", "Contributor"),
    )
    found = api.get(
        "/iam/directory/users?q=alex",
        headers=headers("owner-1", "Owner"),
    )

    assert denied.status_code == 403
    assert found.status_code == 200
    assert found.json() == {
        "provider": "entra",
        "items": [
            {
                "provider": "entra",
                "subject_id": "directory-user-1",
                "username": "alex@example.com",
                "display_name": "Alex Kim",
                "user_type": "member",
                "active": True,
            }
        ],
    }

    roster = api.get(
        "/iam/directory/roster",
        headers=headers("owner-1", "Owner"),
    )
    assert roster.status_code == 200
    assert [item["principal_type"] for item in roster.json()["items"]] == [
        "group",
        "person",
    ]


def test_access_request_validates_directory_identity_and_stamps_provider() -> None:
    api = client(with_directory=True)
    actor_headers = headers("contributor-1", "Contributor")
    valid = api.post(
        "/iam/access-requests",
        headers=actor_headers,
        json=request_payload(
            identity_provider="untrusted-provider",
            target_oid="directory-user-1",
            target_username="alex@example.com",
        ),
    )
    mismatch = api.post(
        "/iam/access-requests",
        headers=actor_headers,
        json=request_payload(
            idempotency_key="iam-request-2",
            target_oid="directory-user-1",
            target_username="other@example.com",
        ),
    )

    assert valid.status_code == 201
    assert valid.json()["identity_provider"] == "entra"
    assert mismatch.status_code == 400
    assert "does not match" in mismatch.json()["error"]["message"]


def test_owner_approves_request_but_requester_cannot_self_approve() -> None:
    api = client()
    request = api.post(
        "/iam/access-requests",
        headers=headers("requester-1", "Contributor"),
        json=request_payload(),
    ).json()
    decision_path = f"/iam/access-requests/{request['request_id']}/decision"
    body = {
        "decision": "approve",
        "justification": "Reviewed against the operator access policy.",
    }

    self_approval = api.post(
        decision_path,
        headers=headers("requester-1", "Owner"),
        json=body,
    )
    approved = api.post(
        decision_path,
        headers=headers("owner-2", "Owner"),
        json=body,
    )

    assert self_approval.status_code == 403
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert approved.json()["reviewed_by"] == "owner-2"
