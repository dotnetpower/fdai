"""Tests for the analyzer tick CLI (delivery/analyzer_tick_cli.py)."""

from __future__ import annotations

import json
import logging

import pytest

from fdai.core.readiness import DetectionObservationStatus
from fdai.delivery.analyzer_tick_cli import (
    _ENV_BUDGET,
    _ENV_TARGETS,
    _ENV_WINDOW,
    _finding_event,
    _inventory_discovery_evidence,
    _load_targets,
    _positive_float,
    _publish_detection_readiness,
    _run_tick,
    _runtime_number,
    _targets_from_inventory,
    main,
)


def test_load_targets_empty_env_returns_empty_tuple(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(_ENV_TARGETS, raising=False)
    assert _load_targets() == ()


def test_load_targets_whitespace_env_returns_empty_tuple(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(_ENV_TARGETS, "   \n\t  ")
    assert _load_targets() == ()


def test_load_targets_parses_valid_json_array(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        _ENV_TARGETS,
        json.dumps(
            [
                {"resource_id": "aks-1", "kind": "aks_cluster"},
                {"resource_id": "mysql-1", "kind": "mysql_flexible_server"},
            ]
        ),
    )
    targets = _load_targets()
    assert len(targets) == 2
    assert targets[0].resource_ref == "aks-1"
    assert targets[0].resource_kind == "aks_cluster"
    assert targets[1].resource_ref == "mysql-1"
    assert targets[1].resource_kind == "mysql_flexible_server"


def test_load_targets_rejects_malformed_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_ENV_TARGETS, "not-json")
    with pytest.raises(ValueError, match="not valid JSON"):
        _load_targets()


def test_load_targets_rejects_non_list_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_ENV_TARGETS, json.dumps({"one": "two"}))
    with pytest.raises(ValueError, match="MUST be a JSON array"):
        _load_targets()


def test_load_targets_rejects_missing_resource_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(_ENV_TARGETS, json.dumps([{"kind": "aks_cluster"}]))
    with pytest.raises(ValueError, match="resource_id MUST be a non-empty string"):
        _load_targets()


def test_load_targets_rejects_missing_kind(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_ENV_TARGETS, json.dumps([{"resource_id": "r"}]))
    with pytest.raises(ValueError, match="kind MUST be a non-empty string"):
        _load_targets()


def test_load_targets_rejects_non_object_item(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(_ENV_TARGETS, json.dumps(["string-item"]))
    with pytest.raises(ValueError, match=r"\[0\] MUST be an object"):
        _load_targets()


def test_inventory_resources_map_to_reference_analyzer_kinds() -> None:
    targets = _targets_from_inventory(
        [
            {"id": "aks-1", "type": "kubernetes-cluster"},
            {"id": "mysql-1", "type": "mysql-server"},
            {"id": "ignored", "type": "object-storage"},
        ]
    )
    assert [(item.resource_ref, item.resource_kind) for item in targets] == [
        ("aks-1", "aks_cluster"),
        ("mysql-1", "mysql_flexible_server"),
    ]


@pytest.mark.parametrize(
    ("graph", "detail"),
    [
        ({"freshness": "stale", "degraded": True}, "inventory_snapshot_stale"),
        ({"freshness": "fresh", "degraded": True}, "inventory_coverage_degraded"),
    ],
)
def test_inventory_discovery_evidence_fails_closed(
    graph: dict[str, object],
    detail: str,
) -> None:
    status, observed_detail = _inventory_discovery_evidence(graph)

    assert status is DetectionObservationStatus.UNAVAILABLE
    assert observed_detail == detail


async def test_stale_inventory_never_publishes_discovery_passed() -> None:
    from datetime import UTC, datetime

    from fdai.delivery.analyzer_tick_cli import _Target
    from fdai.shared.providers.metric import StaticMetricProvider
    from fdai.shared.providers.testing.event_bus import InMemoryEventBus

    now = datetime(2026, 7, 24, 1, 0, tzinfo=UTC)
    bus = InMemoryEventBus()
    await _publish_detection_readiness(
        targets=(
            _Target(
                resource_ref="aks-1",
                resource_kind="aks_cluster",
                discovery_status=DetectionObservationStatus.UNAVAILABLE,
                discovery_source="inventory.snapshot",
                discovery_detail="inventory_snapshot_stale",
            ),
        ),
        metric_provider=StaticMetricProvider(()),
        event_bus=bus,
        topic="events",
        state_store=None,
        observed_at=now,
    )

    discovered = next(
        record[1]["payload"]["detection_readiness"]
        for record in bus._records["events"]
        if record[1]["payload"]["detection_readiness"]["dimension"] == "discovered"
    )
    assert discovered["status"] == "unavailable"
    assert discovered["detail_code"] == "inventory_snapshot_stale"


async def test_readiness_publisher_emits_six_passed_observations_with_prior_snapshot() -> None:
    from datetime import UTC, datetime

    from fdai.core.readiness import detection_readiness_state_key
    from fdai.delivery.analyzer_tick_cli import _Target
    from fdai.shared.providers.metric import MetricPoint, StaticMetricProvider
    from fdai.shared.providers.testing.event_bus import InMemoryEventBus
    from fdai.shared.providers.testing.state_store import InMemoryStateStore

    now = datetime(2026, 7, 24, 1, 0, tzinfo=UTC)
    store = InMemoryStateStore()
    await store.write_state(
        detection_readiness_state_key("aks-1"),
        {"generated_at": now.isoformat()},
    )
    bus = InMemoryEventBus()
    count = await _publish_detection_readiness(
        targets=(_Target(resource_ref="aks-1", resource_kind="aks_cluster"),),
        metric_provider=StaticMetricProvider(
            [MetricPoint("k8s.pod.restarts", now, 0.0, {"resource_id": "aks-1"})]
        ),
        event_bus=bus,
        topic="events",
        state_store=store,
        observed_at=now,
    )

    records = bus._records["events"]
    assert count == 6
    assert len(records) == 6
    assert {record[0] for record in records} == {"aks-1"}
    readiness = [record[1]["payload"]["detection_readiness"] for record in records]
    assert {item["status"] for item in readiness} == {"passed"}
    assert len({item["pass_id"] for item in readiness}) == 1
    assert {item["dimension"] for item in readiness} == {
        "discovered",
        "collector_configured",
        "telemetry_observed",
        "detector_bound",
        "pipeline_observed",
        "action_governed",
    }


async def test_readiness_publisher_is_partial_on_first_pipeline_pass() -> None:
    from datetime import UTC, datetime

    from fdai.delivery.analyzer_tick_cli import _Target
    from fdai.shared.providers.metric import MetricPoint, StaticMetricProvider
    from fdai.shared.providers.testing.event_bus import InMemoryEventBus

    now = datetime(2026, 7, 24, 1, 0, tzinfo=UTC)
    bus = InMemoryEventBus()
    await _publish_detection_readiness(
        targets=(_Target(resource_ref="aks-1", resource_kind="aks_cluster"),),
        metric_provider=StaticMetricProvider(
            [MetricPoint("k8s.pod.restarts", now, 0.0, {"resource_id": "aks-1"})]
        ),
        event_bus=bus,
        topic="events",
        state_store=None,
        observed_at=now,
    )

    pipeline = next(
        record[1]["payload"]["detection_readiness"]
        for record in bus._records["events"]
        if record[1]["payload"]["detection_readiness"]["dimension"] == "pipeline_observed"
    )
    assert pipeline["status"] == "unavailable"
    assert pipeline["detail_code"] == "prior_snapshot_missing"


def test_positive_float_returns_default_on_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(_ENV_WINDOW, raising=False)
    assert _positive_float(_ENV_WINDOW, 7.0) == 7.0


def test_positive_float_parses_valid_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_ENV_WINDOW, "42.5")
    assert _positive_float(_ENV_WINDOW, 7.0) == 42.5


def test_positive_float_rejects_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_ENV_BUDGET, "0")
    with pytest.raises(ValueError, match="MUST be a positive number"):
        _positive_float(_ENV_BUDGET, 7.0)


def test_positive_float_rejects_negative(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_ENV_BUDGET, "-1")
    with pytest.raises(ValueError, match="MUST be a positive number"):
        _positive_float(_ENV_BUDGET, 7.0)


def test_positive_float_rejects_non_numeric(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_ENV_BUDGET, "abc")
    with pytest.raises(ValueError, match="MUST be a positive number"):
        _positive_float(_ENV_BUDGET, 7.0)


def test_runtime_number_prefers_durable_effective_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(_ENV_BUDGET, "99")

    assert (
        _runtime_number(
            {"analyzer.budget_seconds": 12.5},
            "analyzer.budget_seconds",
            _ENV_BUDGET,
            7.0,
        )
        == 12.5
    )


async def test_run_tick_with_noop_provider_logs_warning_and_exits_zero(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The tick fail-soft when the container's metric_provider is Noop:
    log a warning about the noop provider, still run the analyzers (they
    just get no data), and exit 0. Better than crashing - a fork that
    forgot the env variables sees the warning in its logs on the very
    first tick rather than a red exit code."""
    from fdai.composition import default_container
    from fdai.delivery.analyzer_tick_cli import _Target
    from fdai.shared.config import AppConfig

    container = default_container(
        AppConfig.model_validate(
            {
                "schema_version": "1.0.0",
                "azure": {
                    "tenant_id": "00000000-0000-0000-0000-000000000000",
                    "subscription_id": "00000000-0000-0000-0000-000000000000",
                    "region": "krc",
                },
                "kafka": {
                    "bootstrap_servers": "example:9093",
                    "topic_events": "aw.change.events",
                },
                "postgres": {"host": "example", "database": "aw"},
                "runtime": {"env": "dev"},
                "llm": {"mode": "local-fake"},
            }
        )
    )
    with caplog.at_level(logging.INFO, logger="fdai.delivery.analyzer_tick_cli"):
        exit_code = await _run_tick(
            container,
            targets=(_Target(resource_ref="aks-1", resource_kind="aks_cluster"),),
        )
    assert exit_code == 0
    warnings = [r for r in caplog.records if r.message == "analyzer_tick_noop_provider"]
    assert warnings, "noop-provider warning was not emitted"


def test_main_returns_zero_when_no_targets(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Unset env -> exit 0 with a `no targets` info line. Matches the
    scheduler_tick_cli upstream-safe pattern."""
    monkeypatch.delenv(_ENV_TARGETS, raising=False)
    with caplog.at_level(logging.INFO, logger="fdai.delivery.analyzer_tick_cli"):
        assert main() == 0
    assert any(r.message == "analyzer_tick_no_targets" for r in caplog.records), (
        "no-targets info line was not emitted"
    )


def test_main_returns_three_on_malformed_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Malformed target list -> exit 3 (safe to page). The top-level
    `main` guard catches the ValueError and returns 3."""
    monkeypatch.setenv(_ENV_TARGETS, "not-json")
    assert main() == 3


def test_finding_event_is_deterministic_and_canonical() -> None:
    from datetime import UTC, datetime
    from types import SimpleNamespace

    finding = SimpleNamespace(
        resource_ref="resource:example/aks-1",
        resource_kind="kubernetes-cluster",
        signal="cpu_saturation",
        severity=SimpleNamespace(value="high"),
        observation="CPU exceeded the configured threshold.",
        occurred_at=datetime(2026, 7, 15, tzinfo=UTC),
    )
    first = _finding_event("investigation-1", finding)
    second = _finding_event("investigation-1", finding)

    assert first.event_id == second.event_id
    assert first.idempotency_key == second.idempotency_key
    assert first.event_type == "analyzer.cpu_saturation"
    assert first.payload["resource"]["type"] == "kubernetes-cluster"
