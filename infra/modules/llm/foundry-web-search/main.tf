resource "azurerm_cognitive_account" "search" {
  name                          = var.account_name
  location                      = var.location
  resource_group_name           = var.resource_group_name
  kind                          = "AIServices"
  sku_name                      = "S0"
  custom_subdomain_name         = var.account_name
  project_management_enabled    = true
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

resource "azurerm_cognitive_account_project" "search" {
  name                 = var.project_name
  cognitive_account_id = azurerm_cognitive_account.search.id
  location             = var.location
  display_name         = "FDAI Web Search"
  description          = "Deployment-owned Foundry project for bounded public web search."
  tags                 = var.tags

  identity {
    type = "SystemAssigned"
  }
}

resource "azurerm_cognitive_deployment" "search" {
  name                 = var.model_deployment_name
  cognitive_account_id = azurerm_cognitive_account.search.id

  model {
    format = "OpenAI"
    name   = var.model_family
  }

  sku {
    name     = var.model_sku
    capacity = max(1, floor(var.model_capacity_tpm / 1000))
  }

  lifecycle {
    ignore_changes = [model[0].version]
  }
}

resource "azurerm_role_assignment" "project_user" {
  for_each = var.user_principal_ids

  scope                            = azurerm_cognitive_account_project.search.id
  role_definition_name             = "Azure AI User"
  principal_id                     = each.value
  skip_service_principal_aad_check = true
}
