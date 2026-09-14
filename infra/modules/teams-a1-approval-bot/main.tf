# Dedicated A1 approval bot. The user-assigned identity carries no managed-resource
# or executor role; it only lets Teams authenticate the approval bot. Effect
# authority stays with Thor's separate executor identity.

resource "azurerm_user_assigned_identity" "approval_bot" {
  name                = "id-${var.name}"
  resource_group_name = var.resource_group_name
  location            = var.location
  tags                = merge(var.tags, { "fdai:component" = "teams-a1-approval-bot" })
}

resource "azurerm_bot_service_azure_bot" "approval" {
  name                          = var.name
  resource_group_name           = var.resource_group_name
  location                      = "global"
  microsoft_app_id              = azurerm_user_assigned_identity.approval_bot.client_id
  microsoft_app_type            = "UserAssignedMSI"
  microsoft_app_msi_id          = azurerm_user_assigned_identity.approval_bot.id
  microsoft_app_tenant_id       = var.tenant_id
  sku                           = "F0"
  endpoint                      = var.activity_url
  local_authentication_enabled  = false
  public_network_access_enabled = true
  streaming_endpoint_enabled    = false
  tags                          = merge(var.tags, { "fdai:component" = "teams-a1-approval-bot" })
}

resource "azurerm_bot_channel_ms_teams" "approval" {
  bot_name            = azurerm_bot_service_azure_bot.approval.name
  location            = azurerm_bot_service_azure_bot.approval.location
  resource_group_name = var.resource_group_name
  calling_enabled     = false
}
