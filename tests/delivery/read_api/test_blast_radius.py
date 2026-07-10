"""Integration tests for the ``/simulate/blast-radius`` GET route."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from fdai.core.risk_gate.blast_radius_simulator import InMemoryOntologyGraph
from fdai.delivery.read_api.auth import build_authenticator
from fdai.delivery.read_api.main import ReadApiConfig, build_app
from fdai.delivery.read_api.read_model import InMemoryConsoleReadModel


@pytest.fixture(autouse=True)
def _dev_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FDAI_READ_API_DEV_MODE", "1")


def _chain_graph() -> InMemoryOntologyGraph:
    return InMemoryOntologyGraph(
        edges={
            ("sub-a", "contains"): ("rg-1",),
            ("rg-1", "contains"): ("vnet-1",),
            ("vnet-1", "contains"): ("subnet-1",),
            ("subnet-1", "contains"): ("vm-1",),
        },
        link_types=frozenset({"contains", "depends_on"}),
    )


def _client(graph: InMemoryOntologyGraph | None) -> TestClient:
    auth = build_authenticator(verifier=lambda t: {"oid": "u"}, resolver=lambda claims: None)
    app = build_app(
        authenticator=auth,
        read_model=InMemoryConsoleReadModel(),
        config=ReadApiConfig(dev_mode=True, blast_radius_graph=graph),
    )
    return TestClient(app)


def test_blast_radius_route_returns_reached_subgraph() -> None:
    client = _client(_chain_graph())
    resp = client.get(
        "/simulate/blast-radius",
        params=[("target", "sub-a"), ("depth", "3"), ("link", "contains")],
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["target"] == "sub-a"
    assert body["traversal_depth"] == 3
    assert body["traversal_links"] == ["contains"]
    ids = [n["resource_id"] for n in body["reached"]]
    assert ids == ["sub-a", "rg-1", "vnet-1", "subnet-1"]
    assert body["affected_count"] == 3
    assert body["truncated_at_depth"] is True


def test_blast_radius_route_400_on_missing_target() -> None:
    client = _client(_chain_graph())
    resp = client.get("/simulate/blast-radius", params={"depth": "1", "link": "contains"})
    assert resp.status_code == 400
    assert "target" in resp.text


def test_blast_radius_route_400_on_missing_link() -> None:
    client = _client(_chain_graph())
    resp = client.get("/simulate/blast-radius", params={"target": "sub-a", "depth": "1"})
    assert resp.status_code == 400
    assert "link" in resp.text


def test_blast_radius_route_422_on_unknown_link_type() -> None:
    client = _client(_chain_graph())
    resp = client.get(
        "/simulate/blast-radius",
        params=[("target", "sub-a"), ("depth", "1"), ("link", "does-not-exist")],
    )
    assert resp.status_code == 422


def test_blast_radius_route_400_on_bogus_depth() -> None:
    client = _client(_chain_graph())
    resp = client.get(
        "/simulate/blast-radius",
        params=[("target", "sub-a"), ("depth", "not-an-int"), ("link", "contains")],
    )
    assert resp.status_code == 400


def test_blast_radius_route_400_on_depth_exceeding_cap() -> None:
    client = _client(_chain_graph())
    resp = client.get(
        "/simulate/blast-radius",
        params=[("target", "sub-a"), ("depth", "999"), ("link", "contains")],
    )
    assert resp.status_code == 400


def test_blast_radius_route_400_on_oversized_target_and_link() -> None:
    client = _client(_chain_graph())
    # target over the 512-char cap.
    r1 = client.get(
        "/simulate/blast-radius",
        params=[("target", "t" * 513), ("depth", "1"), ("link", "contains")],
    )
    assert r1.status_code == 400
    assert "target" in r1.text
    # link name over the 128-char cap.
    r2 = client.get(
        "/simulate/blast-radius",
        params=[("target", "sub-a"), ("depth", "1"), ("link", "c" * 129)],
    )
    assert r2.status_code == 400
    assert "link" in r2.text


def test_blast_radius_route_400_when_sim_cap_below_route_cap() -> None:
    # The route accepts depth in [1, 8] but the simulator caps traversal
    # at 5; a depth of 6 passes route validation then trips the
    # simulator's TraversalDepthExceededError, surfaced as a 400.
    client = _client(_chain_graph())
    resp = client.get(
        "/simulate/blast-radius",
        params=[("target", "sub-a"), ("depth", "6"), ("link", "contains")],
    )
    assert resp.status_code == 400
    assert "exceeds cap" in resp.text


def test_route_not_registered_when_graph_is_none() -> None:
    client = _client(None)
    resp = client.get(
        "/simulate/blast-radius",
        params=[("target", "sub-a"), ("depth", "1"), ("link", "contains")],
    )
    # Starlette returns 404 for unregistered paths.
    assert resp.status_code == 404


def test_route_is_get_only() -> None:
    client = _client(_chain_graph())
    resp = client.post(
        "/simulate/blast-radius",
        params=[("target", "sub-a"), ("depth", "1"), ("link", "contains")],
    )
    # 405 Method Not Allowed - preserves the read-only invariant.
    assert resp.status_code == 405
