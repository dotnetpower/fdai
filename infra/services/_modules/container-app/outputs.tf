output "id" { value = azurerm_container_app.service.id }
output "name" { value = azurerm_container_app.service.name }
output "latest_revision_name" { value = azurerm_container_app.service.latest_revision_name }
output "fqdn" { value = try(azurerm_container_app.service.ingress[0].fqdn, null) }
