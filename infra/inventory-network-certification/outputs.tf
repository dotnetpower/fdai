output "resource_group_name" {
  description = "Existing development resource group containing the task-owned sandbox resources."
  value       = data.azurerm_resource_group.certification.name
}

output "migration_job_name" {
  description = "One-shot Core schema migration Job."
  value       = azurerm_container_app_job.migrate.name
}

output "campaign_job_name" {
  description = "One-shot restricted-network inventory campaign Job."
  value       = azurerm_container_app_job.campaign.name
}

output "verifier_job_name" {
  description = "Independent private receipt verification Job."
  value       = azurerm_container_app_job.verifier.name
}

output "receipt_url" {
  description = "Private sanitized campaign receipt URL."
  value       = local.receipt_url
}

output "campaign_identity_client_id" {
  description = "Exact campaign workload identity client ID."
  value       = azurerm_user_assigned_identity.campaign.client_id
}

output "verifier_identity_client_id" {
  description = "Independent verifier workload identity client ID."
  value       = azurerm_user_assigned_identity.verifier.client_id
}
