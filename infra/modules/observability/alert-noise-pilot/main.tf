locals {
  # The Core app has at least one active replica in the approved pilot baseline.
  # The baseline cannot fire; treatment changes only this threshold.
  threshold = var.phase == "baseline" ? 0 : 2
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
  scopes              = [var.target_container_app_id]
  description         = "FDAI dev alert-noise qualification pilot on Core replica telemetry"
  severity            = 3
  enabled             = true
  auto_mitigate       = true
  frequency           = "PT5M"
  window_size         = "PT5M"

  criteria {
    metric_namespace = "Microsoft.App/containerApps"
    metric_name      = "Replicas"
    aggregation      = "Average"
    operator         = "LessThan"
    threshold        = local.threshold
  }

  action {
    action_group_id = azurerm_monitor_action_group.pilot.id
  }

  tags = var.tags
}
