"""End-to-end telemetry setup from AppConfig."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fdai.shared.config import AppConfig
from fdai.shared.telemetry import (
    configure_telemetry,
    get_meter,
    get_tracer,
    in_memory_reader,
    setup,
)
from fdai.shared.telemetry.setup import _local_warning_log_path


def test_configure_telemetry_wires_everything(app_config: AppConfig) -> None:
    configure_telemetry(app_config)
    tracer = get_tracer("fdai.tests.setup")
    meter = get_meter("fdai.tests.setup")

    with tracer.start_as_current_span("smoke"):
        counter = meter.create_counter("aw.tests.smoke")
        counter.add(1)

    # In-memory reader is installed (day-zero exporter path).
    reader = in_memory_reader()
    assert reader is not None


def test_configure_telemetry_is_idempotent(app_config: AppConfig) -> None:
    # Calling twice must not raise - the underlying OTel API only accepts
    # one provider install and our wrappers guard against duplicates.
    configure_telemetry(app_config)
    configure_telemetry(app_config)


def test_dev_source_checkout_enables_local_warning_log(
    app_config: AppConfig,
    tmp_path: Path,
) -> None:
    (tmp_path / ".git").mkdir()
    nested = tmp_path / "services/core-control-plane/src/fdai/shared"
    nested.mkdir(parents=True)

    assert _local_warning_log_path(app_config, nested, environ={}) == (
        tmp_path / ".fdai/logs/warnings.jsonl"
    )


def test_pytest_context_disables_local_warning_log(
    app_config: AppConfig,
    tmp_path: Path,
) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "services/core-control-plane/src/fdai").mkdir(parents=True)

    assert (
        _local_warning_log_path(
            app_config,
            tmp_path,
            environ={
                "PYTEST_CURRENT_TEST": (
                    "services/core-control-plane/tests/example.py::test_case (call)"
                )
            },
        )
        is None
    )


def test_non_dev_runtime_disables_local_warning_log(
    app_config: AppConfig,
    tmp_path: Path,
) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "services/core-control-plane/src/fdai").mkdir(parents=True)
    prod_config = app_config.model_copy(
        update={"runtime": app_config.runtime.model_copy(update={"env": "prod"})}
    )

    assert _local_warning_log_path(prod_config, tmp_path, environ={}) is None


def test_application_insights_uses_azure_monitor_without_forwarding_secret(
    app_config: AppConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured: dict[str, Any] = {}

    def record_configuration(**kwargs: Any) -> None:
        configured.update(kwargs)

    monkeypatch.setenv(
        "APPLICATIONINSIGHTS_CONNECTION_STRING",
        "InstrumentationKey=00000000-0000-0000-0000-000000000000",
    )
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.setattr(
        "azure.monitor.opentelemetry.configure_azure_monitor",
        record_configuration,
    )
    monkeypatch.setattr(setup, "configure_logging", lambda **_: None)
    monkeypatch.setattr(
        setup,
        "configure_tracing",
        lambda **_: pytest.fail("the OTLP tracing path must not be configured"),
    )
    monkeypatch.setattr(
        setup,
        "configure_metrics",
        lambda **_: pytest.fail("the OTLP metrics path must not be configured"),
    )
    monkeypatch.setattr(setup, "_AZURE_MONITOR_CONFIGURED", False)

    configure_telemetry(app_config)

    assert configured["logger_name"] == "fdai"
    assert configured["resource"].attributes["service.name"] == "fdai"
    assert configured["resource"].attributes["runtime.env"] == app_config.runtime.env
    assert "connection_string" not in configured


def test_application_insights_rejects_a_second_otlp_exporter_without_secret(
    app_config: AppConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "InstrumentationKey=00000000-0000-0000-0000-000000000000"
    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", secret)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://collector.example.com")
    monkeypatch.setattr(setup, "configure_logging", lambda **_: None)

    with pytest.raises(ValueError) as error:
        configure_telemetry(app_config)

    assert "MUST NOT be configured together" in str(error.value)
    assert secret not in str(error.value)
