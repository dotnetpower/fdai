"""Focused contract tests for the independent Operator IAM route family."""

from __future__ import annotations

import ast
import json
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fdai_operator_service.families.iam import (
    IAM_FAMILY_MANIFEST,
    HilCallbackConfig,
    IamFamilyBindings,
    make_iam_family_routes,
)
from fdai_operator_service.families.iam.access_grants import access_grant_sse_frame
from fdai_operator_service.families.iam.contracts import (
    AccessGrantDecisionCommand,
    AccessGrantDecisionResult,
    AccessGrantRecord,
    AccessGrantSnapshot,
    AccessGrantSnapshotQuery,
    AccessRequestCommand,
    AccessRequestQuery,
    AccessReviewCommand,
    AssignmentCaseQuery,
    AssignmentCreateCommand,
    AssignmentTransitionCommand,
    ConfigurationReviewCommand,
    DirectoryIdentity,
    HandoverGoalCommand,
    HilDecisionCommand,
    HilDecisionOutboxRequest,
    HilDecisionReceipt,
    HilPendingItem,
    IamPrincipal,
    KillSwitchCommand,
    ModelBindingDraftCommand,
    ModelBindingRequestCommand,
    ModelPreferenceCommand,
    RuntimeSettingsCommand,
    SlackWebhookTestCommand,
    SlackWebhookTestResult,
    TeamsWorkflowTestCommand,
    TeamsWorkflowTestResult,
    WebSearchSettingsCommand,
)
from fdai_operator_service.families.iam.hil_callback import compute_hmac
from fdai_service_contracts import OperatorRole
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import StreamingResponse
from starlette.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[3]
FAMILY_SOURCE = REPO_ROOT / "services/operator-service/src/fdai_operator_service/families/iam"
NOW = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)


async def authorize(request: Request) -> IamPrincipal:
    """Resolve a test principal from a non-production header."""
    raw_role = request.headers.get("x-test-role", OperatorRole.READER.value)
    roles = frozenset() if raw_role == "unassigned" else frozenset({OperatorRole(raw_role)})
    return IamPrincipal(
        oid=request.headers.get("x-test-oid", "operator-1"),
        roles=roles,
        username="operator@example.com",
    )


class RecordingAccessGrants:
    def __init__(self) -> None:
        self.decision: AccessGrantDecisionCommand | None = None
        self.snapshot_query: AccessGrantSnapshotQuery | None = None

    async def snapshot(self, query: AccessGrantSnapshotQuery) -> AccessGrantSnapshot:
        self.snapshot_query = query
        return AccessGrantSnapshot(
            sequence=7,
            generated_at=NOW,
            requests=(
                AccessGrantRecord(
                    request_id="grant-1",
                    correlation_id="incident-1",
                    capability_id="metrics.read",
                    scope_ref="scope://example/resource",
                    grant_mode="time_bound",
                    requested_at=NOW,
                    expires_at=NOW + timedelta(hours=1),
                    quorum=1,
                    status="pending",
                    revision=3,
                ),
            ),
        )

    async def decide(self, command: AccessGrantDecisionCommand) -> AccessGrantDecisionResult:
        self.decision = command
        return AccessGrantDecisionResult(
            request_id=command.request_id,
            status="approved",
            revision=command.expected_revision + 1,
            approved_count=1,
            quorum=1,
            reviewed_at=NOW,
        )


class RecordingHumanAccess:
    def __init__(self) -> None:
        self.submitted: AccessRequestCommand | None = None
        self.reviewed: AccessReviewCommand | None = None

    async def list_request_page(
        self, query: AccessRequestQuery
    ) -> tuple[Sequence[Mapping[str, Any]], int]:
        del query
        return (), 0

    async def submit(self, command: AccessRequestCommand) -> Mapping[str, Any]:
        self.submitted = command
        return {"request_id": "request-1", "status": "pending"}

    async def review(self, command: AccessReviewCommand) -> Mapping[str, Any]:
        self.reviewed = command
        return {"request_id": command.request_id, "status": command.decision}


class RecordingDirectory:
    async def search(self, query: str, *, limit: int) -> Sequence[DirectoryIdentity]:
        del query, limit
        return ()

    async def list_role_roster(
        self, role_group_ids: Mapping[str, str], *, limit: int
    ) -> Sequence[DirectoryIdentity]:
        del role_group_ids, limit
        return ()

    async def get_by_subject_id(self, subject_id: str) -> DirectoryIdentity | None:
        return DirectoryIdentity(
            provider="entra",
            subject_id=subject_id,
            username="target@example.com",
            display_name="Target Operator",
            active=True,
        )


class RecordingAssignments:
    def __init__(self) -> None:
        self.created: AssignmentCreateCommand | None = None
        self.transition: AssignmentTransitionCommand | None = None

    async def list_case_page(
        self, query: AssignmentCaseQuery
    ) -> tuple[Sequence[Mapping[str, Any]], int]:
        del query
        return (), 0

    async def get_case(self, case_id: str) -> Mapping[str, Any]:
        return {
            "case_id": case_id,
            "intent": {"subject": {"provider": "entra", "subject_id": "target-1"}},
            "revision": 1,
        }

    async def create_case(self, command: AssignmentCreateCommand) -> Mapping[str, Any]:
        self.created = command
        return {"case_id": "case-1", "revision": 1}

    async def submit_for_review(self, command: AssignmentTransitionCommand) -> Mapping[str, Any]:
        self.transition = command
        return {"case_id": command.case_id, "revision": command.expected_revision + 1}

    async def review(self, command: AssignmentTransitionCommand) -> Mapping[str, Any]:
        self.transition = command
        return {"case_id": command.case_id, "revision": command.expected_revision + 1}

    async def assignment_projection(self, query: AssignmentCaseQuery) -> Mapping[str, Any]:
        del query
        return {"items": [], "total": 0}


class RecordingHandover:
    def __init__(self) -> None:
        self.command: HandoverGoalCommand | None = None

    async def invitation_for_session(
        self, *, subject_ref: str, session_id: str
    ) -> Mapping[str, Any] | None:
        return {"subject_ref": subject_ref, "session_id": session_id}

    async def get_goal(self, goal_id: str) -> Mapping[str, Any]:
        return {"goal_id": goal_id, "subject_ref": "target-1"}

    async def submit(self, command: HandoverGoalCommand) -> Mapping[str, Any]:
        self.command = command
        return {"goal_id": command.goal_id, "revision": command.expected_revision + 1}


class RecordingModelSettings:
    def __init__(self) -> None:
        self.preference: ModelPreferenceCommand | None = None
        self.web: WebSearchSettingsCommand | None = None
        self.binding_draft: ModelBindingDraftCommand | None = None
        self.binding_assessment: ModelBindingRequestCommand | None = None
        self.binding_plan: ModelBindingRequestCommand | None = None

    async def projection(
        self,
        principal_id: str,
        *,
        can_manage_web_search: bool = False,
        can_manage_model_bindings: bool = False,
        refresh_model_catalog: bool = False,
    ) -> Mapping[str, Any]:
        del refresh_model_catalog
        return {
            "principal_id": principal_id,
            "can_manage": can_manage_web_search,
            "can_manage_model_bindings": can_manage_model_bindings,
            "provider": {
                "clientSecret": "must-not-leak",
                "nested": [
                    {
                        "connection-string": "must-not-leak",
                        "visible": "preserved",
                    }
                ],
            },
        }

    async def set_preference(self, command: ModelPreferenceCommand) -> None:
        self.preference = command

    async def set_web_search_settings(self, command: WebSearchSettingsCommand) -> None:
        self.web = command

    async def save_binding_policy(self, command: ModelBindingDraftCommand) -> Mapping[str, Any]:
        self.binding_draft = command
        return {
            "proposal_id": "binding-draft-1",
            "accepted_at": "2026-08-25T00:00:00Z",
            "duplicate": False,
            "state": "draft",
            "policy_digest": command.policy_digest,
            "policy_revision": command.expected_revision + 1,
            "execution_authority": False,
            "activation_boundary": "protected-plan-only",
        }

    async def request_binding_assessment(
        self, command: ModelBindingRequestCommand
    ) -> Mapping[str, Any]:
        self.binding_assessment = command
        return {
            "proposal_id": "binding-assessment-1",
            "accepted_at": "2026-08-25T00:00:00Z",
            "duplicate": False,
            "state": "assessment-requested",
            "policy_digest": command.policy_digest,
            "policy_revision": command.policy_revision,
            "execution_authority": False,
            "activation_boundary": "protected-plan-only",
        }

    async def request_binding_plan(self, command: ModelBindingRequestCommand) -> Mapping[str, Any]:
        self.binding_plan = command
        return {
            "proposal_id": "binding-plan-1",
            "accepted_at": "2026-08-25T00:00:00Z",
            "duplicate": False,
            "state": "plan-requested",
            "policy_digest": command.policy_digest,
            "policy_revision": command.policy_revision,
            "execution_authority": False,
            "activation_boundary": "protected-plan-only",
        }


class RecordingRuntimeSettings:
    def __init__(self) -> None:
        self.command: RuntimeSettingsCommand | None = None

    async def projection(self, *, can_manage: bool) -> Mapping[str, Any]:
        return {
            "revision": 2,
            "can_manage": can_manage,
            "credentials": {"accessToken": "must-not-leak"},
        }

    async def update(self, command: RuntimeSettingsCommand) -> None:
        self.command = command


class RecordingTeamsWorkflowTester:
    def __init__(self) -> None:
        self.command: TeamsWorkflowTestCommand | None = None

    async def test(self, command: TeamsWorkflowTestCommand) -> TeamsWorkflowTestResult:
        self.command = command
        return TeamsWorkflowTestResult(
            request_id=command.request_id,
            accepted=True,
            provider_status=202,
            workflow_run_id="run-1",
            tested_at=NOW,
        )


class RecordingSlackWebhookTester:
    def __init__(self) -> None:
        self.command: SlackWebhookTestCommand | None = None

    async def test(self, command: SlackWebhookTestCommand) -> SlackWebhookTestResult:
        self.command = command
        return SlackWebhookTestResult(
            request_id=command.request_id,
            accepted=True,
            provider_status=200,
            tested_at=NOW,
        )


class RecordingKillSwitch:
    def __init__(self) -> None:
        self.command: KillSwitchCommand | None = None

    async def submit(self, command: KillSwitchCommand) -> Mapping[str, Any]:
        self.command = command
        return {"engaged": command.engaged, "request_id": command.request_id}


class RecordingReview:
    def __init__(self) -> None:
        self.command: ConfigurationReviewCommand | None = None

    async def run(self, command: ConfigurationReviewCommand) -> Mapping[str, Any]:
        self.command = command
        return {"campaign_id": "campaign-1", "state": "collecting"}

    async def resume(self, *, principal_id: str) -> Mapping[str, Any]:
        return {"campaign_id": "campaign-1", "principal_id": principal_id}


class RecordingHilRegistry:
    def __init__(self, *, submitter_oid: str = "submitter-1") -> None:
        self.pending = HilPendingItem(
            approval_id="approval-1",
            idempotency_key="hil-key-1",
            submitter_oid=submitter_oid,
        )
        self.receipt: HilDecisionReceipt | None = None
        self.command: HilDecisionCommand | None = None

    async def get_pending_by_approval_id(self, approval_id: str) -> HilPendingItem | None:
        return self.pending if approval_id == self.pending.approval_id else None

    async def get_decision_by_approval_id(self, approval_id: str) -> HilDecisionReceipt | None:
        return self.receipt if self.receipt and approval_id == self.receipt.approval_id else None

    async def record_decision(self, command: HilDecisionCommand) -> HilDecisionReceipt:
        self.command = command
        self.receipt = HilDecisionReceipt(
            approval_id="approval-1",
            idempotency_key=command.idempotency_key,
            decision=command.decision,
            approver_oid=command.approver_oid,
            decided_at=command.decided_at,
            receipt_ref="receipt-1",
        )
        return self.receipt

    async def mark_delivered(self, receipt: HilDecisionReceipt) -> HilDecisionReceipt:
        self.receipt = replace(receipt, delivered=True)
        return self.receipt


class RecordingHilOutbox:
    def __init__(self) -> None:
        self.request: HilDecisionOutboxRequest | None = None

    async def enqueue(self, request: HilDecisionOutboxRequest) -> None:
        self.request = request


def _bindings(**overrides: object) -> IamFamilyBindings:
    values: dict[str, object] = {
        "authorize": authorize,
        "authenticate": authorize,
    }
    values.update(overrides)
    return IamFamilyBindings(**values)  # type: ignore[arg-type]


def _client(**overrides: object) -> TestClient:
    return TestClient(Starlette(routes=make_iam_family_routes(_bindings(**overrides))))


def test_family_owns_exact_33_route_manifest_without_fdai_implementation_imports() -> None:
    routes = make_iam_family_routes(_bindings())
    snapshot = tuple(
        (next(iter((route.methods or set()) - {"HEAD"})), route.path, route.name)
        for route in routes
    )
    assert snapshot == tuple((item.method, item.path, item.name) for item in IAM_FAMILY_MANIFEST)
    assert len(snapshot) == 33

    for path in FAMILY_SOURCE.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        }
        assert not any(name == "fdai" or name.startswith("fdai.") for name in imports)


def test_unbound_mutations_fail_closed_and_reader_cannot_cross_owner_ceiling() -> None:
    client = _client()
    unavailable = client.post(
        "/system/kill-switch",
        headers={"x-test-role": "Owner"},
        json={
            "engaged": True,
            "reason": "A sufficiently long emergency reason.",
            "request_id": "r1",
        },
    )
    denied = client.put(
        "/runtime/settings",
        headers={"x-test-role": "Reader"},
        json={"changes": {}, "expected_revision": 0},
    )
    assert unavailable.status_code == 503
    assert denied.status_code == 403


def test_assigned_self_status_does_not_require_access_request_projection() -> None:
    response = _client().get(
        "/iam/self",
        headers={"x-test-role": "Reader", "x-test-oid": "reader-1"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "principal": {
            "subject_id": "reader-1",
            "username": "operator@example.com",
            "roles": ["Reader"],
        },
        "request": None,
        "can_access_console": True,
    }


def test_unassigned_self_status_still_requires_access_request_projection() -> None:
    unavailable = _client().get(
        "/iam/self",
        headers={"x-test-role": "unassigned", "x-test-oid": "new-user-1"},
    )
    available = _client(human_access=RecordingHumanAccess()).get(
        "/iam/self",
        headers={"x-test-role": "unassigned", "x-test-oid": "new-user-1"},
    )

    assert unavailable.status_code == 503
    assert available.status_code == 200
    assert available.json()["can_access_console"] is False
    assert available.json()["request"] is None


def test_access_grant_decision_keeps_revision_and_never_claims_permission_applied() -> None:
    grants = RecordingAccessGrants()
    response = _client(access_grants=grants).post(
        "/access-grants/grant-1/decision",
        headers={"x-test-role": "Owner", "x-test-oid": "owner-1"},
        json={
            "decision": "approve",
            "reason": "Bounded observation access is required.",
            "expected_revision": 3,
        },
    )
    assert response.status_code == 200
    assert response.json()["permission_applied"] is False
    assert response.json()["fresh_probe_required"] is True
    assert grants.decision is not None
    assert grants.decision.expected_revision == 3
    assert grants.decision.reviewer_roles == frozenset({"Owner"})


async def test_access_grant_stream_forwards_replay_cursor_and_encodes_sequence() -> None:
    grants = RecordingAccessGrants()
    route = make_iam_family_routes(_bindings(access_grants=grants))[1]
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/access-grants/stream",
            "headers": [(b"last-event-id", b"6")],
            "query_string": b"",
        }
    )
    response = await route.endpoint(request)
    assert isinstance(response, StreamingResponse)
    assert grants.snapshot_query is not None
    assert grants.snapshot_query.after_sequence == 6
    snapshot = await grants.snapshot(grants.snapshot_query)
    frame = access_grant_sse_frame(snapshot)
    assert frame.startswith(b"id: 7\nevent: access-grant\n")
    assert b'"executor_identity_ref"' not in frame


def test_human_access_and_assignment_routes_emit_typed_requests_only() -> None:
    access = RecordingHumanAccess()
    assignments = RecordingAssignments()
    directory = RecordingDirectory()
    client = _client(human_access=access, assignments=assignments, directory=directory)
    owner = {"x-test-role": "Owner", "x-test-oid": "owner-1"}
    submitted = client.post(
        "/iam/access-requests",
        headers=owner,
        json={
            "idempotency_key": "access-1",
            "target_subject_id": "target-1",
            "target_username": "target@example.com",
            "operation": "grant",
            "role": "Reader",
            "justification": "Grant bounded console read access.",
        },
    )
    created = client.post(
        "/iam/assignment-cases",
        headers=owner,
        json={
            "idempotency_key": "case-1",
            "subject": {"provider": "entra", "subject_id": "target-1"},
            "requested_role": "Reader",
            "duty_bindings": [
                {"agent_name": "odin", "duty": "primary", "scope_ref": "scope://example"}
            ],
            "goal_refs": [],
            "justification": "Assign bounded observation duty.",
        },
    )
    assert submitted.status_code == 201
    assert access.submitted is not None and access.submitted.idempotency_key == "access-1"
    assert created.status_code == 201
    assert created.json()["authority"] == "observation_only"
    assert assignments.created is not None and assignments.created.subject_id == "target-1"


def test_settings_kill_switch_and_review_preserve_revision_and_idempotency() -> None:
    models = RecordingModelSettings()
    runtime = RecordingRuntimeSettings()
    kill = RecordingKillSwitch()
    review = RecordingReview()
    client = _client(
        model_settings=models,
        runtime_settings=runtime,
        kill_switch=kill,
        configuration_review=review,
    )
    owner = {"x-test-role": "Owner", "x-test-oid": "owner-1"}
    assert (
        client.put(
            "/models/web-search-settings",
            headers=owner,
            json={
                "enabled": True,
                "allowed_domains": ["Learn.Microsoft.com."],
                "expected_revision": 4,
            },
        ).status_code
        == 200
    )
    assert (
        client.put(
            "/runtime/settings",
            headers=owner,
            json={"changes": {"logging.level": "INFO"}, "expected_revision": 2},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/system/kill-switch",
            headers=owner,
            json={
                "engaged": True,
                "reason": "A sufficiently long emergency reason.",
                "request_id": "stop-1",
            },
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/configuration-baselines/review/run",
            headers={**owner, "Idempotency-Key": "review-1"},
        ).status_code
        == 200
    )
    assert models.web is not None and models.web.allowed_domains == ("learn.microsoft.com",)
    assert runtime.command is not None and runtime.command.expected_revision == 2
    assert kill.command is not None and kill.command.request_id == "stop-1"
    assert review.command is not None and review.command.run_id == "review-1"


def test_owner_can_send_one_secret_free_teams_workflow_diagnostic() -> None:
    tester = RecordingTeamsWorkflowTester()
    webhook_url = (
        "https://example.e4.environment.api.powerplatform.com:443/"
        "powerautomate/automations/direct/workflows/"
        "d74f3e0ee1314a4191c650cfda483a70/triggers/manual/paths/invoke"
        "?api-version=1&sp=%2Ftriggers%2Fmanual%2Frun&sv=1.0"
        "&sig=abcdefghijklmnopqrstuvwxyz012345"
    )
    response = _client(teams_workflow_tester=tester).post(
        "/runtime/integrations/teams-workflow/test",
        headers={"x-test-role": "Owner", "x-test-oid": "owner-1"},
        json={"request_id": "teams-test-1", "webhook_url": webhook_url},
    )

    assert response.status_code == 200
    assert response.json() == {
        "request_id": "teams-test-1",
        "accepted": True,
        "provider_status": 202,
        "workflow_run_id": "run-1",
        "tested_at": NOW.isoformat(),
    }
    assert webhook_url not in response.text
    assert tester.command is not None and tester.command.actor_id == "owner-1"


def test_teams_workflow_diagnostic_requires_owner_and_injected_audit_store() -> None:
    request = {"request_id": "teams-test-1", "webhook_url": "https://example.invalid"}
    reader = _client(teams_workflow_tester=RecordingTeamsWorkflowTester()).post(
        "/runtime/integrations/teams-workflow/test",
        headers={"x-test-role": "Reader"},
        json=request,
    )
    unavailable = _client().post(
        "/runtime/integrations/teams-workflow/test",
        headers={"x-test-role": "Owner"},
        json=request,
    )

    assert reader.status_code == 403
    assert unavailable.status_code == 503


def test_owner_can_send_one_secret_free_slack_webhook_diagnostic() -> None:
    tester = RecordingSlackWebhookTester()
    webhook_url = "https://hooks.slack.com/services/T00000000/B00000000/abcdefghijklmnopqrstuvwxyz"
    response = _client(slack_webhook_tester=tester).post(
        "/runtime/integrations/slack-webhook/test",
        headers={"x-test-role": "Owner", "x-test-oid": "owner-1"},
        json={"request_id": "slack-test-1", "webhook_url": webhook_url},
    )

    assert response.status_code == 200
    assert response.json() == {
        "request_id": "slack-test-1",
        "accepted": True,
        "provider_status": 200,
        "tested_at": NOW.isoformat(),
    }
    assert webhook_url not in response.text
    assert tester.command is not None and tester.command.actor_id == "owner-1"


def test_slack_webhook_diagnostic_requires_owner_and_injected_audit_store() -> None:
    request = {"request_id": "slack-test-1", "webhook_url": "https://example.invalid"}
    reader = _client(slack_webhook_tester=RecordingSlackWebhookTester()).post(
        "/runtime/integrations/slack-webhook/test",
        headers={"x-test-role": "Reader"},
        json=request,
    )
    unavailable = _client().post(
        "/runtime/integrations/slack-webhook/test",
        headers={"x-test-role": "Owner"},
        json=request,
    )

    assert reader.status_code == 403
    assert unavailable.status_code == 503


def test_owner_can_submit_binding_draft_assessment_and_plan_without_authority() -> None:
    models = RecordingModelSettings()
    client = _client(model_settings=models)
    owner = {"x-test-role": "Owner", "x-test-oid": "owner-1"}
    policy = {
        "schema_version": "1.0.0",
        "environment": "staging",
        "revision": 1,
        "expected_active_digest": "sha256:" + "a" * 64,
        "capabilities": {
            "t2.reasoner.primary": {
                "selection_mode": "pinned",
                "publisher": "OpenAI",
                "family": "gpt-4o",
                "version_policy": "latest-compatible",
                "sku": "GlobalProvisionedManaged",
                "capacity": {"unit": "ptu", "value": 30},
            }
        },
    }
    draft = client.put(
        "/models/binding-policy",
        headers=owner,
        json={
            "policy": policy,
            "expected_revision": 0,
            "idempotency_key": "binding-draft-1",
        },
    )
    request = {
        "environment": "staging",
        "policy_revision": 1,
        "policy_digest": models.binding_draft.policy_digest,
        "idempotency_key": "binding-operation-1",
    }
    assessment = client.post(
        "/models/binding-policy/assess",
        headers=owner,
        json=request,
    )
    plan = client.post(
        "/models/binding-policy/plan",
        headers=owner,
        json={**request, "idempotency_key": "binding-operation-2"},
    )

    assert draft.status_code == 200
    assert assessment.status_code == plan.status_code == 202
    assert draft.headers["cache-control"] == "no-store"
    assert assessment.headers["cache-control"] == "no-store"
    assert plan.headers["cache-control"] == "no-store"
    assert draft.json()["execution_authority"] is False
    assert assessment.json()["execution_authority"] is False
    assert plan.json()["execution_authority"] is False
    assert assessment.json()["state"] == "assessment-requested"
    assert plan.json()["state"] == "plan-requested"
    assert assessment.json()["activation_boundary"] == "protected-plan-only"
    assert plan.json()["activation_boundary"] == "protected-plan-only"
    assert models.binding_assessment is not None
    assert models.binding_plan is not None


def test_non_owner_cannot_submit_model_binding_policy() -> None:
    response = _client(model_settings=RecordingModelSettings()).put(
        "/models/binding-policy",
        headers={"x-test-role": "Approver", "x-test-oid": "approver-1"},
        json={},
    )

    assert response.status_code == 403


def test_model_binding_routes_reject_unknown_and_malformed_identity_fields() -> None:
    client = _client(model_settings=RecordingModelSettings())
    owner = {"x-test-role": "Owner", "x-test-oid": "owner-1"}
    invalid_draft = client.put(
        "/models/binding-policy",
        headers=owner,
        json={
            "policy": {
                "schema_version": "1.0.0",
                "environment": "staging",
                "revision": 1,
                "capabilities": {"t1.embedding": {"selection_mode": "auto"}},
            },
            "expected_revision": 0,
            "idempotency_key": "draft-1",
            "execution_authority": True,
        },
    )
    invalid_request = {
        "environment": "STAGING",
        "policy_revision": 1,
        "policy_digest": "not-a-digest",
        "idempotency_key": "key\nforged",
    }

    assert invalid_draft.status_code == 400
    assert "unknown=['execution_authority']" in invalid_draft.text
    for path in ("assess", "plan"):
        response = client.post(
            f"/models/binding-policy/{path}",
            headers=owner,
            json=invalid_request,
        )
        assert response.status_code == 400


def test_iam_settings_redact_nested_sensitive_alias_fields() -> None:
    client = _client(
        model_settings=RecordingModelSettings(),
        runtime_settings=RecordingRuntimeSettings(),
    )
    owner = {"x-test-role": "Owner"}

    models = client.get("/models/settings", headers=owner)
    runtime = client.get("/runtime/settings", headers=owner)

    assert models.status_code == runtime.status_code == 200
    assert models.json()["provider"] == {
        "clientSecret": "[REDACTED]",
        "nested": [
            {
                "connection-string": "[REDACTED]",
                "visible": "preserved",
            }
        ],
    }
    assert runtime.json()["credentials"] == {"accessToken": "[REDACTED]"}


def test_signed_hil_callback_binds_path_rejects_self_approval_and_enqueues_receipt() -> None:
    registry = RecordingHilRegistry()
    hil_outbox = RecordingHilOutbox()
    config = HilCallbackConfig(secret="test-secret")
    client = _client(hil_registry=registry, hil_outbox=hil_outbox, hil_config=config)
    body = json.dumps(
        {
            "decision": "approve",
            "actor_oid": "owner-1",
            "actor_roles": ["Owner"],
            "justification": "Independent approval.",
        },
        separators=(",", ":"),
    ).encode()
    timestamp = datetime.now(UTC).isoformat()
    signature = compute_hmac(
        secret=config.secret,
        timestamp=timestamp,
        approval_id="approval-1",
        payload=body,
    )
    response = client.post(
        "/hil/approval-1/decision",
        content=body,
        headers={
            "X-FDAI-Timestamp": timestamp,
            "X-FDAI-Signature": f"sha256={signature}",
        },
    )
    path_swap = client.post(
        "/hil/approval-2/decision",
        content=body,
        headers={
            "X-FDAI-Timestamp": timestamp,
            "X-FDAI-Signature": f"sha256={signature}",
        },
    )
    assert response.status_code == 200
    assert response.json()["delivered"] is True
    assert registry.command is not None
    assert registry.command.justification == "Independent approval."
    assert hil_outbox.request is not None
    assert path_swap.status_code == 401

    self_registry = RecordingHilRegistry(submitter_oid="OWNER-1")
    self_response = _client(
        hil_registry=self_registry,
        hil_outbox=RecordingHilOutbox(),
        hil_config=config,
    ).post(
        "/hil/approval-1/decision",
        content=body,
        headers={
            "X-FDAI-Timestamp": timestamp,
            "X-FDAI-Signature": f"sha256={signature}",
        },
    )
    assert self_response.status_code == 403
    assert self_registry.command is None


def test_signed_hil_callback_requires_non_empty_justification() -> None:
    config = HilCallbackConfig(secret="test-secret")
    timestamp = datetime.now(UTC).isoformat()

    for payload in (
        {
            "decision": "approve",
            "actor_oid": "owner-1",
            "actor_roles": ["Owner"],
        },
        {
            "decision": "reject",
            "actor_oid": "owner-1",
            "actor_roles": ["Owner"],
            "justification": "   ",
        },
    ):
        registry = RecordingHilRegistry()
        body = json.dumps(payload, separators=(",", ":")).encode()
        signature = compute_hmac(
            secret=config.secret,
            timestamp=timestamp,
            approval_id="approval-1",
            payload=body,
        )

        response = _client(
            hil_registry=registry,
            hil_outbox=RecordingHilOutbox(),
            hil_config=config,
        ).post(
            "/hil/approval-1/decision",
            content=body,
            headers={
                "X-FDAI-Timestamp": timestamp,
                "X-FDAI-Signature": f"sha256={signature}",
            },
        )

        assert response.status_code == 400
        assert response.json()["error"]["message"] == ("'justification' MUST be a non-empty string")
        assert registry.command is None
