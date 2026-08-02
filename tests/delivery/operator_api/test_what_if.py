"""Integration tests for ``GET /audit/{correlation_id}/what-if``."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import pytest
from starlette.testclient import TestClient

from fdai.delivery.operator_api.auth import build_authenticator
from fdai.delivery.operator_api.main import OperatorApiConfig, build_app
from fdai.delivery.operator_api.read_model import InMemoryConsoleReadModel
from fdai.delivery.operator_api.routes.rule_fire_trace_reader import ConsoleReadModelTraceReader


@pytest.fixture(autouse=True)
def _dev_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FDAI_OPERATOR_API_DEV_MODE", "1")


@dataclass(slots=True)
class _StubEvaluator:
    verdicts: list[Mapping[str, Any]] = field(default_factory=list)

    def evaluate(
        self, resource_type: str, resource_props: Mapping[str, Any]
    ) -> Sequence[Mapping[str, Any]]:
        del resource_type, resource_props
        return list(self.verdicts)


def _seed_ingest(model: InMemoryConsoleReadModel, correlation: str) -> None:
    model.record_audit_entry(
        {
            "correlation_id": correlation,
            "pipeline_stage": "event_ingest",
            "payload": {
                "resource": {
                    "resource_id": "vm-1",
                    "type": "compute.vm",
                    "props": {"tier": "S1"},
                }
            },
        },
        action_kind="event.received",
    )


def _client(model: InMemoryConsoleReadModel, evaluators: dict) -> TestClient:
    auth = build_authenticator(verifier=lambda t: {"oid": "u"}, resolver=lambda claims: None)
    app = build_app(
        authenticator=auth,
        read_model=model,
        config=OperatorApiConfig(
            dev_mode=True,
            what_if_reader=ConsoleReadModelTraceReader(model),
            what_if_evaluators=evaluators,
        ),
    )
    return TestClient(app)


def test_what_if_route_returns_replay_report() -> None:
    model = InMemoryConsoleReadModel()
    _seed_ingest(model, "corr-1")
    evaluator = _StubEvaluator(
        verdicts=[{"rule_id": "fork-x.new-rule", "denied": True, "reason": "policy"}]
    )
    with _client(model, {"tighter-tags": evaluator}) as client:
        resp = client.get("/audit/corr-1/what-if", params={"scenario": "tighter-tags"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scenario"] == "tighter-tags"
    assert body["event"]["resource_type"] == "compute.vm"
    assert body["matched_rules"][0]["rule_id"] == "fork-x.new-rule"


def test_what_if_route_404_on_unknown_scenario() -> None:
    model = InMemoryConsoleReadModel()
    _seed_ingest(model, "corr-1")
    with _client(model, {"only-one": _StubEvaluator()}) as client:
        resp = client.get("/audit/corr-1/what-if", params={"scenario": "does-not-exist"})
    assert resp.status_code == 404


def test_what_if_route_400_on_missing_scenario() -> None:
    model = InMemoryConsoleReadModel()
    _seed_ingest(model, "corr-1")
    with _client(model, {"only-one": _StubEvaluator()}) as client:
        resp = client.get("/audit/corr-1/what-if")
    assert resp.status_code == 400


def test_what_if_route_400_on_oversized_correlation_and_scenario() -> None:
    model = InMemoryConsoleReadModel()
    _seed_ingest(model, "corr-1")
    with _client(model, {"only-one": _StubEvaluator()}) as client:
        # correlation_id over the 256-char cap (reflected-error amplification guard).
        r1 = client.get(f"/audit/{'c' * 257}/what-if", params={"scenario": "only-one"})
        assert r1.status_code == 400
        # scenario over the 128-char cap.
        r2 = client.get("/audit/corr-1/what-if", params={"scenario": "s" * 129})
        assert r2.status_code == 400


def test_what_if_route_404_on_unknown_correlation() -> None:
    model = InMemoryConsoleReadModel()
    with _client(model, {"only-one": _StubEvaluator()}) as client:
        resp = client.get("/audit/nope/what-if", params={"scenario": "only-one"})
    assert resp.status_code == 404


def test_what_if_route_422_when_event_cannot_be_reconstructed() -> None:
    model = InMemoryConsoleReadModel()
    # No payload block on the first audit entry -> reconstruction fails.
    model.record_audit_entry(
        {"correlation_id": "corr-noent", "pipeline_stage": "event_ingest"},
        action_kind="event.received",
    )
    with _client(model, {"only-one": _StubEvaluator()}) as client:
        resp = client.get("/audit/corr-noent/what-if", params={"scenario": "only-one"})
    assert resp.status_code == 422


def test_what_if_route_absent_when_evaluators_empty() -> None:
    model = InMemoryConsoleReadModel()
    _seed_ingest(model, "corr-1")
    auth = build_authenticator(verifier=lambda t: {"oid": "u"}, resolver=lambda claims: None)
    app = build_app(
        authenticator=auth,
        read_model=model,
        config=OperatorApiConfig(
            dev_mode=True,
            what_if_reader=ConsoleReadModelTraceReader(model),
            what_if_evaluators={},
        ),
    )
    with TestClient(app) as client:
        resp = client.get("/audit/corr-1/what-if", params={"scenario": "any"})
    assert resp.status_code == 404
