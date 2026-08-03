output "static_web_app_id" {
  description = "Resource id of the design-mocks Static Web App."
  value       = azurerm_static_web_app.design_mocks.id
}

output "default_hostname" {
  description = "Azure-provided default hostname of the design-mocks Static Web App."
  value       = azurerm_static_web_app.design_mocks.default_host_name
}

output "name" {
  description = "Name of the design-mocks Static Web App."
  value       = azurerm_static_web_app.design_mocks.name
}

output "sku_tier" {
  description = "Hosting tier of the design-mocks Static Web App."
  value       = azurerm_static_web_app.design_mocks.sku_tier
}

output "preview_environments_enabled" {
  description = "Whether pull-request preview environments are enabled."
  value       = azurerm_static_web_app.design_mocks.preview_environments_enabled
}
