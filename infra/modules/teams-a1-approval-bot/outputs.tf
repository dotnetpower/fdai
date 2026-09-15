output "identity" {
  description = "Dedicated non-executor approval bot identity."
  value = {
    resource_id  = azurerm_user_assigned_identity.approval_bot.id
    client_id    = azurerm_user_assigned_identity.approval_bot.client_id
    principal_id = azurerm_user_assigned_identity.approval_bot.principal_id
  }
}

output "bot" {
  description = "Provisioned Azure Bot and Teams channel registration."
  value = {
    id         = azurerm_bot_service_azure_bot.approval.id
    name       = azurerm_bot_service_azure_bot.approval.name
    app_id     = azurerm_user_assigned_identity.approval_bot.client_id
    endpoint   = azurerm_bot_service_azure_bot.approval.endpoint
    channel_id = azurerm_bot_channel_ms_teams.approval.id
  }
}

# Shaped to feed the core-control-plane teams_approval_destination contract without
# a person copying identity values by hand.
output "teams_approval_destination" {
  description = "teams_approval_destination contract inputs for the core-control-plane root."
  value = {
    team_id              = var.approval_team_id
    channel_id           = var.approval_channel_id
    activity_url         = var.activity_url
    identity_resource_id = azurerm_user_assigned_identity.approval_bot.id
    identity_client_id   = azurerm_user_assigned_identity.approval_bot.client_id
  }
}
