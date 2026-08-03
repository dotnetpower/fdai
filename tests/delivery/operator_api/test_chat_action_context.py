"""Context-free governed action questions fail closed."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.testclient import TestClient

from fdai.delivery.operator_api.read_model import HilQueueItem, InMemoryConsoleReadModel
from fdai.delivery.operator_api.routes.chat import make_chat_route, make_chat_stream_route
from fdai.delivery.operator_api.routes.chat_action_context import ActionContextChatTools


class Backend:
    calls = 0

    async def answer(self, **kwargs: object) -> dict[str, str]:
        self.calls += 1
        return {"answer": "fallback", "model": "test"}


async def _allow(request: Request) -> str:
    return "reader"


def test_action_lifecycle_questions_require_exact_context() -> None:
    prompts = (
        "실행하지 말고 안전한 완화 방안만 제안해줘.",
        "실행 없이 검토 가능한 안전한 완화 제안을 보여줘.",
        "Propose a mitigation without executing any change.",
        "Show the proposal's impact limit, stop condition, dry run, and rollback.",
        "Why does this action require human approval, and who may approve it?",
        "승인 필요성, 승인 역할, 실행 주체를 분리해서 알려줘.",
        "Explain the approval requirement and the authorized approver role for this action.",
        "Who can approve this change, and why must approval remain separate from execution?",
        "Execute the approved mitigation and stream its governed progress.",
        "Verify the mitigation outcome against explicit recovery criteria.",
        "Prove that retrying this action will not create a duplicate change.",
        "Describe a safe recovery proposal without applying it.",
        "Can this approved action be retried without duplication?",
        "Which action receipt proves the mitigation recovered the service?",
    )
    backend = Backend()
    app = Starlette(
        routes=[
            make_chat_route(
                backend=backend,
                authorize=_allow,
                tool_resolver=ActionContextChatTools(),
            )
        ]
    )
    with TestClient(app) as client:
        for prompt in prompts:
            payload = client.post("/chat", json={"prompt": prompt}).json()
            assert payload["verification"]["authority"] == "server_action_context"
            assert payload["verification"]["status"] == "unverified"
            assert payload["verification"]["reason_code"] == "exact_action_context_required"
    assert backend.calls == 0


def _action_model() -> InMemoryConsoleReadModel:
    model = InMemoryConsoleReadModel()
    model.record_hil_pending(
        HilQueueItem(
            idempotency_key="operator::action-1",
            event_id="event-1",
            action_kind="ops.restart-service",
            reason="Human approval is required by the risk gate.",
            requested_at="2026-08-03T00:00:00Z",
            correlation_id="corr-action-1",
            approval_id="approval-1",
            action_id="action-1",
            target_resource_ref="service/example",
            mode="shadow",
            stop_condition="Stop when error rate increases.",
            rollback_kind="state_forward_only",
            rollback_reference="rollback:action-1",
            blast_radius_scope="resource",
            blast_radius_count=1,
            blast_radius_summary="One service resource.",
            reasons=("high_impact",),
            citing_rule_ids=("rule-1",),
            ttl_expires_at=(datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        )
    )
    common = {
        "event_id": "event-1",
        "correlation_id": "corr-action-1",
        "action_id": "action-1",
        "approval_id": "approval-1",
        "idempotency_key": "operator::action-1",
        "action_type": "ops.restart-service",
        "target_resource_ref": "service/example",
    }
    model.record_audit_entry(
        {
            **common,
            "decision": "hil",
            "stop_condition": "Stop when error rate increases.",
            "rollback_kind": "state_forward_only",
            "rollback_reference": "rollback:action-1",
            "blast_radius_summary": "One service resource.",
            "recorded_at": "2026-08-03T00:00:00Z",
        },
        action_kind="risk_gate.decided",
    )
    model.record_audit_entry(
        {**common, "status": "submitted", "recorded_at": "2026-08-03T00:01:00Z"},
        action_kind="executor.direct_api.dispatched",
    )
    model.record_audit_entry(
        {**common, "outcome": "recovered", "recorded_at": "2026-08-03T00:02:00Z"},
        action_kind="action.effect_verified",
    )
    model.record_audit_entry(
        {
            "event_id": "event-1",
            "action_id": "action-1",
            "idempotency_key": "operator::action-1",
            "action_type": "ops.restart-service",
            "target_resource_ref": "service/example",
            "audit_phase": "terminal",
            "outcome": "already_applied",
            "recorded_at": "2026-08-03T00:03:00Z",
        },
        actor="fdai.core.executor.shadow",
        action_kind="ops.restart-service",
    )
    return model


@pytest.mark.parametrize(
    ("prompt", "reason_code", "answer_token"),
    (
        (
            "Propose a mitigation without executing any change.",
            "action_proposal_grounded",
            "does not execute",
        ),
        (
            "Show the proposal's impact limit, stop condition, dry run, and rollback.",
            "action_safety_grounded",
            "Stop when error rate increases",
        ),
        (
            "Why does this action require human approval, and who may approve it?",
            "action_approval_grounded",
            "separation-of-duty",
        ),
        (
            "Execute the approved mitigation and stream its governed progress.",
            "action_execution_grounded",
            "did not execute",
        ),
        (
            "Verify the mitigation outcome against explicit recovery criteria.",
            "action_verification_grounded",
            "latest outcome: recovered",
        ),
        (
            "Prove that retrying this action will not create a duplicate change.",
            "action_idempotency_grounded",
            "execution receipt(s)",
        ),
    ),
)
def test_exact_action_context_projects_read_only_lifecycle_evidence(
    prompt: str,
    reason_code: str,
    answer_token: str,
) -> None:
    backend = Backend()
    app = Starlette(
        routes=[
            make_chat_route(
                backend=backend,
                authorize=_allow,
                tool_resolver=ActionContextChatTools(read_model=_action_model()),
            )
        ]
    )
    payload = (
        TestClient(app)
        .post(
            "/chat",
            json={
                "prompt": prompt,
                "conversation_context": {
                    "kind": "action",
                    "action_id": "action-1",
                    "correlation_id": "corr-action-1",
                },
            },
        )
        .json()
    )

    assert payload["verification"]["status"] in {"verified", "corrected"}
    assert payload["verification"]["authority"] == "server_action_context"
    assert payload["verification"]["reason_code"] == reason_code
    assert answer_token in payload["answer"]
    assert payload["verification"]["evidence_refs"]
    assert backend.calls == 0


def test_mismatched_action_selectors_fail_closed() -> None:
    backend = Backend()
    app = Starlette(
        routes=[
            make_chat_route(
                backend=backend,
                authorize=_allow,
                tool_resolver=ActionContextChatTools(read_model=_action_model()),
            )
        ]
    )
    payload = (
        TestClient(app)
        .post(
            "/chat",
            json={
                "prompt": "Why does this action require human approval?",
                "conversation_context": {
                    "kind": "action",
                    "action_id": "action-1",
                    "approval_id": "approval-other",
                    "correlation_id": "corr-action-1",
                },
            },
        )
        .json()
    )

    assert payload["verification"]["status"] == "unverified"
    assert payload["verification"]["reason_code"] == "exact_action_context_required"
    assert backend.calls == 0


def test_hil_only_identity_cannot_ground_reader_action_context() -> None:
    model = InMemoryConsoleReadModel()
    model.record_hil_pending(
        HilQueueItem(
            idempotency_key="key-hil-only",
            event_id="event-hil-only",
            action_kind="ops.restart-service",
            reason="Sensitive approval reason.",
            requested_at="2026-08-03T00:00:00Z",
            correlation_id="corr-hil-only",
            approval_id="approval-hil-only",
            action_id="action-hil-only",
            target_resource_ref="service/hil-only",
            stop_condition="Sensitive stop condition.",
        )
    )
    app = Starlette(
        routes=[
            make_chat_route(
                backend=Backend(),
                authorize=_allow,
                tool_resolver=ActionContextChatTools(read_model=model),
            )
        ]
    )
    payload = (
        TestClient(app)
        .post(
            "/chat",
            json={
                "prompt": "Show the proposal stop condition and rollback.",
                "conversation_context": {
                    "kind": "action",
                    "action_id": "action-hil-only",
                    "correlation_id": "corr-hil-only",
                },
            },
        )
        .json()
    )

    assert payload["verification"]["status"] == "unverified"
    assert "Sensitive" not in payload["answer"]


def test_correlation_free_executor_terminal_receipt_is_joined_by_exact_action() -> None:
    app = Starlette(
        routes=[
            make_chat_route(
                backend=Backend(),
                authorize=_allow,
                tool_resolver=ActionContextChatTools(read_model=_action_model()),
            )
        ]
    )
    payload = (
        TestClient(app)
        .post(
            "/chat",
            json={
                "prompt": "Prove that retrying this action will not create a duplicate change.",
                "conversation_context": {
                    "kind": "action",
                    "approval_id": "approval-1",
                    "correlation_id": "corr-action-1",
                },
            },
        )
        .json()
    )

    assert "2 execution receipt(s)" in payload["answer"]
    assert "1 duplicate receipt(s)" in payload["answer"]
    assert any(ref.startswith("audit:none:") for ref in payload["verification"]["evidence_refs"])


def test_resolved_approval_only_context_derives_sparse_terminal_identity() -> None:
    model = InMemoryConsoleReadModel()
    common = {
        "event_id": "event-resolved",
        "action_id": "action-resolved",
        "idempotency_key": "operator::resolved",
        "action_type": "ops.restart-service",
        "target_resource_ref": "service/resolved",
    }
    model.record_audit_entry(
        {
            **common,
            "correlation_id": "corr-resolved",
            "approval_id": "approval-resolved",
            "decision": "approved",
            "recorded_at": "2026-08-03T00:00:00Z",
        },
        action_kind="hil.approved",
    )
    model.record_audit_entry(
        {
            **common,
            "audit_phase": "terminal",
            "outcome": "already_applied",
            "recorded_at": "2026-08-03T00:01:00Z",
        },
        actor="fdai.core.executor.shadow",
        action_kind="ops.restart-service",
    )
    app = Starlette(
        routes=[
            make_chat_route(
                backend=Backend(),
                authorize=_allow,
                tool_resolver=ActionContextChatTools(read_model=model),
            )
        ]
    )
    payload = (
        TestClient(app)
        .post(
            "/chat",
            json={
                "prompt": "Prove that retrying this action will not create a duplicate change.",
                "conversation_context": {
                    "kind": "action",
                    "approval_id": "approval-resolved",
                    "correlation_id": "corr-resolved",
                },
            },
        )
        .json()
    )

    assert payload["verification"]["reason_code"] == "action_idempotency_grounded"
    assert "1 execution receipt(s)" in payload["answer"]
    assert "1 duplicate receipt(s)" in payload["answer"]


def test_approval_selector_never_derives_identity_from_another_correlated_action() -> None:
    model = InMemoryConsoleReadModel()
    model.record_audit_entry(
        {
            "event_id": "event-shared",
            "correlation_id": "corr-shared",
            "approval_id": "approval-a",
            "decision": "approved",
        },
        action_kind="hil.approved",
    )
    model.record_audit_entry(
        {
            "event_id": "event-shared",
            "correlation_id": "corr-shared",
            "action_id": "action-b",
            "idempotency_key": "key-b",
            "audit_phase": "terminal",
            "outcome": "already_applied",
        },
        actor="fdai.core.executor.shadow",
        action_kind="ops.restart-service",
    )
    app = Starlette(
        routes=[
            make_chat_route(
                backend=Backend(),
                authorize=_allow,
                tool_resolver=ActionContextChatTools(read_model=model),
            )
        ]
    )
    payload = (
        TestClient(app)
        .post(
            "/chat",
            json={
                "prompt": "Prove that retrying this action will not create a duplicate change.",
                "conversation_context": {
                    "kind": "action",
                    "approval_id": "approval-a",
                    "correlation_id": "corr-shared",
                },
            },
        )
        .json()
    )

    assert payload["verification"]["status"] == "unverified"
    assert payload["verification"]["reason_code"] == "exact_action_context_required"


def test_terminal_approval_audit_overrides_stale_pending_queue() -> None:
    model = _action_model()
    model.record_audit_entry(
        {
            "event_id": "event-1",
            "correlation_id": "corr-action-1",
            "action_id": "action-1",
            "approval_id": "approval-1",
            "idempotency_key": "operator::action-1",
            "approval_status": "approved",
            "recorded_at": "2026-08-03T00:03:00Z",
        },
        action_kind="hil.approved",
    )
    app = Starlette(
        routes=[
            make_chat_route(
                backend=Backend(),
                authorize=_allow,
                tool_resolver=ActionContextChatTools(read_model=model),
            )
        ]
    )
    payload = (
        TestClient(app)
        .post(
            "/chat",
            json={
                "prompt": "Why does this action require human approval?",
                "conversation_context": {
                    "kind": "action",
                    "approval_id": "approval-1",
                    "correlation_id": "corr-action-1",
                },
            },
        )
        .json()
    )

    assert "approved" in payload["answer"]
    assert "pending" not in payload["answer"]


@pytest.mark.parametrize(
    ("action_kind", "decision", "expected"),
    (
        ("hil.rejected", None, "rejected"),
        ("hil.timeout", None, "expired"),
        ("hil.decided", "reject", "rejected"),
        ("hil.decided", "approve", "approved"),
    ),
)
def test_terminal_approval_aliases_override_stale_pending_queue(
    action_kind: str,
    decision: str | None,
    expected: str,
) -> None:
    model = _action_model()
    entry: dict[str, object] = {
        "event_id": "event-1",
        "correlation_id": "corr-action-1",
        "action_id": "action-1",
        "approval_id": "approval-1",
        "idempotency_key": "operator::action-1",
        "recorded_at": "2026-08-03T00:03:00Z",
    }
    if decision is not None:
        entry["decision"] = decision
    model.record_audit_entry(entry, action_kind=action_kind)
    app = Starlette(
        routes=[
            make_chat_route(
                backend=Backend(),
                authorize=_allow,
                tool_resolver=ActionContextChatTools(read_model=model),
            )
        ]
    )
    payload = (
        TestClient(app)
        .post(
            "/chat",
            json={
                "prompt": "Why does this action require human approval?",
                "conversation_context": {
                    "kind": "action",
                    "approval_id": "approval-1",
                    "correlation_id": "corr-action-1",
                },
            },
        )
        .json()
    )

    assert expected in payload["answer"]
    assert "pending" not in payload["answer"]


def test_exact_action_context_is_identical_across_json_and_stream() -> None:
    backend = Backend()
    tools = ActionContextChatTools(read_model=_action_model())
    app = Starlette(
        routes=[
            make_chat_route(backend=backend, authorize=_allow, tool_resolver=tools),
            make_chat_stream_route(backend=backend, authorize=_allow, tool_resolver=tools),
        ]
    )
    body = {
        "prompt": "Why does this action require human approval, and who may approve it?",
        "conversation_context": {
            "kind": "action",
            "approval_id": "approval-1",
            "correlation_id": "corr-action-1",
        },
    }
    with TestClient(app) as client:
        direct = client.post("/chat", json=body).json()
        streamed = client.post("/chat/stream", json=body).text
    done = next(
        json.loads(block.split("data: ", maxsplit=1)[1])
        for block in streamed.split("\n\n")
        if block.startswith("event: done\n")
    )

    assert done["answer"] == direct["answer"]
    assert done["verification"] == direct["verification"]
    assert backend.calls == 0


@pytest.mark.parametrize(
    "context",
    (
        {"kind": "action", "correlation_id": "corr-action-1"},
        {"kind": "action", "action_id": ""},
        {"kind": "other", "action_id": "action-1"},
    ),
)
def test_action_context_boundary_rejects_non_exact_selectors(
    context: dict[str, str],
) -> None:
    app = Starlette(routes=[make_chat_route(backend=Backend(), authorize=_allow)])
    response = TestClient(app).post(
        "/chat",
        json={
            "prompt": "Why does this action require approval?",
            "conversation_context": context,
        },
    )

    assert response.status_code == 400
