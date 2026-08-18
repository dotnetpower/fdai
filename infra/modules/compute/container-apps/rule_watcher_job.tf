// Rule-catalog source watcher - Container Apps Job that runs the verified
// collector wrapper on a configured cron. The watcher itself filters by
// manifest cadence, so one job covers every source without per-cadence jobs.
//
//   src/fdai/rule_catalog/pipeline/watcher_cli.py
//   docs/roadmap/phases/phase-2-quality-and-t1.md § Continuous Rule Update Pipeline
//
// The job never auto-promotes: it produces snapshots + verify reports and
// records validated success evidence in the existing state store. Promotion
// into the T0 catalog stays a reviewed catalog-as-code PR.
//
// The job reuses the non-effect inventory identity, which already has ACR pull
// and access to the StateStore secret. It never receives the executor identity.

resource "azurerm_container_app_job" "rule_watcher" {
  name                         = var.rule_watcher_job_name
  container_app_environment_id = azurerm_container_app_environment.primary.id
  resource_group_name          = var.resource_group_name
  location                     = var.location
  workload_profile_name        = "Consumption"
  // Rule watcher is a short-lived batch: pull each due source, snapshot,
  // verify. Anything longer means a source manifest points at a huge tree
  // and needs its own dedicated job.
  replica_timeout_in_seconds = 900
  replica_retry_limit        = 2

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

  dynamic "secret" {
    for_each = nonsensitive(var.state_store_dsn_secret_id) == "" ? toset([]) : toset(["1"])
    content {
      name                = "rule-collector-store-dsn"
      identity            = var.inventory_identity_id
      key_vault_secret_id = var.state_store_dsn_secret_id
    }
  }

  schedule_trigger_config {
    cron_expression          = var.rule_watcher_cron_expression
    replica_completion_count = 1
    parallelism              = 1
  }

  template {
    container {
      name    = "rule-watcher"
      image   = var.image
      cpu     = 0.25
      memory  = "0.5Gi"
      command = ["python", "-m", "fdai.delivery.rule_collector_job_cli"]

      dynamic "env" {
        for_each = nonsensitive(var.state_store_dsn_secret_id) == "" ? toset([]) : toset(["1"])
        content {
          name        = "FDAI_STATE_STORE_DSN"
          secret_name = "rule-collector-store-dsn"
        }
      }
    }
  }

  tags = var.tags
}
