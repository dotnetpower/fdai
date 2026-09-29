output "id" { value = azurerm_container_app.service.id }
output "name" { value = azurerm_container_app.service.name }
output "latest_revision_name" { value = azurerm_container_app.service.latest_revision_name }
output "fqdn" { value = try(azurerm_container_app.service.ingress[0].fqdn, null) }
output "ingress_external_enabled" { value = try(azurerm_container_app.service.ingress[0].external_enabled, null) }
output "ingress_target_port" { value = try(azurerm_container_app.service.ingress[0].target_port, null) }
