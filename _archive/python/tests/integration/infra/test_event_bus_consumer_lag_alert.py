from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_MODULE = _ROOT / "infra" / "modules" / "observability" / "monitoring"


def test_monitoring_alerts_on_exported_ingress_consumer_lag() -> None:
    module = (_MODULE / "main.tf").read_text(encoding="utf-8")
    normalized = " ".join(module.split())

    assert 'resource "azurerm_monitor_scheduled_query_rules_alert_v2" "consumer_lag"' in module
    assert "scopes = [var.log_analytics_workspace_id]" in normalized
    assert 'tostring(log.message) == "event_bus_consumer_progress"' in module
    assert 'tostring(log.topic) == "fdai.change.events"' in module
    assert "max(tolong(log.consumer_lag))" in module
    assert "tostring(log.consumer_group)" in module
    assert "toint(log.partition)" in module
    assert "threshold               = 0" in module
    assert "action_groups = [azurerm_monitor_action_group.primary.id]" in module
    assert "auto_mitigation_enabled = true" in module


def test_consumer_lag_alert_threshold_is_configurable_and_bounded() -> None:
    variables = (_MODULE / "variables.tf").read_text(encoding="utf-8")
    module = (_MODULE / "main.tf").read_text(encoding="utf-8")

    assert 'variable "event_bus_consumer_lag_threshold"' in variables
    assert "default     = 100" in variables
    assert "var.event_bus_consumer_lag_threshold >= 1" in variables
    assert "consumer_lag > ${var.event_bus_consumer_lag_threshold}" in module


def test_monitoring_root_supplies_alert_location() -> None:
    root = (_ROOT / "infra" / "main.tf").read_text(encoding="utf-8")
    variables = (_MODULE / "variables.tf").read_text(encoding="utf-8")

    assert 'variable "location"' in variables
    assert "location                    = var.region" in root
