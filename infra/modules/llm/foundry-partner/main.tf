locals {
  deployments = {
    for deployment in var.deployments : deployment.name => merge(deployment, {
      model_format = {
        Anthropic = "Anthropic"
        MistralAI = "Mistral AI"
      }[deployment.publisher]
      capacity_units = max(1, floor(deployment.capacity_tpm / 1000))
    })
  }
}

resource "azurerm_cognitive_account" "partner" {
  # checkov:skip=CKV2_AZURE_22:Platform-managed encryption protects replaceable model deployments without a second Key Vault lifecycle.
  name                          = var.account_name
  location                      = var.location
  resource_group_name           = var.resource_group_name
  kind                          = "AIServices"
  sku_name                      = "S0"
  custom_subdomain_name         = var.account_name
  project_management_enabled    = true
  public_network_access_enabled = false
  local_auth_enabled            = false
  tags                          = var.tags

  identity {
    type = "SystemAssigned"
  }

  lifecycle {
    ignore_changes = [network_acls]
  }
}

resource "azurerm_cognitive_account_project" "partner" {
  name                 = var.project_name
  cognitive_account_id = azurerm_cognitive_account.partner.id
  location             = var.location
  display_name         = "FDAI Partner Models"
  description          = "Deployment-owned Foundry project for independent model families."
  tags                 = var.tags

  identity {
    type = "SystemAssigned"
  }
}

resource "azurerm_cognitive_deployment" "capability" {
  for_each             = local.deployments
  name                 = each.value.name
  cognitive_account_id = azurerm_cognitive_account.partner.id

  model {
    format  = each.value.model_format
    name    = each.value.family
    version = each.value.version
  }

  sku {
    name     = each.value.sku
    capacity = each.value.capacity_units
  }
}

resource "azurerm_role_assignment" "project_user" {
  for_each = var.user_principal_ids

  scope                            = azurerm_cognitive_account_project.partner.id
  role_definition_name             = "Azure AI User"
  principal_id                     = each.value
  skip_service_principal_aad_check = true
}
