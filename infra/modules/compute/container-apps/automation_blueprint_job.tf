// Automation blueprint tick - a Container Apps Job (cron) that runs one
// suggestion and review pass per fire:
// `python -m fdai.delivery.automation_blueprint_tick_cli`.
//
// Each pass turns qualifying completed operator turns into inert durable
// candidates and applies queued accept, reject, and materialize proposals
// through the Core review service, which binds each reviewer from the
// server-recorded Operator roles. A materialized candidate becomes an inert
// scheduled task; the job never executes a change or grants authority.
//
// Opt-in: an empty `automation_blueprint_cron_expression` (the default)
// provisions no job. The job reuses the scheduler identity and the
// state-store DSN secret because it writes schedule-owned candidates in the
// same PostgreSQL database.

resource "azurerm_container_app_job" "automation_blueprint_tick" {
  count = var.automation_blueprint_cron_expression == "" ? 0 : 1

  name                         = local.core_job_names.blueprint
  container_app_environment_id = azurerm_container_app_environment.primary.id
  resource_group_name          = var.resource_group_name
  location                     = var.location
  workload_profile_name        = "Consumption"
  replica_timeout_in_seconds   = 300
  replica_retry_limit          = 2

  identity {
    type         = "UserAssigned"
    identity_ids = [var.scheduler_identity_id]
  }

  dynamic "registry" {
    for_each = var.acr_login_server == "" ? toset([]) : toset(["1"])
    content {
      server   = var.acr_login_server
      identity = var.scheduler_identity_id
    }
  }

  dynamic "secret" {
    for_each = nonsensitive(var.state_store_dsn_secret_id) == "" ? toset([]) : toset(["1"])
    content {
      name                = "automation-blueprint-dsn"
      identity            = var.scheduler_identity_id
      key_vault_secret_id = var.state_store_dsn_secret_id
    }
  }

  schedule_trigger_config {
    cron_expression          = var.automation_blueprint_cron_expression
    replica_completion_count = 1
    parallelism              = 1
  }

  template {
    container {
      name    = "automation-blueprint-tick"
      image   = var.image
      cpu     = 0.25
      memory  = "0.5Gi"
      command = ["python", "-m", "fdai.delivery.automation_blueprint_tick_cli"]

      dynamic "env" {
        for_each = merge(local.core_config_env, local.optional_config_env)
        content {
          name  = env.key
          value = env.value
        }
      }

      env {
        name  = "FDAI_MI_CLIENT_ID"
        value = var.scheduler_identity_client_id
      }

      dynamic "env" {
        for_each = nonsensitive(var.state_store_dsn_secret_id) == "" ? toset([]) : toset(["1"])
        content {
          name        = "FDAI_AUTOMATION_BLUEPRINT_DSN"
          secret_name = "automation-blueprint-dsn"
        }
      }
    }
  }

  lifecycle {
    precondition {
      condition = (
        var.scheduler_identity_id != "" &&
        var.scheduler_identity_client_id != "" &&
        nonsensitive(var.state_store_dsn_secret_id) != ""
      )
      error_message = "enabled automation blueprint Job requires the scheduler identity and state-store secret reference."
    }
  }

  tags = var.tags
}
