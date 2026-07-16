// Deep DB-DR drill - Container Apps Job that runs the scheduled restore
// -> integrity -> smoke -> teardown cycle documented in
// docs/runbooks/db-dr-drill.md and implemented in
// src/fdai/core/verticals/db_dr_drill_cli.py.
//
// The job is opt-in: a fork enables it by setting
// var.dr_drill_enabled = true and supplying var.dr_drill_source_server_arm_id
// (the ARM id of the production Postgres Flexible Server whose PITR
// checkpoint the drill restores). Upstream ships the module unwired so a
// generic deploy does not incur drill cost until the fork opts in.
//
// The job reuses the same Container Apps environment + user-assigned MI
// as the core app - the drill's least-privilege identity gate lives in
// the fork's role-assignment module, not here.

resource "azurerm_container_app_job" "dr_drill" {
  count = var.dr_drill_enabled ? 1 : 0

  name                         = var.dr_drill_job_name
  container_app_environment_id = azurerm_container_app_environment.primary.id
  resource_group_name          = var.resource_group_name
  location                     = var.location
  // A drill can take 15-40 minutes for a small dev DB; a 1-hour ceiling
  // covers headroom without leaving a runaway job on the environment.
  replica_timeout_in_seconds = 3600
  replica_retry_limit        = 0 // Idempotency lives in the CLI, not here.

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
    // Default: 04:00 UTC on the 1st and 15th of each month - two runs a
    // month gives PITR coverage against the standard 7-day retention
    // without saturating the drill budget. A fork tunes as needed.
    cron_expression          = var.dr_drill_cron_expression
    replica_completion_count = 1
    parallelism              = 1
  }

  template {
    container {
      name    = "db-dr-drill"
      image   = var.image
      cpu     = 0.5
      memory  = "1.0Gi"
      command = ["python", "-m", "fdai.core.verticals.db_dr_drill_cli"]

      env {
        name  = "FDAI_DR_DRILL_SOURCE_SERVER_ARM_ID"
        value = var.dr_drill_source_server_arm_id
      }
      env {
        name  = "FDAI_DR_DRILL_TARGET_LOCATION"
        value = var.location
      }
      env {
        name  = "FDAI_DR_DRILL_TARGET_RG_PREFIX"
        value = var.dr_drill_target_rg_prefix
      }
      env {
        name  = "FDAI_DR_DRILL_TARGET_SERVER_PREFIX"
        value = var.dr_drill_target_server_prefix
      }
      env {
        name  = "FDAI_DR_DRILL_PITR_OFFSET_MINUTES"
        value = tostring(var.dr_drill_pitr_offset_minutes)
      }
      env {
        name  = "FDAI_DR_DRILL_DRY_RUN"
        value = var.dr_drill_dry_run ? "1" : "0"
      }
    }
  }

  tags = merge(var.tags, {
    purpose = "dr-drill"
  })
}
