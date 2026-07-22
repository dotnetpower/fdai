"""Tests for the dev-mode entrypoint at :mod:`fdai.delivery.read_api.dev.local`."""

from __future__ import annotations

import asyncio
import base64
import json
import time
from pathlib import Path

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from fdai.core.control_loop import ControlLoopOutcome
from fdai.core.rbac.resolver import Principal
from fdai.core.rbac.roles import Role
from fdai.delivery.read_api.dev import factory as _local_factory
from fdai.delivery.read_api.dev import local as _local
from fdai.delivery.read_api.dev.azure_cli_identity import LocalAzureCliIdentity
from fdai.delivery.read_api.dev.config import (
    entra_application_id_from_env,
    local_entra_verifier_environment,
)
from fdai.delivery.read_api.dev.runtime_wiring import build_interactive_pantheon_wiring
from fdai.delivery.read_api.postgres_read_model import PostgresConsoleReadModel
from fdai.delivery.read_api.read_model import InMemoryConsoleReadModel
from fdai.delivery.read_api.streaming.agent_activity_stream import (
    DEFAULT_CHANNEL,
    SseAgentActivityPublisher,
    runtime_agent_state_snapshot,
)
from fdai.delivery.read_api.streaming.pantheon_activity_observer import (
    PantheonActivityObserver,
)
from fdai.shared.providers.local import LocalSseSink
from fdai.shared.providers.testing.live_event_bus import LiveInMemoryEventBus

_DEV_ENV = "FDAI_READ_API_DEV_MODE"
_LOCAL_ENTRA_ENV = "FDAI_READ_API_LOCAL_ENTRA"
_LOCAL_AZURE_CLI_ENV = "FDAI_READ_API_LOCAL_AZURE_CLI"
_LOCAL_SCENARIO_REPLAY_ENV = "FDAI_LOCAL_SCENARIO_REPLAY"
_LOCAL_AZURE_DISCOVERY_ENV = "FDAI_LOCAL_AZURE_DISCOVERY"
_LOCAL_AZURE_SUBSCRIPTION_ENV = "FDAI_LOCAL_AZURE_SUBSCRIPTION_ID"
_START_PANTHEON_ENV = "FDAI_START_PANTHEON"
_KAFKA_BOOTSTRAP_ENV = "FDAI_KAFKA_BOOTSTRAP_SERVERS"
_KAFKA_EVENT_TOPIC_ENV = "KAFKA_TOPIC_EVENTS"
_DATABASE_URL_ENV = "FDAI_DATABASE_URL"
_EMBED_PANTHEON_ENV = "FDAI_READ_API_EMBED_PANTHEON"
_AUTHORITATIVE_READ_API_ENV = "FDAI_AUTHORITATIVE_READ_API_BASE_URL"
_REPO_ROOT = Path(__file__).resolve().parents[3]


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


def test_interactive_pantheon_wires_all_agents_without_fixture_executors() -> None:
    wiring = build_interactive_pantheon_wiring(
        event_bus=LiveInMemoryEventBus(),
        event_topic="aw.events",
        read_model=InMemoryConsoleReadModel(),
        action_types=(),
    )

    assert len(wiring.pantheon_runtime.agents) == 15
    assert wiring.pantheon_runtime.enforce is False
    assert wiring.console_action is None
    assert wiring.python_tasks is None
    assert wiring.operator_runtime is None


async def test_interactive_local_event_streams_huginn_and_heimdall_activity() -> None:
    event_bus = LiveInMemoryEventBus()
    sink = LocalSseSink()
    observer = PantheonActivityObserver(
        publisher=SseAgentActivityPublisher(sink=sink, channel=DEFAULT_CHANNEL)
    )
    wiring = build_interactive_pantheon_wiring(
        event_bus=event_bus,
        event_topic="aw.events",
        read_model=InMemoryConsoleReadModel(),
        action_types=(),
        handler_observer=observer,
    )
    frames: list[dict[str, object]] = []

    async def collect() -> None:
        async for event in sink.subscribe(DEFAULT_CHANNEL):
            frames.append(json.loads(event.data))
            completed = {
                str(frame["agent"])
                for frame in frames
                if frame["agent"] in {"Huginn", "Heimdall"}
                and frame["state"] == "watching"
                and str(frame["detail"]).startswith("Processed ")
            }
            if completed == {"Huginn", "Heimdall"}:
                return

    collector = asyncio.create_task(collect())
    while sink.subscriber_count(DEFAULT_CHANNEL) == 0:
        await asyncio.sleep(0)
    await wiring.start_pantheon_runtime()
    await event_bus.publish(
        "aw.events",
        "event-local-1",
        {
            "event_id": "event-local-1",
            "idempotency_key": "event-local-1",
            "correlation_id": "corr-local-live",
            "resource_id": "resource-local-1",
            "resource_type": "compute.vm",
            "event_type": "resource.changed",
        },
    )
    try:
        await asyncio.wait_for(collector, timeout=2.0)
    finally:
        collector.cancel()
        await asyncio.gather(collector, return_exceptions=True)
        await wiring.stop_pantheon_runtime()

    by_agent = {
        agent: [frame["state"] for frame in frames if frame["agent"] == agent]
        for agent in ("Huginn", "Heimdall")
    }
    assert by_agent == {
        "Huginn": ["collecting", "watching"],
        "Heimdall": ["analyzing", "watching"],
    }
    active_frames = [frame for frame in frames if frame["state"] not in {"idle", "watching"}]
    assert all(frame["correlation_id"] == "corr-local-live" for frame in active_frames)
    assert all(frame["source"] == "runtime-observed" for frame in frames)


def test_full_stack_launch_uses_entra_rbac_without_fixture_or_cli_principal() -> None:
    launch = json.loads((_REPO_ROOT / ".vscode" / "launch.json").read_text(encoding="utf-8"))
    settings = json.loads((_REPO_ROOT / ".vscode" / "settings.json").read_text(encoding="utf-8"))
    configs = {item["name"]: item for item in launch["configurations"]}
    api_env = configs["Console Web: Read API"]["env"]
    frontend_env = configs["Console Web: Frontend"]["env"]
    compound = next(
        item for item in launch["compounds"] if item["name"] == "Console Web: Full Stack"
    )

    assert api_env["FDAI_READ_API_LOCAL_ENTRA"] == "1"
    assert api_env["FDAI_READ_API_DEV_MODE"] == "0"
    assert api_env["FDAI_READ_API_LOCAL_AZURE_CLI"] == "0"
    assert api_env[_EMBED_PANTHEON_ENV] == "0"
    assert _START_PANTHEON_ENV not in api_env
    assert configs["Console Web: Read API"]["preLaunchTask"] == "console: prepare full stack"
    assert configs["Console Web: Read API"]["envFile"].endswith("/.fdai/local-runtime.env")
    assert frontend_env["VITE_DEV_MODE"] == "0"
    assert frontend_env["VITE_LOCAL_AZURE_CLI_AUTH"] == "0"
    assert settings["liveServer.settings.host"] == "127.0.0.1"
    assert settings["liveServer.settings.port"] == 5373
    assert configs["Console Web: Frontend"]["command"].endswith("--port 5273 --strictPort")
    read_api_args = configs["Console Web: Read API"]["args"]
    ingestion_args = configs["Console Web: Ingestion Gateway"]["args"]
    assert read_api_args[read_api_args.index("--port") + 1] == "8010"
    assert ingestion_args[ingestion_args.index("--port") + 1] == "8011"
    assert compound["configurations"] == [
        "Console Web: Core Runtime",
        "Console Web: Read API",
        "Console Web: Frontend",
    ]


def test_design_mock_launch_uses_fixed_static_server_port() -> None:
    launch = json.loads((_REPO_ROOT / ".vscode" / "launch.json").read_text(encoding="utf-8"))
    configs = {item["name"]: item for item in launch["configurations"]}
    mock_site = configs["Design Mocks: Static Site"]

    assert mock_site["command"] == "python3 -u -m http.server 5373 --bind 127.0.0.1"
    assert mock_site["cwd"] == "${workspaceFolder}"
    assert mock_site["serverReadyAction"] == {
        "pattern": r"Serving HTTP on 127\.0\.0\.1 port 5373",
        "uriFormat": "http://127.0.0.1:5373",
        "action": "debugWithChrome",
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
        monkeypatch.delenv("AZURE_SUBSCRIPTION_ID", raising=False)

        provider = _local._build_inventory_graph_provider()

        assert isinstance(provider, AzureCliInventoryGraphProvider)
        assert provider.cache_path is None

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
        assert provider.inventory.subscription_id == "00000000-0000-0000-0000-000000000000"
        assert provider.cache_path is not None
        assert provider.cache_identity is not None
        assert provider.cache_identity in provider.cache_path.name
        assert provider.invalidation_path is not None
        assert provider.cache_identity in provider.invalidation_path.name

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
        assert "/skills" in {route.path for route in application.routes}
        assert application.state.skill_disclosure.inspect()["installed_count"] == 0
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
            action_run = None
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                action_run = thor.action_runs.get(payload["correlation_id"])
                if action_run is not None and action_run.state.value == "succeeded":
                    break
                time.sleep(0.01)
            assert action_run is not None
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
        monkeypatch.delenv(_KAFKA_BOOTSTRAP_ENV, raising=False)
        monkeypatch.delenv(_KAFKA_EVENT_TOPIC_ENV, raising=False)
        monkeypatch.delenv(_DATABASE_URL_ENV, raising=False)
        monkeypatch.delenv(_AUTHORITATIVE_READ_API_ENV, raising=False)
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
        monkeypatch.delenv(_START_PANTHEON_ENV, raising=False)

        application = _local.app()

        assert isinstance(application, Starlette)
        assert "/iam" in {route.path for route in application.routes}
        assert "/agents/stream" in {route.path for route in application.routes}
        assert application.state.pantheon_runtime is not None
        assert len(application.state.pantheon_runtime.agents) == 15
        assert application.state.pantheon_runtime.bridge.handler_observer is not None

    def test_explicit_pantheon_disable_omits_runtime_and_stream(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._enable(monkeypatch)
        monkeypatch.setenv(_START_PANTHEON_ENV, "0")
        captured: dict[str, object] = {}
        original = _local_factory.build_local_data_sources

        def capture_sources(**kwargs: object):  # type: ignore[no-untyped-def]
            captured.update(kwargs)
            return original(**kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(_local_factory, "build_local_data_sources", capture_sources)

        application = _local.app()
        paths = {route.path for route in application.routes}

        assert application.state.pantheon_runtime is None
        assert "/agents/stream" not in paths
        assert "/live/stream" not in paths
        assert captured["runtime_streams_configured"] is False

    def test_full_stack_core_owns_pantheon_while_read_api_relays_streams(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._enable(monkeypatch)
        monkeypatch.delenv(_START_PANTHEON_ENV, raising=False)
        monkeypatch.setenv(_EMBED_PANTHEON_ENV, "0")
        monkeypatch.setenv(
            _KAFKA_BOOTSTRAP_ENV,
            "example.servicebus.windows.net:9093",
        )
        monkeypatch.setenv(_KAFKA_EVENT_TOPIC_ENV, "aw.change.events")
        captured: dict[str, object] = {}
        original = _local_factory.build_local_data_sources

        def capture_sources(**kwargs: object):  # type: ignore[no-untyped-def]
            captured.update(kwargs)
            return original(**kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(_local_factory, "build_local_data_sources", capture_sources)

        application = _local.app()
        paths = {route.path for route in application.routes}

        assert application.state.pantheon_runtime is None
        assert "/agents/stream" in paths
        assert "/live/stream" in paths
        assert captured["runtime_streams_configured"] is True

    def test_local_transport_rejects_enforce_allowlist(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._enable(monkeypatch)
        monkeypatch.delenv(_START_PANTHEON_ENV, raising=False)
        monkeypatch.setenv("FDAI_WORKFLOW_ENFORCE_ALLOWLIST", "architecture-review")

        with pytest.raises(RuntimeError, match="requires local Azure event transport"):
            _local.app()

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
        monkeypatch.delenv("VITE_MSAL_TENANT_ID", raising=False)
        monkeypatch.delenv("VITE_MSAL_API_SCOPE", raising=False)
        with pytest.raises(ValueError, match="FDAI_ENTRA_TENANT_ID"):
            _local.app(test_fixtures=True)


class TestLocalAzureCliHarness:
    @pytest.fixture(autouse=True)
    def _without_full_stack_runtime(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(_KAFKA_BOOTSTRAP_ENV, raising=False)
        monkeypatch.delenv(_KAFKA_EVENT_TOPIC_ENV, raising=False)
        monkeypatch.delenv(_DATABASE_URL_ENV, raising=False)

    def test_authoritative_proxy_is_declared_without_synthetic_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(_DEV_ENV, raising=False)
        monkeypatch.delenv(_LOCAL_ENTRA_ENV, raising=False)
        monkeypatch.setenv(_LOCAL_AZURE_CLI_ENV, "1")
        monkeypatch.setenv(
            _AUTHORITATIVE_READ_API_ENV,
            "https://read.example.test",
        )
        monkeypatch.setattr(
            _local,
            "resolve_azure_cli_identity",
            lambda: LocalAzureCliIdentity(
                principal=Principal(
                    oid="cli-user",
                    roles=frozenset({Role.CONTRIBUTOR}),
                ),
                username="user@example.com",
            ),
        )

        with TestClient(_local.app()) as client:
            sources = {
                item["key"]: item for item in client.get("/system/data-sources").json()["sources"]
            }

        assert sources["operational-state"]["source"] == "remote-read-api"
        assert sources["operational-state"]["authoritative"] is True
        assert sources["operational-state"]["durable"] is True
        assert sources["overview-measurement"]["availability"] == "unknown"

    def test_rejects_local_postgresql_with_authoritative_proxy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(_DEV_ENV, raising=False)
        monkeypatch.delenv(_LOCAL_ENTRA_ENV, raising=False)
        monkeypatch.setenv(_LOCAL_AZURE_CLI_ENV, "1")
        monkeypatch.setenv(_DATABASE_URL_ENV, "postgresql://example.invalid/fdai")
        monkeypatch.setenv(_AUTHORITATIVE_READ_API_ENV, "https://read.example.test")

        with pytest.raises(RuntimeError, match="MUST NOT be configured together"):
            _local.app()

    def test_local_postgresql_profile_registers_durable_read_surfaces(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(_DEV_ENV, raising=False)
        monkeypatch.delenv(_LOCAL_ENTRA_ENV, raising=False)
        monkeypatch.setenv(_LOCAL_AZURE_CLI_ENV, "1")
        monkeypatch.setenv(_DATABASE_URL_ENV, "postgresql://example.invalid/fdai")
        monkeypatch.setenv(_EMBED_PANTHEON_ENV, "0")
        monkeypatch.setenv("AZURE_SUBSCRIPTION_ID", "subscription-a")
        monkeypatch.setenv("AZURE_RESOURCE_GROUP", "resource-group-a")
        monkeypatch.setattr(
            _local,
            "resolve_azure_cli_identity",
            lambda: LocalAzureCliIdentity(
                principal=Principal(
                    oid="cli-user",
                    roles=frozenset({Role.CONTRIBUTOR}),
                ),
                username="user@example.com",
            ),
        )

        application = _local.app()
        paths = {route.path for route in application.routes}

        assert {
            "/automation-blueprints",
            "/context-selection-comparisons",
            "/conversation-delivery",
            "/finops",
            "/kpi/autonomy",
            "/kpi/promotion-gates",
            "/operator-memory",
            "/reports",
            "/scheduler-runs",
            "/scope",
        } <= paths
        assert application.state.pantheon_runtime is None

    def test_local_postgresql_profile_fails_startup_when_database_is_unreachable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(_DEV_ENV, raising=False)
        monkeypatch.delenv(_LOCAL_ENTRA_ENV, raising=False)
        monkeypatch.setenv(_LOCAL_AZURE_CLI_ENV, "1")
        monkeypatch.setenv(_DATABASE_URL_ENV, "postgresql://example.invalid/fdai")
        monkeypatch.setenv(_EMBED_PANTHEON_ENV, "0")
        monkeypatch.setattr(
            _local,
            "resolve_azure_cli_identity",
            lambda: LocalAzureCliIdentity(
                principal=Principal(
                    oid="cli-user",
                    roles=frozenset({Role.CONTRIBUTOR}),
                ),
                username="user@example.com",
            ),
        )

        async def fail_connection(_read_model: PostgresConsoleReadModel) -> None:
            raise RuntimeError("PostgreSQL startup verification failed")

        monkeypatch.setattr(PostgresConsoleReadModel, "verify_connection", fail_connection)

        with pytest.raises(RuntimeError, match="startup verification failed"):
            with TestClient(_local.app()):
                pass

    def test_default_local_transport_starts_all_pantheon_consumers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(_DEV_ENV, raising=False)
        monkeypatch.delenv(_LOCAL_ENTRA_ENV, raising=False)
        monkeypatch.setenv(_LOCAL_AZURE_CLI_ENV, "1")
        monkeypatch.delenv(_START_PANTHEON_ENV, raising=False)
        identity = LocalAzureCliIdentity(
            principal=Principal(
                oid="cli-user",
                roles=frozenset({Role.CONTRIBUTOR}),
            ),
            username="user@example.com",
        )
        monkeypatch.setattr(_local, "resolve_azure_cli_identity", lambda: identity)

        with TestClient(_local.app()) as client:
            runtime = client.app.state.pantheon_runtime
            paths = {route.path for route in client.app.routes}

            assert runtime is not None
            assert len(runtime.agents) == 15
            assert runtime.health()["consumers_live"] > 0
            assert len(runtime_agent_state_snapshot(runtime.health())) == 15
            assert "/agents/stream" in paths

    def test_builds_with_resolved_cli_identity(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(_DEV_ENV, raising=False)
        monkeypatch.delenv(_LOCAL_ENTRA_ENV, raising=False)
        monkeypatch.delenv(_AUTHORITATIVE_READ_API_ENV, raising=False)
        monkeypatch.setenv(_LOCAL_AZURE_CLI_ENV, "1")
        monkeypatch.delenv(_START_PANTHEON_ENV, raising=False)
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
        assert "/capabilities" in paths
        assert "/onboarding" in paths
        assert "/kpi/llm-cost" in paths
        assert "/system/data-sources" in paths
        assert "/workflows/run" in paths
        assert "/views/process" in paths
        assert "/arb/status" in paths
        assert "/agents/stream" in paths
        assert "/live/stream" in paths
        assert "/provision/stream" not in paths
        assert "/simulate/blast-radius" not in paths
        assert "/scope" not in paths
        assert "/promotion-gates" not in paths
        assert "/stewardship" not in paths
        sources = {
            item["key"]: item for item in client.get("/system/data-sources").json()["sources"]
        }
        assert sources["operational-state"]["availability"] == "unavailable"
        assert sources["operational-state"]["authoritative"] is False
        assert sources["catalogs"]["availability"] == "available"
        assert sources["local-metering"]["durable"] is False
        assert client.get("/local-auth/me").json()["source"] == "azure-cli"

        started = client.post(
            "/workflows/run",
            json={
                "workflow": "architecture-review",
                "target_resource_id": "fdai-control-plane",
                "trigger_ts": "2026-07-20T00:00:00Z",
                "mode": "shadow",
            },
        )
        assert started.status_code == 200
        assert started.json()["process"]["status"] == "waiting"
        status = client.get("/arb/status").json()
        assert status["contract"]["healthy"] is True
        assert status["production"]["ready"] is False
        assert status["runtime"]["health"] == "healthy"
        assert status["runtime"]["next_action"] == "publish evidence.updated"
