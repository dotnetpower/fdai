# Plan-level evidence for independent ingestion API, worker, and migration roles.
# All values are synthetic; mock providers perform no Azure operations.

mock_provider "azurerm" {}
mock_provider "archive" {}

override_module {
  target = module.identity
  outputs = {
    resource_id  = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-fdai-executor"
    client_id    = "executor-client"
    principal_id = "executor-principal"
  }
}

override_module {
  target = module.ingestion_identity
  outputs = {
    resource_id  = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-fdai-ingestion"
    client_id    = "api-client"
    principal_id = "api-principal"
  }
}

override_module {
  target = module.ingestion_worker_identity
  outputs = {
    resource_id  = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-fdai-ingestion-worker"
    client_id    = "worker-client"
    principal_id = "worker-principal"
  }
}

override_module {
  target = module.ingestion_migration_identity
  outputs = {
    resource_id  = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-fdai-ingestion-migration"
    client_id    = "migration-client"
    principal_id = "migration-principal"
  }
}

override_module {
  target = module.document_storage
  outputs = {
    id                    = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai/providers/Microsoft.Storage/storageAccounts/stfdaidoc"
    name                  = "stfdaidoc"
    primary_dfs_endpoint  = "https://stfdaidoc.dfs.example.com/"
    primary_blob_endpoint = "https://stfdaidoc.blob.example.com/"
    source_file_system    = "documents"
    derived_file_system   = "derived"
  }
}

variables {
  region                         = "koreacentral"
  tenant_id                      = "00000000-0000-0000-0000-000000000000"
  postgres_admin_login           = "fdaiadmin"
  postgres_admin_password        = "terraform-test-placeholder-value"
  core_image                     = "mcr.microsoft.com/example/fdai@sha256:0000000000000000000000000000000000000000000000000000000000000000"
  enable_document_ingestion      = true
  enable_llm                     = true
  operator_api_audience          = "00000000-0000-0000-0000-000000000000"
  rbac_readers_group_id          = "00000000-0000-0000-0000-000000000000"
  rbac_contributors_group_id     = "00000000-0000-0000-0000-000000000000"
  rbac_approvers_group_id        = "00000000-0000-0000-0000-000000000000"
  rbac_owners_group_id           = "00000000-0000-0000-0000-000000000000"
  rbac_break_glass_group_id      = "00000000-0000-0000-0000-000000000000"
  ingestion_cors_allow_origins   = "https://console.example.com"
  ingestion_embedding_capability = "t1.embedding"
  resolved_capabilities = [{
    name         = "t1.embedding"
    family       = "text-embedding-3-small"
    sku          = "Standard"
    capacity_tpm = 10000
  }]
}

run "split_roles_are_independent_by_default" {
  command = plan

  variables {
    ingestion_worker_min_replicas = 1
    ingestion_worker_max_replicas = 2
    ingestion_worker_cpu          = 2
    ingestion_worker_memory       = "4Gi"
  }

  assert {
    condition     = length(module.ingestion_worker_identity) == 1
    error_message = "split mode must provision a dedicated worker identity"
  }

  assert {
    condition     = module.ingestion_gateway[0].worker_name != ""
    error_message = "split mode must provision the internal worker Container App"
  }

  assert {
    condition = (
      module.ingestion_identity[0].principal_id != module.identity.principal_id &&
      module.ingestion_worker_identity[0].principal_id != module.identity.principal_id
    )
    error_message = "ingestion API and worker identities must remain distinct from Thor's executor"
  }

  assert {
    condition = (
      azurerm_role_assignment.ingestion_worker_pantheon_receiver[0].principal_id ==
      module.ingestion_worker_identity[0].principal_id
    )
    error_message = "Event Hubs receive must belong to the worker identity"
  }

  assert {
    condition = (
      azurerm_role_assignment.ingestion_eventhubs_sender[0].principal_id ==
      module.ingestion_identity[0].principal_id
    )
    error_message = "the API identity must retain send-only event publication"
  }

  assert {
    condition = (
      length(azurerm_role_assignment.ingestion_document_data) == 1 &&
      azurerm_role_assignment.ingestion_document_data[0].role_definition_name ==
      "Storage Blob Data Contributor" &&
      azurerm_role_assignment.ingestion_document_data[0].scope ==
      module.document_storage[0].id &&
      azurerm_role_assignment.ingestion_document_data[0].principal_id ==
      module.ingestion_identity[0].principal_id &&
      azurerm_role_assignment.ingestion_document_data[0].principal_id !=
      module.identity.principal_id
    )
    error_message = "the API must have exactly one account-scoped ADLS contributor role without executor spread"
  }

  assert {
    condition = (
      length(azurerm_role_assignment.ingestion_worker_document_data) == 1 &&
      azurerm_role_assignment.ingestion_worker_document_data[0].role_definition_name ==
      "Storage Blob Data Contributor" &&
      azurerm_role_assignment.ingestion_worker_document_data[0].scope ==
      module.document_storage[0].id &&
      azurerm_role_assignment.ingestion_worker_document_data[0].principal_id ==
      module.ingestion_worker_identity[0].principal_id &&
      azurerm_role_assignment.ingestion_worker_document_data[0].principal_id !=
      module.identity.principal_id
    )
    error_message = "the worker must have exactly one account-scoped ADLS contributor role without executor spread"
  }

  assert {
    condition = (
      azurerm_role_assignment.ingestion_migration_kv_secrets_user[0].principal_id ==
      module.ingestion_migration_identity[0].principal_id
    )
    error_message = "the administrator DSN must belong only to the migration identity"
  }
}

run "cohost_flag_restores_single_app_rollback" {
  command = plan

  variables {
    ingestion_cohost_worker = true
  }

  assert {
    condition     = length(module.ingestion_worker_identity) == 0
    error_message = "co-host rollback must remove the split worker identity"
  }

  assert {
    condition     = module.ingestion_gateway[0].worker_name == ""
    error_message = "co-host rollback must remove the split worker Container App"
  }

  assert {
    condition = (
      azurerm_role_assignment.ingestion_eventhubs_receiver[0].principal_id ==
      module.ingestion_identity[0].principal_id
    )
    error_message = "co-host rollback must return receive permission to the API identity"
  }

  assert {
    condition = (
      length(azurerm_role_assignment.ingestion_document_data) == 1 &&
      azurerm_role_assignment.ingestion_document_data[0].role_definition_name ==
      "Storage Blob Data Contributor" &&
      azurerm_role_assignment.ingestion_document_data[0].scope ==
      module.document_storage[0].id &&
      azurerm_role_assignment.ingestion_document_data[0].principal_id ==
      module.ingestion_identity[0].principal_id &&
      azurerm_role_assignment.ingestion_document_data[0].principal_id !=
      module.identity.principal_id
    )
    error_message = "co-host rollback must keep one API-owned ADLS contributor role without executor spread"
  }

  assert {
    condition     = length(azurerm_role_assignment.ingestion_worker_document_data) == 0
    error_message = "co-host rollback must not retain a separate worker ADLS role"
  }
}

run "worker_scale_to_zero_is_rejected_without_kafka_scaler" {
  command = plan

  variables {
    ingestion_worker_min_replicas = 0
  }

  expect_failures = [var.ingestion_worker_min_replicas]
}
