"""Production composition contract for the isolated Executor entry point."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import httpx
import pytest

import fdai.runtime.isolated_executor_cli as cli
from fdai.core.executor.lock import ResourceLockManager
from fdai.delivery.azure.event_bus import EventHubsKafkaBusConfig
from fdai.runtime.isolated_executor_cli import (
    IsolatedExecutorRuntimeConfig,
    build_isolated_executor_supervisor,
)
from fdai.shared.providers.testing import InMemoryEventBus, InMemoryStateStore


def _environment(**changes: str) -> dict[str, str]:
    values = {
        "RUNTIME_ENV": "staging",
        "FDAI_ISOLATED_EXECUTOR_DEPLOYED": "1",
        "KAFKA_BOOTSTRAP_SERVERS": "example.servicebus.windows.net:9093",
        "KAFKA_TOPIC_DLQ_SUFFIX": ".dlq",
        "FDAI_STATE_STORE_DSN": "postgresql://example.invalid/fdai",
        "FDAI_ISOLATED_EXECUTOR_MI_CLIENT_ID": "shadow-identity-client",
        "FDAI_ISOLATED_EXECUTOR_INSTANCE_ID": "executor-shadow-1",
    }
    values.update(changes)
    return values


def test_config_requires_deployed_shadow_identity_and_durability() -> None:
    for missing in (
        "KAFKA_BOOTSTRAP_SERVERS",
        "FDAI_STATE_STORE_DSN",
        "FDAI_ISOLATED_EXECUTOR_MI_CLIENT_ID",
    ):
        environment = _environment()
        environment.pop(missing)
        with pytest.raises(RuntimeError, match=missing):
            IsolatedExecutorRuntimeConfig.from_env(environment)

    with pytest.raises(RuntimeError, match="FDAI_ISOLATED_EXECUTOR_DEPLOYED"):
        IsolatedExecutorRuntimeConfig.from_env(_environment(FDAI_ISOLATED_EXECUTOR_DEPLOYED="0"))

    config = IsolatedExecutorRuntimeConfig.from_env(_environment(RUNTIME_ENV="dev"))
    assert config.executor_instance_id == "executor-shadow-1"


def test_config_rejects_ambiguous_topics_and_invalid_health_port() -> None:
    with pytest.raises(RuntimeError, match="topics MUST be distinct"):
        IsolatedExecutorRuntimeConfig.from_env(
            _environment(
                FDAI_EXECUTOR_COMMAND_TOPIC="object.same",
                FDAI_EXECUTOR_RECEIPT_TOPIC="object.same",
            )
        )
    with pytest.raises(RuntimeError, match="between 1 and 65535"):
        IsolatedExecutorRuntimeConfig.from_env(_environment(FDAI_ISOLATED_EXECUTOR_HEALTH_PORT="0"))


class _ClosableBus(InMemoryEventBus):
    def __init__(self) -> None:
        super().__init__()
        self.closed = False

    async def close(self) -> None:
        self.closed = True


def test_composition_uses_earliest_transport_and_locked_shadow_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    bus = _ClosableBus()

    def event_bus_factory(*, identity: object, config: object) -> _ClosableBus:
        captured["identity"] = identity
        captured["config"] = config
        return bus

    identity = object()
    monkeypatch.setattr(cli, "EventHubsKafkaBus", event_bus_factory)
    monkeypatch.setattr(cli, "build_runtime_workload_identity", lambda *_args, **_kwargs: identity)
    monkeypatch.setattr(cli, "_build_audit_store", InMemoryStateStore)
    monkeypatch.setattr(cli, "_build_resource_lock", ResourceLockManager)
    config = IsolatedExecutorRuntimeConfig.from_env(_environment())
    http_client = httpx.AsyncClient()

    supervisor = build_isolated_executor_supervisor(
        config=config,
        http_client=http_client,
    )

    assert captured["identity"] is identity
    kafka_config = captured["config"]
    assert isinstance(kafka_config, EventHubsKafkaBusConfig)
    assert kafka_config.auto_offset_reset == "earliest"
    assert kafka_config.client_id == "fdai-isolated-executor-shadow"
    assert supervisor.ready is False


def test_entrypoint_imports_no_effect_or_core_executor_adapter() -> None:
    source_path = Path(cli.__file__)
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imports = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}

    assert "fdai.runtime.delivery" not in imports
    assert "fdai.core.executor" not in imports
    assert "fdai.delivery.remediation" not in imports
