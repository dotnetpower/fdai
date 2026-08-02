"""Integration tests for ``GET /audit/{correlation_id}/bitemporal``."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from starlette.testclient import TestClient

from fdai.delivery.operator_api.auth import build_authenticator
from fdai.delivery.operator_api.main import OperatorApiConfig, build_app
from fdai.delivery.operator_api.read_model import InMemoryConsoleReadModel
from fdai.delivery.operator_api.routes.rule_fire_trace_reader import ConsoleReadModelTraceReader


@pytest.fixture(autouse=True)
def _dev_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FDAI_OPERATOR_API_DEV_MODE", "1")


def _seed_state(model: InMemoryConsoleReadModel, correlation: str) -> None:
    """Seed two state changes: tier S1 (2026-01-01), tier S2 (2026-03-01)."""
    model.record_audit_entry(
        {
            "correlation_id": correlation,
            "recorded_at": datetime(2026, 1, 2, tzinfo=UTC).isoformat(),
            "state": {"tier": "S1"},
            "effective_at": datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
        },
        action_kind="state.change",
    )
    model.record_audit_entry(
        {
            "correlation_id": correlation,
            "recorded_at": datetime(2026, 3, 2, tzinfo=UTC).isoformat(),
            "state": {"tier": "S2", "region": "us"},
            "effective_at": datetime(2026, 3, 1, tzinfo=UTC).isoformat(),
        },
        action_kind="state.change",
    )


def _client(model: InMemoryConsoleReadModel) -> TestClient:
    auth = build_authenticator(verifier=lambda t: {"oid": "u"}, resolver=lambda claims: None)
    app = build_app(
        authenticator=auth,
        read_model=model,
        config=OperatorApiConfig(
            dev_mode=True,
            bitemporal_reader=ConsoleReadModelTraceReader(model),
        ),
    )
    return TestClient(app)


def test_bitemporal_route_reconstructs_state_at_as_of() -> None:
    model = InMemoryConsoleReadModel()
    _seed_state(model, "corr-1")
    with _client(model) as client:
        resp = client.get(
            "/audit/corr-1/bitemporal",
            params={
                "resource_id": "vm-1",
                "as_of": "2026-04-01T00:00:00+00:00",
            },
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["state"] == {"tier": "S2", "region": "us"}
    assert set(body["source_seqs"]) == {1, 2}


def test_bitemporal_route_400_on_missing_params() -> None:
    model = InMemoryConsoleReadModel()
    _seed_state(model, "corr-1")
    with _client(model) as client:
        # missing resource_id
        r1 = client.get("/audit/corr-1/bitemporal", params={"as_of": "2026-06-01T00:00:00Z"})
        assert r1.status_code == 400
        # missing as_of
        r2 = client.get("/audit/corr-1/bitemporal", params={"resource_id": "vm-1"})
        assert r2.status_code == 400


def test_bitemporal_route_400_on_bad_timestamp() -> None:
    model = InMemoryConsoleReadModel()
    _seed_state(model, "corr-1")
    with _client(model) as client:
        resp = client.get(
            "/audit/corr-1/bitemporal",
            params={"resource_id": "vm-1", "as_of": "not-a-ts"},
        )
    assert resp.status_code == 400


def test_bitemporal_route_400_on_oversized_ids() -> None:
    model = InMemoryConsoleReadModel()
    _seed_state(model, "corr-1")
    with _client(model) as client:
        # correlation_id over the 256-char cap.
        r1 = client.get(
            f"/audit/{'c' * 257}/bitemporal",
            params={"resource_id": "vm-1", "as_of": "2026-06-01T00:00:00Z"},
        )
        assert r1.status_code == 400
        # resource_id over the 512-char cap.
        r2 = client.get(
            "/audit/corr-1/bitemporal",
            params={"resource_id": "v" * 513, "as_of": "2026-06-01T00:00:00Z"},
        )
        assert r2.status_code == 400


def test_bitemporal_route_400_on_bad_effective_timestamp() -> None:
    model = InMemoryConsoleReadModel()
    _seed_state(model, "corr-1")
    with _client(model) as client:
        resp = client.get(
            "/audit/corr-1/bitemporal",
            params={
                "resource_id": "vm-1",
                "as_of": "2026-06-01T00:00:00Z",
                "effective": "not-a-ts",
            },
        )
    assert resp.status_code == 400


def test_parse_ts_returns_none_for_empty_input() -> None:
    from fdai.delivery.operator_api.routes.bitemporal import _parse_ts

    # Defensive falsy-guard branch: an empty / None raw parses to None
    # rather than raising, so a caller can treat "absent" uniformly.
    assert _parse_ts(None) is None
    assert _parse_ts("") is None
    # A valid RFC 3339 string still round-trips.
    assert _parse_ts("2026-06-01T00:00:00Z") == datetime(2026, 6, 1, tzinfo=UTC)


def test_bitemporal_route_400_when_effective_after_as_of() -> None:
    model = InMemoryConsoleReadModel()
    _seed_state(model, "corr-1")
    with _client(model) as client:
        resp = client.get(
            "/audit/corr-1/bitemporal",
            params={
                "resource_id": "vm-1",
                "as_of": "2026-01-01T00:00:00Z",
                "effective": "2026-06-01T00:00:00Z",
            },
        )
    assert resp.status_code == 400


def test_bitemporal_route_404_when_correlation_unknown() -> None:
    model = InMemoryConsoleReadModel()
    with _client(model) as client:
        resp = client.get(
            "/audit/nope/bitemporal",
            params={"resource_id": "vm-1", "as_of": "2026-06-01T00:00:00Z"},
        )
    assert resp.status_code == 404


def test_bitemporal_route_absent_when_reader_not_configured() -> None:
    auth = build_authenticator(verifier=lambda t: {"oid": "u"}, resolver=lambda claims: None)
    app = build_app(
        authenticator=auth,
        read_model=InMemoryConsoleReadModel(),
        config=OperatorApiConfig(dev_mode=True),
    )
    with TestClient(app) as client:
        resp = client.get(
            "/audit/x/bitemporal", params={"resource_id": "y", "as_of": "2026-01-01T00:00:00Z"}
        )
    assert resp.status_code == 404
