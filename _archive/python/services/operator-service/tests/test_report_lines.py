"""Focused Operator report-line route tests with no Core or provider mutation."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from fdai_operator_service.families.iam import IamFamilyBindings, make_iam_family_routes
from fdai_operator_service.families.iam.contracts import (
    IamPrincipal,
    JsonMapping,
    ReportingLineCaseQuery,
    ReportingLineCreateCommand,
    ReportingLineTransitionCommand,
    ReportLineContactContext,
)
from fdai_service_contracts import OperatorRole, ReportLineContactCommand
from starlette.applications import Starlette
from starlette.testclient import TestClient

NOW = datetime(2026, 9, 16, 1, 0, tzinfo=UTC)
CASE = {
    "operator_case_id": "operator-" + "a" * 32,
    "case_id": "00000000-0000-0000-0000-000000000001",
    "candidate_id": "report-line-" + "b" * 32,
    "upload_id": "00000000-0000-0000-0000-000000000002",
    "requester_ref": "uploader",
    "subject_ref": "person-a",
    "manager_ref": "person-b",
    "state": "pending_confirmation",
    "revision": 1,
    "edge_digest": "c" * 64,
    "execution_authority": False,
    "approval_authority": False,
}


class Outbox:
    def __init__(self) -> None:
        self.created: list[ReportingLineCreateCommand] = []
        self.confirmed: list[ReportingLineTransitionCommand] = []
        self.reviewed: list[ReportingLineTransitionCommand] = []
        self.contacts: list[ReportLineContactCommand] = []

    async def list_report_line_case_page(
        self,
        query: ReportingLineCaseQuery,
    ) -> tuple[Sequence[JsonMapping], int]:
        del query
        return (CASE,), 1

    async def get_report_line_case(
        self,
        case_id: str,
        *,
        principal: IamPrincipal,
    ) -> JsonMapping:
        del principal
        assert case_id == CASE["operator_case_id"]
        return CASE

    async def create_report_line_case(
        self,
        command: ReportingLineCreateCommand,
    ) -> JsonMapping:
        self.created.append(command)
        return {**CASE, "state": "awaiting_core", "revision": 0}

    async def confirm_report_line(
        self,
        command: ReportingLineTransitionCommand,
    ) -> JsonMapping:
        self.confirmed.append(command)
        return CASE

    async def review_report_line(
        self,
        command: ReportingLineTransitionCommand,
    ) -> JsonMapping:
        self.reviewed.append(command)
        return CASE

    async def report_line_projection(self, query: ReportingLineCaseQuery) -> JsonMapping:
        del query
        return {
            "schema_version": "1.0.0",
            "graph_revision": "d" * 64,
            "items": [CASE],
            "total": 1,
            "next_cursor": None,
            "summary": {
                "active": 0,
                "pending_confirmation": 1,
                "pending_owner_review": 0,
                "activation_pending": 0,
                "conflict": 0,
                "awaiting_core": 0,
            },
            "execution_authority": False,
            "approval_authority": False,
        }

    async def get_report_line_contact_context(
        self,
        approval_id: str,
    ) -> ReportLineContactContext | None:
        if approval_id != "approval-1":
            return None
        return ReportLineContactContext(
            approval_id=approval_id,
            requester_ref="person-a",
            consent_id="00000000-0000-0000-0000-000000000003",
            consent_revision=0,
            action_type="ops.restart-service",
            target_ref="scope://service/example",
            route_subjects=("person-b",),
            consent_requested_at=NOW,
            expires_at=datetime(2026, 9, 16, 1, 5, tzinfo=UTC),
        )

    async def list_report_line_contact_contexts(
        self,
        *,
        requester_ref: str,
        limit: int,
    ) -> tuple[ReportLineContactContext, ...]:
        context = await self.get_report_line_contact_context("approval-1")
        if requester_ref != "person-a" or context is None:
            return ()
        return (context,)[:limit]

    async def enqueue_report_line_contact(
        self,
        command: ReportLineContactCommand,
    ) -> None:
        self.contacts.append(command)


def _client(
    role: OperatorRole,
    *,
    actor: str = "person-a",
) -> tuple[TestClient, Outbox]:
    outbox = Outbox()

    async def authorize(_request: Any) -> IamPrincipal:
        return IamPrincipal(actor, frozenset({role}))

    routes = make_iam_family_routes(
        IamFamilyBindings(
            authorize=authorize,
            authenticate=authorize,
            reporting_lines=outbox,
            report_line_contact=outbox,
        )
    )
    return TestClient(Starlette(routes=routes)), outbox


def test_contributor_can_submit_exact_candidate_without_activation() -> None:
    client, outbox = _client(OperatorRole.CONTRIBUTOR, actor="uploader")

    response = client.post(
        "/handover/reporting-line-cases",
        json={
            "idempotency_key": "report-line-import-example",
            "upload_id": CASE["upload_id"],
            "candidate_id": CASE["candidate_id"],
            "effective_from": NOW.isoformat(),
            "effective_until": "2026-12-15T01:00:00+00:00",
            "supersedes_case_id": None,
        },
    )

    assert response.status_code == 201
    assert response.json()["authority"] == "observation_only"
    assert outbox.created[0].case_kind == "report_line"
    assert outbox.created[0].principal.oid == "uploader"


def test_reader_cannot_create_report_line_case() -> None:
    client, outbox = _client(OperatorRole.READER)

    response = client.post(
        "/handover/reporting-line-cases",
        json={
            "idempotency_key": "report-line-import-example",
            "upload_id": CASE["upload_id"],
            "candidate_id": CASE["candidate_id"],
            "effective_from": None,
            "effective_until": None,
            "supersedes_case_id": None,
        },
    )

    assert response.status_code == 403
    assert outbox.created == []


def test_endpoint_can_confirm_but_cannot_owner_review() -> None:
    client, outbox = _client(OperatorRole.READER)
    path = f"/handover/reporting-line-cases/{CASE['operator_case_id']}"
    body = {
        "expected_revision": 1,
        "decision": "confirm",
        "edge_digest": CASE["edge_digest"],
    }

    assert client.post(path + "/confirm", json=body).status_code == 202
    assert len(outbox.confirmed) == 1
    assert client.post(path + "/review", json={**body, "decision": "approve"}).status_code == 403
    assert outbox.reviewed == []


def test_owner_can_review_and_projection_carries_no_authority() -> None:
    client, outbox = _client(OperatorRole.OWNER, actor="owner")
    path = f"/handover/reporting-line-cases/{CASE['operator_case_id']}"

    response = client.post(
        path + "/review",
        json={
            "expected_revision": 1,
            "decision": "approve",
            "edge_digest": CASE["edge_digest"],
        },
    )
    projection = client.get("/handover/reporting-lines")

    assert response.status_code == 202
    assert len(outbox.reviewed) == 1
    assert projection.status_code == 200
    assert projection.json()["approval_authority"] is False
    assert projection.headers["cache-control"] == "no-store"


def test_requester_can_consent_to_contact_without_approving_action() -> None:
    client, outbox = _client(OperatorRole.READER, actor="person-a")

    response = client.post(
        "/hil/approval-1/report-line-contact",
        headers={"Idempotency-Key": "report-line-contact-1"},
        json={"consent": True, "expected_revision": 0},
    )

    assert response.status_code == 202
    assert response.json()["approval_authority"] is False
    assert response.json()["execution_authority"] is False
    assert len(outbox.contacts) == 1
    assert outbox.contacts[0].requester_ref == "person-a"
    replay = client.post(
        "/hil/approval-1/report-line-contact",
        headers={"Idempotency-Key": "report-line-contact-1"},
        json={"consent": True, "expected_revision": 0},
    )
    assert replay.status_code == 202
    assert outbox.contacts[1] == outbox.contacts[0]
    listed = client.get("/hil/report-line-contact-requests")
    assert listed.status_code == 200
    assert listed.json()["items"][0]["approval_id"] == "approval-1"


def test_non_requester_cannot_consent_to_contact() -> None:
    client, outbox = _client(OperatorRole.OWNER, actor="owner")

    response = client.post(
        "/hil/approval-1/report-line-contact",
        headers={"Idempotency-Key": "report-line-contact-1"},
        json={"consent": True, "expected_revision": 0},
    )

    assert response.status_code == 403
    assert outbox.contacts == []
