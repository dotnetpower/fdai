output "account_id" {
  description = "AI Services account ARM id."
  value       = azurerm_cognitive_account.search.id
}

output "project_id" {
  description = "Foundry project ARM id."
  value       = azurerm_cognitive_account_project.search.id
}

output "project_endpoint" {
  description = "Foundry project data-plane endpoint used by the agent reconciler and read API."
  value       = "https://${var.account_name}.services.ai.azure.com/api/projects/${var.project_name}"
}

output "agent_name" {
  description = "Stable prompt-agent name reconciled after Terraform apply."
  value       = "fdai-web-search"
}

output "model_deployment_name" {
  description = "Model deployment referenced by the prompt agent."
  value       = azurerm_cognitive_deployment.search.name
}
