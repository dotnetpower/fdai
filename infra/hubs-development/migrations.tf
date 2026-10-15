resource "azurerm_container_app_job" "migrate" {
  for_each                     = var.enable_migration_jobs ? local.kinds : toset([])
  name                         = "caj-${var.prefix}-${each.key}-migrate"
  location                     = var.location
  resource_group_name          = azurerm_resource_group.hub[each.key].name
  container_app_environment_id = azurerm_container_app_environment.hub[each.key].id
  replica_timeout_in_seconds   = 120
  replica_retry_limit          = 0
  manual_trigger_config {
    parallelism              = 1
    replica_completion_count = 1
  }
  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.hub[each.key].id]
  }
  registry {
    server   = var.registry.server
    identity = azurerm_user_assigned_identity.hub[each.key].id
  }
  secret {
    name                = "database-url"
    identity            = azurerm_user_assigned_identity.hub[each.key].id
    key_vault_secret_id = "${azurerm_key_vault.hub[each.key].vault_uri}secrets/hub-database-url/${var.secret_versions[each.key].database}"
  }
  template {
    container {
      name    = "migrate"
      image   = var.images[each.key]
      cpu     = 0.5
      memory  = "1Gi"
      command = ["python", "-m", "fdai_lifecycle_hub.remote"]
      args    = ["migrate"]
      env {
        name  = "FDAI_HUB_REMOTE_CONFIG"
        value = jsonencode(local.configs[each.key])
      }
      env {
        name        = each.key == "release" ? "FDAI_RELEASE_HUB_DATABASE_URL" : "FDAI_LIFECYCLE_HUB_DATABASE_URL"
        secret_name = "database-url"
      }
      env {
        name  = "FDAI_HUB_MANAGED_IDENTITY_CLIENT_ID"
        value = azurerm_user_assigned_identity.hub[each.key].client_id
      }
    }
  }
  depends_on = [azurerm_role_assignment.registry_reader, azurerm_role_assignment.secret_reader]
}
