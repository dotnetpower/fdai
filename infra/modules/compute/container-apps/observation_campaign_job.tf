// Permission-aware read campaign. PostgreSQL due state keeps every source on
// its own cadence even though the Container Apps Job wakes once per minute.
resource "azurerm_container_app_job" "observation_campaign" {
  count = var.observation_campaign_cron_expression == "" ? 0 : 1

  name                         = "${var.core_app_name}-observation"
  container_app_environment_id = azurerm_container_app_environment.primary.id
  resource_group_name          = var.resource_group_name
  location                     = var.location
  workload_profile_name        = "Consumption"
  replica_timeout_in_seconds   = 900
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
    name                = "observation-dsn"
    identity            = var.inventory_identity_id
    key_vault_secret_id = var.inventory_dsn_secret_id
  }

  schedule_trigger_config {
    cron_expression          = var.observation_campaign_cron_expression
    replica_completion_count = 1
    parallelism              = 1
  }

  template {
    container {
      name    = "observation-campaign"
      image   = var.image
      cpu     = 0.5
      memory  = "1Gi"
      command = ["python", "-m", "fdai.delivery.observation_campaign_cli"]

      dynamic "env" {
        for_each = local.core_config_env
        content {
          name  = env.key
          value = env.value
        }
      }

      env {
        name        = "FDAI_OBSERVATION_DSN"
        secret_name = "observation-dsn"
      }
      env {
        name  = "FDAI_OBSERVATION_SCOPES"
        value = var.azure_subscription_id
      }
      env {
        name  = "FDAI_MI_CLIENT_ID"
        value = var.inventory_identity_client_id
      }
    }
  }

  tags = var.tags
}
