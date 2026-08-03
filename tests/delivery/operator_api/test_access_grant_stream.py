"""Browser-safe execution access-grant stream tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from starlette.routing import Route

from fdai.core.execution_authorization import AccessGrantRequestService
from fdai.core.rbac.resolver import GroupMapping, Principal, RoleResolver
from fdai.core.rbac.roles import Role
from fdai.delivery.operator_api.auth import UnsafeClaimsExtractor, build_authenticator
from fdai.delivery.operator_api.main import OperatorApiConfig, build_app
from fdai.delivery.operator_api.read_model import InMemoryConsoleReadModel
from fdai.delivery.operator_api.routes.access_grant_stream import (
    access_grant_snapshot,
    make_access_grant_stream_route,
)
from fdai.shared.providers.testing import InMemoryStateStore

_NOW = datetime(2026, 8, 4, tzinfo=UTC)


async def test_snapshot_is_role_scoped_and_redacts_internal_grant_fields() -> None:
    service = AccessGrantRequestService(store=InMemoryStateStore())
    request = await service.submit(
        idempotency_key="grant-metrics",
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
        requester_ref="heimdall",
        requested_at=_NOW,
        expires_at=_NOW + timedelta(hours=1),
        quorum=1,
        approver_roles=frozenset({"owner"}),
    )

    snapshot = await access_grant_snapshot(
        service=service,
        principal=Principal(oid="owner-1", roles=frozenset({Role.OWNER})),
        now=_NOW + timedelta(minutes=1),
    )

    assert snapshot["event"] == "access_grant.snapshot"
    assert snapshot["requests"] == [
        {
            "request_id": request.request_id,
            "correlation_id": "incident-1",
            "capability_id": "kubernetes.metrics.read",
            "scope_ref": "scope://example/cluster/namespace/example-app",
            "grant_mode": "time_bound",
            "requested_at": "2026-08-04T00:00:00+00:00",
            "expires_at": "2026-08-04T01:00:00+00:00",
            "quorum": 1,
            "status": "pending",
            "revision": 0,
        }
    ]
    encoded = json.dumps(snapshot)
    assert "plan-v1" not in encoded
    assert "mapping-v1" not in encoded
    assert "identity/reader" not in encoded
    assert "heimdall" not in encoded

    reader_snapshot = await access_grant_snapshot(
        service=service,
        principal=Principal(oid="reader-1", roles=frozenset({Role.READER})),
        now=_NOW + timedelta(minutes=1),
    )
    assert reader_snapshot["requests"] == []


def test_stream_route_rejects_invalid_configuration() -> None:
    async def authorize(_request):  # type: ignore[no-untyped-def]
        return Principal(oid="owner-1", roles=frozenset({Role.OWNER}))

    service = AccessGrantRequestService(store=InMemoryStateStore())
    with pytest.raises(ValueError, match="path"):
        make_access_grant_stream_route(service=service, authorize=authorize, path="bad")


def test_operator_api_registers_access_grant_stream_as_get_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FDAI_OPERATOR_API_DEV_MODE", "1")
    mapping = GroupMapping(
        reader_group_id="reader-group",
        contributor_group_id="contributor-group",
        approver_group_id="approver-group",
        owner_group_id="owner-group",
        break_glass_group_id="break-glass-group",
    )
    app = build_app(
        authenticator=build_authenticator(
            verifier=UnsafeClaimsExtractor(),
            resolver=RoleResolver(group_mapping=mapping),
        ),
        read_model=InMemoryConsoleReadModel(),
        config=OperatorApiConfig(
            dev_mode=True,
            execution_access_grants=AccessGrantRequestService(store=InMemoryStateStore()),
        ),
    )

    route = next(
        item
        for item in app.routes
        if isinstance(item, Route) and item.path == "/access-grants/stream"
    )
    assert route.methods == {"GET", "HEAD"}
