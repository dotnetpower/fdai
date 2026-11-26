"""Actual Operator scoped routes and adapter using isolated synthetic proposal/state sources."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fdai_operator_service.assignment_notice import assignment_notice_from_record
from fdai_operator_service.families.iam import IamFamilyBindings, make_iam_family_routes
from fdai_operator_service.families.iam.contracts import IamPrincipal
from fdai_operator_service.families.iam.errors import IamUnavailableError
from fdai_operator_service.postgres_scoped_duties import PostgresScopedDuties
from fdai_service_contracts import OperatorRole
from fdai_service_contracts.assignment_transport import assignment_content_digest
from starlette.applications import Starlette
from starlette.testclient import TestClient

NOW = datetime(2026, 9, 14, 12, tzinfo=UTC)
CORE_ID = "00000000-0000-0000-0000-000000000001"
BODY = {
    "idempotency_key": "example-case",
    "justification": "Review explicit scoped duty coverage.",
    "request": {
        "schema_version": "1.0.0",
        "source_revision": "revision:example",
        "bindings": [
            {
                "subject": {"kind": "group", "ref": "00000000-0000-0000-0000-000000000002"},
                "agent_name": "Odin",
                "scope_ref": "scope:example",
                "duty": "primary",
                "effective_from": NOW.isoformat(),
                "effective_until": (NOW + timedelta(hours=1)).isoformat(),
                "fallback": None,
            }
        ],
    },
}


class Store:
    def __init__(self):
        self.proposals = []
        self.state = {}

    async def append_proposal(self, **request):
        digest = assignment_content_digest(request)
        identifier = "operator-" + digest[:32]
        record = {
            **request,
            "kind": "operator.proposal",
            "mode": "shadow",
            "request_digest": digest,
            "proposal_id": identifier,
            "accepted_at": NOW.isoformat(),
        }
        self.proposals.append(record)
        return SimpleNamespace(proposal_id=identifier, accepted_at=NOW.isoformat(), record=record)

    async def find_state(self, *, prefix, field, value):
        return next((row for row in self.proposals if row[field] == value), None)

    async def read_state(self, key):
        return deepcopy(self.state.get(key))


def client(role=OperatorRole.OWNER, actor="human:owner", *, bound=True):
    store = Store()

    async def authorize(request):
        return IamPrincipal(actor, frozenset({role}))

    routes = make_iam_family_routes(
        IamFamilyBindings(
            authorize=authorize,
            authenticate=authorize,
            scoped_duties=PostgresScopedDuties(store) if bound else None,
        )
    )
    return TestClient(Starlette(routes=routes)), store


def seed_core(store, case_id):
    source = store.proposals[0]
    store.state["human_assignment:operator-case:" + case_id] = {
        "case_kind": "scoped_duty",
        "case_id": CORE_ID,
        "request_digest": source["request_digest"],
    }
    plan = {
        "kind": "scoped_duty_review",
        "schema_version": "1.0.0",
        "source_revision": "revision:example",
        "review_required": True,
        "execution_authority": False,
        "current_coverage": False,
    }
    digest = hashlib.sha256(
        json.dumps(plan, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    plan["digest"] = digest
    store.state["human_assignment:scoped-case:" + CORE_ID] = {
        "kind": "scoped_duty_case",
        "case_id": CORE_ID,
        "request": source["payload"]["request"],
        "state": "draft",
        "revision": 1,
        "execution_authority": False,
        "requester_ref": "human:owner",
        "plan_json": json.dumps(plan),
        "reviews": [],
        "commands": [{"proposal_id": case_id, "request_digest": source["request_digest"]}],
    }


def test_actual_family_queues_only_scoped_intent_and_versioned_notice():
    app, store = client()
    response = app.post("/handover/scoped-duty-cases", json=BODY)
    assert response.status_code == 202 and response.json()["state"] == "awaiting_core"
    assert response.headers["cache-control"] == "no-store"
    payload = store.proposals[0]["payload"]
    assert payload["case_kind"] == "scoped_duty" and payload["principal"]["roles"] == ["Owner"]
    assert "requested_role" not in payload and "subject_id" not in payload
    notice = assignment_notice_from_record(store.proposals[0])
    assert notice.schema_version == "1.2.0" and notice.case_id == response.json()["case_id"]
    assert store.state == {}


@pytest.mark.parametrize(
    "role",
    [
        OperatorRole.READER,
        OperatorRole.CONTRIBUTOR,
        OperatorRole.APPROVER,
        OperatorRole.BREAK_GLASS,
    ],
)
def test_scoped_route_requires_owner_before_any_source_io(role):
    app, store = client(role)
    assert app.post("/handover/scoped-duty-cases", json=BODY).status_code == 403
    assert app.get("/handover/scoped-duties/catalog").status_code == 403
    assert store.proposals == [] and store.state == {}


@pytest.mark.parametrize(
    "case", ["role", "authority", "numeric_time", "naive", "fallback", "duplicate", "oversized"]
)
def test_malformed_scoped_fields_never_enter_outbox(case):
    app, store = client()
    value = deepcopy(BODY)
    if case == "role":
        value["requested_role"] = "Owner"
    elif case == "authority":
        value["request"]["execution_authority"] = True
    elif case == "numeric_time":
        value["request"]["bindings"][0]["effective_from"] = 1
    elif case == "naive":
        value["request"]["bindings"][0]["effective_from"] = NOW.replace(tzinfo=None).isoformat()
    elif case == "fallback":
        value["request"]["bindings"][0]["subject"]["kind"] = "schedule"
    elif case == "duplicate":
        value["request"]["bindings"] *= 2
    else:
        value["request"]["bindings"] *= 31
    assert app.post("/handover/scoped-duty-cases", json=value).status_code == 400
    assert not store.proposals


def test_unbound_scoped_routes_remain_explicitly_unavailable():
    app, store = client(bound=False)
    assert app.post("/handover/scoped-duty-cases", json=BODY).status_code == 503
    assert not store.proposals


def test_exact_core_source_and_submission_do_not_advance_case_locally():
    app, store = client()
    case_id = app.post("/handover/scoped-duty-cases", json=BODY).json()["case_id"]
    route = "/handover/scoped-duty-cases/" + case_id
    assert app.get(route).json()["state"] == "awaiting_core"
    seed_core(store, case_id)
    assert app.get(route).json()["state"] == "draft"
    assert app.post(route + "/submit", json={"expected_revision": 1}).status_code == 202
    assert store.state["human_assignment:scoped-case:" + CORE_ID]["state"] == "draft"
    assert app.post(route + "/submit", json={"expected_revision": 2}).status_code == 409


@pytest.mark.parametrize("tamper", ["digest", "alias", "receipt", "authority"])
def test_scoped_source_corruption_never_becomes_a_ready_preview(tamper):
    app, store = client()
    case_id = app.post("/handover/scoped-duty-cases", json=BODY).json()["case_id"]
    seed_core(store, case_id)
    current = store.state["human_assignment:scoped-case:" + CORE_ID]
    if tamper == "digest":
        current["plan_json"] = current["plan_json"].replace(
            '"current_coverage": false', '"current_coverage": true'
        )
    elif tamper == "alias":
        store.state["human_assignment:operator-case:" + case_id]["request_digest"] = "b" * 64
    elif tamper == "receipt":
        current["commands"] = []
    else:
        current["execution_authority"] = 0
    assert app.get("/handover/scoped-duty-cases/" + case_id).status_code == 503


async def test_projection_uses_exact_scope_and_original_expiry():
    store = Store()
    now = datetime.now(UTC)
    store.state["human_assignment:scoped-observation"] = {
        "source_revision": "revision:example",
        "scopes": ["scope:example"],
        "observed_at": now.isoformat(),
        "expires_at": (now + timedelta(seconds=30)).isoformat(),
        "execution_authority": False,
        "artifact_delivery_available": False,
        "partial": False,
        "invalid_cases": 0,
        "items": [{"agent_name": "Odin", "scope_ref": "scope:example", "state": "held"}],
    }
    adapter = PostgresScopedDuties(store)
    result = await adapter.projection(agent_name="Odin", scope_ref="scope:example")
    assert result["state"] == "held"
    with pytest.raises(IamUnavailableError):
        await adapter.projection(agent_name="Odin", scope_ref="scope:platform")
    store.state["human_assignment:scoped-observation"]["expires_at"] = now.isoformat()
    with pytest.raises(IamUnavailableError):
        await adapter.catalog()
