// Phase-4 continuous-measurement runners - Container Apps Jobs that wire the
// two library-only measurement modules into scheduled processes:
//
//   src/fdai/core/measurement/runners.py::AutomatedBaselineRunner
//   src/fdai/core/measurement/runners.py::PatternGrowthIntakeRunner
//
// See:
//   docs/roadmap/phases/phase-4-scale.md § Continuous Measurement
//   docs/roadmap/phases/phase-4-scale.md § Pattern Library Growth (T1)
//
// Two jobs, one shared Container Apps environment + user-assigned MI (the
// same one the core app + rule-watcher already use). No new seams are
// introduced - cadence + identity + logging are provided by the caller so a
// non-Azure adapter can render the same manifest without touching the core.
//
// Safety
// ------
// * The regression runner NEVER auto-promotes; it only demotes an ActionType
//   back to shadow through ActionPromotionRegistry.demote(). The cron
//   therefore fires with the least-privileged executor identity - no extra
//   Contributor role is needed.
// * The growth runner ingests candidate patterns in **shadow** mode
//   (historical_success_rate=0.0); the T1 tier's min_success_rate floor
//   keeps them out of execution until a reviewed promotion step measures
//   and lifts them.

resource "azurerm_container_app_job" "baseline_regression" {
  name                         = var.baseline_job_name
  container_app_environment_id = var.container_app_environment_id
  resource_group_name          = var.resource_group_name
  location                     = var.location
  // One full replay of the P0 scenario set. If a replay takes longer than
  // this, the scenario set has grown past its budget and needs to be split.
  replica_timeout_in_seconds = 1800
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

  secret {
    name                = "state-store-dsn"
    identity            = var.executor_identity_id
    key_vault_secret_id = var.state_store_dsn_secret_id
  }

  schedule_trigger_config {
    // Daily at 02:00 UTC - off-peak for all supported regions; runs before
    // the 03:00 UTC rule-watcher so a fresh rule promotion still sees the
    // regression signal from the prior day.
    cron_expression          = var.baseline_cron_expression
    replica_completion_count = 1
    parallelism              = 1
  }

  template {
    container {
      name    = "measurement-baseline"
      image   = var.image
      cpu     = 0.5
      memory  = "1Gi"
      command = ["python", "-m", "fdai.delivery.measurement_runner_cli"]
      args    = ["baseline"]

      env {
        name  = "FDAI_SCENARIO_SET_VERSION"
        value = var.scenario_set_version
      }
      env {
        name  = "FDAI_MEASUREMENT_MODE"
        value = "baseline"
      }
      env {
        name        = "FDAI_STATE_STORE_DSN"
        secret_name = "state-store-dsn"
      }
      dynamic "env" {
        for_each = var.environment
        content {
          name  = env.key
          value = env.value
        }
      }
    }
  }

  tags = var.tags
}

resource "azurerm_container_app_job" "pattern_growth" {
  name                         = var.growth_job_name
  container_app_environment_id = var.container_app_environment_id
  resource_group_name          = var.resource_group_name
  location                     = var.location
  // A single drain of the audit outcome stream. Anything longer indicates
  // the audit tail grew unboundedly and the drain cadence needs to be
  // shortened, not this timeout raised.
  replica_timeout_in_seconds = 600
  replica_retry_limit        = 3

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


  secret {
    name                = "state-store-dsn"
    identity            = var.executor_identity_id
    key_vault_secret_id = var.state_store_dsn_secret_id
  }

  schedule_trigger_config {
    // Every 15 minutes - "continuous" in the phase-4 sense: the job wakes,
    // drains, and exits so an idle system scales to zero.
    cron_expression          = var.growth_cron_expression
    replica_completion_count = 1
    parallelism              = 1
  }

  template {
    container {
      name    = "measurement-growth"
      image   = var.image
      cpu     = 0.25
      memory  = "0.5Gi"
      command = ["python", "-m", "fdai.delivery.measurement_runner_cli"]
      args    = ["growth"]

      env {
        name  = "FDAI_MEASUREMENT_MODE"
        value = "growth"
      }
      env {
        name        = "FDAI_STATE_STORE_DSN"
        secret_name = "state-store-dsn"
      }
      dynamic "env" {
        for_each = var.environment
        content {
          name  = env.key
          value = env.value
        }
      }
    }
  }

  tags = var.tags
}
