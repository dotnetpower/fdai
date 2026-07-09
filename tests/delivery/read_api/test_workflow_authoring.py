"""Integration tests for the custom workflow authoring endpoints."""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from fdai.delivery.read_api.auth import build_authenticator
from fdai.delivery.read_api.main import ReadApiConfig, build_app
from fdai.delivery.read_api.read_model import InMemoryConsoleReadModel
from fdai.delivery.read_api.workflow_authoring import WorkflowAuthoringConfig
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry

REPO_ROOT = Path(__file__).resolve().parents[3]
ACTION_TYPES_ROOT = REPO_ROOT / "rule-catalog" / "action-types"


@pytest.fixture(autouse=True)
def _dev_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FDAI_READ_API_DEV_MODE", "1")


def _authoring_config() -> WorkflowAuthoringConfig:
    registry = PackageResourceSchemaRegistry()
    action_types = load_action_type_catalog(
        ACTION_TYPES_ROOT, schema_registry=registry, probes_root=None
    )
    return WorkflowAuthoringConfig(
        schema_registry=registry,
        action_types=action_types,
        rule_ids=frozenset(),
    )


def _client(*, authoring: bool) -> TestClient:
    auth = build_authenticator(verifier=lambda t: {"oid": "u"}, resolver=lambda claims: None)
    app = build_app(
        authenticator=auth,
        read_model=InMemoryConsoleReadModel(),
        config=ReadApiConfig(
            dev_mode=True,
            workflow_authoring=_authoring_config() if authoring else None,
        ),
    )
    return TestClient(app)


def _valid_draft(action_type_ref: str) -> dict:
    return {
        "schema_version": "1.0.0",
        "name": "custom-example",
        "version": "1.0.0",
        "description": "A custom operator-authored process.",
        "trigger": {"kind": "signal", "signal_type": "object.drift"},
        "default_mode": "shadow",
        "promotion_gate": {
            "min_shadow_days": 14,
            "min_samples": 100,
            "min_accuracy": 0.95,
            "max_policy_escapes": 0,
        },
        "steps": [{"id": "step_one", "action_type_ref": action_type_ref}],
    }


def _first_action_type_name() -> str:
    registry = PackageResourceSchemaRegistry()
    action_types = load_action_type_catalog(
        ACTION_TYPES_ROOT, schema_registry=registry, probes_root=None
    )
    return action_types[0].name


def test_authoring_endpoints_unregistered_by_default() -> None:
    client = _client(authoring=False)
    assert client.get("/workflows/action-types").status_code == 404
    assert client.post("/workflows/validate", json={}).status_code == 404


def test_action_types_palette_lists_the_catalog() -> None:
    client = _client(authoring=True)
    resp = client.get("/workflows/action-types")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] == len(body["action_types"])
    assert body["count"] > 0
    entry = body["action_types"][0]
    # Palette is sorted by name and carries the safety-relevant surface.
    names = [a["name"] for a in body["action_types"]]
    assert names == sorted(names)
    for key in ("name", "operation", "rollback_contract", "irreversible", "default_mode"):
        assert key in entry


def test_action_types_route_is_get_only() -> None:
    client = _client(authoring=True)
    assert client.post("/workflows/action-types").status_code == 405


def test_validate_accepts_a_well_formed_draft() -> None:
    client = _client(authoring=True)
    draft = _valid_draft(_first_action_type_name())
    resp = client.post("/workflows/validate", json=draft)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["valid"] is True
    assert body["issues"] == []
    assert body["yaml_preview"]
    assert "name: custom-example" in body["yaml_preview"]


def test_validate_flags_an_unknown_action_type() -> None:
    client = _client(authoring=True)
    draft = _valid_draft("remediate.does-not-exist")
    body = client.post("/workflows/validate", json=draft).json()
    assert body["valid"] is False
    assert body["yaml_preview"] is None
    assert any("action_type_ref" in i["key"] for i in body["issues"])


def test_validate_flags_a_schema_violation() -> None:
    client = _client(authoring=True)
    draft = _valid_draft(_first_action_type_name())
    del draft["steps"]  # steps is required
    body = client.post("/workflows/validate", json=draft).json()
    assert body["valid"] is False
    assert body["issues"]


def test_validate_rejects_a_non_object_body() -> None:
    client = _client(authoring=True)
    resp = client.post("/workflows/validate", json=["not", "an", "object"])
    assert resp.status_code == 400


def test_validate_route_is_post_only() -> None:
    client = _client(authoring=True)
    assert client.get("/workflows/validate").status_code == 405
