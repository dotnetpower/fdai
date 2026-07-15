"""Tests for the dev-mode entrypoint at :mod:`fdai.delivery.read_api.dev.local`."""

from __future__ import annotations

import time

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from fdai.core.rbac.resolver import Principal
from fdai.core.rbac.roles import Role
from fdai.delivery.read_api.dev import local as _local
from fdai.delivery.read_api.dev.azure_cli_identity import LocalAzureCliIdentity

_DEV_ENV = "FDAI_READ_API_DEV_MODE"
_LOCAL_ENTRA_ENV = "FDAI_READ_API_LOCAL_ENTRA"
_LOCAL_AZURE_CLI_ENV = "FDAI_READ_API_LOCAL_AZURE_CLI"


class TestLocalEntrypoint:
    def test_refuses_without_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(_DEV_ENV, raising=False)
        monkeypatch.delenv(_LOCAL_ENTRA_ENV, raising=False)
        monkeypatch.delenv(_LOCAL_AZURE_CLI_ENV, raising=False)
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

    def test_wires_action_proposal_route(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(_DEV_ENV, "1")
        application = _local.app()
        with TestClient(application) as client:
            response = client.post(
                "/chat/action",
                json={
                    "prompt": "restart test-service-1",
                    "idempotency_key": "local-action-1",
                },
            )

            assert response.status_code == 200
            payload = response.json()
            assert payload["submitted"] is True
            assert payload["action_type"] == "ops.restart-service"

            thor = application.state.pantheon_runtime.agents["Thor"]
            deadline = time.monotonic() + 1.0
            while payload["correlation_id"] not in thor.action_runs and time.monotonic() < deadline:
                time.sleep(0.01)
            action_run = thor.action_runs[payload["correlation_id"]]
            assert action_run.state.value == "succeeded"
            assert action_run.shadow_mode is True
            assert action_run.outcome == "shadow_success"

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

    def test_vite_preview_origin_is_allowed_by_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(_DEV_ENV, "1")
        monkeypatch.delenv("FDAI_READ_API_CORS_ALLOW_ORIGINS", raising=False)
        client = TestClient(_local.app())

        response = client.get("/healthz", headers={"origin": "http://127.0.0.1:4173"})

        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:4173"

    def test_custom_console_origin_rejects_wildcard(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(_DEV_ENV, "1")
        monkeypatch.setenv("FDAI_READ_API_CORS_ALLOW_ORIGINS", "*")

        with pytest.raises(ValueError, match="explicit HTTP"):
            _local.app()


class TestLocalEntraLoginHarness:
    """`FDAI_READ_API_LOCAL_ENTRA=1` serves seed data behind REAL Entra auth."""

    def _enable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(_DEV_ENV, raising=False)
        monkeypatch.delenv(_LOCAL_AZURE_CLI_ENV, raising=False)
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


class TestLocalAzureCliHarness:
    def test_builds_with_resolved_cli_identity(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(_DEV_ENV, raising=False)
        monkeypatch.delenv(_LOCAL_ENTRA_ENV, raising=False)
        monkeypatch.setenv(_LOCAL_AZURE_CLI_ENV, "1")
        identity = LocalAzureCliIdentity(
            principal=Principal(
                oid="cli-user",
                roles=frozenset({Role.CONTRIBUTOR}),
            ),
            username="user@example.com",
        )
        monkeypatch.setattr(_local, "resolve_azure_cli_identity", lambda: identity)

        client = TestClient(_local.app())

        assert client.get("/audit").status_code == 200
        assert client.get("/local-auth/me").json()["source"] == "azure-cli"
