output "action_group_id" {
  description = "Dedicated pilot Action Group resource id."
  value       = azurerm_monitor_action_group.pilot.id
}

output "alert_rule_id" {
  description = "Single pilot Metric Alert resource id."
  value       = azurerm_monitor_metric_alert.pilot.id
}

output "phase" {
  description = "Applied single-axis phase."
  value       = var.phase
}

output "threshold" {
  description = "Applied deterministic threshold."
  value       = local.threshold
}
