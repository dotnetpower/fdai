"""Tests for the analyzer tick CLI (delivery/analyzer_tick_cli.py)."""

from __future__ import annotations

import json
import logging

import pytest

from fdai.delivery.analyzer_tick_cli import (
    _ENV_BUDGET,
    _ENV_TARGETS,
    _ENV_WINDOW,
    _load_targets,
    _positive_float,
    _run_tick,
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
