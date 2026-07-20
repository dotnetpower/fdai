"""Integration tests for the ``/ontology/graph`` GET route."""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from fdai.delivery.read_api.auth import build_authenticator
from fdai.delivery.read_api.main import ReadApiConfig, build_app
from fdai.delivery.read_api.read_model import InMemoryConsoleReadModel
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.rule_catalog.schema.link_type import load_link_type_catalog
from fdai.rule_catalog.schema.object_type import load_object_type_catalog
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry

REPO_ROOT = Path(__file__).resolve().parents[3]
OBJECT_TYPES_ROOT = REPO_ROOT / "rule-catalog" / "vocabulary" / "object-types"
LINK_TYPES_ROOT = REPO_ROOT / "rule-catalog" / "vocabulary" / "link-types"
ACTION_TYPES_ROOT = REPO_ROOT / "rule-catalog" / "action-types"


@pytest.fixture(autouse=True)
def _dev_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FDAI_READ_API_DEV_MODE", "1")


def _catalog() -> tuple:
    registry = PackageResourceSchemaRegistry()
    objects = load_object_type_catalog(OBJECT_TYPES_ROOT, schema_registry=registry)
    links = load_link_type_catalog(LINK_TYPES_ROOT, schema_registry=registry, object_types=objects)
    actions = load_action_type_catalog(ACTION_TYPES_ROOT, schema_registry=registry)
    return objects, links, actions


def _client(*, wire_ontology: bool) -> TestClient:
    objects, links, actions = _catalog() if wire_ontology else ((), (), ())
    auth = build_authenticator(verifier=lambda t: {"oid": "u"}, resolver=lambda claims: None)
    app = build_app(
        authenticator=auth,
        read_model=InMemoryConsoleReadModel(),
        config=ReadApiConfig(
            dev_mode=True,
            ontology_object_types=tuple(objects),
            ontology_link_types=tuple(links),
            ontology_action_types=tuple(actions),
        ),
    )
    return TestClient(app)


def test_ontology_graph_returns_mermaid_and_counts() -> None:
    client = _client(wire_ontology=True)
    resp = client.get("/ontology/graph")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["mermaid"].startswith("classDiagram\n")
    assert body["object_type_count"] >= 4
    assert body["link_type_count"] >= 5
    assert body["action_type_count"] >= 1
    assert "Resource" in body["object_types"]
    assert "contains" in body["link_types"]
    action = next(item for item in body["action_types"] if item["name"] == "ops.scale-out")
    assert action["default_mode"] == "shadow"
    assert action["rollback_contract"] == "state_forward_only"
    assert action["stop_conditions"]
    issue = next(item for item in body["nodes"] if item["name"] == "Issue")
    assert issue["lifecycle"]["owner"] == "Saga"
    assert issue["lifecycle"]["creation"][0]["source_refs"]
    assert issue["lifecycle"]["deduplication"]["strategy"] == "deterministic fingerprint"


def test_slim_mode_omits_properties() -> None:
    client = _client(wire_ontology=True)
    verbose = client.get("/ontology/graph").json()
    slim = client.get("/ontology/graph", params={"include_properties": "false"}).json()
    assert len(slim["mermaid"]) < len(verbose["mermaid"])
    assert slim["object_type_count"] == verbose["object_type_count"]


def test_property_limit_rejects_zero() -> None:
    client = _client(wire_ontology=True)
    resp = client.get("/ontology/graph", params={"property_limit": "0"})
    assert resp.status_code == 400


def test_property_limit_rejects_non_int() -> None:
    client = _client(wire_ontology=True)
    resp = client.get("/ontology/graph", params={"property_limit": "abc"})
    assert resp.status_code == 400


def test_route_absent_when_ontology_not_configured() -> None:
    client = _client(wire_ontology=False)
    resp = client.get("/ontology/graph")
    assert resp.status_code == 404


def test_route_is_get_only() -> None:
    client = _client(wire_ontology=True)
    resp = client.post("/ontology/graph")
    assert resp.status_code == 405
