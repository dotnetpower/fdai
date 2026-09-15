"""Alert-noise pilot Terraform boundary contracts."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MODULE = ROOT / "infra/modules/observability/alert-noise-pilot"


def test_alert_noise_pilot_is_one_rule_one_recipient_and_one_axis() -> None:
    main = (MODULE / "main.tf").read_text(encoding="utf-8")

    assert main.count('resource "azurerm_monitor_metric_alert"') == 1
    assert main.count('resource "azurerm_monitor_action_group"') == 1
    assert main.count("email_receiver {") == 1
    assert "webhook_receiver" not in main
    assert 'threshold       = var.phase == "baseline" ? 0 : 101' in main
    assert 'metric_name      = "Availability"' in main
    assert "severity            = 3" in main
    assert "auto_mitigate       = true" in main
    assert 'data "azurerm_key_vault" "target"' in main
    assert "scopes              = [data.azurerm_key_vault.target.id]" in main
    assert "lower(data.azurerm_key_vault.target.id) == lower(var.target_resource_id)" in main


def test_alert_noise_pilot_is_default_off_dev_only_and_secret_bound() -> None:
    variables = (ROOT / "infra/variables.tf").read_text(encoding="utf-8")
    root = (ROOT / "infra/main.tf").read_text(encoding="utf-8")
    module_variables = (MODULE / "variables.tf").read_text(encoding="utf-8")

    block = variables.split('variable "enable_alert_noise_pilot"', 1)[1].split("}\n", 1)[0]
    assert "default     = false" in block
    assert 'condition     = var.environment == "dev"' in module_variables
    assert 'variable "receiver_email"' in module_variables
    assert "sensitive   = true" in module_variables
    assert "receiver_email          = var.alert_noise_pilot_email" in root
    assert "target_resource_id      = var.alert_noise_pilot_target_resource_id" in root
    assert "target_resource_id      = module.key_vault.id" not in root
    assert "!var.enable_monitoring" in root
    assert '"fdai:component" = "alert-noise-pilot"' in root
