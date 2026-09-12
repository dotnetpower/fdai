mock_provider "azurerm" {}
mock_provider "archive" {}

override_data {
  target = data.azurerm_client_config.current
  values = {
    subscription_id = "00000000-0000-0000-0000-000000000000"
    tenant_id       = "00000000-0000-0000-0000-000000000000"
    object_id       = "00000000-0000-0000-0000-000000000001"
  }
}

override_data {
  target = data.azurerm_container_app_environment.cost_governance[0]
  values = {
    id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai-dev-krc/providers/Microsoft.App/managedEnvironments/cae-fdai-dev-krc"
  }
}

override_data {
  target = data.azurerm_user_assigned_identity.cost_governance_inventory[0]
  values = {
    id        = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai-dev-krc/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-fdai-dev-krc-inventory"
    client_id = "00000000-0000-0000-0000-000000000002"
  }
}

variables {
  env                                       = "dev"
  region                                    = "koreacentral"
  region_short                              = "krc"
  deploy_runner_principal_id                = "00000000-0000-0000-0000-000000000001"
  tenant_id                                 = "00000000-0000-0000-0000-000000000000"
  postgres_admin_login                      = "fdaiadmin"
  postgres_admin_password                   = "terraform-test-placeholder-value"
  core_image                                = "mcr.microsoft.com/example/fdai@sha256:0000000000000000000000000000000000000000000000000000000000000000"
  cost_governance_image                     = "example.azurecr.io/fdai-cost-governance@sha256:1111111111111111111111111111111111111111111111111111111111111111"
  cost_governance_collector_cron_expression = "0 */6 * * *"
  cost_governance_analyzer_cron_expression  = "30 */6 * * *"
  cost_governance_scope_id                  = "/subscriptions/00000000-0000-0000-0000-000000000000"
  cost_governance_known_service_ids_json    = "[\"Compute\"]"
  cost_governance_ontology_release_id       = "ontology-release:example"
  cost_governance_ontology_release_digest   = "sha256:2222222222222222222222222222222222222222222222222222222222222222"
}

run "package_jobs_are_root_owned" {
  command = plan

  assert {
    condition = (
      length(azurerm_container_app_job.cost_governance_collector) == 1 &&
      length(azurerm_container_app_job.cost_governance_analyzer) == 1
    )
    error_message = "Cost Governance must plan exactly two root-owned Jobs."
  }

  assert {
    condition = (
      azurerm_container_app_job.cost_governance_collector[0].container_app_environment_id ==
      data.azurerm_container_app_environment.cost_governance[0].id &&
      azurerm_container_app_job.cost_governance_analyzer[0].identity[0].identity_ids ==
      toset([data.azurerm_user_assigned_identity.cost_governance_inventory[0].id])
    )
    error_message = "Cost Governance Jobs must bind existing platform environment and inventory identity data."
  }

  assert {
    condition = (
      one(azurerm_container_app_job.cost_governance_collector[0].secret).key_vault_secret_id ==
      "https://kv-fdai-dev-krc.vault.azure.net/secrets/fdai-state-store-dsn" &&
      one(azurerm_container_app_job.cost_governance_analyzer[0].secret).key_vault_secret_id ==
      "https://kv-fdai-dev-krc.vault.azure.net/secrets/fdai-state-store-dsn"
    )
    error_message = "Cost Governance Jobs must use the versionless Key Vault secret URI."
  }

  assert {
    condition = (
      module.compute.cost_governance_collector_job_name == null &&
      module.compute.cost_governance_analyzer_job_name == null &&
      output.cost_governance_collector_job_name == "caj-fdai-dev-cost-collect" &&
      output.cost_governance_analyzer_job_name == "caj-fdai-dev-cost-analyze"
    )
    error_message = "Only root Terraform may export the active Cost Governance Job names."
  }
}

run "package_jobs_and_lookups_are_absent_without_schedules" {
  command = plan

  variables {
    cost_governance_collector_cron_expression = ""
    cost_governance_analyzer_cron_expression  = ""
  }

  assert {
    condition = (
      length(azurerm_container_app_job.cost_governance_collector) == 0 &&
      length(azurerm_container_app_job.cost_governance_analyzer) == 0 &&
      length(data.azurerm_container_app_environment.cost_governance) == 0 &&
      length(data.azurerm_user_assigned_identity.cost_governance_inventory) == 0
    )
    error_message = "Disabled Cost Governance schedules must create no Jobs or prerequisite reads."
  }
}