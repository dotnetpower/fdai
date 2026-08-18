output "action_group_id" {
  value       = azurerm_monitor_action_group.primary.id
  description = "Action group all metric alerts fire to."
}

output "alert_names" {
  value = sort(concat(
    [for alert in azurerm_monitor_metric_alert.this : alert.name],
    [azurerm_monitor_scheduled_query_rules_alert_v2.consumer_lag.name],
  ))
  description = "Provisioned metric alert names."
}
