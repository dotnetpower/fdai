output "api_management_id" {
  description = "Resource id of the API Management service."
  value       = var.enabled ? azurerm_api_management.browser_gateway[0].id : ""
}

output "api_management_name" {
  description = "Name of the API Management service."
  value       = var.enabled ? azurerm_api_management.browser_gateway[0].name : ""
}

output "gateway_url" {
  description = "HTTPS API Management gateway origin."
  value       = var.enabled ? azurerm_api_management.browser_gateway[0].gateway_url : ""
}

output "operator_url" {
  description = "HTTPS base URL for the root-routed Operator API."
  value       = var.enabled ? azurerm_api_management.browser_gateway[0].gateway_url : ""
}

output "ingestion_url" {
  description = "HTTPS base URL for the document-ingestion API."
  value       = var.enabled ? "${azurerm_api_management.browser_gateway[0].gateway_url}/ingestion" : ""
}

output "backend_nsg_id" {
  description = "Backend subnet NSG bound to the optional HTTP LoadBalancer path."
  value       = var.enabled ? var.backend_nsg_id : ""
}

output "tags" {
  description = "Azure-safe tags applied to API Management."
  value       = var.enabled ? local.tags : {}
}
