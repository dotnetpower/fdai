output "id" {
  description = "Isolated Executor shadow Container App resource id."
  value       = azurerm_container_app.shadow.id
}

output "name" {
  description = "Isolated Executor shadow Container App resource name."
  value       = azurerm_container_app.shadow.name
}

output "identity_ids" {
  description = "The sole UAMI attached to the shadow Container App."
  value       = azurerm_container_app.shadow.identity[0].identity_ids
}
