output "environment_id" {
  description = "Container Apps Environment resource id."
  value       = azurerm_container_app_environment.primary.id
}

output "core_app_id" {
  description = "Core Container App resource id."
  value       = azurerm_container_app.core.id
}

output "core_app_name" {
  description = "Core Container App name."
  value       = azurerm_container_app.core.name
}

output "oob_job_name" {
  description = "Out-of-band Container Apps Job name."
  value       = azurerm_container_app_job.oob.name
}

output "rule_watcher_job_name" {
  description = "Rule-catalog source watcher Container Apps Job name."
  value       = azurerm_container_app_job.rule_watcher.name
}

output "rule_watcher_job_id" {
  description = "Rule-catalog source watcher Container Apps Job resource id."
  value       = azurerm_container_app_job.rule_watcher.id
}

