resource "azurerm_user_assigned_identity" "bootstrap" {
  count               = var.enable_bootstrap_job ? 1 : 0
  name                = "id-${var.prefix}-${var.kind}-bootstrap"
  location            = var.location
  resource_group_name = azurerm_resource_group.hub[var.kind].name
}

resource "azurerm_role_assignment" "bootstrap_registry" {
  count                = var.enable_bootstrap_job ? 1 : 0
  scope                = var.registry.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.bootstrap[0].principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_role_assignment" "bootstrap_secrets" {
  count                = var.enable_bootstrap_job ? 1 : 0
  scope                = azurerm_key_vault.hub[var.kind].id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = azurerm_user_assigned_identity.bootstrap[0].principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_postgresql_flexible_server_active_directory_administrator" "bootstrap" {
  count               = var.enable_bootstrap_job ? 1 : 0
  server_name         = azurerm_postgresql_flexible_server.hub[var.kind].name
  resource_group_name = azurerm_resource_group.hub[var.kind].name
  tenant_id           = var.tenant_id
  object_id           = azurerm_user_assigned_identity.bootstrap[0].principal_id
  principal_name      = azurerm_user_assigned_identity.bootstrap[0].name
  principal_type      = "ServicePrincipal"
}

resource "azurerm_container_app_job" "bootstrap" {
  count                        = var.enable_bootstrap_job ? 1 : 0
  name                         = "caj-${var.prefix}-${var.kind}-bootstrap"
  location                     = var.location
  resource_group_name          = azurerm_resource_group.hub[var.kind].name
  container_app_environment_id = azurerm_container_app_environment.hub[var.kind].id
  replica_timeout_in_seconds   = 120
  replica_retry_limit          = 0
  workload_profile_name        = "Consumption"
  manual_trigger_config {
    parallelism              = 1
    replica_completion_count = 1
  }
  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.bootstrap[0].id]
  }
  registry {
    server   = var.registry.server
    identity = azurerm_user_assigned_identity.bootstrap[0].id
  }
  template {
    container {
      name    = "bootstrap"
      image   = var.image
      cpu     = 0.5
      memory  = "1Gi"
      command = ["python", "-m", "fdai_lifecycle_hub.bootstrap"]
      env {
        name = "FDAI_HUB_BOOTSTRAP_CONFIG"
        value = jsonencode({
          database_host       = azurerm_postgresql_flexible_server.hub[var.kind].fqdn
          database_name       = azurerm_postgresql_flexible_server_database.hub[var.kind].name
          runtime_name        = azurerm_user_assigned_identity.hub[var.kind].name
          runtime_object_id   = azurerm_user_assigned_identity.hub[var.kind].principal_id
          bootstrap_name      = azurerm_user_assigned_identity.bootstrap[0].name
          bootstrap_client_id = azurerm_user_assigned_identity.bootstrap[0].client_id
          vault_uri           = azurerm_key_vault.hub[var.kind].vault_uri
        })
      }
    }
  }
  depends_on = [
    azurerm_role_assignment.bootstrap_registry,
    azurerm_role_assignment.bootstrap_secrets,
    azurerm_postgresql_flexible_server_active_directory_administrator.bootstrap,
    azurerm_postgresql_flexible_server_configuration.tls_floor,
    azurerm_private_endpoint.vault,
    azurerm_private_dns_zone_virtual_network_link.vault,
  ]
}

output "bootstrap_job" {
  value = var.enable_bootstrap_job ? azurerm_container_app_job.bootstrap[0].name : null
}
