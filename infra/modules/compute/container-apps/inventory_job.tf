// Periodic Azure inventory reconciliation. The job shares the VNet-integrated
// environment but uses a dedicated read-only identity, never the executor MI.
resource "azurerm_container_app_job" "inventory" {
  count = var.inventory_cron_expression == "" ? 0 : 1

  name                         = "${var.core_app_name}-inventory"
  container_app_environment_id = azurerm_container_app_environment.primary.id
  resource_group_name          = var.resource_group_name
  location                     = var.location
  replica_timeout_in_seconds   = 1800
  replica_retry_limit          = 2

  identity {
    type         = "UserAssigned"
    identity_ids = [var.inventory_identity_id]
  }

  dynamic "registry" {
    for_each = var.acr_login_server == "" ? toset([]) : toset(["1"])
    content {
      server   = var.acr_login_server
      identity = var.inventory_identity_id
    }
  }

  secret {
    name                = "inventory-dsn"
    identity            = var.inventory_identity_id
    key_vault_secret_id = var.inventory_dsn_secret_id
  }

  schedule_trigger_config {
    cron_expression          = var.inventory_cron_expression
    replica_completion_count = 1
    parallelism              = 1
  }

  template {
    container {
      name    = "inventory"
      image   = var.image
      cpu     = 0.5
      memory  = "1Gi"
      command = ["python", "-m", "fdai.delivery.inventory_sync_cli"]

      env {
        name        = "FDAI_INVENTORY_DSN"
        secret_name = "inventory-dsn"
      }
      env {
        name  = "FDAI_INVENTORY_SCOPES"
        value = var.azure_subscription_id
      }
      env {
        name  = "FDAI_INVENTORY_SOURCES"
        value = var.inventory_sources
      }
      env {
        name  = "FDAI_INVENTORY_FRESHNESS_SECONDS"
        value = tostring(var.inventory_freshness_seconds)
      }
      env {
        name  = "FDAI_MI_CLIENT_ID"
        value = var.inventory_identity_client_id
      }
    }
  }

  tags = var.tags
}
