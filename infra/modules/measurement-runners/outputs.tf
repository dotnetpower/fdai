output "baseline_job_id" {
  description = "Automated-baseline regression Container Apps Job resource id, or null when disabled."
  value       = try(azurerm_container_app_job.baseline_regression[0].id, null)
}

output "baseline_job_name" {
  description = "Automated-baseline regression Container Apps Job name, or null when disabled."
  value       = try(azurerm_container_app_job.baseline_regression[0].name, null)
}

output "growth_job_id" {
  description = "Pattern-growth intake Container Apps Job resource id, or null when disabled."
  value       = try(azurerm_container_app_job.pattern_growth[0].id, null)
}

output "growth_job_name" {
  description = "Pattern-growth intake Container Apps Job name, or null when disabled."
  value       = try(azurerm_container_app_job.pattern_growth[0].name, null)
}

output "operational_promotion_job_id" {
  description = "Operational-promotion measurement Job resource id, or null when disabled."
  value       = try(azurerm_container_app_job.operational_promotion[0].id, null)
}

output "operational_promotion_job_name" {
  description = "Operational-promotion measurement Job name, or null when disabled."
  value       = try(azurerm_container_app_job.operational_promotion[0].name, null)
}
