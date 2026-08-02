from __future__ import annotations

from datetime import UTC, datetime
from functools import partial

from starlette.applications import Starlette
from starlette.testclient import TestClient

from fdai.core.human_assignment import (
    AssignmentCase,
    AssignmentCaseService,
    AssignmentIntent,
    AssignmentState,
    DutyBinding,
    EffectKind,
    EffectReceipt,
    HandoverGoalService,
    ProviderSubject,
)
from fdai.core.rbac.resolver import Principal
from fdai.core.rbac.roles import Role
from fdai.core.stewardship import Duty
from fdai.delivery.operator_api.routes.handover_goals import make_handover_goal_routes
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_NOW = datetime(2026, 8, 3, tzinfo=UTC)


def _assignment() -> AssignmentCase:
    return AssignmentCase(
        case_id="case-1",
        intent=AssignmentIntent(
            idempotency_key="assignment-1",
            subject=ProviderSubject("entra", "subject-1"),
            requested_role=Role.READER,
            duty_bindings=(DutyBinding("Muninn", Duty.PRIMARY, "scope:platform"),),
            goal_refs=("runbook-v1",),
            requester_ref="requester-1",
            justification="Collect admitted operational evidence for this assignment.",
        ),
        state=AssignmentState.ACTIVE,
        revision=4,
        effect_receipts=(
            EffectReceipt(EffectKind.OWNERSHIP, "pr-1", "a" * 64, _NOW),
            EffectReceipt(EffectKind.IAM, "iam-1", "b" * 64, _NOW),
        ),
    )


def test_goal_routes_enforce_subject_and_independent_review() -> None:
    store = InMemoryStateStore()
    service = HandoverGoalService(
        store=store,
        assignments=AssignmentCaseService(store),
    )

    async def authorize(request):
        return request.headers.get("x-subject", "subject-1")

    async def authorize_principal(request):
        subject = request.headers.get("x-subject", "subject-1")
        roles = (
            frozenset({Role.OWNER}) if request.headers.get("x-owner") else frozenset({Role.READER})
        )
        return Principal(oid=subject, roles=roles)

    app = Starlette(
        routes=list(
            make_handover_goal_routes(
                service=service,
                authorize=authorize,
                authorize_principal=authorize_principal,
            )
        )
    )
    with TestClient(app) as client:
        client.portal.call(
            store.write_state,
            "human_assignment:case:case-1",
            _assignment().to_dict(),
        )
        goal = client.portal.call(
            partial(
                service.create_goal,
                assignment_case_id="case-1",
                agent_name="Muninn",
                scope_ref="scope:platform",
                prompt_ref="goal-template:runbook:v1",
                priority=90,
                now=_NOW,
            )
        )
        invitation = client.get(
            "/handover/goals/invitation?session_id=session-1",
            headers={"x-subject": "subject-1"},
        )
        assert invitation.status_code == 200
        assert invitation.json()["invitation"]["goal_id"] == goal.goal_id

        raw_answer = client.post(
            f"/handover/goals/{goal.goal_id}/evidence",
            headers={"x-subject": "subject-1"},
            json={"expected_revision": 1, "answer": "raw text"},
        )
        assert raw_answer.status_code == 400

        evidence = client.post(
            f"/handover/goals/{goal.goal_id}/evidence",
            headers={"x-subject": "subject-1"},
            json={
                "expected_revision": 1,
                "evidence_ref": "doc:document-1:version-1",
                "digest": "c" * 64,
                "kind": "document_span",
            },
        )
        assert evidence.status_code == 200
        revision = evidence.json()["goal"]["revision"]

        self_review = client.post(
            f"/handover/goals/{goal.goal_id}/accept",
            headers={"x-subject": "subject-1", "x-owner": "1"},
            json={"expected_revision": revision},
        )
        assert self_review.status_code == 403

        accepted = client.post(
            f"/handover/goals/{goal.goal_id}/accept",
            headers={"x-subject": "reviewer-1", "x-owner": "1"},
            json={"expected_revision": revision},
        )
        assert accepted.status_code == 200
        assert accepted.json()["goal"]["state"] == "accepted"
