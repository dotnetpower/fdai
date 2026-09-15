locals {
  # Availability is a percentage. The baseline cannot fire; the treatment changes
  # only this threshold and is expected to fire after the provider evaluation window.
  threshold       = var.phase == "baseline" ? 0 : 101
  target_id_parts = split("/", var.target_resource_id)
}

data "azurerm_key_vault" "target" {
  name                = local.target_id_parts[8]
  resource_group_name = local.target_id_parts[4]
}

resource "azurerm_monitor_action_group" "pilot" {
  name                = var.action_group_name
  resource_group_name = var.resource_group_name
  short_name          = var.action_group_short_name

  email_receiver {
    name                    = "approved-test-recipient"
    email_address           = var.receiver_email
    use_common_alert_schema = true
  }

  tags = var.tags
}

resource "azurerm_monitor_metric_alert" "pilot" {
  name                = var.alert_name
  resource_group_name = var.resource_group_name
  scopes              = [data.azurerm_key_vault.target.id]
  description         = "FDAI dev alert-noise qualification pilot"
  severity            = 3
  enabled             = true
  auto_mitigate       = true
  frequency           = "PT5M"
  window_size         = "PT5M"

  criteria {
    metric_namespace = "Microsoft.KeyVault/vaults"
    metric_name      = "Availability"
    aggregation      = "Average"
    operator         = "LessThan"
    threshold        = local.threshold
  }

  action {
    action_group_id = azurerm_monitor_action_group.pilot.id
  }

  lifecycle {
    precondition {
      condition     = lower(data.azurerm_key_vault.target.id) == lower(var.target_resource_id)
      error_message = "Resolved Key Vault must exactly match the protected target resource id."
    }
  }

  tags = var.tags
}
