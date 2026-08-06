# SD-03 rollback rehearsal: apply split, co-host, then split again in Terraform's
# disposable test state. Mock providers perform no Azure operations.

mock_provider "azurerm" {}

variables {
  name                             = "ca-fdai-ingestion"
  worker_name                      = "ca-fdai-ingestion-worker"
  migrate_job_name                 = "caj-fdai-docmig"
  container_app_environment_id     = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai/providers/Microsoft.App/managedEnvironments/cae-fdai"
  location                         = "koreacentral"
  resource_group_name              = "rg-fdai"
  image                            = "registry.example.com/fdai@sha256:0000000000000000000000000000000000000000000000000000000000000000"
  clamav_image                     = "registry.example.com/clamav@sha256:0000000000000000000000000000000000000000000000000000000000000000"
  identity_id                      = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-fdai-ingestion"
  identity_client_id               = "api-client"
  database_dsn_secret_id           = "https://vault.example.com/secrets/ingestion-api-dsn"
  api_database_role                = "fdai_ingestion_api"
  worker_identity_id               = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-fdai-ingestion-worker"
  worker_identity_client_id        = "worker-client"
  migration_identity_id            = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-fdai-ingestion-migration"
  migration_identity_client_id     = "migration-client"
  worker_database_dsn_secret_id    = "https://vault.example.com/secrets/ingestion-worker-dsn"
  migration_database_dsn_secret_id = "https://vault.example.com/secrets/ingestion-migration-dsn"
  stewardship_governance_enabled   = false
  gitops_owner                     = ""
  gitops_repo                      = ""
  gitops_token_secret_id           = ""
  github_webhook_secret_id         = ""
  chatops_webhook_url_secret_id    = ""
  stewardship_maintainers          = ""
  stewardship_agent_bindings       = {}
  entra_tenant_id                  = "00000000-0000-0000-0000-000000000000"
  api_audience                     = "00000000-0000-0000-0000-000000000000"
  rbac_readers_group_id            = "00000000-0000-0000-0000-000000000000"
  rbac_contributors_group_id       = "00000000-0000-0000-0000-000000000000"
  rbac_approvers_group_id          = "00000000-0000-0000-0000-000000000000"
  rbac_owners_group_id             = "00000000-0000-0000-0000-000000000000"
  rbac_break_glass_group_id        = "00000000-0000-0000-0000-000000000000"
  cors_allow_origins               = "https://console.example.com"
  adls_account_name                = "stfdaidoc"
  adls_account_url                 = "https://storage.example.com/"
  adls_source_file_system          = "documents"
  adls_derived_file_system         = "derived"
  embedding_endpoint               = "https://embedding.example.com/"
  embedding_deployment             = "embedding"
  ocr_endpoint                     = ""
  kafka_bootstrap_servers          = "kafka.example.com:9093"
  document_event_topic             = "aw.pipeline.stages"
  runtime_env                      = "dev"
  document_collections             = "operations"
}

run "establish_split_topology" {
  command = apply

  module {
    source = "./modules/ingestion-gateway/container-app"
  }

  assert {
    condition     = length(azurerm_container_app.worker) == 1
    error_message = "the rehearsal must start with an independently deployed ingestion worker"
  }

  assert {
    condition = one([
      for item in one([
        for container in azurerm_container_app.worker[0].template[0].container :
        container if container.name == "worker"
      ]).env : item.value if item.name == "FDAI_DOCUMENT_EVENT_TOPIC"
    ]) == "aw.pipeline.stages"
    error_message = "split mode must retain the pipeline stage topic"
  }

  assert {
    condition = one([
      for item in one([
        for container in azurerm_container_app.ingestion.template[0].container :
        container if container.name == "ingestion"
      ]).env : item.value if item.name == "FDAI_INGESTION_COHOST_WORKER"
    ]) == "0"
    error_message = "the rehearsal baseline must keep worker loops out of the API app"
  }

  assert {
    condition = (
      one([
        for container in azurerm_container_app.worker[0].template[0].container :
        container.image if container.name == "worker"
      ]) == var.image &&
      contains(azurerm_container_app_job.migrate.identity[0].identity_ids, var.migration_identity_id) &&
      one([
        for secret in azurerm_container_app_job.migrate.secret :
        secret.identity if secret.name == "database-dsn"
      ]) == var.migration_identity_id
    )
    error_message = "split mode must retain the immutable runtime and dedicated migration authority"
  }
}

run "rollback_to_cohost" {
  command = apply

  module {
    source = "./modules/ingestion-gateway/container-app"
  }

  variables {
    cohost_worker     = true
    api_database_role = "fdai_ingestion_cohost"
  }

  assert {
    condition     = length(azurerm_container_app.worker) == 0
    error_message = "co-host rollback must remove the independent worker topology"
  }

  assert {
    condition = one([
      for item in one([
        for container in azurerm_container_app.ingestion.template[0].container :
        container if container.name == "ingestion"
      ]).env : item.value if item.name == "FDAI_INGESTION_COHOST_WORKER"
    ]) == "1"
    error_message = "co-host rollback must start worker loops in the API app"
  }

  assert {
    condition = one([
      for item in one([
        for container in azurerm_container_app.ingestion.template[0].container :
        container if container.name == "ingestion"
      ]).env : item.value if item.name == "FDAI_DOCUMENT_EVENT_TOPIC"
    ]) == "aw.pipeline.stages"
    error_message = "co-host rollback must retain the pipeline stage topic"
  }

  assert {
    condition = (
      one([
        for container in azurerm_container_app.ingestion.template[0].container :
        container.image if container.name == "ingestion"
      ]) == var.image &&
      contains(azurerm_container_app_job.migrate.identity[0].identity_ids, var.migration_identity_id) &&
      one([
        for secret in azurerm_container_app_job.migrate.secret :
        secret.identity if secret.name == "database-dsn"
      ]) == var.migration_identity_id
    )
    error_message = "co-host rollback must not replace the runtime or move migration authority"
  }
}

run "restore_split_topology" {
  command = apply

  module {
    source = "./modules/ingestion-gateway/container-app"
  }

  assert {
    condition     = length(azurerm_container_app.worker) == 1
    error_message = "the rehearsal must restore the independent ingestion worker"
  }

  assert {
    condition = one([
      for item in one([
        for container in azurerm_container_app.worker[0].template[0].container :
        container if container.name == "worker"
      ]).env : item.value if item.name == "FDAI_DOCUMENT_EVENT_TOPIC"
    ]) == "aw.pipeline.stages"
    error_message = "split restore must return to the original pipeline stage topic"
  }

  assert {
    condition = one([
      for item in one([
        for container in azurerm_container_app.ingestion.template[0].container :
        container if container.name == "ingestion"
      ]).env : item.value if item.name == "FDAI_INGESTION_COHOST_WORKER"
    ]) == "0"
    error_message = "split restore must remove worker loops from the API app"
  }

  assert {
    condition = (
      one([
        for container in azurerm_container_app.worker[0].template[0].container :
        container.image if container.name == "worker"
      ]) == var.image &&
      contains(azurerm_container_app_job.migrate.identity[0].identity_ids, var.migration_identity_id) &&
      one([
        for secret in azurerm_container_app_job.migrate.secret :
        secret.identity if secret.name == "database-dsn"
      ]) == var.migration_identity_id
    )
    error_message = "split restore must recover the original runtime and migration authority"
  }
}
