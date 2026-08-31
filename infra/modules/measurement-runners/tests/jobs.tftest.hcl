mock_provider "azurerm" {}

variables {
  baseline_job_name              = "caj-fdai-example-baseline"
  growth_job_name                = "caj-fdai-example-growth"
  operational_promotion_job_name = "caj-fdai-example-promotion"
  container_app_environment_id   = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example/providers/Microsoft.App/managedEnvironments/cae-example"
  location                       = "koreacentral"
  resource_group_name            = "rg-example"
  measurement_identity_id        = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-example-measurement"
  image                          = "example.azurecr.io/fdai@sha256:0000000000000000000000000000000000000000000000000000000000000000"
  acr_login_server               = "example.azurecr.io"
  scenario_set_version           = "v2026.07"
  state_store_dsn_secret_id      = "https://example.vault.azure.net/secrets/state-store"
}

run "all_jobs_are_disabled_by_default" {
  command = plan

  assert {
    condition = (
      length(azurerm_container_app_job.baseline_regression) == 0 &&
      length(azurerm_container_app_job.pattern_growth) == 0 &&
      length(azurerm_container_app_job.operational_promotion) == 0
    )
    error_message = "every measurement Job must be opt-in"
  }

  assert {
    condition = (
      output.baseline_job_name == null &&
      output.growth_job_name == null &&
      output.operational_promotion_job_name == null
    )
    error_message = "disabled measurement Job outputs must remain null"
  }
}

run "enabled_jobs_preserve_bounded_contracts" {
  command = plan

  variables {
    baseline_enabled                    = true
    growth_enabled                      = true
    operational_promotion_enabled       = true
    operational_promotion_fdai_revision = "0000000000000000000000000000000000000000"
    operational_promotion_evidence_root = "/evidence"
    operational_promotion_manifest      = "manifest.json"
  }

  assert {
    condition = alltrue([
      for job in [
        azurerm_container_app_job.baseline_regression[0],
        azurerm_container_app_job.pattern_growth[0],
        azurerm_container_app_job.operational_promotion[0],
      ] : job.identity[0].identity_ids == toset([var.measurement_identity_id])
    ])
    error_message = "measurement Jobs must attach only the dedicated non-executor identity"
  }

  assert {
    condition = alltrue([
      for job in [
        azurerm_container_app_job.baseline_regression[0],
        azurerm_container_app_job.pattern_growth[0],
        azurerm_container_app_job.operational_promotion[0],
        ] : (
        one(job.secret).identity == var.measurement_identity_id &&
        one(job.secret).key_vault_secret_id == var.state_store_dsn_secret_id
      )
    ])
    error_message = "measurement Jobs must expose only the Key Vault secret reference"
  }

  assert {
    condition = (
      azurerm_container_app_job.baseline_regression[0].schedule_trigger_config[0].cron_expression == "0 2 * * *" &&
      azurerm_container_app_job.baseline_regression[0].schedule_trigger_config[0].replica_completion_count == 1 &&
      azurerm_container_app_job.baseline_regression[0].schedule_trigger_config[0].parallelism == 1 &&
      azurerm_container_app_job.baseline_regression[0].replica_timeout_in_seconds == 1800 &&
      azurerm_container_app_job.baseline_regression[0].replica_retry_limit == 2 &&
      azurerm_container_app_job.baseline_regression[0].template[0].container[0].cpu == 0.5 &&
      azurerm_container_app_job.baseline_regression[0].template[0].container[0].memory == "1Gi"
    )
    error_message = "baseline Job schedule and resource bounds must remain reviewed"
  }

  assert {
    condition = (
      azurerm_container_app_job.pattern_growth[0].schedule_trigger_config[0].cron_expression == "*/15 * * * *" &&
      azurerm_container_app_job.pattern_growth[0].schedule_trigger_config[0].replica_completion_count == 1 &&
      azurerm_container_app_job.pattern_growth[0].schedule_trigger_config[0].parallelism == 1 &&
      azurerm_container_app_job.pattern_growth[0].replica_timeout_in_seconds == 600 &&
      azurerm_container_app_job.pattern_growth[0].replica_retry_limit == 3 &&
      azurerm_container_app_job.pattern_growth[0].template[0].container[0].cpu == 0.25 &&
      azurerm_container_app_job.pattern_growth[0].template[0].container[0].memory == "0.5Gi"
    )
    error_message = "growth Job schedule and resource bounds must remain reviewed"
  }

  assert {
    condition = (
      azurerm_container_app_job.operational_promotion[0].schedule_trigger_config[0].cron_expression == "30 2 * * *" &&
      azurerm_container_app_job.operational_promotion[0].schedule_trigger_config[0].replica_completion_count == 1 &&
      azurerm_container_app_job.operational_promotion[0].schedule_trigger_config[0].parallelism == 1 &&
      azurerm_container_app_job.operational_promotion[0].replica_timeout_in_seconds == 1800 &&
      azurerm_container_app_job.operational_promotion[0].replica_retry_limit == 1 &&
      azurerm_container_app_job.operational_promotion[0].template[0].container[0].cpu == 0.5 &&
      azurerm_container_app_job.operational_promotion[0].template[0].container[0].memory == "1Gi"
    )
    error_message = "operational-promotion Job schedule and resource bounds must remain reviewed"
  }

  assert {
    condition = alltrue([
      for job in [
        azurerm_container_app_job.baseline_regression[0],
        azurerm_container_app_job.pattern_growth[0],
        azurerm_container_app_job.operational_promotion[0],
        ] : (
        job.template[0].container[0].command == tolist(["python", "-m", "fdai.delivery.measurement_runner_cli"]) &&
        {
          for env in job.template[0].container[0].env :
          env.name => env.secret_name if env.secret_name != null
        }["FDAI_STATE_STORE_DSN"] == "state-store-dsn"
      )
    ])
    error_message = "every measurement Job must use the delivery CLI and secret-backed state"
  }

  assert {
    condition = (
      azurerm_container_app_job.baseline_regression[0].template[0].container[0].args == tolist(["baseline"]) &&
      azurerm_container_app_job.pattern_growth[0].template[0].container[0].args == tolist(["growth"]) &&
      azurerm_container_app_job.operational_promotion[0].template[0].container[0].args == tolist(["operational-promotion"])
    )
    error_message = "measurement Job arguments must select the reviewed delivery modes"
  }
}
