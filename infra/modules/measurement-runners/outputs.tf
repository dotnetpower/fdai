output "baseline_job_id" {
  description = "Automated-baseline regression Container Apps Job resource id."
  value       = azurerm_container_app_job.baseline_regression.id
}

output "baseline_job_name" {
  description = "Automated-baseline regression Container Apps Job name."
  value       = azurerm_container_app_job.baseline_regression.name
}

output "growth_job_id" {
  description = "Pattern-growth intake Container Apps Job resource id."
  value       = azurerm_container_app_job.pattern_growth.id
}

output "growth_job_name" {
  description = "Pattern-growth intake Container Apps Job name."
  value       = azurerm_container_app_job.pattern_growth.name
}

output "operational_promotion_job_id" {
  description = "Operational-promotion measurement Job resource id, or null when disabled."
  value       = try(azurerm_container_app_job.operational_promotion[0].id, null)
}

output "operational_promotion_job_name" {
  description = "Operational-promotion measurement Job name, or null when disabled."
  value       = try(azurerm_container_app_job.operational_promotion[0].name, null)
}
