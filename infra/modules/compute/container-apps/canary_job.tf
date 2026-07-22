// Trusted synthetic canary publisher. It has no executor, Key Vault, or
// Postgres permissions: only ACR pull and Event Hubs send are granted by the
// root module. The core consumes this topic through a dedicated no-op path.

resource "azurerm_container_app_job" "canary" {
  count = var.canary_cron_expression == "" ? 0 : 1

  name                         = "${var.core_app_name}-canary"
  container_app_environment_id = azurerm_container_app_environment.primary.id
  resource_group_name          = var.resource_group_name
  location                     = var.location
  workload_profile_name        = "Consumption"
  replica_timeout_in_seconds   = 120
  replica_retry_limit          = 2

  identity {
    type         = "UserAssigned"
    identity_ids = [var.canary_identity_id]
  }

  dynamic "registry" {
    for_each = var.acr_login_server == "" ? toset([]) : toset(["1"])
    content {
      server   = var.acr_login_server
      identity = var.canary_identity_id
    }
  }

  schedule_trigger_config {
    cron_expression          = var.canary_cron_expression
    replica_completion_count = 1
    parallelism              = 1
  }

  template {
    container {
      name    = "canary"
      image   = var.image
      cpu     = 0.25
      memory  = "0.5Gi"
      command = ["python", "-m", "fdai.delivery.canary_cli"]

      env {
        name  = "KAFKA_BOOTSTRAP_SERVERS"
        value = var.operational_kafka_bootstrap_servers
      }
      env {
        name  = "FDAI_CANARY_TOPIC"
        value = var.canary_topic
      }
      env {
        name  = "FDAI_MI_CLIENT_ID"
        value = var.canary_identity_client_id
      }
    }
  }

  tags = merge(var.tags, { "fdai:component" = "control-loop-canary" })
}
