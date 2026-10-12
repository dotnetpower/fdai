"""Focused observation campaign CLI composition tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fdai.delivery import observation_campaign_cli as cli
from fdai.delivery.azure.metric_logs import AzureMonitorLogsMetricProvider
from fdai.delivery.observation_campaign_cli import (
    _build_event_bus,
    _build_probes,
    _campaign_id,
    _csv,
    _main,
    _required_consistent,
    _required_first,
)
from fdai.runtime.venue import ExecutionVenue
from fdai.shared.providers.testing.workload_identity import StaticWorkloadIdentity


def test_campaign_id_is_bounded_machine_identifier() -> None:
    values = {_campaign_id() for _ in range(100)}
    value = next(iter(values))

    assert len(values) == 100
    assert value.startswith("campaign-")
    assert value == value.lower()
    assert len(value) < 96


def test_csv_deduplicates_scopes_in_order() -> None:
    assert _csv("first, second, first") == ("first", "second")


def test_required_first_uses_first_populated_environment(monkeypatch) -> None:
    monkeypatch.setenv("SECOND", "value")

    assert _required_first("FIRST", "SECOND") == "value"


def test_required_consistent_rejects_conflicting_aliases(monkeypatch) -> None:
    monkeypatch.setenv("FIRST", "one")
    monkeypatch.setenv("SECOND", "two")

    with pytest.raises(ValueError, match="MUST agree"):
        _required_consistent("FIRST", "SECOND")


def test_event_bus_composition_ignores_unrelated_core_configuration(monkeypatch) -> None:
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "127.0.0.1:19092")
    monkeypatch.setenv("KAFKA_TOPIC_DLQ_SUFFIX", ".dead-letter")
    monkeypatch.setenv("FDAI_WEB_SEARCH_ENABLED", "1")
    monkeypatch.setenv("FDAI_WEB_SEARCH_ALLOWED_DOMAINS", "learn.example.com")

    bus = _build_event_bus(
        identity=StaticWorkloadIdentity(audience="unused", token="unused"),
        venue=ExecutionVenue.LOCAL,
    )

    assert bus._config.bootstrap_servers == "127.0.0.1:19092"
    assert bus._config.dlq_suffix == ".dead-letter"
    assert bus._config.security_protocol == "PLAINTEXT"


async def test_workspace_metric_coverage_uses_target_free_log_analytics(
    monkeypatch,
) -> None:
    monkeypatch.setenv("FDAI_MONITOR_WORKSPACE_ID", "workspace")
    monkeypatch.delenv("FDAI_PROMETHEUS_ENDPOINT", raising=False)
    identity = StaticWorkloadIdentity(
        audience="https://management.azure.com/.default",
        token="token",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _request: None)) as client:
        probes = _build_probes(
            dsn="postgresql://example",
            subscriptions=("sub",),
            identity=identity,
            http_client=client,
        )

    metric_probe = probes["metrics"]
    assert isinstance(metric_probe._provider, AzureMonitorLogsMetricProvider)


async def test_one_shot_returns_failure_for_partial_required_coverage(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def partial_run_once() -> dict[str, object]:
        return {"campaign_id": "campaign-1", "status": "partial", "sources": []}

    monkeypatch.setattr(
        "fdai.delivery.observation_campaign_cli.run_once",
        partial_run_once,
    )

    assert await _main([]) == 1
    assert '"status":"partial"' in capsys.readouterr().out


async def test_campaign_closes_owned_bus_and_state_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "FDAI_OBSERVATION_DSN",
        "FDAI_STATE_STORE_DSN",
        "FDAI_INVENTORY_DSN",
    ):
        monkeypatch.setenv(name, "postgresql://example")
    for name in (
        "FDAI_OBSERVATION_SCOPES",
        "FDAI_INVENTORY_SCOPES",
        "AZURE_SUBSCRIPTION_ID",
    ):
        monkeypatch.setenv(name, "00000000-0000-0000-0000-000000000000")
    store = SimpleNamespace(aclose=AsyncMock())
    bus = SimpleNamespace(close=AsyncMock())
    summary = SimpleNamespace(campaign_id="campaign-1", status="completed", sources=())
    runner = SimpleNamespace(run=AsyncMock(return_value=summary))
    monkeypatch.setattr(cli, "resolve_execution_venue", lambda: ExecutionVenue.LOCAL)
    monkeypatch.setattr(
        cli.AsyncAzureCliWorkloadIdentity,
        "from_env",
        lambda: StaticWorkloadIdentity(audience="unused", token="unused"),
    )
    monkeypatch.setattr(cli, "_build_probes", lambda **_: {})
    monkeypatch.setattr(cli, "_build_event_bus", lambda **_: bus)
    monkeypatch.setattr(cli, "PostgresStateStore", lambda **_: store)
    monkeypatch.setattr(cli, "ObservationCampaignRunner", lambda **_: runner)

    result = await cli.run_once(campaign_id="campaign-1")

    assert result["status"] == "completed"
    bus.close.assert_awaited_once_with()
    store.aclose.assert_awaited_once_with()
