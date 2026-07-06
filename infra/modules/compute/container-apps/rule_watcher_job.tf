// Rule-catalog source watcher — Container Apps Job that runs the watcher CLI
// on a daily cron. The watcher itself filters by manifest cadence, so the
// same job picks up weekly / monthly sources on their due day — no per-cadence
// job proliferation. See:
//
//   src/aiopspilot/rule_catalog/pipeline/watcher_cli.py
//   docs/roadmap/phases/phase-2-quality-and-t1.md § Continuous Rule Update Pipeline
//
// The job never auto-promotes: it produces snapshots + verify reports under
// rule-catalog/sources/<id>/<revision>/. Promotion into the T0 catalog stays a
// reviewed catalog-as-code PR.
//
// The job reuses the same Container Apps environment + user-assigned MI as the
// core app so no new seams are introduced.

resource "azurerm_container_app_job" "rule_watcher" {
  name                         = var.rule_watcher_job_name
  container_app_environment_id = azurerm_container_app_environment.primary.id
  resource_group_name          = var.resource_group_name
  location                     = var.location
  // Rule watcher is a short-lived batch: pull each due source, snapshot,
  // verify. Anything longer means a source manifest points at a huge tree
  // and needs its own dedicated job.
  replica_timeout_in_seconds = 900
  replica_retry_limit        = 2

  identity {
    type         = "UserAssigned"
    identity_ids = [var.executor_identity_id]
  }

  schedule_trigger_config {
    // 03:00 UTC daily — off-peak for all supported regions. The CLI itself
    // filters by cadence, so weekly / monthly sources also fire from here.
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
      command = ["python", "-m", "aiopspilot.rule_catalog.pipeline.watcher_cli"]
      // Only --verify is passed by default. Snapshots land under
      // /workspace/rule-catalog/sources which is baked into the image alongside
      // the source manifests. The container writes to an ephemeral path — the
      // actual PR-worthy diff is produced by a follow-up job that reads the
      // audit trail; that seam is deferred and lives outside this module.
      args = ["--verify"]
    }
  }

  tags = var.tags
}
