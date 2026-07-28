// Scheduler tick job - a Container Apps Job (cron) that drives the scheduler
// out-of-band, matching the event-driven / scale-to-zero shape
// (docs/roadmap/app-shape.instructions.md; P2-6).
//
// The job launches `python -m fdai.delivery.scheduler_tick_cli` once per fire.
// The CLI reads the persistent PostgresScheduleStore (shared with the
// operator console) from FDAI_SCHEDULE_STORE_DSN and computes the due set;
// a fork binds an EventBus so the same tick publishes each due task's
// synthetic event onto the ingest topic, where the standard trust-router +
// risk-gate govern any action. The scheduler never executes a change.
//
// Opt-in: an empty `scheduler_cron_expression` (the default) provisions no
// job, so day-zero applies are unchanged. The DSN is sourced from the same
// Key Vault secret as the core app's state store (one Postgres, one secret).

resource "azurerm_container_app_job" "scheduler_tick" {
  count = var.scheduler_cron_expression == "" ? 0 : 1

  name                         = "${var.core_app_name}-scheduler"
  container_app_environment_id = azurerm_container_app_environment.primary.id
  resource_group_name          = var.resource_group_name
  location                     = var.location
  workload_profile_name        = "Consumption"
  // One due-lookup + publish pass. A tick that runs longer than this means
  // the schedule set has grown past its budget and needs sharding.
  replica_timeout_in_seconds = 300
  replica_retry_limit        = 2

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

  // Schedule DSN reuses the state-store secret (same Postgres instance).
  dynamic "secret" {
    for_each = nonsensitive(var.state_store_dsn_secret_id) == "" ? toset([]) : toset(["1"])
    content {
      name                = "schedule-store-dsn"
      identity            = var.executor_identity_id
      key_vault_secret_id = var.state_store_dsn_secret_id
    }
  }

  schedule_trigger_config {
    cron_expression          = var.scheduler_cron_expression
    replica_completion_count = 1
    parallelism              = 1
  }

  template {
    container {
      name    = "scheduler-tick"
      image   = var.image
      cpu     = 0.25
      memory  = "0.5Gi"
      command = ["python", "-m", "fdai.delivery.scheduler_tick_cli"]

      dynamic "env" {
        for_each = merge(local.core_config_env, local.optional_config_env)
        content {
          name  = env.key
          value = env.value
        }
      }

      env {
        name  = "FDAI_MI_CLIENT_ID"
        value = var.executor_identity_client_id
      }

      dynamic "env" {
        for_each = nonsensitive(var.state_store_dsn_secret_id) == "" ? toset([]) : toset(["1"])
        content {
          name        = "FDAI_SCHEDULE_STORE_DSN"
          secret_name = "schedule-store-dsn"
        }
      }
    }
  }

  tags = var.tags
}
