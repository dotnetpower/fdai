output "static_web_app_id" {
  description = "Resource id of the Static Web App."
  value       = azurerm_static_web_app.console.id
}

output "default_hostname" {
  description = "Azure-provided default hostname (e.g. `<name>.azurestaticapps.net`). Use this as the origin for MSAL redirect URIs when no custom domain is configured."
  value       = azurerm_static_web_app.console.default_host_name
}

output "custom_hostname" {
  description = "Custom hostname (empty when disabled)."
  value       = var.custom_hostname
}
