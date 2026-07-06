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
