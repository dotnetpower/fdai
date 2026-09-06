output "name" {
  description = "Resource group name."
  value       = var.reference_existing ? data.azurerm_resource_group.foundation[0].name : azurerm_resource_group.primary[0].name
}

output "id" {
  description = "Resource group id."
  value       = var.reference_existing ? data.azurerm_resource_group.foundation[0].id : azurerm_resource_group.primary[0].id
}

output "location" {
  description = "Resource group location."
  value       = var.reference_existing ? data.azurerm_resource_group.foundation[0].location : azurerm_resource_group.primary[0].location
}
