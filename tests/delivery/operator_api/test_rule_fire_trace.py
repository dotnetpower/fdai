"""Tests for rule-fire trace reader + integration route."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from starlette.testclient import TestClient

from fdai.core.audit.rule_fire_trace import (
    build_rule_fire_trace,
)
from fdai.delivery.operator_api.auth import build_authenticator
from fdai.delivery.operator_api.main import OperatorApiConfig, build_app
from fdai.delivery.operator_api.read_model import InMemoryConsoleReadModel
from fdai.delivery.operator_api.routes.rule_fire_trace_reader import ConsoleReadModelTraceReader


@pytest.fixture(autouse=True)
def _dev_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FDAI_OPERATOR_API_DEV_MODE", "1")


def _seed_trace(model: InMemoryConsoleReadModel, correlation: str) -> None:
    """Seed a four-step trace: ingest -> route -> t0 -> executor."""
    base = datetime(2026, 7, 8, 10, 0, 0, tzinfo=UTC)
    steps = [
        {
            "correlation_id": correlation,
            "pipeline_stage": "event_ingest",
            "action_kind": "event.received",
            "mode": "shadow",
            "recorded_at": base.replace(second=0).isoformat(),
        },
        {
            "correlation_id": correlation,
            "pipeline_stage": "L1_evaluate",
            "decision": "deny",
            "deny_reason": "public_access_enabled",
            "action_kind": "trust_router.route",
            "mode": "shadow",
            "recorded_at": base.replace(second=1).isoformat(),
        },
        {
            "correlation_id": correlation,
            "pipeline_stage": "risk_gate",
            "decision": "allow",
            "reason": "static_bucket=resource",
            "action_kind": "risk_gate.evaluate",
            "mode": "shadow",
            "recorded_at": base.replace(second=2).isoformat(),
        },
        {
            "correlation_id": correlation,
            "pipeline_stage": "remediate",
            "decision": "executed",
            "action_kind": "remediate.disable-public-access",
            "mode": "shadow",
            "recorded_at": base.replace(second=3).isoformat(),
        },
    ]
    for entry in steps:
        model.record_audit_entry(entry)


def test_build_rule_fire_trace_returns_none_on_empty_items() -> None:
    trace = build_rule_fire_trace("corr-1", items=[])
    assert trace is None


@pytest.mark.asyncio
async def test_trace_preserves_stage_less_activity_and_last_named_terminal_stage() -> None:
    model = InMemoryConsoleReadModel()
    model.record_audit_entry(
        {
            "correlation_id": "corr-activity",
            "pipeline_stage": "risk_gate",
            "action_kind": "risk_gate.evaluate",
            "mode": "shadow",
        }
    )
    model.record_audit_entry(
        {
            "correlation_id": "corr-activity",
            "kind": "notification.escalation",
            "reason": "no delivery channel is available",
            "mode": "shadow",
        },
        action_kind="notification.escalation",
    )
    items = await ConsoleReadModelTraceReader(model).read_items("corr-activity")

    trace = build_rule_fire_trace("corr-activity", items)

    assert trace is not None
    body = trace.as_json()
    assert [step["stage"] for step in body["steps"]] == ["risk_gate", None]
    assert body["terminal_stage"] == "risk_gate"


def test_trace_reader_returns_oldest_first_from_console_model() -> None:
    model = InMemoryConsoleReadModel()
    _seed_trace(model, "corr-42")
    reader = ConsoleReadModelTraceReader(model)

    import asyncio

    items = asyncio.run(reader.read_items("corr-42"))
    assert [i.seq for i in items] == sorted(i.seq for i in items)  # ascending


@pytest.mark.asyncio
async def test_trace_route_returns_full_ordered_trace() -> None:
    model = InMemoryConsoleReadModel()
    _seed_trace(model, "corr-99")
    auth = build_authenticator(verifier=lambda t: {"oid": "u"}, resolver=lambda claims: None)
    app = build_app(
        authenticator=auth,
        read_model=model,
        config=OperatorApiConfig(
            dev_mode=True,
            trace_reader=ConsoleReadModelTraceReader(model),
        ),
    )
    with TestClient(app) as client:
        resp = client.get("/audit/corr-99/trace")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["correlation_id"] == "corr-99"
    assert body["step_count"] == 4
    stages = [step["stage"] for step in body["steps"]]
    assert stages == ["event_ingest", "L1_evaluate", "risk_gate", "remediate"]
    l1 = next(step for step in body["steps"] if step["stage"] == "L1_evaluate")
    assert l1["reason"] == "public_access_enabled"
    assert body["terminal_stage"] == "remediate"


def test_trace_route_404_on_unknown_correlation() -> None:
    model = InMemoryConsoleReadModel()
    auth = build_authenticator(verifier=lambda t: {"oid": "u"}, resolver=lambda claims: None)
    app = build_app(
        authenticator=auth,
        read_model=model,
        config=OperatorApiConfig(
            dev_mode=True,
            trace_reader=ConsoleReadModelTraceReader(model),
        ),
    )
    with TestClient(app) as client:
        resp = client.get("/audit/does-not-exist/trace")
    assert resp.status_code == 404


def test_trace_route_400_on_oversized_correlation() -> None:
    model = InMemoryConsoleReadModel()
    auth = build_authenticator(verifier=lambda t: {"oid": "u"}, resolver=lambda claims: None)
    app = build_app(
        authenticator=auth,
        read_model=model,
        config=OperatorApiConfig(
            dev_mode=True,
            trace_reader=ConsoleReadModelTraceReader(model),
        ),
    )
    with TestClient(app) as client:
        # correlation_id over the 256-char cap is rejected before any read.
        resp = client.get(f"/audit/{'c' * 257}/trace")
    assert resp.status_code == 400


def test_trace_route_absent_when_reader_not_configured() -> None:
    auth = build_authenticator(verifier=lambda t: {"oid": "u"}, resolver=lambda claims: None)
    app = build_app(
        authenticator=auth,
        read_model=InMemoryConsoleReadModel(),
        config=OperatorApiConfig(dev_mode=True),
    )
    with TestClient(app) as client:
        resp = client.get("/audit/anything/trace")
    assert resp.status_code == 404


def test_trace_route_is_get_only() -> None:
    model = InMemoryConsoleReadModel()
    _seed_trace(model, "corr-x")
    auth = build_authenticator(verifier=lambda t: {"oid": "u"}, resolver=lambda claims: None)
    app = build_app(
        authenticator=auth,
        read_model=model,
        config=OperatorApiConfig(
            dev_mode=True,
            trace_reader=ConsoleReadModelTraceReader(model),
        ),
    )
    with TestClient(app) as client:
        resp = client.post("/audit/corr-x/trace")
    assert resp.status_code == 405
