"""Focused contract tests for the independent Operator IAM route family."""

from __future__ import annotations

import ast
import json
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fdai_operator_service.auth import OperatorAuthenticator
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
    HilApprovalDecision,
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
from fdai_operator_service.families.iam.errors import IamConflictError, IamFamilyError
from fdai_operator_service.families.iam.hil_callback import (
    compute_hmac,
    make_hil_callback_route,
)
from fdai_operator_service.families.iam.hil_callback_audit import (
    HilCallbackAuditRecord,
    HilCallbackOutcome,
)
from fdai_operator_service.families.iam.hil_callback_authority import (
    EntraHilCallbackAuthority,
    HilCallbackActor,
    HilCallbackAuthorityConfig,
    HilCallbackAuthorityError,
    HilCallbackChannel,
)
from fdai_operator_service.families.iam.hil_callback_context import HilCallbackContext
from fdai_operator_service.families.iam.hil_decision_outbox import (
    DurableHilDecisionOutboxPublisher,
)
from fdai_operator_service.postgres_family_store import StoredProposal
from fdai_operator_service.postgres_iam import PostgresIamAdapters
from fdai_service_contracts import OperatorRole
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import StreamingResponse
from starlette.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[3]
FAMILY_SOURCE = REPO_ROOT / "services/operator-service/src/fdai_operator_service/families/iam"
NOW = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)


class _RuntimeSettingsStore:
    def __init__(self) -> None:
        self.state: dict[str, dict[str, object]] = {}
        self.proposals: list[dict[str, object]] = []
        self.runtime_projection = {
            "revision": 0,
            "can_manage": False,
            "updated_at": None,
            "updated_by": None,
            "integrations": [],
            "runtime": {},
            "settings": [
                {
                    "key": "conversation.answer_continuity.enabled",
                    "group": "conversation",
                    "value_type": "boolean",
                    "environment_value": False,
                    "override_value": None,
                    "effective_value": False,
                    "minimum": None,
                    "maximum": None,
                    "options": [],
                    "restart_required": True,
                    "available": True,
                    "unavailable_reason": None,
                },
                {
                    "key": "conversation.t2_escalation.aggressive_enabled",
                    "group": "conversation",
                    "value_type": "boolean",
                    "environment_value": True,
                    "override_value": None,
                    "effective_value": True,
                    "minimum": None,
                    "maximum": None,
                    "options": [],
                    "restart_required": False,
                    "available": True,
                    "unavailable_reason": None,
                },
                {
                    "key": "conversation.prompt_ablation.profile",
                    "group": "conversation",
                    "value_type": "enum",
                    "environment_value": "NONE",
                    "override_value": None,
                    "effective_value": "NONE",
                    "minimum": None,
                    "maximum": None,
                    "options": ["NONE", "TOOLS"],
                    "restart_required": True,
                    "available": True,
                    "unavailable_reason": None,
                },
                {
                    "key": "analyzer.budget_seconds",
                    "group": "analysis",
                    "value_type": "number",
                    "environment_value": 60.0,
                    "override_value": None,
                    "effective_value": 60.0,
                    "minimum": 1,
                    "maximum": 3600,
                    "options": [],
                    "restart_required": False,
                    "available": True,
                    "unavailable_reason": None,
                },
            ],
        }

    async def read_projection(self, *, family: str, operation: str) -> Mapping[str, object]:
        assert family == "iam"
        assert operation == "runtime-settings"
        return deepcopy(self.runtime_projection)

    async def read_state(self, key: str) -> Mapping[str, object] | None:
        return deepcopy(self.state.get(key))

    async def append_revisioned_proposal(
        self,
        *,
        family: str,
        operation: str,
        principal_id: str | None,
        idempotency_key: str,
        payload: Mapping[str, object],
        state_key: str,
        state_value: Mapping[str, object],
        expected_revision: int,
    ) -> StoredProposal:
        current = self.state.get(state_key)
        revision = current.get("revision", 0) if current is not None else 0
        if revision != expected_revision:
            raise IamConflictError("state revision conflict")
        self.state[state_key] = dict(state_value)
        self.proposals.append(
            {
                "family": family,
                "operation": operation,
                "principal_id": principal_id,
                "idempotency_key": idempotency_key,
                "payload": dict(payload),
            }
        )
        return StoredProposal(
            proposal_id="operator-runtime-settings",
            accepted_at=NOW.isoformat(),
            duplicate=False,
            record={},
        )


async def authorize(request: Request) -> IamPrincipal:
    """Resolve a test principal from a non-production header."""
    raw_role = request.headers.get("x-test-role", OperatorRole.READER.value)
    roles = frozenset() if raw_role == "unassigned" else frozenset({OperatorRole(raw_role)})
    return IamPrincipal(
        oid=request.headers.get("x-test-oid", "operator-1"),
        roles=roles,
        username="operator@example.com",
    )


async def test_postgres_runtime_settings_toggle_updates_core_policy_and_projection() -> None:
    store = _RuntimeSettingsStore()
    adapter = PostgresIamAdapters(store)  # type: ignore[arg-type]

    initial = await adapter.projection(can_manage=True)
    await adapter.update(
        RuntimeSettingsCommand(
            actor_id="owner-1",
            changes={
                "conversation.answer_continuity.enabled": True,
                "conversation.t2_escalation.aggressive_enabled": False,
                "conversation.prompt_ablation.profile": "TOOLS",
            },
            expected_revision=0,
        )
    )
    updated = await adapter.projection(can_manage=True)

    assert initial["revision"] == 0
    assert updated["revision"] == 1
    settings = {item["key"]: item for item in updated["settings"]}
    assert settings["conversation.answer_continuity.enabled"]["effective_value"] is True
    assert settings["conversation.t2_escalation.aggressive_enabled"]["effective_value"] is False
    assert settings["conversation.prompt_ablation.profile"]["effective_value"] == "TOOLS"
    assert store.state["runtime-settings:policy"]["overrides"] == {
        "conversation.answer_continuity.enabled": True,
        "conversation.t2_escalation.aggressive_enabled": False,
        "conversation.prompt_ablation.profile": "TOOLS",
    }
    assert store.proposals[0]["operation"] == "runtime-settings.update"

    with pytest.raises(IamConflictError, match="revision mismatch"):
        await adapter.update(
            RuntimeSettingsCommand(
                actor_id="owner-2",
                changes={"conversation.answer_continuity.enabled": False},
                expected_revision=0,
            )
        )


async def test_postgres_runtime_settings_rejects_unreviewed_ablation_profile() -> None:
    adapter = PostgresIamAdapters(_RuntimeSettingsStore())  # type: ignore[arg-type]

    with pytest.raises(IamFamilyError, match="projected options"):
        await adapter.update(
            RuntimeSettingsCommand(
                actor_id="owner-1",
                changes={"conversation.prompt_ablation.profile": "CUSTOM"},
                expected_revision=0,
            )
        )


def test_runtime_settings_http_reports_invalid_profile_as_bad_request() -> None:
    store = _RuntimeSettingsStore()
    client = _client(
        runtime_settings=PostgresIamAdapters(store),  # type: ignore[arg-type]
    )

    response = client.put(
        "/runtime/settings",
        headers={"x-test-role": "Owner", "x-test-oid": "owner-1"},
        json={
            "changes": {"conversation.prompt_ablation.profile": "CUSTOM"},
            "expected_revision": 0,
        },
    )

    assert response.status_code == 400
    assert "projected options" in response.json()["error"]["message"]
    assert store.state == {}
    assert store.proposals == []


def test_runtime_settings_http_rejects_non_finite_number() -> None:
    store = _RuntimeSettingsStore()
    client = _client(
        runtime_settings=PostgresIamAdapters(store),  # type: ignore[arg-type]
    )

    response = client.put(
        "/runtime/settings",
        headers={
            "content-type": "application/json",
            "x-test-role": "Owner",
            "x-test-oid": "owner-1",
        },
        content=('{"changes":{"analyzer.budget_seconds":NaN},"expected_revision":0}'),
    )

    assert response.status_code == 400
    assert "MUST be finite" in response.json()["error"]["message"]
    assert store.state == {}


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

    async def save_and_test(
        self,
        command: TeamsWorkflowTestCommand,
    ) -> TeamsWorkflowTestResult:
        self.command = command
        return TeamsWorkflowTestResult(
            request_id=command.request_id,
            saved=True,
            binding_version="version-1",
            saved_at=NOW,
            accepted=True,
            provider_status=202,
            workflow_run_id="run-1",
            tested_at=NOW,
        )

    async def reveal_binding(self, *, actor_id: str) -> Mapping[str, object]:
        self.reveal_actor_id = actor_id
        return {
            "webhook_url": "https://example.e4.environment.api.powerplatform.com/signed",
            "binding_version": "version-1",
            "revealed_at": NOW.isoformat(),
        }


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
        self.pending: HilPendingItem | None = HilPendingItem(
            approval_id="approval-1",
            idempotency_key="hil-key-1",
            submitter_oid=submitter_oid,
            metadata={
                "correlation_id": "correlation-1",
                "action_hash": "action-hash-1",
                "expires_at": (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
            },
        )
        self.receipt: HilDecisionReceipt | None = None
        self.command: HilDecisionCommand | None = None
        self.context = HilCallbackContext(
            approval_id=self.pending.approval_id,
            correlation_id=self.pending.metadata["correlation_id"],
            idempotency_key=self.pending.idempotency_key,
            action_hash=self.pending.metadata["action_hash"],
            expires_at=datetime.fromisoformat(self.pending.metadata["expires_at"]),
            submitter_oid=self.pending.submitter_oid,
            metadata=self.pending.metadata,
        )

    async def get_pending_by_approval_id(self, approval_id: str) -> HilPendingItem | None:
        return (
            self.pending
            if self.pending is not None and approval_id == self.pending.approval_id
            else None
        )

    async def get_decision_by_approval_id(self, approval_id: str) -> HilDecisionReceipt | None:
        return self.receipt if self.receipt and approval_id == self.receipt.approval_id else None

    async def get_callback_context(self, approval_id: str) -> HilCallbackContext | None:
        return self.context if approval_id == self.context.approval_id else None

    async def record_decision(self, command: HilDecisionCommand) -> HilDecisionReceipt:
        self.command = command
        self.receipt = HilDecisionReceipt(
            approval_id="approval-1",
            idempotency_key=command.idempotency_key,
            decision=command.decision,
            approver_oid=command.approver_oid,
            decided_at=command.decided_at,
            receipt_ref="receipt-1",
            justification=command.justification,
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


class RecordingHilAuthority:
    def __init__(
        self,
        *,
        oid: str = "owner-1",
        error: HilCallbackAuthorityError | None = None,
    ) -> None:
        self.oid = oid
        self.error = error
        self.authorization: str | None = None

    async def authenticate(
        self,
        *,
        authorization: str | None,
        channel: HilCallbackChannel,
        provider_actor_id: str,
        audience: str,
    ) -> HilCallbackActor:
        self.authorization = authorization
        del provider_actor_id, audience
        if self.error is not None:
            raise self.error
        return HilCallbackActor(
            oid=self.oid,
            identity_ref=f"sha256:{'a' * 64}",
            roles=frozenset({OperatorRole.OWNER}),
            authority_basis=f"{channel.value}:test-authority",
        )


class RecordingHilAudit:
    def __init__(self) -> None:
        self.records: list[HilCallbackAuditRecord] = []

    async def append_callback_audit(self, record: HilCallbackAuditRecord) -> None:
        self.records.append(record)


def _bindings(**overrides: object) -> IamFamilyBindings:
    values: dict[str, object] = {
        "authorize": authorize,
        "authenticate": authorize,
    }
    values.update(overrides)
    return IamFamilyBindings(**values)  # type: ignore[arg-type]


def _client(**overrides: object) -> TestClient:
    return TestClient(Starlette(routes=make_iam_family_routes(_bindings(**overrides))))


def test_family_owns_exact_route_manifest_without_fdai_implementation_imports() -> None:
    routes = make_iam_family_routes(_bindings())
    snapshot = tuple(
        (next(iter((route.methods or set()) - {"HEAD"})), route.path, route.name)
        for route in routes
    )
    assert snapshot == tuple((item.method, item.path, item.name) for item in IAM_FAMILY_MANIFEST)
    assert len(snapshot) == 35

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


def test_iam_overview_distinguishes_fdai_owner_and_directory_status() -> None:
    owner = _client(directory=RecordingDirectory()).get(
        "/iam",
        headers={"x-test-role": "Owner", "x-test-oid": "owner-1"},
    )
    reader = _client().get(
        "/iam",
        headers={"x-test-role": "Reader", "x-test-oid": "reader-1"},
    )

    assert owner.status_code == 200
    assert owner.json()["access_authority"] == {
        "source": "server-verified",
        "is_owner": True,
        "can_manage_group_membership": True,
    }
    assert owner.json()["directory"]["availability"] == "unknown"
    assert reader.json()["access_authority"]["is_owner"] is False
    assert reader.json()["directory"]["availability"] == "not_configured"


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
        "saved": True,
        "binding_version": "version-1",
        "saved_at": NOW.isoformat(),
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


def test_contributor_can_reveal_saved_teams_binding_but_reader_cannot() -> None:
    tester = RecordingTeamsWorkflowTester()
    contributor = _client(teams_workflow_tester=tester).get(
        "/runtime/integrations/teams-workflow/binding",
        headers={"x-test-role": "Contributor", "x-test-oid": "contributor-1"},
    )
    reader = _client(teams_workflow_tester=tester).get(
        "/runtime/integrations/teams-workflow/binding",
        headers={"x-test-role": "Reader", "x-test-oid": "reader-1"},
    )

    assert contributor.status_code == 200
    assert contributor.json() == {
        "visible": True,
        "configured": True,
        "webhook_url": "https://example.e4.environment.api.powerplatform.com/signed",
        "binding_version": "version-1",
        "revealed_at": NOW.isoformat(),
    }
    assert tester.reveal_actor_id == "contributor-1"
    assert reader.status_code == 200
    assert reader.json() == {"visible": False}
    assert "webhook_url" not in reader.text


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
    audit = RecordingHilAudit()
    config = HilCallbackConfig(secret="test-secret")
    client = _client(
        hil_registry=registry,
        hil_outbox=hil_outbox,
        hil_config=config,
        hil_authority=RecordingHilAuthority(),
        hil_audit=audit,
        hil_context=registry,
    )
    body = json.dumps(
        {
            "decision": "approve",
            "justification": "Independent approval.",
            "channel": "slack",
            "provider_actor_id": "slack-owner",
            "audience": "slack:slack-team",
            "correlation_id": "correlation-1",
            "idempotency_key": "hil-key-1",
            "action_hash": "action-hash-1",
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
    assert registry.command.decided_at == datetime.fromisoformat(timestamp)
    assert hil_outbox.request is not None
    assert path_swap.status_code == 401
    assert [record.outcome for record in audit.records] == [
        HilCallbackOutcome.PENDING,
        HilCallbackOutcome.ACCEPTED,
    ]

    self_registry = RecordingHilRegistry(submitter_oid="OWNER-1")
    self_response = _client(
        hil_registry=self_registry,
        hil_outbox=RecordingHilOutbox(),
        hil_config=config,
        hil_authority=RecordingHilAuthority(),
        hil_audit=RecordingHilAudit(),
        hil_context=self_registry,
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
            "channel": "slack",
            "provider_actor_id": "slack-owner",
            "audience": "slack:slack-team",
            "correlation_id": "correlation-1",
            "idempotency_key": "hil-key-1",
            "action_hash": "action-hash-1",
        },
        {
            "decision": "reject",
            "channel": "slack",
            "provider_actor_id": "slack-owner",
            "audience": "slack:slack-team",
            "correlation_id": "correlation-1",
            "idempotency_key": "hil-key-1",
            "action_hash": "action-hash-1",
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
            hil_authority=RecordingHilAuthority(),
            hil_audit=RecordingHilAudit(),
            hil_context=registry,
        ).post(
            "/hil/approval-1/decision",
            content=body,
            headers={
                "X-FDAI-Timestamp": timestamp,
                "X-FDAI-Signature": f"sha256={signature}",
            },
        )

        assert response.status_code == 400
        assert response.json()["error"]["message"] in {
            "callback body fields do not match the contract",
            "'justification' MUST be bounded non-empty text",
        }
        assert registry.command is None


def _callback_body(**overrides: object) -> bytes:
    payload: dict[str, object] = {
        "decision": "approve",
        "justification": "Verified rollback and impact bounds.",
        "channel": "slack",
        "provider_actor_id": "slack-owner",
        "audience": "slack:slack-team",
        "correlation_id": "correlation-1",
        "idempotency_key": "hil-key-1",
        "action_hash": "action-hash-1",
    }
    payload.update(overrides)
    return json.dumps(payload, separators=(",", ":")).encode()


def _signed_callback(
    client: TestClient,
    config: HilCallbackConfig,
    *,
    body: bytes,
    timestamp: str | None = None,
    bearer: str = "callback-token",
) -> Any:
    timestamp = timestamp or datetime.now(UTC).isoformat()
    return client.post(
        "/hil/approval-1/decision",
        content=body,
        headers={
            "Authorization": f"Bearer {bearer}",
            "X-FDAI-Timestamp": timestamp,
            "X-FDAI-Signature": "sha256="
            + compute_hmac(
                secret=config.secret,
                timestamp=timestamp,
                approval_id="approval-1",
                payload=body,
            ),
        },
    )


def test_hil_callback_duplicate_is_idempotent_and_audited() -> None:
    registry = RecordingHilRegistry()
    audit = RecordingHilAudit()
    config = HilCallbackConfig(secret="test-secret")
    client = _client(
        hil_registry=registry,
        hil_outbox=RecordingHilOutbox(),
        hil_config=config,
        hil_authority=RecordingHilAuthority(),
        hil_audit=audit,
        hil_context=registry,
    )
    body = _callback_body()

    first = _signed_callback(client, config, body=body)
    registry.pending = None
    duplicate = _signed_callback(client, config, body=body)

    assert first.status_code == duplicate.status_code == 200
    assert duplicate.json()["already_recorded"] is True
    assert duplicate.json()["idempotency_key"] == "hil-key-1"
    assert [record.phase.value for record in audit.records] == [
        "prepared",
        "completed",
        "prepared",
        "completed",
    ]
    assert all(record.correlation_id == "correlation-1" for record in audit.records)
    assert audit.records[-1].outcome is HilCallbackOutcome.ACCEPTED


def test_exact_callback_retry_with_moving_clock_retains_first_audit_times() -> None:
    class AuditStore:
        def __init__(self) -> None:
            self.values: dict[str, dict[str, object]] = {}

        async def create_state(self, key: str, value: Mapping[str, object]) -> bool:
            if key in self.values:
                return False
            self.values[key] = dict(value)
            return True

        async def read_state(self, key: str) -> dict[str, object] | None:
            return self.values.get(key)

    registry = RecordingHilRegistry()
    audit_store = AuditStore()
    audit = PostgresIamAdapters(audit_store)  # type: ignore[arg-type]
    config = HilCallbackConfig(secret="test-secret")
    current = [NOW]
    client = TestClient(
        Starlette(
            routes=[
                make_hil_callback_route(
                    registry=registry,
                    outbox=RecordingHilOutbox(),
                    config=config,
                    authority=RecordingHilAuthority(),
                    audit=audit,
                    context_reader=registry,
                    clock=lambda: current[0],
                )
            ]
        )
    )
    body = _callback_body()
    timestamp = NOW.isoformat()

    first = _signed_callback(client, config, body=body, timestamp=timestamp)
    current[0] += timedelta(seconds=1)
    duplicate = _signed_callback(client, config, body=body, timestamp=timestamp)

    assert first.status_code == duplicate.status_code == 200
    assert duplicate.json()["already_recorded"] is True
    assert len(audit_store.values) == 2
    assert {value["recorded_at"] for value in audit_store.values.values()} == {NOW.isoformat()}


def test_hil_callback_publish_failure_remains_retryable_until_broker_acceptance() -> None:
    class FailOnceOutbox(RecordingHilOutbox):
        attempts = 0

        async def enqueue(self, request: HilDecisionOutboxRequest) -> None:
            self.attempts += 1
            await super().enqueue(request)
            if self.attempts == 1:
                raise RuntimeError("broker unavailable")

    registry = RecordingHilRegistry()
    outbox = FailOnceOutbox()
    config = HilCallbackConfig(secret="test-secret")
    client = _client(
        hil_registry=registry,
        hil_outbox=outbox,
        hil_config=config,
        hil_authority=RecordingHilAuthority(),
        hil_audit=RecordingHilAudit(),
        hil_context=registry,
    )
    body = _callback_body()
    timestamp = datetime.now(UTC).isoformat()

    failed = _signed_callback(client, config, body=body, timestamp=timestamp)
    retried = _signed_callback(client, config, body=body, timestamp=timestamp)

    assert failed.status_code == 503
    assert failed.json()["error"]["kind"] == "decision_publish_failed"
    assert retried.status_code == 200
    assert retried.json()["already_recorded"] is True
    assert retried.json()["delivered"] is True
    assert outbox.attempts == 2


@pytest.mark.asyncio
async def test_durable_hil_outbox_persists_before_exact_broker_payload() -> None:
    order: list[str] = []

    class DurableOutbox:
        async def enqueue(self, request: HilDecisionOutboxRequest) -> None:
            assert request.receipt.justification == "Independent approval."
            order.append("persisted")

    class Publisher:
        payload: dict[str, object] | None = None

        async def publish(
            self,
            topic: str,
            key: str,
            payload: dict[str, object],
        ) -> object:
            assert order == ["persisted"]
            assert topic == "fdai.hil.decisions"
            assert key == "approval-1"
            self.payload = payload
            order.append("published")
            return object()

    publisher = Publisher()
    outbox = DurableHilDecisionOutboxPublisher(
        durable=DurableOutbox(),
        publisher=publisher,
        topic="fdai.hil.decisions",
    )
    await outbox.enqueue(
        HilDecisionOutboxRequest(
            HilDecisionReceipt(
                approval_id="approval-1",
                idempotency_key="hil-key-1",
                decision=HilApprovalDecision.APPROVE,
                approver_oid="owner-1",
                decided_at=NOW,
                receipt_ref="receipt-1",
                justification="Independent approval.",
            )
        )
    )

    assert order == ["persisted", "published"]
    assert publisher.payload == {
        "approval_id": "approval-1",
        "idempotency_key": "hil-key-1",
        "decision": "approve",
        "approver_oid": "owner-1",
        "justification": "Independent approval.",
        "decided_at": NOW.isoformat(),
        "receipt_ref": "receipt-1",
    }


def test_hil_callback_timeout_and_unavailable_authority_fail_closed_with_audit() -> None:
    config = HilCallbackConfig(secret="test-secret")
    expired_registry = RecordingHilRegistry()
    assert expired_registry.pending is not None
    expired_registry.pending = replace(
        expired_registry.pending,
        metadata={
            **expired_registry.pending.metadata,
            "expires_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
        },
    )
    expired_registry.context = replace(
        expired_registry.context,
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    expired_audit = RecordingHilAudit()
    expired = _signed_callback(
        _client(
            hil_registry=expired_registry,
            hil_outbox=RecordingHilOutbox(),
            hil_config=config,
            hil_authority=RecordingHilAuthority(),
            hil_audit=expired_audit,
            hil_context=expired_registry,
        ),
        config,
        body=_callback_body(),
    )
    assert expired.status_code == 410
    assert expired_registry.command is None
    assert expired_audit.records[-1].outcome is HilCallbackOutcome.EXPIRED

    unavailable_registry = RecordingHilRegistry()
    unavailable_audit = RecordingHilAudit()
    unavailable = _signed_callback(
        _client(
            hil_registry=unavailable_registry,
            hil_outbox=RecordingHilOutbox(),
            hil_config=config,
            hil_authority=RecordingHilAuthority(
                error=HilCallbackAuthorityError(
                    "current authority source is unavailable",
                    status_code=503,
                    kind="authority_unavailable",
                )
            ),
            hil_audit=unavailable_audit,
            hil_context=unavailable_registry,
        ),
        config,
        body=_callback_body(),
    )
    assert unavailable.status_code == 503
    assert unavailable_registry.command is None
    assert unavailable_audit.records[-1].outcome is HilCallbackOutcome.INVALID


def test_hil_callback_context_mismatch_is_invalid_before_decision() -> None:
    registry = RecordingHilRegistry()
    audit = RecordingHilAudit()
    config = HilCallbackConfig(secret="test-secret")
    response = _signed_callback(
        _client(
            hil_registry=registry,
            hil_outbox=RecordingHilOutbox(),
            hil_config=config,
            hil_authority=RecordingHilAuthority(),
            hil_audit=audit,
            hil_context=registry,
        ),
        config,
        body=_callback_body(correlation_id="different-correlation"),
    )

    assert response.status_code == 409
    assert registry.command is None
    assert audit.records[-1].outcome is HilCallbackOutcome.INVALID
    assert audit.records[-1].correlation_id == "correlation-1"


def test_unverified_callback_does_not_consume_durable_audit_storage() -> None:
    registry = RecordingHilRegistry()
    audit = RecordingHilAudit()
    body = _callback_body(channel="attacker-controlled-audit-text")
    response = _client(
        hil_registry=registry,
        hil_outbox=RecordingHilOutbox(),
        hil_config=HilCallbackConfig(secret="test-secret"),
        hil_authority=RecordingHilAuthority(),
        hil_audit=audit,
        hil_context=registry,
    ).post("/hil/approval-1/decision", content=body)

    assert response.status_code == 401
    assert audit.records == []


def _authority(
    *,
    slack_mapping: str = '{"slack-owner":"owner-1"}',
    claims: Mapping[str, object] | None = None,
) -> EntraHilCallbackAuthority:
    group_ids = {
        OperatorRole.READER: "readers",
        OperatorRole.CONTRIBUTOR: "contributors",
        OperatorRole.APPROVER: "approvers",
        OperatorRole.OWNER: "owners",
        OperatorRole.BREAK_GLASS: "break-glass",
    }
    resolved_claims = deepcopy(
        claims
        or {
            "oid": "owner-1",
            "roles": ["Owner"],
            "idtyp": "user",
            "azp": "approval-bot",
        }
    )
    authenticator = OperatorAuthenticator(
        verifier=lambda _token: resolved_claims,
        group_ids=group_ids,
    )
    environment = {
        "FDAI_TEAMS_APPLICATION_ID": "approval-bot",
        "FDAI_TEAMS_APPROVAL_TEAM_ID": "approval-team",
        "FDAI_TEAMS_APPROVAL_CHANNEL_ID": "approval-channel",
        "FDAI_TEAMS_PRINCIPAL_MAP_JSON": '{"teams-owner":"owner-1"}',
        "FDAI_SLACK_PRINCIPAL_MAP_JSON": slack_mapping,
    }
    if slack_mapping:
        environment["FDAI_SLACK_TEAM_ID"] = "slack-team"
    return EntraHilCallbackAuthority(
        authenticator=authenticator,
        config=HilCallbackAuthorityConfig.from_environment(
            environment,
            group_ids=group_ids,
        ),
    )


_AUTHORIZATION = "Bearer callback-token"  # noqa: S105 - synthetic test header.


@pytest.mark.asyncio
async def test_teams_obo_authority_rejects_wrong_actor_audience_and_client() -> None:
    authority = _authority()

    accepted = await authority.authenticate(
        authorization=_AUTHORIZATION,
        channel=HilCallbackChannel.TEAMS,
        provider_actor_id="teams-owner",
        audience="teams:approval-team:approval-channel",
    )
    assert accepted.oid == "owner-1"
    assert accepted.authority_basis == "teams_sso_obo+entra_app_role"

    for kwargs, kind in (
        ({"provider_actor_id": "unknown"}, "actor_mapping_missing"),
        ({"audience": "teams:other-team:other-channel"}, "wrong_audience"),
    ):
        values = {
            "channel": HilCallbackChannel.TEAMS,
            "provider_actor_id": "teams-owner",
            "audience": "teams:approval-team:approval-channel",
            **kwargs,
        }
        with pytest.raises(HilCallbackAuthorityError) as raised:
            await authority.authenticate(authorization=_AUTHORIZATION, **values)
        assert raised.value.kind == kind

    wrong_client = _authority(
        claims={
            "oid": "owner-1",
            "roles": ["Owner"],
            "idtyp": "user",
            "azp": "different-client",
        }
    )
    with pytest.raises(HilCallbackAuthorityError) as raised:
        await wrong_client.authenticate(
            authorization=_AUTHORIZATION,
            channel=HilCallbackChannel.TEAMS,
            provider_actor_id="teams-owner",
            audience="teams:approval-team:approval-channel",
        )
    assert raised.value.kind == "wrong_client"


@pytest.mark.asyncio
async def test_slack_a1_requires_non_empty_mapping_and_mapped_entra_identity() -> None:
    disabled = _authority(slack_mapping="")
    with pytest.raises(HilCallbackAuthorityError) as raised:
        await disabled.authenticate(
            authorization=_AUTHORIZATION,
            channel=HilCallbackChannel.SLACK,
            provider_actor_id="slack-owner",
            audience="slack:slack-team",
        )
    assert raised.value.kind == "slack_a1_disabled"

    mapped = _authority()
    actor = await mapped.authenticate(
        authorization=_AUTHORIZATION,
        channel=HilCallbackChannel.SLACK,
        provider_actor_id="slack-owner",
        audience="slack:slack-team",
    )
    assert actor.oid == "owner-1"
    assert actor.authority_basis == "slack_mapping+entra_browser_reauthentication"

    wrong_actor = _authority(
        claims={
            "oid": "different-owner",
            "roles": ["Owner"],
            "idtyp": "user",
        }
    )
    with pytest.raises(HilCallbackAuthorityError) as raised:
        await wrong_actor.authenticate(
            authorization=_AUTHORIZATION,
            channel=HilCallbackChannel.SLACK,
            provider_actor_id="slack-owner",
            audience="slack:slack-team",
        )
    assert raised.value.kind == "wrong_actor"


@pytest.mark.asyncio
async def test_break_glass_token_cannot_gain_callback_approval_authority() -> None:
    break_glass = _authority(
        claims={
            "oid": "owner-1",
            "roles": ["BreakGlass"],
            "idtyp": "user",
            "azp": "approval-bot",
        }
    )

    principal = break_glass.authenticator.authenticate("Bearer callback-token")
    assert principal.roles == frozenset({OperatorRole.BREAK_GLASS})
    with pytest.raises(HilCallbackAuthorityError) as raised:
        await break_glass.authenticate(
            authorization=_AUTHORIZATION,
            channel=HilCallbackChannel.TEAMS,
            provider_actor_id="teams-owner",
            audience="teams:approval-team:approval-channel",
        )

    assert raised.value.kind == "capability_forbidden"


def test_callback_authority_keeps_role_groups_separate_from_channel_audiences() -> None:
    groups = {
        OperatorRole.READER: "readers",
        OperatorRole.CONTRIBUTOR: "contributors",
        OperatorRole.APPROVER: "approvers",
        OperatorRole.OWNER: "owners",
        OperatorRole.BREAK_GLASS: "break-glass",
    }
    config = HilCallbackAuthorityConfig.from_environment(
        {
            "FDAI_TEAMS_APPLICATION_ID": "approval-bot",
            "FDAI_TEAMS_APPROVAL_TEAM_ID": "approval-team",
            "FDAI_TEAMS_APPROVAL_CHANNEL_ID": "approval-channel",
            "FDAI_TEAMS_PRINCIPAL_MAP_JSON": '{"teams-owner":"owner-1"}',
        },
        group_ids=groups,
    )

    assert config.teams_approval_audience == "teams:approval-team:approval-channel"
    with pytest.raises(ValueError, match="all five"):
        HilCallbackAuthorityConfig.from_environment(
            {},
            group_ids={
                role: value for role, value in groups.items() if role is not OperatorRole.OWNER
            },
        )


@pytest.mark.asyncio
async def test_callback_authority_rejects_partial_teams_config_but_allows_slack_only() -> None:
    groups = {
        OperatorRole.READER: "readers",
        OperatorRole.CONTRIBUTOR: "contributors",
        OperatorRole.APPROVER: "approvers",
        OperatorRole.OWNER: "owners",
        OperatorRole.BREAK_GLASS: "break-glass",
    }
    with pytest.raises(ValueError, match="Teams A1 requires"):
        HilCallbackAuthorityConfig.from_environment(
            {"FDAI_TEAMS_APPROVAL_TEAM_ID": "approval-team"},
            group_ids=groups,
        )

    slack = HilCallbackAuthorityConfig.from_environment(
        {
            "FDAI_SLACK_TEAM_ID": "slack-team",
            "FDAI_SLACK_PRINCIPAL_MAP_JSON": '{"slack-owner":"owner-1"}',
        },
        group_ids=groups,
    )
    assert slack.teams_approval_audience is None
    assert slack.slack_approval_audience == "slack:slack-team"
    authority = EntraHilCallbackAuthority(
        authenticator=OperatorAuthenticator(
            verifier=lambda _token: {
                "oid": "owner-1",
                "roles": ["Owner"],
                "idtyp": "user",
            },
            group_ids=groups,
        ),
        config=slack,
    )
    actor = await authority.authenticate(
        authorization=_AUTHORIZATION,
        channel=HilCallbackChannel.SLACK,
        provider_actor_id="slack-owner",
        audience="slack:slack-team",
    )
    assert actor.oid == "owner-1"
