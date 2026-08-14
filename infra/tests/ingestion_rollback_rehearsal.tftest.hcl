# Compatibility retirement guard for the disabled legacy ingestion module.

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

run "reject_retired_cohost" {
  command = plan

  module {
    source = "./modules/ingestion-gateway/container-app"
  }

  variables {
    cohost_worker = true
  }

  expect_failures = [var.cohost_worker]
}
