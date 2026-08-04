"""Integration tests for the stewardship / handover-map read endpoint."""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from fdai.core.stewardship import (
    AgentStewardship,
    Responsibility,
    StewardKind,
    StewardSubject,
    load_stewardship_from_yaml,
)
from fdai.delivery.operator_api.auth import build_authenticator
from fdai.delivery.operator_api.main import OperatorApiConfig, build_app
from fdai.delivery.operator_api.read_model import InMemoryConsoleReadModel
from fdai.delivery.operator_api.routes import stewardship as stewardship_route

_CONFIG = Path("config/agent-stewardship.yaml")


@pytest.fixture(autouse=True)
def _dev_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FDAI_OPERATOR_API_DEV_MODE", "1")


def _client(*, expose: bool, health_reader=None) -> TestClient:
    auth = build_authenticator(verifier=lambda t: {"oid": "u"}, resolver=lambda claims: None)
    stewardship = load_stewardship_from_yaml(_CONFIG) if expose else None
    app = build_app(
        authenticator=auth,
        read_model=InMemoryConsoleReadModel(),
        config=OperatorApiConfig(
            dev_mode=True,
            stewardship_map=stewardship,
            stewardship_health_reader=health_reader,
        ),
    )
    return TestClient(app)


def test_stewardship_unregistered_by_default() -> None:
    assert _client(expose=False).get("/stewardship").status_code == 404


def test_stewardship_returns_map_and_coverage() -> None:
    resp = _client(expose=True).get("/stewardship")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["map"]["maintainer_count"] == 2
    names = {a["name"] for a in body["map"]["agents"]}
    assert len(names) == 15 and "Loki" in names
    accountable = [
        steward
        for agent in body["map"]["agents"]
        for steward in agent["stewards"]
        if steward["responsibility"] == "accountable"
    ]
    assert accountable
    assert all(steward["duty"] in {"primary", "backup", "escalation"} for steward in accountable)
    assert all(
        "duty" not in steward
        for agent in body["map"]["agents"]
        for steward in agent["stewards"]
        if steward["responsibility"] == "informed"
    )
    # Coverage report is present with the headline counts.
    assert body["coverage"]["total_agents"] == 15
    assert "is_clean" in body["coverage"]


def test_stewardship_bus_factor_counts_distinct_accountable_units() -> None:
    subject = StewardSubject(
        kind=StewardKind.GROUP,
        id="example-team",
        responsibility=Responsibility.ACCOUNTABLE,
    )
    agent = AgentStewardship(agent_name="Odin", stewards=(subject, subject))

    serialized = stewardship_route._serialize_agent(agent)

    assert serialized["bus_factor"] == 1


def test_stewardship_marks_autonomous_agent() -> None:
    body = _client(expose=True).get("/stewardship").json()
    loki = next(a for a in body["map"]["agents"] if a["name"] == "Loki")
    assert loki["autonomous"] is True
    assert loki["accept_autonomous_reason"]


def test_stewardship_merges_scheduled_stale_oid_findings() -> None:
    class HealthReader:
        async def read_state(self, key: str):
            assert key == "stewardship_health:current"
            return {
                "checked_at": "2026-07-22T00:00:00+00:00",
                "findings": [
                    {
                        "code": "stale_oid",
                        "severity": "warn",
                        "message": "Steward no longer resolves.",
                        "agent": "Thor",
                    }
                ],
            }

    body = _client(expose=True, health_reader=HealthReader()).get("/stewardship").json()

    assert body["identity_health"]["status"] == "warn"
    assert any(item["code"] == "stale_oid" for item in body["coverage"]["findings"])
    assert body["coverage"]["is_clean"] is False


def test_stewardship_marks_malformed_health_unavailable() -> None:
    class HealthReader:
        async def read_state(self, _key: str):
            return {"checked_at": 123, "findings": "bad"}

    body = _client(expose=True, health_reader=HealthReader()).get("/stewardship").json()

    assert body["identity_health"]["status"] == "unavailable"
    assert not any(item["code"] == "stale_oid" for item in body["coverage"]["findings"])
