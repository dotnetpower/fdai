"""Focused tests for authoritative principal-scoped Process transition projections."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai_operator_service.process_transition_projection import (
    ProcessControlUnavailableError,
    ProcessTransitionDeniedError,
    authorize_process_transition,
    project_process_control,
)
from fdai_service_contracts import OperatorRole

NOW = datetime(2026, 8, 31, tzinfo=UTC)


def _process(
    *,
    status: str = "waiting",
    current_step: str = "current",
    revision: int = 3,
) -> dict[str, object]:
    return {
        "process_id": "process-1",
        "workflow_ref": "review-workflow",
        "workflow_version": "1.0.0",
        "status": status,
        "current_step": current_step,
        "target_resource_id": "resource-1",
        "started_at": NOW,
        "updated_at": NOW,
        "correlation_id": "correlation-1",
        "revision": revision,
    }


def _events(
    *,
    kind: str,
    reason: str = "waiting",
    requester: str = "operator-a",
    attempt: int = 1,
    extras: tuple[dict[str, object], ...] = (),
) -> list[dict[str, object]]:
    return [
        {
            "event_id": "created",
            "kind": "process.created",
            "recorded_at": NOW,
            "correlation_id": "correlation-1",
            "causation_id": None,
            "step_id": None,
            "attempt": 1,
            "payload": {
                "resume": {
                    "mode": "shadow",
                    "context": {"requester.principal": requester},
                }
            },
        },
        {
            "event_id": "started",
            "kind": "step.started",
            "recorded_at": NOW,
            "correlation_id": "correlation-1",
            "causation_id": None,
            "step_id": "current",
            "attempt": attempt,
            "payload": {},
        },
        *extras,
        {
            "event_id": "waiting",
            "kind": "step.waiting" if kind != "approval" else "approval.requested",
            "recorded_at": NOW,
            "correlation_id": "correlation-1",
            "causation_id": None,
            "step_id": "current",
            "attempt": attempt,
            "payload": {"step_kind": kind, "reason": reason, "decision": "pending"},
        },
    ]


def _catalog(step: dict[str, object]) -> dict[str, object]:
    return {
        "_revision": "catalog-7",
        "workflows": [
            {
                "name": "review-workflow",
                "version": "1.0.0",
                "steps": [{"id": "current", **step}],
            }
        ],
    }


def _approval_state(*, state: str = "pending") -> dict[str, object]:
    return {
        "process_id": "process-1",
        "step_id": "current",
        "attempt": 1,
        "requester_principal": "operator-a",
        "required_role": "approver",
        "quorum": 2,
        "no_self_approval": True,
        "timeout_seconds": 600,
        "expires_at": (NOW + timedelta(seconds=600)).isoformat(),
        "state": state,
        "revision": 1,
        "decision_claims": {},
        "_external_decisions": [],
    }


@pytest.mark.parametrize(
    ("step", "expected"),
    [
        (
            {"kind": "wait", "wait_for": "evidence.updated", "timeout_seconds": 300},
            {"wait_for": "evidence.updated", "timeout_seconds": 300},
        ),
        (
            {
                "kind": "approval",
                "approval_role": "approver",
                "quorum": 2,
                "no_self_approval": True,
                "timeout_seconds": 600,
            },
            {"approval_role": "approver", "quorum": 2, "no_self_approval": True},
        ),
        (
            {"kind": "decision", "outcomes": ["approved", "held"]},
            {"outcomes": ["approved", "held"], "decision": "pending"},
        ),
        (
            {"kind": "parallel", "branches": ["security", "reliability"]},
            {"branches": ["security", "reliability"], "join": "all"},
        ),
        (
            {"kind": "gate", "gate_ref": "release.production-ready"},
            {"gate_ref": "release.production-ready", "evidence_state": "pending"},
        ),
    ],
)
def test_projects_each_governed_step_from_authoritative_sources(
    step: dict[str, object],
    expected: dict[str, object],
) -> None:
    kind = str(step["kind"])
    state = project_process_control(
        process=_process(),
        events=_events(kind=kind),
        workflow_catalog=_catalog(step),
        principal_id="operator-a",
        roles=frozenset({OperatorRole.CONTRIBUTOR, OperatorRole.APPROVER}),
        approval_state=_approval_state() if kind == "approval" else None,
    )

    assert state.payload["authoritative"] is True
    assert state.payload["principal_scoped"] is True
    assert state.payload["acceptance_is_success"] is False
    projected_step = state.payload["step"]
    assert isinstance(projected_step, dict)
    requirements = projected_step["requirements"]
    assert isinstance(requirements, dict)
    assert requirements.items() >= expected.items()
    transition_ids = {
        transition["id"]
        for transition in state.payload["permitted_transitions"]  # type: ignore[union-attr]
    }
    expected_transitions = {"cancel"} if kind == "approval" else {"resume", "cancel"}
    assert expected_transitions <= transition_ids
    assert "review_approval" not in transition_ids


def test_parallel_projection_carries_only_observed_branch_receipts() -> None:
    completed = {
        "event_id": "branch-complete",
        "kind": "parallel.branch.completed",
        "recorded_at": NOW,
        "correlation_id": "correlation-1",
        "causation_id": None,
        "step_id": "current",
        "attempt": 1,
        "payload": {"branch": "security"},
    }
    state = project_process_control(
        process=_process(),
        events=_events(kind="parallel", extras=(completed,)),
        workflow_catalog=_catalog({"kind": "parallel", "branches": ["security", "reliability"]}),
        principal_id="operator-a",
        roles=frozenset({OperatorRole.CONTRIBUTOR}),
    )

    step = state.payload["step"]
    assert isinstance(step, dict)
    assert step["requirements"]["completed_branches"] == ["security"]  # type: ignore[index]
    assert step["requirements"]["failed_branches"] == []  # type: ignore[index]


def test_principal_scope_and_missing_catalog_fail_closed() -> None:
    with pytest.raises(ProcessTransitionDeniedError, match="not visible"):
        project_process_control(
            process=_process(),
            events=_events(kind="gate"),
            workflow_catalog=_catalog({"kind": "gate", "gate_ref": "release.production-ready"}),
            principal_id="operator-b",
            roles=frozenset({OperatorRole.OWNER}),
        )

    with pytest.raises(ProcessControlUnavailableError, match="Pinned Process workflow"):
        project_process_control(
            process=_process(),
            events=_events(kind="gate"),
            workflow_catalog={"_revision": "catalog-7", "workflows": []},
            principal_id="operator-a",
            roles=frozenset({OperatorRole.OWNER}),
            approval_state=_approval_state(state="timed_out"),
        )


def test_approval_projection_uses_durable_receipts_and_excludes_self_approval() -> None:
    approval = _approval_state()
    approval["decision_claims"] = {"slot-1": {"principal": "operator-b", "decision": "approved"}}
    state = project_process_control(
        process=_process(),
        events=_events(kind="approval"),
        workflow_catalog=_catalog(
            {
                "kind": "approval",
                "approval_role": "approver",
                "quorum": 2,
                "no_self_approval": True,
                "timeout_seconds": 600,
            }
        ),
        principal_id="operator-a",
        roles=frozenset({OperatorRole.APPROVER}),
        approval_state=approval,
    )
    step = state.payload["step"]
    assert isinstance(step, dict)
    assert step["requirements"]["approved_count"] == 1  # type: ignore[index]
    assert step["requirements"]["remaining_quorum"] == 1  # type: ignore[index]

    approval["decision_claims"] = {"slot-1": {"principal": "OPERATOR-A", "decision": "approved"}}
    self_state = project_process_control(
        process=_process(),
        events=_events(kind="approval"),
        workflow_catalog=_catalog(
            {
                "kind": "approval",
                "approval_role": "approver",
                "quorum": 2,
                "no_self_approval": True,
                "timeout_seconds": 600,
            }
        ),
        principal_id="operator-a",
        roles=frozenset({OperatorRole.APPROVER}),
        approval_state=approval,
    )
    self_step = self_state.payload["step"]
    assert isinstance(self_step, dict)
    assert self_step["requirements"]["approved_count"] == 0  # type: ignore[index]
    assert self_step["requirements"]["remaining_quorum"] == 2  # type: ignore[index]

    approval["no_self_approval"] = False
    allowed_state = project_process_control(
        process=_process(),
        events=_events(kind="approval"),
        workflow_catalog=_catalog(
            {
                "kind": "approval",
                "approval_role": "approver",
                "quorum": 2,
                "no_self_approval": False,
                "timeout_seconds": 600,
            }
        ),
        principal_id="operator-a",
        roles=frozenset({OperatorRole.APPROVER}),
        approval_state=approval,
    )
    allowed_step = allowed_state.payload["step"]
    assert isinstance(allowed_step, dict)
    assert allowed_step["requirements"]["approved_count"] == 1  # type: ignore[index]


def test_enforce_requires_owner_and_retry_requires_effect_free_terminal_evidence() -> None:
    events = _events(kind="approval", reason="approval_timed_out")
    events[0]["payload"]["resume"]["mode"] = "enforce"  # type: ignore[index]
    events[-1]["kind"] = "process.timed_out"
    state = project_process_control(
        process=_process(status="timed_out"),
        events=events,
        workflow_catalog=_catalog(
            {
                "kind": "approval",
                "approval_role": "approver",
                "quorum": 2,
                "no_self_approval": True,
                "timeout_seconds": 600,
            }
        ),
        principal_id="operator-a",
        roles=frozenset({OperatorRole.OWNER}),
        approval_state=_approval_state(state="timed_out"),
    )

    assert state.permitted_transition_ids == frozenset({"retry"})
    authorize_process_transition(
        operation="workflow.retry-request",
        expected_revision="3",
        state=state,
    )
    with pytest.raises(ProcessTransitionDeniedError, match="stale"):
        authorize_process_transition(
            operation="workflow.retry-request",
            expected_revision="2",
            state=state,
        )
    with pytest.raises(ProcessTransitionDeniedError, match="not permitted"):
        authorize_process_transition(
            operation="workflow.resume-request",
            expected_revision="3",
            state=state,
        )
