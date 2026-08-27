// Mechanical forecast tick. The job publishes only a raw ingress event;
// Heimdall remains the sole owner of forecast evaluation and outcome closure.

resource "azurerm_container_app_job" "forecast_tick" {
  count = var.forecast_tick_cron_expression == "" ? 0 : 1

  name                         = local.core_job_names.forecast
  container_app_environment_id = azurerm_container_app_environment.primary.id
  resource_group_name          = var.resource_group_name
  location                     = var.location
  workload_profile_name        = "Consumption"
  replica_timeout_in_seconds   = 120
  replica_retry_limit          = 2

  identity {
    type         = "UserAssigned"
    identity_ids = [var.executor_identity_id]
  }

  dynamic "registry" {
    for_each = var.acr_login_server == "" ? toset([]) : toset(["1"])
    content {
      server   = var.acr_login_server
      identity = var.executor_identity_id
    }
  }

  schedule_trigger_config {
    cron_expression          = var.forecast_tick_cron_expression
    replica_completion_count = 1
    parallelism              = 1
  }

  template {
    container {
      name    = "forecast-tick"
      image   = var.image
      cpu     = 0.25
      memory  = "0.5Gi"
      command = ["python", "-m", "fdai.delivery.forecast_tick_cli"]

      dynamic "env" {
        for_each = local.core_config_env
        content {
          name  = env.key
          value = env.value
        }
      }
    }
  }

  tags = var.tags
}
