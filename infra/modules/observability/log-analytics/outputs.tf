output "workspace_id" {
  description = "Log Analytics workspace resource id."
  value       = azurerm_log_analytics_workspace.primary.id
}

output "workspace_name" {
  description = "Workspace name."
  value       = azurerm_log_analytics_workspace.primary.name
}

output "workspace_customer_id" {
  description = <<-EOT
    Log Analytics workspace **customer GUID** (the ``workspace_id``
    attribute on ``azurerm_log_analytics_workspace``, NOT the ARM
    resource id). This is what the Azure Monitor Logs query API - and
    the ``AzureMonitorLogsMetricProvider`` composition-root binding via
    ``FDAI_MONITOR_WORKSPACE_ID`` - expects. Confusingly, the provider
    calls the ARM id ``id`` and the customer GUID ``workspace_id``, so
    the two outputs above and below deliberately disambiguate.
  EOT
  value       = azurerm_log_analytics_workspace.primary.workspace_id
}

