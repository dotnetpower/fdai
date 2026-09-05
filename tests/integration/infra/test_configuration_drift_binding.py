"""Infrastructure contract for opt-in Azure configuration drift binding."""

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_SERVICE_MAIN = (_ROOT / "infra/services/core-control-plane/main.tf").read_text(encoding="utf-8")
_SERVICE_VARIABLES = (_ROOT / "infra/services/core-control-plane/variables.tf").read_text(
    encoding="utf-8"
)
_MODULE_MAIN = (
    _ROOT / "infra/services/core-control-plane/modules/core-control-plane/main.tf"
).read_text(encoding="utf-8")
_MODULE_VARIABLES = (
    _ROOT / "infra/services/core-control-plane/modules/core-control-plane/variables.tf"
).read_text(encoding="utf-8")


def test_configuration_drift_is_explicitly_opt_in() -> None:
    assert 'variable "configuration_drift"' in _SERVICE_VARIABLES
    assert 'variable "configuration_drift"' in _MODULE_VARIABLES
    assert re.search(
        r"^\s*configuration_drift\s*=\s*var\.configuration_drift\s*$",
        _SERVICE_MAIN,
        re.MULTILINE,
    )
    assert "!var.configuration_drift.enabled ? [] : [" in _MODULE_MAIN
    assert "FDAI_CONFIGURATION_DRIFT_ENABLED" in _MODULE_MAIN


def test_configuration_drift_threads_every_runtime_prerequisite() -> None:
    for key in (
        "FDAI_CONFIGURATION_BASELINE_PATH",
        "FDAI_CONFIGURATION_BASELINE_VERSION",
        "FDAI_CONFIGURATION_BASELINE_SHA256",
        "FDAI_CONFIGURATION_SCOPE",
        "FDAI_CONFIGURATION_SUBSCRIPTIONS_JSON",
        "FDAI_CONFIGURATION_ATTRIBUTE_PATHS_JSON",
        "FDAI_CONFIGURATION_ARG_ENDPOINT",
    ):
        assert key in _MODULE_MAIN

    assert "ordered unique subscriptions" in _MODULE_VARIABLES
    assert "ordered unique scalar attribute paths" in _MODULE_VARIABLES
    assert "https://management.azure.com" in _MODULE_VARIABLES


def test_diagnostic_ingest_is_complete_and_opt_in() -> None:
    assert 'variable "diagnostic_ingest"' in _SERVICE_VARIABLES
    assert 'variable "diagnostic_ingest"' in _MODULE_VARIABLES
    assert "diagnostic_ingest" in _SERVICE_MAIN
    assert "var.diagnostic_ingest" in _SERVICE_MAIN
    assert "!var.diagnostic_ingest.enabled ? [] : [" in _MODULE_MAIN
    for key in (
        "FDAI_DIAGNOSTIC_KAFKA_BOOTSTRAP_SERVERS",
        "FDAI_DIAGNOSTIC_TOPIC",
        "FDAI_DIAGNOSTIC_METRIC_WHITELIST_JSON",
        "FDAI_DIAGNOSTIC_CONSUMER_GROUP_ID",
    ):
        assert key in _MODULE_MAIN
    assert "1-256 ordered unique metric names" in _MODULE_VARIABLES
