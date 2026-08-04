"""Authenticated execution access-grant review tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from starlette.applications import Starlette
from starlette.testclient import TestClient

from fdai.core.execution_authorization import AccessGrantRequestService
from fdai.core.rbac.resolver import Principal
from fdai.core.rbac.roles import Role
from fdai.delivery.operator_api.routes.access_grant_decision import (
    make_access_grant_decision_route,
)
from fdai.shared.providers.testing import InMemoryStateStore

_NOW = datetime.now(UTC)


async def _submitted(
    service: AccessGrantRequestService,
    *,
    requester_ref: str = "heimdall",
):
    return await service.submit(
        idempotency_key=f"grant-{requester_ref}",
        original_action_id="incident-1",
        authorization_decision_digest="decision-v1",
        requirement_id="requirement.metrics-read",
        capability_id="kubernetes.metrics.read",
        execution_profile="observation-reader",
        executor_identity_ref="identity/reader",
        scope_ref="scope://example/cluster/namespace/example-app",
        grant_mode="time_bound",
        mapping_digest="mapping-v1",
        plan_digest="plan-v1",
        requester_ref=requester_ref,
        requested_at=_NOW,
        expires_at=_NOW + timedelta(hours=1),
        quorum=1,
        approver_roles=frozenset({"owner"}),
    )


def _client(
    service: AccessGrantRequestService,
    *,
    oid: str = "owner-1",
    roles: frozenset[Role] = frozenset({Role.OWNER}),
) -> TestClient:
    async def authorize(_request):  # type: ignore[no-untyped-def]
        return Principal(oid=oid, roles=roles)

    return TestClient(
        Starlette(routes=[make_access_grant_decision_route(service=service, authorize=authorize)])
    )


async def test_approve_records_review_without_claiming_permission_applied() -> None:
    service = AccessGrantRequestService(store=InMemoryStateStore())
    request = await _submitted(service)

    response = _client(service).post(
        f"/access-grants/{request.request_id}/decision",
        json={
            "decision": "approve",
            "reason": "Incident investigation requires bounded metrics access.",
            "expected_revision": request.revision,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "approved"
    assert body["revision"] == 1
    assert body["approved_count"] == body["quorum"] == 1
    assert body["permission_applied"] is False
    assert body["fresh_probe_required"] is True
    assert "executor_identity_ref" not in body
    assert "plan_digest" not in body


async def test_review_rejects_self_approval_and_stale_revision() -> None:
    service = AccessGrantRequestService(store=InMemoryStateStore())
    self_request = await _submitted(service, requester_ref="owner-1")
    body = {
        "decision": "approve",
        "reason": "Incident investigation requires bounded metrics access.",
        "expected_revision": 0,
    }
    self_response = _client(service).post(
        f"/access-grants/{self_request.request_id}/decision",
        json=body,
    )
    assert self_response.status_code == 403

    request = await _submitted(service, requester_ref="heimdall-2")
    stale_response = _client(service).post(
        f"/access-grants/{request.request_id}/decision",
        json={**body, "decision": "reject", "expected_revision": 1},
    )
    assert stale_response.status_code == 409


async def test_reject_records_terminal_review_and_insufficient_role_is_denied() -> None:
    service = AccessGrantRequestService(store=InMemoryStateStore())
    request = await _submitted(service)
    body = {
        "decision": "reject",
        "reason": "The requested scope is wider than the investigation requires.",
        "expected_revision": 0,
    }

    denied = _client(service, roles=frozenset({Role.APPROVER})).post(
        f"/access-grants/{request.request_id}/decision",
        json=body,
    )
    assert denied.status_code == 403

    rejected = _client(service).post(
        f"/access-grants/{request.request_id}/decision",
        json=body,
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["permission_applied"] is False
    assert rejected.json()["fresh_probe_required"] is True
