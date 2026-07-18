"""End-to-end telemetry setup from AppConfig."""

from __future__ import annotations

from pathlib import Path

from fdai.shared.config import AppConfig
from fdai.shared.telemetry import (
    configure_telemetry,
    get_meter,
    get_tracer,
    in_memory_reader,
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
    nested = tmp_path / "src/fdai/shared"
    nested.mkdir(parents=True)

    assert _local_warning_log_path(app_config, nested, environ={}) == (
        tmp_path / ".fdai/logs/warnings.jsonl"
    )


def test_pytest_context_disables_local_warning_log(
    app_config: AppConfig,
    tmp_path: Path,
) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "src/fdai").mkdir(parents=True)

    assert (
        _local_warning_log_path(
            app_config,
            tmp_path,
            environ={"PYTEST_CURRENT_TEST": "tests/example.py::test_case (call)"},
        )
        is None
    )


def test_non_dev_runtime_disables_local_warning_log(
    app_config: AppConfig,
    tmp_path: Path,
) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "src/fdai").mkdir(parents=True)
    prod_config = app_config.model_copy(
        update={"runtime": app_config.runtime.model_copy(update={"env": "prod"})}
    )

    assert _local_warning_log_path(prod_config, tmp_path, environ={}) is None
