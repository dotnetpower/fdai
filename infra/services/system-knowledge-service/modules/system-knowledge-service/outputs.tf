output "service" {
  value = {
    id                   = module.container_app.id
    name                 = module.container_app.name
    fqdn                 = module.container_app.fqdn
    latest_revision_name = module.container_app.latest_revision_name
  }
}

output "identity" {
  value = {
    resource_id  = azurerm_user_assigned_identity.service.id
    client_id    = azurerm_user_assigned_identity.service.client_id
    principal_id = azurerm_user_assigned_identity.service.principal_id
  }
}

output "bot" {
  value = local.bot_framework_enabled ? {
    id         = azurerm_bot_service_azure_bot.service[0].id
    name       = azurerm_bot_service_azure_bot.service[0].name
    app_id     = azurerm_user_assigned_identity.service.client_id
    endpoint   = azurerm_bot_service_azure_bot.service[0].endpoint
    channel_id = azurerm_bot_channel_ms_teams.service[0].id
  } : null
}

output "claim_store" {
  value = {
    container_id  = azurerm_storage_container.claims.id
    container_url = local.claim_container_url
  }
}
