"""Tests for the dev-mode entrypoint at :mod:`fdai.delivery.read_api.dev.local`."""

from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from fdai.delivery.read_api.dev import local as _local

_DEV_ENV = "FDAI_READ_API_DEV_MODE"
_LOCAL_ENTRA_ENV = "FDAI_READ_API_LOCAL_ENTRA"


class TestLocalEntrypoint:
    def test_refuses_without_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(_DEV_ENV, raising=False)
        monkeypatch.delenv(_LOCAL_ENTRA_ENV, raising=False)
        with pytest.raises(RuntimeError, match=_DEV_ENV):
            _local.app()

    def test_builds_and_serves_seeded_data(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(_DEV_ENV, "1")
        application = _local.app()
        assert isinstance(application, Starlette)
        client = TestClient(application)
        # Seed produced at least one audit row + one HIL entry.
        audit = client.get("/audit").json()
        assert len(audit["items"]) >= 1
        hil = client.get("/hil-queue").json()
        assert len(hil["items"]) >= 1
        kpi = client.get("/kpi").json()
        assert kpi["event_count"] >= 1
        assert kpi["hil_pending"] >= 1
        processes = client.get("/views/process").json()
        assert processes["items"][0]["id"] == "dev-architecture-review"
        review = client.get("/views/process/dev-architecture-review").json()
        assert review["id"] == "architecture-review"
        assert review["process"]["status"] == "waiting"
        assert review["regions"][0]["report"]["id"] == "architecture-review-process"

    async def test_builds_inside_running_event_loop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(_DEV_ENV, "1")
        application = _local.app()
        assert isinstance(application, Starlette)

    def test_custom_console_origin_is_allowed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(_DEV_ENV, "1")
        monkeypatch.setenv("FDAI_READ_API_CORS_ALLOW_ORIGINS", "http://127.0.0.1:5178")
        client = TestClient(_local.app())

        response = client.get("/healthz", headers={"origin": "http://127.0.0.1:5178"})

        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5178"

    def test_custom_console_origin_rejects_wildcard(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(_DEV_ENV, "1")
        monkeypatch.setenv("FDAI_READ_API_CORS_ALLOW_ORIGINS", "*")

        with pytest.raises(ValueError, match="explicit HTTP"):
            _local.app()


class TestLocalEntraLoginHarness:
    """`FDAI_READ_API_LOCAL_ENTRA=1` serves seed data behind REAL Entra auth."""

    def _enable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(_DEV_ENV, raising=False)
        monkeypatch.setenv(_LOCAL_ENTRA_ENV, "1")
        monkeypatch.setenv("FDAI_ENTRA_TENANT_ID", "00000000-0000-0000-0000-000000000abc")
        monkeypatch.setenv("FDAI_API_AUDIENCE", "api://00000000-0000-0000-0000-000000000def")

    def test_builds_with_real_verifier(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._enable(monkeypatch)
        application = _local.app()
        assert isinstance(application, Starlette)

    def test_unauthenticated_request_is_401_not_dev_anon(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The whole point: auth is enforced (not bypassed to dev-anon), so a
        # request with no bearer token is rejected before any data is served.
        self._enable(monkeypatch)
        client = TestClient(_local.app())
        assert client.get("/audit").status_code == 401
        assert client.get("/kpi").status_code == 401

    def test_missing_entra_env_fails_fast(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(_DEV_ENV, raising=False)
        monkeypatch.setenv(_LOCAL_ENTRA_ENV, "1")
        monkeypatch.delenv("FDAI_ENTRA_TENANT_ID", raising=False)
        monkeypatch.delenv("FDAI_API_AUDIENCE", raising=False)
        with pytest.raises(ValueError, match="FDAI_ENTRA_TENANT_ID"):
            _local.app()
