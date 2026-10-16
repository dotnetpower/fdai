// Workload SLO burn job - one bounded read-only metric evaluation pass.
// The job publishes breach Events to the normal ingest topic and never holds
// executor identity or managed-resource mutation authority.

resource "azurerm_container_app_job" "slo_burn" {
  count = var.slo_burn_cron_expression == "" ? 0 : 1

  name                         = local.core_job_names.slo_burn
  container_app_environment_id = azurerm_container_app_environment.primary.id
  resource_group_name          = var.resource_group_name
  location                     = var.location
  workload_profile_name        = "Consumption"
  replica_timeout_in_seconds   = 300
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

  schedule_trigger_config {
    cron_expression          = var.slo_burn_cron_expression
    replica_completion_count = 1
    parallelism              = 1
  }

  template {
    container {
      name    = "slo-burn"
      image   = var.image
      cpu     = 0.25
      memory  = "0.5Gi"
      command = ["python", "-m", "fdai.delivery.slo_burn_cli"]

      dynamic "env" {
        for_each = merge(local.core_config_env, local.optional_config_env)
        content {
          name  = env.key
          value = env.value
        }
      }

      env {
        name  = "FDAI_MI_CLIENT_ID"
        value = var.inventory_identity_client_id
      }

      env {
        name  = "FDAI_SLO_CATALOG_DIR"
        value = var.slo_catalog_dir
      }
    }
  }

  lifecycle {
    precondition {
      condition     = var.inventory_identity_id != ""
      error_message = "enabled SLO burn Job requires the read-only inventory identity resource id."
    }
    precondition {
      condition     = var.inventory_identity_client_id != ""
      error_message = "enabled SLO burn Job requires the read-only inventory identity client id."
    }
    precondition {
      condition     = trimspace(var.slo_catalog_dir) != ""
      error_message = "enabled SLO burn Job requires a non-empty in-image SLO catalog path."
    }
  }

  tags = var.tags
}
