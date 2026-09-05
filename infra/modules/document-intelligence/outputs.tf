output "name" {
  description = "Document Intelligence account name."
  value       = azurerm_cognitive_account.document_intelligence.name
}

output "endpoint" {
  description = "Document Intelligence endpoint (custom-subdomain URL)."
  value       = azurerm_cognitive_account.document_intelligence.endpoint
}

output "resource_id" {
  description = "Document Intelligence account ARM id."
  value       = azurerm_cognitive_account.document_intelligence.id
}

output "diagnostic_setting_id" {
  description = "Document Intelligence diagnostic-setting id."
  value       = azurerm_monitor_diagnostic_setting.document_intelligence.id
}
