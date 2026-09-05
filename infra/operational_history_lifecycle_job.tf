// Bounded operational-history lifecycle coordination. Stable resource IDs keep
// the protected target from pulling unrelated monolithic compute-module inputs.
resource "azurerm_container_app_job" "operational_history_lifecycle" {
  count = var.enable_operational_history && var.operational_history_lifecycle_cron_expression != "" ? 1 : 0

  name = "caj-${var.workload}${local.full_suffix}-history"
  container_app_environment_id = format(
    "/subscriptions/%s/resourceGroups/%s/providers/Microsoft.App/managedEnvironments/%s",
    data.azurerm_client_config.current.subscription_id,
    module.resource_group.name,
    "cae-${var.workload}${local.full_suffix}",
  )
  resource_group_name        = module.resource_group.name
  location                   = var.region
  workload_profile_name      = "Consumption"
  replica_timeout_in_seconds = 1800
  replica_retry_limit        = 0

  identity {
    type         = "UserAssigned"
    identity_ids = [module.inventory_identity.resource_id]
  }

  registry {
    server   = module.container_registry.login_server
    identity = module.inventory_identity.resource_id
  }

  secret {
    name     = "operational-history-dsn"
    identity = module.inventory_identity.resource_id
    key_vault_secret_id = format(
      "%ssecrets/fdai-state-store-dsn",
      module.key_vault.uri,
    )
  }

  schedule_trigger_config {
    cron_expression          = var.operational_history_lifecycle_cron_expression
    replica_completion_count = 1
    parallelism              = 1
  }

  template {
    container {
      name    = "operational-history-lifecycle"
      image   = var.core_image
      cpu     = 0.5
      memory  = "1Gi"
      command = ["python", "-m", "fdai.delivery.operational_history_lifecycle_runner"]
      args    = ["--mode", "shadow"]

      env {
        name        = "FDAI_DATABASE_URL"
        secret_name = "operational-history-dsn"
      }
      env {
        name  = "FDAI_OPERATIONAL_HISTORY_CONTAINER_URL"
        value = module.operational_history_storage[0].container_url
      }
      env {
        name  = "FDAI_OPERATIONAL_HISTORY_MODE"
        value = "shadow"
      }
      env {
        name  = "FDAI_OPERATIONAL_HISTORY_MAX_PARTITIONS"
        value = tostring(var.operational_history_lifecycle_max_partitions)
      }
      env {
        name  = "FDAI_MI_CLIENT_ID"
        value = module.inventory_identity.client_id
      }
    }
  }

  tags = merge(local.tags, { "fdai:component" = "operational-history-lifecycle" })

  lifecycle {
    precondition {
      condition     = module.operational_history_storage[0].container_url != ""
      error_message = "The operational-history lifecycle Job requires a private Blob container."
    }
  }
}
