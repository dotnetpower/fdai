output "environment_id" {
  description = "Container Apps Environment resource id."
  value       = azurerm_container_app_environment.primary.id
}

output "attached_identity_ids" {
  description = "User-assigned identity resource ids attached to the core Container App."
  value       = azurerm_container_app.core.identity[0].identity_ids
}

output "vertical_identity_client_ids" {
  description = "Vertical identity client ids exposed to the core runtime."
  value = {
    change     = var.change_identity_client_id
    resilience = var.resilience_identity_client_id
    finops     = var.finops_identity_client_id
  }
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

output "inventory_job_id" {
  description = "Scheduled inventory reconciliation job resource id, or null when disabled."
  value       = try(azurerm_container_app_job.inventory[0].id, null)
}

output "canary_job_name" {
  description = "Synthetic full-loop canary publisher Job name, or empty when disabled."
  value       = try(azurerm_container_app_job.canary[0].name, "")
}
