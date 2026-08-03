"""Durable browser incident-attention stream tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from starlette.routing import Route

from fdai.core.rbac.resolver import GroupMapping, RoleResolver
from fdai.delivery.operator_api.auth import UnsafeClaimsExtractor, build_authenticator
from fdai.delivery.operator_api.main import OperatorApiConfig, build_app
from fdai.delivery.operator_api.read_model import InMemoryConsoleReadModel
from fdai.delivery.operator_api.routes.incident_attention_stream import (
    incident_attention_snapshot,
    make_incident_attention_stream_route,
)

_NOW = datetime(2026, 8, 4, tzinfo=UTC)


async def test_snapshot_projects_only_durable_active_incident_binding() -> None:
    model = InMemoryConsoleReadModel()
    model.record_audit_entry(
        {
            "kind": "incident.open",
            "event_id": "event-1",
            "correlation_id": "corr-1",
            "incident_id": "INC-1",
            "severity": "high",
            "state": "open",
            "opened_at": _NOW.isoformat(),
            "recorded_at": _NOW.isoformat(),
            "correlation_keys": ["resource:example-app"],
        },
        action_kind="incident.open",
    )

    snapshot = await incident_attention_snapshot(read_model=model, now=_NOW)

    assert snapshot["event"] == "incident_attention.snapshot"
    assert snapshot["incidents"] == [
        {
            "incident_id": "INC-1",
            "correlation_id": "corr-1",
            "title": "Resource example-app",
            "severity": "high",
            "status": "open",
            "opened_at": "2026-08-04T00:00:00+00:00",
            "last_updated_at": "2026-08-04T00:00:00+00:00",
        }
    ]


def test_stream_route_rejects_invalid_configuration() -> None:
    async def authorize(_request):  # type: ignore[no-untyped-def]
        return "reader-1"

    with pytest.raises(ValueError, match="path"):
        make_incident_attention_stream_route(
            read_model=InMemoryConsoleReadModel(), authorize=authorize, path="bad"
        )


def test_operator_api_registers_incident_attention_stream_as_get_only(
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
        config=OperatorApiConfig(dev_mode=True),
    )

    route = next(
        item for item in app.routes if isinstance(item, Route) and item.path == "/incidents/stream"
    )
    assert route.methods == {"GET", "HEAD"}
