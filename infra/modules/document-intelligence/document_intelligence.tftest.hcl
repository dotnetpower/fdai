mock_provider "azurerm" {}

variables {
  account_name               = "di-fdai-dev-krc"
  location                   = "koreacentral"
  resource_group_name        = "rg-fdai-dev-krc"
  private_networking_enabled = true
  log_analytics_workspace_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai-dev-krc/providers/Microsoft.OperationalInsights/workspaces/log-fdai-dev-krc"
  tags = {
    "fdai:managed"   = "true"
    "fdai:component" = "document-intelligence"
  }
}

run "plans_private_document_intelligence" {
  command = plan

  assert {
    condition     = azurerm_cognitive_account.document_intelligence.kind == "FormRecognizer"
    error_message = "Document Intelligence must use the FormRecognizer account kind."
  }

  assert {
    condition     = azurerm_cognitive_account.document_intelligence.sku_name == "S0"
    error_message = "Document Intelligence must use the S0 SKU."
  }

  assert {
    condition     = azurerm_cognitive_account.document_intelligence.custom_subdomain_name == var.account_name
    error_message = "Document Intelligence must use the custom subdomain that matches the account name."
  }

  assert {
    condition     = azurerm_cognitive_account.document_intelligence.public_network_access_enabled == false
    error_message = "Private Document Intelligence must disable public network access."
  }

  assert {
    condition     = azurerm_cognitive_account.document_intelligence.local_auth_enabled == false
    error_message = "Document Intelligence must disable local authentication."
  }

  assert {
    condition     = azurerm_cognitive_account.document_intelligence.identity[0].type == "SystemAssigned"
    error_message = "Document Intelligence must keep its system-assigned identity."
  }

  assert {
    condition     = azurerm_monitor_diagnostic_setting.document_intelligence.name == "diag-di-fdai-dev-krc"
    error_message = "Document Intelligence diagnostics must use deterministic naming."
  }

  assert {
    condition = (
      azurerm_monitor_diagnostic_setting.document_intelligence.log_analytics_workspace_id ==
      var.log_analytics_workspace_id
    )
    error_message = "Document Intelligence diagnostics must stream to the supplied Log Analytics workspace."
  }
}

run "public_mode_keeps_public_access_enabled" {
  command = plan

  variables {
    private_networking_enabled = false
  }

  assert {
    condition     = azurerm_cognitive_account.document_intelligence.public_network_access_enabled == true
    error_message = "Public-mode Document Intelligence must leave public network access enabled."
  }
}
