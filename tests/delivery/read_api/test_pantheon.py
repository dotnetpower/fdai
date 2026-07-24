"""Integration tests for the pantheon read-only endpoints."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from fdai.delivery.read_api.auth import build_authenticator
from fdai.delivery.read_api.main import ReadApiConfig, build_app
from fdai.delivery.read_api.read_model import InMemoryConsoleReadModel


@pytest.fixture(autouse=True)
def _dev_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FDAI_READ_API_DEV_MODE", "1")


def _client(*, expose: bool) -> TestClient:
    auth = build_authenticator(verifier=lambda t: {"oid": "u"}, resolver=lambda claims: None)
    app = build_app(
        authenticator=auth,
        read_model=InMemoryConsoleReadModel(),
        config=ReadApiConfig(dev_mode=True, expose_pantheon=expose),
    )
    return TestClient(app)


def test_pantheon_endpoints_unregistered_by_default() -> None:
    client = _client(expose=False)
    assert client.get("/pantheon/graph").status_code == 404
    assert client.get("/pantheon/workflows").status_code == 404


def test_pantheon_graph_returns_all_fifteen_agents() -> None:
    client = _client(expose=True)
    resp = client.get("/pantheon/graph")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["agent_count"] == 15
    names = {a["name"] for a in body["agents"]}
    expected = {
        "Odin",
        "Thor",
        "Forseti",
        "Huginn",
        "Heimdall",
        "Vidar",
        "Var",
        "Bragi",
        "Saga",
        "Mimir",
        "Muninn",
        "Norns",
        "Njord",
        "Freyr",
        "Loki",
    }
    assert names == expected


def test_pantheon_graph_reports_hard_dependencies_and_llm_agents() -> None:
    client = _client(expose=True)
    body = client.get("/pantheon/graph").json()
    assert set(body["hard_dependency_agents"]) == {"Saga", "Vidar"}
    assert set(body["hot_path_llm_agents"]) == {"Bragi", "Forseti"}


def test_pantheon_graph_carries_org_chart_edges() -> None:
    client = _client(expose=True)
    body = client.get("/pantheon/graph").json()
    edges = body["org_edges"]
    # Every non-Odin agent has an edge whose 'to' matches its name.
    to_names = {e["to"] for e in edges}
    assert "Odin" not in to_names
    assert "Thor" in to_names
    assert "Forseti" in to_names


def test_pantheon_workflows_returns_registered_catalog() -> None:
    client = _client(expose=True)
    resp = client.get("/pantheon/workflows")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] == 11
    ids = {w["id"] for w in body["workflows"]}
    assert "handoff-capability" in ids
    assert "security-escalation" in ids
    assert "detection-readiness-assurance" in ids


def test_pantheon_workflows_include_primary_agent_and_gate() -> None:
    client = _client(expose=True)
    body = client.get("/pantheon/workflows").json()
    for w in body["workflows"]:
        assert w["primary_agent"] in {
            a
            for a in [
                "Odin",
                "Thor",
                "Forseti",
                "Huginn",
                "Heimdall",
                "Vidar",
                "Var",
                "Bragi",
                "Saga",
                "Mimir",
                "Muninn",
                "Norns",
                "Njord",
                "Freyr",
                "Loki",
            ]
        }
        assert w["promotion_gate"]  # non-empty string


def test_pantheon_endpoints_are_get_only() -> None:
    client = _client(expose=True)
    assert client.post("/pantheon/graph").status_code == 405
    assert client.post("/pantheon/workflows").status_code == 405


def test_pantheon_graph_serializes_topics() -> None:
    client = _client(expose=True)
    body = client.get("/pantheon/graph").json()
    thor = next(a for a in body["agents"] if a["name"] == "Thor")
    assert "object.action-run" in thor["publishes"]
    saga = next(a for a in body["agents"] if a["name"] == "Saga")
    assert "object.audit-entry" in saga["publishes"]


def test_pantheon_graph_includes_mermaid_org_chart() -> None:
    client = _client(expose=True)
    body = client.get("/pantheon/graph").json()
    mermaid = body["mermaid"]
    assert mermaid.startswith("graph TD")
    # Every non-Odin agent must appear as a node with its layer label.
    assert "Thor[" in mermaid
    assert "Forseti[" in mermaid
    # At least one edge from Odin
    assert "Odin --> Thor" in mermaid or "Odin -.-> Thor" in mermaid


def test_pantheon_graph_mermaid_is_deterministic() -> None:
    """Same registry -> byte-identical mermaid across calls."""
    client = _client(expose=True)
    a = client.get("/pantheon/graph").json()["mermaid"]
    b = client.get("/pantheon/graph").json()["mermaid"]
    assert a == b
