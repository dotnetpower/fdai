// Analyzer tick job - a Container Apps Job (cron) that drives the
// reference threshold analyzers out-of-band. Matches the event-driven /
// scale-to-zero shape (docs/roadmap/app-shape.instructions.md).
//
// The job launches `python -m fdai.delivery.analyzer_tick_cli` once per
// fire. The CLI reads FDAI_ANALYZER_TARGETS (a JSON list of
// {resource_id, kind} pairs), builds the container, instantiates the
// default_analyzers wired to whichever MetricProvider was bound at
// composition time (AML KQL, Prom, or the routed Prom-primary +
// AML-fallback composite), and logs any findings.
//
// Latency envelope: the tick cadence is bounded below by the metric
// backend's ingestion floor - Log Analytics has a 2-5 min lag, AKS
// Managed Prometheus scrapes every 15 s. Picking a 60 s cron is a
// safe default: it never runs faster than either backend can
// serve, and it recovers on the next fire when a tick fails.
//
// Opt-in: an empty `analyzer_tick_cron_expression` (the default)
// provisions no job, so day-zero applies are unchanged. FDAI_ANALYZER_TARGETS
// is required at runtime - the CLI exits 0 with a `no targets` info
// line when unset, so a stray misconfigured cron does not crash-loop.

resource "azurerm_container_app_job" "analyzer_tick" {
  count = var.analyzer_tick_cron_expression == "" ? 0 : 1

  name                         = "${var.core_app_name}-analyzer"
  container_app_environment_id = azurerm_container_app_environment.primary.id
  resource_group_name          = var.resource_group_name
  location                     = var.location
  // One analyzer pass. A tick that runs longer than this means the
  // target list has grown past its budget and needs sharding.
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

  schedule_trigger_config {
    cron_expression          = var.analyzer_tick_cron_expression
    replica_completion_count = 1
    parallelism              = 1
  }

  template {
    container {
      name    = "analyzer-tick"
      image   = var.image
      cpu     = 0.25
      memory  = "0.5Gi"
      command = ["python", "-m", "fdai.delivery.analyzer_tick_cli"]

      // Same required config env vars as the core app - the tick runs
      // the same image and would crash-loop on `ConfigError` without them.
      // Includes the optional adapter-wiring env vars (Prom / AML) so
      // whichever backend the deploy has bound is available inside the
      // tick's container binding too.
      dynamic "env" {
        for_each = merge(local.core_config_env, local.optional_config_env)
        content {
          name  = env.key
          value = env.value
        }
      }

      // Explicit target list. Empty / unset -> the CLI logs a
      // `no targets` info line and exits 0, so a misconfigured cron
      // stays quiet instead of crash-looping.
      env {
        name  = "FDAI_ANALYZER_TARGETS"
        value = var.analyzer_targets_json
      }

      // Analyzer window / budget (both optional; positive-number
      // validation lives in the CLI itself).
      dynamic "env" {
        for_each = var.analyzer_window_seconds == "" ? toset([]) : toset(["1"])
        content {
          name  = "FDAI_ANALYZER_WINDOW_SECONDS"
          value = var.analyzer_window_seconds
        }
      }

      dynamic "env" {
        for_each = var.analyzer_budget_seconds == "" ? toset([]) : toset(["1"])
        content {
          name  = "FDAI_ANALYZER_BUDGET_SECONDS"
          value = var.analyzer_budget_seconds
        }
      }
    }
  }

  tags = var.tags
}
