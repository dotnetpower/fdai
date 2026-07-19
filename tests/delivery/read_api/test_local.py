"""Tests for the dev-mode entrypoint at :mod:`fdai.delivery.read_api.dev.local`."""

from __future__ import annotations

import base64
import json
import time

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from fdai.core.control_loop import ControlLoopOutcome
from fdai.core.rbac.resolver import Principal
from fdai.core.rbac.roles import Role
from fdai.delivery.read_api.dev import local as _local
from fdai.delivery.read_api.dev.azure_cli_identity import LocalAzureCliIdentity
from fdai.delivery.read_api.dev.config import (
    entra_application_id_from_env,
    local_entra_verifier_environment,
)

_DEV_ENV = "FDAI_READ_API_DEV_MODE"
_LOCAL_ENTRA_ENV = "FDAI_READ_API_LOCAL_ENTRA"
_LOCAL_AZURE_CLI_ENV = "FDAI_READ_API_LOCAL_AZURE_CLI"
_LOCAL_SCENARIO_REPLAY_ENV = "FDAI_LOCAL_SCENARIO_REPLAY"
_LOCAL_AZURE_DISCOVERY_ENV = "FDAI_LOCAL_AZURE_DISCOVERY"
_LOCAL_AZURE_SUBSCRIPTION_ENV = "FDAI_LOCAL_AZURE_SUBSCRIPTION_ID"


def _unsigned_token(claims: dict[str, object]) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    return f"{header}.{payload}.local"


def _python_task() -> dict[str, object]:
    return {
        "task_id": "gpu.local-health",
        "version": "1.0.0",
        "entrypoint": "main.py",
        "files": [{"path": "main.py", "content": "print('ok')\n"}],
        "required_modules": [],
        "capabilities": [],
        "timeout_seconds": 60,
        "python_executable": "/usr/bin/python3",
    }


class TestLocalEntrypoint:
    def test_maps_local_vite_msal_settings_to_read_api_contract(self) -> None:
        env = local_entra_verifier_environment(
            {
                "VITE_MSAL_TENANT_ID": "tenant-id",
                "VITE_MSAL_API_SCOPE": "api://api-app-id/access",
            }
        )

        assert env["FDAI_ENTRA_TENANT_ID"] == "tenant-id"
        assert env["FDAI_API_AUDIENCE"] == "api-app-id"
        assert entra_application_id_from_env(env) == "api-app-id"

    def test_inventory_graph_defaults_to_azure_cli(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from fdai.delivery.read_api.dev.azure_inventory_graph import (
            AzureCliInventoryGraphProvider,
        )

        monkeypatch.delenv(_LOCAL_AZURE_DISCOVERY_ENV, raising=False)
        monkeypatch.delenv(_LOCAL_AZURE_SUBSCRIPTION_ENV, raising=False)

        provider = _local._build_inventory_graph_provider()

        assert isinstance(provider, AzureCliInventoryGraphProvider)

    def test_local_azure_discovery_rejects_synthetic_opt_out(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(_LOCAL_AZURE_DISCOVERY_ENV, "0")

        with pytest.raises(ValueError, match="MUST use Azure"):
            _local._build_inventory_graph_provider()

    def test_local_azure_discovery_builds_cli_provider(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from fdai.delivery.read_api.dev.azure_inventory_graph import (
            AzureCliInventoryGraphProvider,
        )

        monkeypatch.setenv(_LOCAL_AZURE_DISCOVERY_ENV, "1")
        monkeypatch.setenv(
            _LOCAL_AZURE_SUBSCRIPTION_ENV,
            "00000000-0000-0000-0000-000000000000",
        )
        provider = _local._build_inventory_graph_provider()
        assert isinstance(provider, AzureCliInventoryGraphProvider)

    def test_agent_stream_uses_real_runtime_relay_by_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(_LOCAL_SCENARIO_REPLAY_ENV, raising=False)
        monkeypatch.delenv("FDAI_AGENTS_REAL_RELAY", raising=False)

        live, agents = _local._build_agent_streams()

        assert live.sink is not None
        assert live.emitter_factory is None
        assert live.stage_publisher_wrapper is not None
        assert agents.sink is not None
        assert agents.emitter_factory is None

    def test_agent_stream_uses_control_loop_relay_when_replay_enabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(_LOCAL_SCENARIO_REPLAY_ENV, "1")
        monkeypatch.delenv("FDAI_AGENTS_REAL_RELAY", raising=False)

        live, agents = _local._build_agent_streams()

        assert live.emitter_factory is not None
        assert agents.sink is not None
        assert agents.emitter_factory is None

    def test_agent_stream_ignores_removed_synthetic_demo_switch(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(_LOCAL_SCENARIO_REPLAY_ENV, "1")
        monkeypatch.setenv("FDAI_AGENTS_REAL_RELAY", "0")

        live, agents = _local._build_agent_streams()

        assert live.emitter_factory is not None
        assert agents.sink is not None
        assert agents.emitter_factory is None

    def test_refuses_without_interactive_auth_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(_DEV_ENV, raising=False)
        monkeypatch.delenv(_LOCAL_ENTRA_ENV, raising=False)
        monkeypatch.delenv(_LOCAL_AZURE_CLI_ENV, raising=False)
        with pytest.raises(RuntimeError, match="interactive local read API"):
            _local.app()

    def test_fixture_mode_is_not_available_to_interactive_processes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(_DEV_ENV, "1")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

        with pytest.raises(RuntimeError, match="pytest-only"):
            _local.app(test_fixtures=True)

    def test_builds_and_serves_seeded_data(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(_DEV_ENV, "1")
        application = _local.app(test_fixtures=True)
        assert isinstance(application, Starlette)
        client = TestClient(application)
        assert "/provision/stream" in {route.path for route in application.routes}
        # Seed produced at least one audit row + one HIL entry.
        audit = client.get("/audit").json()
        assert len(audit["items"]) >= 1
        hil = client.get("/hil-queue").json()
        assert len(hil["items"]) >= 1
        assert hil["detail_level"] == "full"
        assert hil["items"][0]["stop_condition"]
        assert hil["items"][0]["rollback_kind"] == "pr_revert"
        assert hil["items"][0]["blast_radius_count"] == 12
        assert hil["items"][0]["citing_rule_ids"] == ["network.nsg.no-inbound-any-ssh"]
        assert hil["items"][0]["action_kind"] == "remediate.restrict-network-access"
        assert hil["items"][0]["target_resource_ref"] == "web-api"
        kpi = client.get("/kpi").json()
        assert kpi["event_count"] >= 1
        assert kpi["hil_pending"] >= 1
        processes = client.get("/views/process").json()
        assert processes["items"][0]["id"] == "dev-architecture-review"
        review = client.get("/views/process/dev-architecture-review").json()
        assert review["id"] == "architecture-review"
        assert review["process"]["status"] == "waiting"
        assert review["regions"][0]["report"]["id"] == "architecture-review-process"

    def test_dev_mode_honors_owner_role_from_present_bearer_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(_DEV_ENV, "1")
        client = TestClient(_local.app(test_fixtures=True))
        token = _unsigned_token({"oid": "owner-1", "roles": ["Owner"]})

        anonymous = client.get("/iam").json()["principal"]
        owner = client.get(
            "/iam",
            headers={"authorization": f"Bearer {token}"},
        ).json()["principal"]

        assert anonymous["roles"] == ["Contributor"]
        assert owner["oid"] == "owner-1"
        assert owner["roles"] == ["Owner"]
        assert "manage-group-membership" in owner["capabilities"]
        metric_report = client.get(
            "/reports/metric-explorer/render",
            params={
                "metric_name": "fdai.audit.entries.count",
                "group_by": "actor",
            },
        ).json()
        total = next(widget for widget in metric_report["widgets"] if widget["id"] == "total")
        trend = next(widget for widget in metric_report["widgets"] if widget["id"] == "trend")
        assert total["data"]["value"] == 34.0
        assert {series["label"] for series in trend["data"]["series"]} >= {
            "Huginn",
            "Forseti",
            "Thor",
        }

    def test_wires_action_proposal_route(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(_DEV_ENV, "1")
        application = _local.app(test_fixtures=True)
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

    def test_python_task_request_reaches_authoritative_hil(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(_DEV_ENV, "1")
        application = _local.app(test_fixtures=True)
        with TestClient(application) as client:
            staged = client.post("/python-tasks/stage", json=_python_task())
            assert staged.status_code == 200
            submitted = client.post(
                "/python-tasks/request-run",
                json={
                    "artifact_ref": staged.json()["artifact_ref"],
                    "target_resource_ref": "resource:compute/vm/gpu-worker",
                    "reason": "Run the local governed health task.",
                    "idempotency_key": "local-gpu-health-1",
                },
            )
            assert submitted.status_code == 202

            runtime = application.state.local_operator_runtime
            assert runtime is not None
            deadline = time.monotonic() + 1.0
            while not runtime.results and time.monotonic() < deadline:
                time.sleep(0.01)

            assert runtime.results[-1].outcome is ControlLoopOutcome.HIL
            assert len(runtime.hil_channel.sent) == 1

    async def test_builds_inside_running_event_loop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(_DEV_ENV, "1")
        application = _local.app(test_fixtures=True)
        assert isinstance(application, Starlette)

    def test_custom_console_origin_is_allowed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(_DEV_ENV, "1")
        monkeypatch.setenv("FDAI_READ_API_CORS_ALLOW_ORIGINS", "http://127.0.0.1:5178")
        client = TestClient(_local.app(test_fixtures=True))

        response = client.get("/healthz", headers={"origin": "http://127.0.0.1:5178"})

        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5178"

    def test_vite_preview_origin_is_allowed_by_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(_DEV_ENV, "1")
        monkeypatch.delenv("FDAI_READ_API_CORS_ALLOW_ORIGINS", raising=False)
        client = TestClient(_local.app(test_fixtures=True))

        response = client.get("/healthz", headers={"origin": "http://127.0.0.1:4173"})

        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:4173"

    def test_vite_development_origin_is_allowed_by_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(_DEV_ENV, "1")
        monkeypatch.delenv("FDAI_READ_API_CORS_ALLOW_ORIGINS", raising=False)
        client = TestClient(_local.app(test_fixtures=True))

        response = client.get("/healthz", headers={"origin": "http://127.0.0.1:5273"})

        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5273"

    def test_nonstandard_vite_origin_is_not_allowed_by_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(_DEV_ENV, "1")
        monkeypatch.delenv("FDAI_READ_API_CORS_ALLOW_ORIGINS", raising=False)
        client = TestClient(_local.app(test_fixtures=True))

        response = client.get("/healthz", headers={"origin": "http://127.0.0.1:5173"})

        assert response.status_code == 200
        assert "access-control-allow-origin" not in response.headers

    def test_custom_console_origin_rejects_wildcard(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(_DEV_ENV, "1")
        monkeypatch.setenv("FDAI_READ_API_CORS_ALLOW_ORIGINS", "*")

        with pytest.raises(ValueError, match="explicit HTTP"):
            _local.app(test_fixtures=True)


class TestLocalEntraLoginHarness:
    """Entra verification over Azure-backed local or isolated fixture data."""

    def _enable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(_DEV_ENV, raising=False)
        monkeypatch.delenv(_LOCAL_AZURE_CLI_ENV, raising=False)
        monkeypatch.setenv(_LOCAL_ENTRA_ENV, "1")
        monkeypatch.setenv("FDAI_ENTRA_TENANT_ID", "00000000-0000-0000-0000-000000000abc")
        monkeypatch.setenv("FDAI_API_AUDIENCE", "api://00000000-0000-0000-0000-000000000def")

    def test_builds_with_real_verifier(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._enable(monkeypatch)
        application = _local.app(test_fixtures=True)
        assert isinstance(application, Starlette)

    def test_builds_azure_backed_mode_without_test_fixtures(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._enable(monkeypatch)

        application = _local.app()

        assert isinstance(application, Starlette)
        assert "/iam" in {route.path for route in application.routes}

    def test_unauthenticated_request_is_401_not_dev_anon(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The whole point: auth is enforced (not bypassed to dev-anon), so a
        # request with no bearer token is rejected before any data is served.
        self._enable(monkeypatch)
        client = TestClient(_local.app(test_fixtures=True))
        assert client.get("/audit").status_code == 401
        assert client.get("/kpi").status_code == 401

    def test_missing_entra_env_fails_fast(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(_DEV_ENV, raising=False)
        monkeypatch.setenv(_LOCAL_ENTRA_ENV, "1")
        monkeypatch.delenv("FDAI_ENTRA_TENANT_ID", raising=False)
        monkeypatch.delenv("FDAI_API_AUDIENCE", raising=False)
        with pytest.raises(ValueError, match="FDAI_ENTRA_TENANT_ID"):
            _local.app(test_fixtures=True)


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

        assert client.get("/audit").json()["items"] == []
        assert client.get("/hil-queue").json()["items"] == []
        paths = {route.path for route in client.app.routes}
        assert "/inventory/graph" in paths
        assert "/models/settings" in paths
        assert "/agents/stream" not in paths
        assert "/live/stream" not in paths
        assert "/provision/stream" not in paths
        assert "/simulate/blast-radius" not in paths
        assert "/scope" not in paths
        assert "/promotion-gates" not in paths
        assert "/stewardship" not in paths
        assert client.get("/local-auth/me").json()["source"] == "azure-cli"
