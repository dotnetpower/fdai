// Bounded operational-history lifecycle coordination. The scheduled Job is
// immutable shadow mode under the non-executor inventory identity; enforce and
// certify remain explicit operator invocations with external authority receipts.
resource "azurerm_container_app_job" "operational_history_lifecycle" {
  count = var.operational_history_lifecycle_cron_expression == "" ? 0 : 1

  name                         = var.operational_history_lifecycle_job_name
  container_app_environment_id = azurerm_container_app_environment.primary.id
  resource_group_name          = var.resource_group_name
  location                     = var.location
  workload_profile_name        = "Consumption"
  replica_timeout_in_seconds   = 1800
  replica_retry_limit          = 0

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
    name                = "operational-history-dsn"
    identity            = var.inventory_identity_id
    key_vault_secret_id = var.state_store_dsn_secret_id
  }

  schedule_trigger_config {
    cron_expression          = var.operational_history_lifecycle_cron_expression
    replica_completion_count = 1
    parallelism              = 1
  }

  template {
    container {
      name    = "operational-history-lifecycle"
      image   = var.image
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
        value = var.operational_history_container_url
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
        value = var.inventory_identity_client_id
      }
    }
  }

  tags = merge(var.tags, { "fdai:component" = "operational-history-lifecycle" })

  lifecycle {
    precondition {
      condition = (
        var.operational_history_lifecycle_job_name != "" &&
        var.operational_history_container_url != ""
      )
      error_message = "The operational-history lifecycle Job requires a name and private Blob container."
    }
  }
}
