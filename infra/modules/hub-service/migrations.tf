resource "azurerm_container_app_job" "migrate" {
  for_each                     = var.enable_migration_jobs ? local.kinds : toset([])
  name                         = "caj-${var.prefix}-${each.key}-migrate"
  location                     = var.location
  resource_group_name          = local.foundation[each.key].resource_group
  container_app_environment_id = local.foundation[each.key].environment_id
  replica_timeout_in_seconds   = 120
  replica_retry_limit          = 0
  workload_profile_name        = "Consumption"
  manual_trigger_config {
    parallelism              = 1
    replica_completion_count = 1
  }
  identity {
    type         = "UserAssigned"
    identity_ids = [local.foundation[each.key].identity_id]
  }
  registry {
    server   = var.registry.server
    identity = local.foundation[each.key].identity_id
  }
  secret {
    name                = "database-url"
    identity            = local.foundation[each.key].identity_id
    key_vault_secret_id = "${local.foundation[each.key].vault_uri}secrets/hub-database-url/${var.secret_versions.database}"
  }
  template {
    container {
      name    = "migrate"
      image   = var.image
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
        value = local.foundation[each.key].identity_client_id
      }
    }
  }
  depends_on = [
    azurerm_role_assignment.registry_reader, azurerm_role_assignment.secret_reader,
    azurerm_private_endpoint.vault,
    azurerm_private_dns_zone_virtual_network_link.vault,
    azurerm_postgresql_flexible_server_configuration.log_connections,
    azurerm_postgresql_flexible_server_configuration.log_checkpoints,
    azurerm_postgresql_flexible_server_configuration.connection_throttle,
    azurerm_postgresql_flexible_server_configuration.tls_floor,
  ]
  lifecycle {
    prevent_destroy = true
  }
}
