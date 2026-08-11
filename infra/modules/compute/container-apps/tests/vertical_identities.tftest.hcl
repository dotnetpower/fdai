mock_provider "azurerm" {}

variables {
  env_name                            = "cae-fdai-example"
  core_app_name                       = "ca-fdai-example-core"
  oob_job_name                        = "caj-fdai-example-oob"
  rule_watcher_job_name               = "caj-fdai-example-watcher"
  location                            = "koreacentral"
  resource_group_name                 = "rg-example"
  log_workspace_id                    = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example/providers/Microsoft.OperationalInsights/workspaces/log-example"
  executor_identity_id                = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-executor"
  executor_identity_client_id         = "00000000-0000-0000-0000-000000000000"
  change_identity_client_id           = "00000000-0000-0000-0000-000000000000"
  resilience_identity_client_id       = "00000000-0000-0000-0000-000000000000"
  finops_identity_client_id           = "00000000-0000-0000-0000-000000000000"
  t1_similarity_threshold             = 0.8
  t1_min_success_rate                 = 0.9
  quality_gate_confidence_threshold   = 0.7
  quality_gate_quorum                 = 2
  startup_kafka_settle_seconds        = 12
  startup_probe_timeout_seconds       = 30
  startup_phase_timeout_seconds       = 75
  inventory_identity_id               = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-inventory"
  inventory_identity_client_id        = "00000000-0000-0000-0000-000000000000"
  inventory_raw_topic                 = "aw.inventory.raw"
  canary_identity_id                  = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-canary"
  canary_identity_client_id           = "00000000-0000-0000-0000-000000000000"
  canary_topic                        = "aw.control.canary"
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
