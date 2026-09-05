resource "azurerm_cognitive_account" "document_intelligence" {
  # checkov:skip=CKV_AZURE_134:The production private-networking gate disables public access for deployment-owned Document Intelligence.
  # checkov:skip=CKV2_AZURE_22:Platform-managed encryption protects replaceable OCR infrastructure without a second Key Vault lifecycle.
  name                          = var.account_name
  location                      = var.location
  resource_group_name           = var.resource_group_name
  kind                          = "FormRecognizer"
  sku_name                      = "S0"
  custom_subdomain_name         = var.account_name
  public_network_access_enabled = !var.private_networking_enabled
  local_auth_enabled            = false
  tags                          = var.tags

  identity {
    type = "SystemAssigned"
  }

  lifecycle {
    ignore_changes = [network_acls]
  }
}

resource "azurerm_monitor_diagnostic_setting" "document_intelligence" {
  name                       = "diag-${var.account_name}"
  target_resource_id         = azurerm_cognitive_account.document_intelligence.id
  log_analytics_workspace_id = var.log_analytics_workspace_id

  enabled_metric {
    category = "AllMetrics"
  }
}
