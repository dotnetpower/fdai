"""Authenticated HTTP removal requests remain inert and require an exact person."""

from __future__ import annotations

from dataclasses import replace

import pytest
from fdai_operator_service.families.iam.assignments import make_assignment_routes
from fdai_operator_service.families.iam.contracts import DirectoryIdentity, IamPrincipal
from fdai_service_contracts import OperatorRole
from starlette.applications import Starlette
from starlette.testclient import TestClient

IDENTITY = DirectoryIdentity("entra", "target-1", "user@example.com", None, True)
REMOVAL = {"case_id": "old", "revision": 7, "replacement_revisions": {"primary": 7, "backup": 7}}
BODY = {
    "idempotency_key": "remove-1",
    "subject": {"provider": "entra", "subject_id": "target-1"},
    "requested_role": "Reader",
    "duty_bindings": [{"agent_name": "Thor", "duty": "primary", "scope_ref": "scope:platform"}],
    "goal_refs": [],
    "justification": "Review removal after independently confirmed replacement coverage.",
    "revocation": REMOVAL,
}


class Directory:
    def __init__(self, identity):
        self.identity = identity
        self.reads = 0

    async def get_by_subject_id(self, subject_id):
        self.reads += 1
        return self.identity


class Outbox:
    def __init__(self):
        self.created = []
        self.submitted = []

    async def create_case(self, command):
        self.created.append(command)
        return {"case_id": "removal", "state": "draft", "revision": 1}

    async def get_case(self, case_id):
        return {
            "case_id": case_id,
            "intent": {"subject": BODY["subject"], "revocation": REMOVAL},
            "state": "draft",
            "revision": 1,
        }

    async def submit_for_review(self, command):
        self.submitted.append(command)
        return {"case_id": command.case_id, "state": "draft", "revision": 1}


def _client(identity=IDENTITY, *, role=OperatorRole.OWNER):
    outbox, directory = Outbox(), Directory(identity)

    async def authorize(request):
        return IamPrincipal("human:owner", frozenset({role}))

    routes = make_assignment_routes(outbox=outbox, directory=directory, authorize=authorize)
    return TestClient(Starlette(routes=routes)), outbox, directory


def test_owner_submits_exact_removal_as_an_observation_only_request():
    client, outbox, _ = _client()
    response = client.post("/iam/assignment-cases", json=BODY)
    assert response.status_code == 201
    assert response.json()["authority"] == "observation_only"
    assert outbox.created[0].revocation == REMOVAL
    assert not hasattr(outbox, "apply")


@pytest.mark.parametrize(
    "identity", [replace(IDENTITY, subject_id="other"), replace(IDENTITY, principal_type="group")]
)
def test_removal_rejects_a_different_identity_or_non_person(identity):
    client, outbox, _ = _client(identity)
    response = client.post("/iam/assignment-cases", json=BODY)
    assert response.status_code == 400
    assert outbox.created == []


def test_disabled_exact_person_may_request_removal_but_never_a_grant():
    client, outbox, _ = _client(replace(IDENTITY, active=False))
    response = client.post("/iam/assignment-cases", json=BODY)
    assert response.status_code == 201
    grant = {key: value for key, value in BODY.items() if key != "revocation"}
    assert client.post("/iam/assignment-cases", json=grant).status_code == 400
    assert len(outbox.created) == 1
    submitted = client.post("/iam/assignment-cases/removal/submit", json={"expected_revision": 1})
    assert submitted.status_code == 200
    assert len(outbox.submitted) == 1


@pytest.mark.parametrize(
    "role",
    [
        OperatorRole.READER,
        OperatorRole.CONTRIBUTOR,
        OperatorRole.APPROVER,
        OperatorRole.BREAK_GLASS,
    ],
)
def test_removal_intent_cannot_bypass_owner_authority(role):
    client, outbox, directory = _client(role=role)
    assert client.post("/iam/assignment-cases", json=BODY).status_code == 403
    assert outbox.created == []
    assert directory.reads == 0


@pytest.mark.parametrize("revision", [True, "7", 0, -1])
def test_malformed_removal_is_held_before_directory_lookup(revision):
    client, outbox, directory = _client()
    body = {**BODY, "revocation": {**REMOVAL, "revision": revision}}
    assert client.post("/iam/assignment-cases", json=body).status_code == 400
    assert directory.reads == 0
    assert outbox.created == []
