mock_provider "azurerm" {}

variables {
  env_name                            = "cae-fdai-example"
  core_app_name                       = "ca-fdai-example-core"
  oob_job_name                        = "caj-fdai-example-oob"
  rule_watcher_job_name               = "caj-fdai-example-watcher"
  provider_schema_job_name            = "caj-fdai-example-provider-schema"
  browser_evidence_cleanup_job_name   = "caj-fdai-example-browser-gc"
  location                            = "koreacentral"
  resource_group_name                 = "rg-example"
  log_workspace_id                    = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example/providers/Microsoft.OperationalInsights/workspaces/log-example"
  executor_identity_id                = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-executor"
  executor_identity_client_id         = "00000000-0000-0000-0000-000000000000"
  change_identity_client_id           = "00000000-0000-0000-0000-000000000000"
  resilience_identity_client_id       = "00000000-0000-0000-0000-000000000000"
  finops_identity_client_id           = "00000000-0000-0000-0000-000000000000"
  startup_kafka_settle_seconds        = 12
  startup_probe_timeout_seconds       = 30
  startup_phase_timeout_seconds       = 75
  inventory_identity_id               = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-inventory"
  inventory_identity_client_id        = "00000000-0000-0000-0000-000000000000"
  canary_identity_id                  = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-canary"
  canary_identity_client_id           = "00000000-0000-0000-0000-000000000000"
  canary_topic                        = "fdai.control.canary"
  operational_kafka_bootstrap_servers = "example.servicebus.windows.net:9093"
  inventory_dsn_secret_id             = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example/providers/Microsoft.KeyVault/vaults/kv-example/secrets/inventory-dsn"
  image                               = "mcr.microsoft.com/example/fdai@sha256:0000000000000000000000000000000000000000000000000000000000000000"
  azure_tenant_id                     = "00000000-0000-0000-0000-000000000000"
  azure_subscription_id               = "00000000-0000-0000-0000-000000000000"
  azure_resource_group                = "rg-example"
  azure_region                        = "koreacentral"
  kafka_bootstrap_servers             = "example.servicebus.windows.net:9093"
  postgres_host                       = "postgres.example.com"
  postgres_database                   = "fdai"
  runtime_env                         = "dev"
  extra_identity_ids = [
    "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-change",
    "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-resilience",
    "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-finops",
  ]
}

run "legacy_workflow_retains_vertical_identity_catalog" {
  command = plan

  assert {
    condition = alltrue([
      contains(output.attached_identity_ids, var.extra_identity_ids[0]),
      contains(output.attached_identity_ids, var.extra_identity_ids[1]),
      contains(output.attached_identity_ids, var.extra_identity_ids[2]),
    ])
    error_message = "legacy workflow compatibility MUST retain every declared vertical identity"
  }

  assert {
    condition = output.vertical_identity_client_ids == {
      change     = var.change_identity_client_id
      resilience = var.resilience_identity_client_id
      finops     = var.finops_identity_client_id
    }
    error_message = "legacy workflow compatibility MUST retain each vertical identity client id"
  }
}

run "scheduled_jobs_use_complete_non_executor_bindings" {
  command = plan

  variables {
    scheduler_cron_expression      = "* * * * *"
    scheduler_identity_id          = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-scheduler"
    scheduler_identity_client_id   = "00000000-0000-0000-0000-000000000001"
    state_store_dsn_secret_id      = "https://example.vault.azure.net/secrets/state-store-dsn"
    dr_drill_enabled               = true
    dr_drill_job_name              = "caj-fdai-example-drill"
    dr_drill_identity_id           = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-db-dr"
    dr_drill_identity_client_id    = "00000000-0000-0000-0000-000000000002"
    dr_drill_source_server_arm_id  = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-source/providers/Microsoft.DBforPostgreSQL/flexibleServers/psql-source"
    dr_drill_target_resource_group = "rg-db-dr"
    dr_drill_integrity_tables      = ["alembic_version"]
  }

  assert {
    condition = (
      azurerm_container_app_job.scheduler_tick[0].identity[0].identity_ids == toset([var.scheduler_identity_id]) &&
      azurerm_container_app_job.dr_drill[0].identity[0].identity_ids == toset([var.dr_drill_identity_id])
    )
    error_message = "scheduler and DB-DR must use distinct dedicated identities"
  }

  assert {
    condition = (
      azurerm_container_app_job.scheduler_tick[0].template[0].container[0].command == tolist(["python", "-m", "fdai.delivery.scheduler_tick_cli"]) &&
      azurerm_container_app_job.dr_drill[0].template[0].container[0].command == tolist(["python", "-m", "fdai.delivery.db_dr_drill_cli"])
    )
    error_message = "enabled jobs must invoke importable delivery entrypoints"
  }

  assert {
    condition = {
      for env in azurerm_container_app_job.dr_drill[0].template[0].container[0].env :
      env.name => env.secret_name if env.secret_name != null
    }["FDAI_STATE_STORE_DSN"] == "state-store-dsn"
    error_message = "DB-DR must receive the state DSN only through its Key Vault reference"
  }
}
