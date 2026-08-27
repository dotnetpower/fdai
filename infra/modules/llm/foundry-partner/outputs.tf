output "account_id" {
  description = "AI Services account ARM id."
  value       = azurerm_cognitive_account.partner.id
}

output "project_id" {
  description = "Foundry project ARM id."
  value       = azurerm_cognitive_account_project.partner.id
}

output "endpoint" {
  description = "Foundry account endpoint shared by the partner deployments."
  value       = azurerm_cognitive_account.partner.endpoint
}

output "deployments" {
  description = "Capability-to-deployment mapping."
  value       = { for name, deployment in azurerm_cognitive_deployment.capability : name => deployment.name }
}
