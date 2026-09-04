// Read-only WARA assessment over deployment-declared workload scopes.
resource "azurerm_container_app_job" "wara_assessment" {
  count = var.wara_assessment_cron_expression == "" || length(var.wara_assessment_workload_ids) == 0 ? 0 : 1

  name                         = local.core_job_names.wara
  container_app_environment_id = azurerm_container_app_environment.primary.id
  resource_group_name          = var.resource_group_name
  location                     = var.location
  workload_profile_name        = "Consumption"
  replica_timeout_in_seconds   = 600
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
    name                = "wara-dsn"
    identity            = var.inventory_identity_id
    key_vault_secret_id = var.inventory_dsn_secret_id
  }

  schedule_trigger_config {
    cron_expression          = var.wara_assessment_cron_expression
    replica_completion_count = 1
    parallelism              = 1
  }

  template {
    container {
      name    = "wara-assessment"
      image   = var.image
      cpu     = 0.5
      memory  = "1Gi"
      command = ["python", "-m", "fdai.delivery.wara_assessment_cli"]

      dynamic "env" {
        for_each = local.core_config_env
        content {
          name  = env.key
          value = env.value
        }
      }

      env {
        name        = "FDAI_WARA_DSN"
        secret_name = "wara-dsn"
      }
      env {
        name  = "FDAI_SEMANTIC_TURN_PHYSICAL_TOPIC"
        value = var.semantic_turn_physical_topic
      }
      env {
        name  = "FDAI_WARA_WORKLOAD_IDS_JSON"
        value = jsonencode(sort(var.wara_assessment_workload_ids))
      }
      env {
        name  = "FDAI_WARA_WORKLOAD_TAGS_JSON"
        value = jsonencode(var.wara_assessment_workload_tags)
      }
      env {
        name  = "FDAI_WARA_INVENTORY_FRESHNESS_SECONDS"
        value = tostring(var.wara_assessment_inventory_freshness_seconds)
      }
      env {
        name  = "FDAI_WARA_RUN_SLOT_SECONDS"
        value = tostring(var.wara_assessment_run_slot_seconds)
      }
      env {
        name  = "FDAI_WARA_TICK_TIMEOUT_SECONDS"
        value = "540"
      }
      env {
        name  = "FDAI_MI_CLIENT_ID"
        value = var.inventory_identity_client_id
      }
    }
  }

  tags = var.tags
}
