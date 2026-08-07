output "id" {
  description = "Isolated Executor shadow Container App resource id."
  value       = azurerm_container_app.shadow.id
}

output "name" {
  description = "Isolated Executor shadow Container App resource name."
  value       = azurerm_container_app.shadow.name
}

output "identity_ids" {
  description = "The transport UAMI and any cutover-only action identities attached to the Container App."
  value       = azurerm_container_app.shadow.identity[0].identity_ids
}
