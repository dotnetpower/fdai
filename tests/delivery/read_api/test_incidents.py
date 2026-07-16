"""Incident roster projection and GET-only route tests."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from starlette.testclient import TestClient

from fdai.core.rbac.resolver import GroupMapping, RoleResolver
from fdai.delivery.read_api.auth import build_authenticator
from fdai.delivery.read_api.main import ReadApiConfig, build_app
from fdai.delivery.read_api.read_model import AuditItem, InMemoryConsoleReadModel
from fdai.delivery.read_api.routes.incident_projection import project_incidents


def _item(
    seq: int,
    correlation_id: str | None,
    *,
    event_id: str = "00000000-0000-0000-0000-000000000001",
    action_kind: str = "control.stage",
    entry: dict[str, object] | None = None,
) -> AuditItem:
    return AuditItem(
        seq=seq,
        event_id=event_id,
        correlation_id=correlation_id,
        actor="Saga",
        action_kind=action_kind,
        mode="shadow",
        entry=entry or {},
        entry_hash=f"hash-{seq}",
        previous_hash=f"hash-{seq - 1}",
        recorded_at=f"2026-07-14T10:{seq:02d}:00+00:00",
    )


def test_projection_groups_direct_and_event_anchored_history() -> None:
    items = (
        _item(
            1,
            "corr-1",
            entry={
                "stage": "ingest",
                "rule_id": "storage.public-access",
                "severity": "high",
                "vertical": "change_safety",
            },
        ),
        _item(2, None, entry={"stage": "execute", "outcome": "published"}),
        _item(
            3,
            "corr-1",
            action_kind="audit.record",
            entry={"stage": "audit", "phase": "done", "outcome": "remediated"},
        ),
    )
    summary = project_incidents(items)[0]
    assert summary.correlation_id == "corr-1"
    assert summary.history_count == 3
    assert summary.title == "storage.public-access"
    assert summary.severity == "high"
    assert summary.vertical == "change_safety"
    assert summary.status == "resolved"
    assert summary.disposition == "action_delivered"
    assert summary.involved_agents == ("Saga",)


def test_lifecycle_status_is_authoritative_and_hil_stays_active() -> None:
    lifecycle = (
        _item(
            1,
            None,
            entry={
                "kind": "incident.open",
                "incident_id": "inc-1",
                "state": "open",
                "severity": "critical",
                "correlation_keys": ["corr:corr-life"],
            },
        ),
        _item(
            2,
            None,
            entry={
                "kind": "incident.transition",
                "incident_id": "inc-1",
                "to_state": "triaging",
            },
        ),
        _item(3, "corr-life", entry={"stage": "gate", "decision": "hil"}),
    )
    active = project_incidents(lifecycle, status="active")
    assert len(active) == 1
    assert active[0].status == "in_progress"
    assert active[0].status_source == "incident_lifecycle"
    assert active[0].disposition == "awaiting_hil"
    assert active[0].verdict == "hil"
    assert project_incidents(lifecycle, status="resolved") == ()


def test_ambiguous_event_anchor_is_not_cross_attached() -> None:
    items = (
        _item(1, "corr-a"),
        _item(2, "corr-b"),
        _item(3, None, entry={"stage": "execute"}),
    )
    summaries = project_incidents(items)
    assert {item.correlation_id for item in summaries} == {"corr-a", "corr-b"}
    assert all(item.history_count == 1 for item in summaries)


def test_denied_terminal_audit_does_not_claim_incident_resolution() -> None:
    items = (
        _item(1, "corr-denied", entry={"stage": "gate", "decision": "deny"}),
        _item(
            2,
            "corr-denied",
            action_kind="audit.record",
            entry={"stage": "audit", "phase": "done", "outcome": "recorded"},
        ),
    )
    summary = project_incidents(items)[0]
    assert summary.status == "in_progress"
    assert summary.disposition == "no_action"


def test_hil_action_kinds_project_as_awaiting_approval() -> None:
    items = (
        _item(
            1,
            "corr-hil",
            action_kind="hil.requested",
            entry={
                "action_kind": "hil.requested",
                "approval_id": "approval-1",
                "rule_id": "network.load-balancer.unused-backend",
                "category": "config_drift",
            },
        ),
        _item(
            2,
            "corr-hil",
            action_kind="hil.request.dispatch_unavailable",
            entry={
                "action_kind": "hil.request.dispatch_unavailable",
                "approval_id": "approval-1",
            },
        ),
    )

    summary = project_incidents(items)[0]

    assert summary.status == "in_progress"
    assert summary.verdict == "hil"
    assert summary.disposition == "awaiting_hil"
    assert summary.involved_agents == ("Huginn", "Heimdall", "Var", "Saga")
    assert summary.vertical == "change_safety"


def test_operator_request_abstain_stays_open_and_reports_no_action() -> None:
    summary = project_incidents(
        (
            _item(
                1,
                "corr-operator",
                action_kind="control_loop.operator_request_abstain",
                entry={
                    "action_kind": "control_loop.operator_request_abstain",
                    "producer_principal": "Heimdall",
                },
            ),
        )
    )[0]

    assert summary.status == "open"
    assert summary.verdict == "abstain"
    assert summary.disposition == "no_action"
    assert summary.involved_agents == ("Huginn", "Heimdall", "Saga")


def test_multiple_correlation_keys_and_conflicting_opens_fail_closed() -> None:
    items = (
        _item(
            1,
            None,
            entry={
                "kind": "incident.open",
                "incident_id": "inc-ambiguous",
                "correlation_keys": ["corr:corr-a", "corr:corr-b"],
            },
        ),
        _item(
            2,
            None,
            entry={
                "kind": "incident.transition",
                "incident_id": "inc-ambiguous",
                "to_state": "resolved",
            },
        ),
    )
    assert project_incidents(items) == ()


async def test_incident_cursor_holds_snapshot_across_concurrent_updates() -> None:
    model = InMemoryConsoleReadModel()
    for index in range(3):
        model.record_audit_entry(
            {
                "event_id": f"00000000-0000-0000-0000-00000000000{index + 1}",
                "correlation_id": f"corr-{index}",
                "stage": "gate",
            }
        )
    first = await model.list_incidents(status="all", limit=2)
    assert first.next_cursor is not None
    model.record_audit_entry(
        {
            "event_id": "00000000-0000-0000-0000-000000000001",
            "correlation_id": "corr-0",
            "stage": "execute",
        }
    )
    second = await model.list_incidents(status="all", limit=2, cursor=first.next_cursor)
    assert [item.correlation_id for item in second.items] == ["corr-0"]


async def test_incident_cursor_rejects_status_mismatch() -> None:
    model = InMemoryConsoleReadModel()
    for index in range(2):
        model.record_audit_entry(
            {
                "event_id": f"00000000-0000-0000-0000-00000000001{index}",
                "correlation_id": f"corr-{index}",
            }
        )
    first = await model.list_incidents(status="active", limit=1)
    assert first.next_cursor is not None
    with pytest.raises(ValueError, match="status mismatch"):
        await model.list_incidents(status="all", cursor=first.next_cursor)


async def test_incident_cursor_rejects_vertical_mismatch() -> None:
    model = InMemoryConsoleReadModel()
    for index in range(2):
        model.record_audit_entry(
            {
                "correlation_id": f"corr-{index}",
                "vertical": "change_safety",
                "recorded_at": f"2026-07-14T10:0{index}:00+00:00",
            }
        )
    first = await model.list_incidents(
        status="all",
        vertical="change_safety",
        limit=1,
    )
    assert first.next_cursor is not None
    with pytest.raises(ValueError, match="cursor"):
        await model.list_incidents(
            status="all",
            vertical="resilience",
            cursor=first.next_cursor,
        )


@pytest.fixture
def dev_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("FDAI_READ_API_DEV_MODE", "1")
    yield


def _client() -> tuple[TestClient, InMemoryConsoleReadModel]:
    mapping = GroupMapping(
        reader_group_id="reader",
        contributor_group_id="contributor",
        approver_group_id="approver",
        owner_group_id="owner",
        break_glass_group_id="break-glass",
    )
    auth = build_authenticator(
        verifier=lambda _: {"oid": "unused"},
        resolver=RoleResolver(group_mapping=mapping),
    )
    read_model = InMemoryConsoleReadModel()
    app = build_app(
        authenticator=auth,
        read_model=read_model,
        config=ReadApiConfig(dev_mode=True),
    )
    return TestClient(app), read_model


def test_incidents_route_filters_pages_and_is_get_only(dev_env: None) -> None:
    del dev_env
    client, read_model = _client()
    for index in range(3):
        read_model.record_audit_entry(
            {
                "event_id": f"00000000-0000-0000-0000-00000000000{index + 1}",
                "correlation_id": f"corr-{index}",
                "stage": "gate",
                "decision": "hil",
            }
        )
    first = client.get("/incidents?status=active&limit=2")
    assert first.status_code == 200
    assert len(first.json()["items"]) == 2
    assert first.json()["next_cursor"] is not None
    second = client.get(
        "/incidents",
        params={"status": "active", "limit": "2", "cursor": first.json()["next_cursor"]},
    )
    assert second.status_code == 200
    assert len(second.json()["items"]) == 1
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        assert client.request(method, "/incidents").status_code == 405


def test_incidents_route_rejects_bad_query(dev_env: None) -> None:
    del dev_env
    client, _ = _client()
    assert client.get("/incidents?status=closed").status_code == 400
    assert client.get("/incidents?limit=NaN").status_code == 400
    assert client.get("/incidents?cursor=bad").status_code == 400
    assert client.get("/incidents?vertical=other").status_code == 400


def test_incidents_route_filters_vertical_before_limit(dev_env: None) -> None:
    del dev_env
    client, read_model = _client()
    read_model.record_audit_entry(
        {"event_id": "target", "correlation_id": "corr-target", "vertical": "resilience"}
    )
    for index in range(30):
        read_model.record_audit_entry(
            {
                "event_id": f"other-{index}",
                "correlation_id": f"corr-other-{index}",
                "vertical": "change_safety",
            }
        )
    response = client.get("/incidents?status=all&limit=25&vertical=resilience")
    assert response.status_code == 200
    assert [item["correlation_id"] for item in response.json()["items"]] == ["corr-target"]


def test_correlation_filtered_audit_and_default_trace(dev_env: None) -> None:
    del dev_env
    client, read_model = _client()
    read_model.record_audit_entry(
        {
            "event_id": "00000000-0000-0000-0000-000000000001",
            "correlation_id": "corr-target",
            "stage": "gate",
            "decision": "auto",
        }
    )
    read_model.record_audit_entry(
        {
            "event_id": "00000000-0000-0000-0000-000000000002",
            "correlation_id": "corr-other",
            "stage": "gate",
        }
    )
    audit = client.get("/audit?correlation_id=corr-target")
    assert audit.status_code == 200
    assert [item["correlation_id"] for item in audit.json()["items"]] == ["corr-target"]
    trace = client.get("/audit/corr-target/trace")
    assert trace.status_code == 200
    assert trace.json()["correlation_id"] == "corr-target"
