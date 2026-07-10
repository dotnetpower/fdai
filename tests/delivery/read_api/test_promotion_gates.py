"""Integration tests for ``/kpi/promotion-gates``."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from fdai.core.measurement.promotion_gate import (
    InMemoryShadowVerdictSource,
    ShadowVerdictRecord,
)
from fdai.delivery.read_api.auth import build_authenticator
from fdai.delivery.read_api.main import ReadApiConfig, build_app
from fdai.delivery.read_api.read_model import InMemoryConsoleReadModel
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry

REPO_ROOT = Path(__file__).resolve().parents[3]
ACTION_TYPES_ROOT = REPO_ROOT / "rule-catalog" / "action-types"


@pytest.fixture(autouse=True)
def _dev_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FDAI_READ_API_DEV_MODE", "1")


def _catalog() -> tuple:
    return load_action_type_catalog(
        ACTION_TYPES_ROOT,
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=None,
    )


def _client(source, action_types) -> TestClient:
    auth = build_authenticator(verifier=lambda t: {"oid": "u"}, resolver=lambda claims: None)
    app = build_app(
        authenticator=auth,
        read_model=InMemoryConsoleReadModel(),
        config=ReadApiConfig(
            dev_mode=True,
            promotion_gate_action_types=tuple(action_types),
            promotion_gate_source=source,
        ),
    )
    return TestClient(app)


def test_route_returns_ready_and_blocked_counts() -> None:
    catalog = _catalog()
    fresh = datetime.now(tz=UTC) - timedelta(days=1)
    source = InMemoryShadowVerdictSource(
        verdicts=[
            ShadowVerdictRecord(
                action_type_name="ops.publish-change-summary",
                observed_at=fresh,
                was_policy_escape=False,
                operator_reviewed=True,
                operator_agreed=True,
            )
        ]
    )
    client = _client(source, catalog)
    resp = client.get("/kpi/promotion-gates")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ready_count"] + body["blocked_count"] == len(catalog)
    # A single fresh reviewed verdict is not enough to promote anything.
    assert body["ready_count"] == 0
    assert body["blocked_count"] == len(catalog)
    change_row = next(
        row for row in body["rows"] if row["action_type_name"] == "ops.publish-change-summary"
    )
    assert change_row["sample_count"] == 1
    assert any("min_samples" in g for g in change_row["gaps"])


def test_action_type_filter_returns_only_one_row() -> None:
    catalog = _catalog()
    client = _client(InMemoryShadowVerdictSource(), catalog)
    resp = client.get(
        "/kpi/promotion-gates",
        params={"action_type": "ops.publish-change-summary"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["rows"]) == 1
    assert body["rows"][0]["action_type_name"] == "ops.publish-change-summary"


def test_action_type_filter_404_on_unknown_name() -> None:
    catalog = _catalog()
    client = _client(InMemoryShadowVerdictSource(), catalog)
    resp = client.get(
        "/kpi/promotion-gates",
        params={"action_type": "does-not-exist"},
    )
    assert resp.status_code == 404


def test_window_days_validated() -> None:
    catalog = _catalog()
    client = _client(InMemoryShadowVerdictSource(), catalog)
    assert client.get("/kpi/promotion-gates", params={"window_days": "0"}).status_code == 400
    assert client.get("/kpi/promotion-gates", params={"window_days": "abc"}).status_code == 400
    # Above the one-year cap is rejected so a caller cannot request an
    # unbounded window.
    assert client.get("/kpi/promotion-gates", params={"window_days": "366"}).status_code == 400
    # The one-year boundary itself is accepted.
    assert client.get("/kpi/promotion-gates", params={"window_days": "365"}).status_code == 200


def test_action_type_filter_length_capped() -> None:
    catalog = _catalog()
    client = _client(InMemoryShadowVerdictSource(), catalog)
    resp = client.get(
        "/kpi/promotion-gates",
        params={"action_type": "x" * 257},
    )
    assert resp.status_code == 400


def test_route_absent_when_source_not_configured() -> None:
    catalog = _catalog()
    # No source -> route not registered.
    auth = build_authenticator(verifier=lambda t: {"oid": "u"}, resolver=lambda claims: None)
    app = build_app(
        authenticator=auth,
        read_model=InMemoryConsoleReadModel(),
        config=ReadApiConfig(
            dev_mode=True,
            promotion_gate_action_types=tuple(catalog),
            promotion_gate_source=None,
        ),
    )
    client = TestClient(app)
    assert client.get("/kpi/promotion-gates").status_code == 404


def test_route_is_get_only() -> None:
    catalog = _catalog()
    client = _client(InMemoryShadowVerdictSource(), catalog)
    resp = client.post("/kpi/promotion-gates")
    assert resp.status_code == 405
