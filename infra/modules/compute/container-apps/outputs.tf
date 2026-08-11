output "environment_id" {
  description = "Container Apps Environment resource id."
  value       = azurerm_container_app_environment.primary.id
}

output "attached_identity_ids" {
  description = "Declared identity resource ids retained for legacy workflow compatibility."
  value       = concat([var.executor_identity_id], var.extra_identity_ids)
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
  description = "Retired legacy Core resource id. The independent service owns the live id."
  value       = ""
}

output "core_app_name" {
  description = "Deterministic independent Core Container App name."
  value       = var.core_app_name
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
