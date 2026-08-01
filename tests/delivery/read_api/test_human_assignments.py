from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from typing import Any

from starlette.testclient import TestClient

from fdai.core.human_assignment import AssignmentCaseService
from fdai.core.rbac.resolver import GroupMapping, RoleResolver
from fdai.core.stewardship.model import (
    AgentStewardship,
    Duty,
    Maintainer,
    Responsibility,
    StewardKind,
    StewardshipMap,
    StewardSubject,
)
from fdai.delivery.read_api.auth import UnsafeClaimsExtractor, build_authenticator
from fdai.delivery.read_api.main import ReadApiConfig, build_app
from fdai.delivery.read_api.read_model import InMemoryConsoleReadModel
from fdai.shared.providers.human_identity import (
    HumanIdentity,
    IdentityRosterEntry,
    StaticHumanIdentityDirectory,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore


def _token(claims: dict[str, Any]) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"RS256","typ":"JWT"}').rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    signature = base64.urlsafe_b64encode(b"sig").rstrip(b"=").decode()
    return f"{header}.{payload}.{signature}"


def _headers(oid: str, role: str) -> dict[str, str]:
    return {"authorization": f"Bearer {_token({'oid': oid, 'roles': [role]})}"}


def _stewardship() -> StewardshipMap:
    return StewardshipMap(
        version=2,
        maintainers=(Maintainer("maintainer-1"),),
        agents={
            "Odin": AgentStewardship(
                agent_name="Odin",
                stewards=(
                    StewardSubject(
                        StewardKind.USER,
                        "target-1",
                        Responsibility.ACCOUNTABLE,
                        Duty.PRIMARY,
                    ),
                    StewardSubject(
                        StewardKind.USER,
                        "backup-1",
                        Responsibility.ACCOUNTABLE,
                        Duty.BACKUP,
                    ),
                ),
            )
        },
    )


def _directory(*, roster: bool = True, active: bool = True) -> StaticHumanIdentityDirectory:
    return StaticHumanIdentityDirectory(
        identities=(
            HumanIdentity(
                provider="entra",
                subject_id="target-1",
                username="target@example.com",
                display_name="Target User",
                active=active,
            ),
        ),
        roster=(
            (
                IdentityRosterEntry(
                    provider="entra",
                    subject_id="target-1",
                    display_name="Target User",
                    principal_type="person",
                    roles=("Reader",),
                    username="target@example.com",
                ),
            )
            if roster
            else ()
        ),
    )


class _UnavailableDirectory(StaticHumanIdentityDirectory):
    async def get_by_subject_id(self, subject_id: str) -> HumanIdentity | None:
        del subject_id
        raise RuntimeError("provider response must not escape")

    async def list_role_roster(
        self,
        role_group_ids: Mapping[str, str],
        *,
        limit: int = 200,
    ) -> tuple[IdentityRosterEntry, ...]:
        del role_group_ids, limit
        raise RuntimeError("provider response must not escape")


def _client(
    *,
    directory: StaticHumanIdentityDirectory | None = None,
) -> TestClient:
    mapping = GroupMapping(
        reader_group_id="reader-group",
        contributor_group_id="contributor-group",
        approver_group_id="approver-group",
        owner_group_id="owner-group",
        break_glass_group_id="break-glass-group",
    )
    store = InMemoryStateStore()
    return TestClient(
        build_app(
            authenticator=build_authenticator(
                verifier=UnsafeClaimsExtractor(),
                resolver=RoleResolver(group_mapping=mapping),
            ),
            read_model=InMemoryConsoleReadModel(),
            config=ReadApiConfig(
                human_assignments=AssignmentCaseService(store=store),
                iam_directory=directory,
                iam_role_group_ids={"Reader": "reader-group"},
                stewardship_map=_stewardship(),
            ),
        )
    )


def _payload(**overrides: object) -> dict[str, object]:
    return {
        "idempotency_key": "assignment-api-1",
        "subject": {"provider": "entra", "subject_id": "target-1"},
        "requested_role": "Reader",
        "duty_bindings": [{"agent_name": "Odin", "duty": "primary", "scope_ref": "scope:platform"}],
        "goal_refs": ["goal:odin:operations:v1"],
        "justification": "Assign bounded platform ownership and console access.",
        **overrides,
    }


def test_assignment_routes_are_owner_only_and_bounded() -> None:
    api = _client(directory=_directory())

    assert (
        api.get("/iam/assignment-cases", headers=_headers("reader-1", "Reader")).status_code == 403
    )
    assert (
        api.post(
            "/iam/assignment-cases",
            headers=_headers("contributor-1", "Contributor"),
            json=_payload(),
        ).status_code
        == 403
    )
    assert (
        api.get(
            "/iam/assignment-cases?limit=101",
            headers=_headers("owner-1", "Owner"),
        ).status_code
        == 400
    )
    oversized = api.post(
        "/iam/assignment-cases",
        headers={**_headers("owner-1", "Owner"), "content-type": "application/json"},
        content=json.dumps(_payload(justification="x" * 33_000)),
    )
    assert oversized.status_code == 400
    assert "at most 32000 bytes" in oversized.json()["error"]["message"]


def test_create_revalidates_exact_active_subject_and_handles_directory_outage() -> None:
    inactive = _client(directory=_directory(active=False)).post(
        "/iam/assignment-cases",
        headers=_headers("owner-1", "Owner"),
        json=_payload(),
    )
    unavailable = _client(directory=_UnavailableDirectory()).post(
        "/iam/assignment-cases",
        headers=_headers("owner-1", "Owner"),
        json=_payload(),
    )

    assert inactive.status_code == 400
    assert inactive.json()["error"]["message"] == "target identity is inactive"
    assert unavailable.status_code == 503
    assert unavailable.json()["error"]["message"] == "human identity directory is unavailable"


def test_owner_creates_submits_gets_lists_and_reviews_with_cas() -> None:
    api = _client(directory=_directory())
    owner = _headers("owner-1", "Owner")
    created = api.post("/iam/assignment-cases", headers=owner, json=_payload())

    assert created.status_code == 201
    case = created.json()
    assert case["authority"] == "observation_only"
    assert case["intent"]["requester_ref"] == "owner-1"
    case_id = case["case_id"]
    stale = api.post(
        f"/iam/assignment-cases/{case_id}/submit",
        headers=owner,
        json={"expected_revision": 0},
    )
    submitted = api.post(
        f"/iam/assignment-cases/{case_id}/submit",
        headers=owner,
        json={"expected_revision": 1},
    )
    reviewed = api.post(
        f"/iam/assignment-cases/{case_id}/review",
        headers=_headers("owner-2", "Owner"),
        json={"expected_revision": 2, "decision": "approve"},
    )

    assert stale.status_code == 409
    assert submitted.status_code == 200
    assert submitted.json()["state"] == "pending_review"
    assert reviewed.status_code == 200
    assert reviewed.json()["state"] == "approved"
    assert api.get(f"/iam/assignment-cases/{case_id}", headers=owner).status_code == 200
    listed = api.get("/iam/assignment-cases?limit=1", headers=owner).json()
    assert listed["total"] == 1
    assert listed["items"][0]["case_id"] == case_id


def test_assignment_projection_joins_only_observed_provider_state() -> None:
    api = _client(directory=_directory(roster=False))
    owner = _headers("owner-1", "Owner")
    assert api.post("/iam/assignment-cases", headers=owner, json=_payload()).status_code == 201

    projection = api.get("/iam/assignments", headers=owner)

    assert projection.status_code == 200
    body = projection.json()
    assert body["authority"] == "observation_only"
    target = next(item for item in body["items"] if item["subject"]["subject_id"] == "target-1")
    assert target["subject"]["active"] is None
    assert target["subject"]["display_name"] is None
    assert target["roles"] is None
    assert target["duties"][0]["source"] == "stewardship"
    assert target["coverage"][0]["backup_or_escalation_count"] == 1
    assert target["case"]["state"] == "draft"
    assert target["handover"] == {
        "goal_refs": ["goal:odin:operations:v1"],
        "state": None,
        "evidence_refs": None,
        "availability": "not_connected",
    }
