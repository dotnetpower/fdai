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

override_module {
  target = module.llm_azure_openai
  outputs = {
    endpoint       = "https://models.example.com/"
    resource_id    = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai/providers/Microsoft.CognitiveServices/accounts/oai-fdai"
    deployments    = { "t1.embedding" = "embedding" }
    capacity_units = { "t1.embedding" = 10 }
  }
}

override_module {
  target = module.event_bus
  outputs = {
    namespace_id    = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai/providers/Microsoft.EventHub/namespaces/evhns-fdai"
    namespace_name  = "evhns-fdai"
    kafka_bootstrap = "evhns-fdai.servicebus.example.com:9093"
    topics = [
      "aw.change.events",
      "aw.dr.events",
      "aw.finops.events",
      "aw.pantheon.objects",
    ]
    topic_ids = {
      "aw.change.events"    = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai/providers/Microsoft.EventHub/namespaces/evhns-fdai/eventhubs/aw.change.events"
      "aw.dr.events"        = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai/providers/Microsoft.EventHub/namespaces/evhns-fdai/eventhubs/aw.dr.events"
      "aw.finops.events"    = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai/providers/Microsoft.EventHub/namespaces/evhns-fdai/eventhubs/aw.finops.events"
      "aw.pantheon.objects" = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai/providers/Microsoft.EventHub/namespaces/evhns-fdai/eventhubs/aw.pantheon.objects"
    }
    dlq_topics = [
      "aw.change.events.dlq",
      "aw.dr.events.dlq",
      "aw.finops.events.dlq",
      "aw.pantheon.objects.dlq",
    ]
    dlq_topic_ids = {
      "aw.change.events.dlq"    = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai/providers/Microsoft.EventHub/namespaces/evhns-fdai/eventhubs/aw.change.events.dlq"
      "aw.dr.events.dlq"        = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai/providers/Microsoft.EventHub/namespaces/evhns-fdai/eventhubs/aw.dr.events.dlq"
      "aw.finops.events.dlq"    = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai/providers/Microsoft.EventHub/namespaces/evhns-fdai/eventhubs/aw.finops.events.dlq"
      "aw.pantheon.objects.dlq" = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai/providers/Microsoft.EventHub/namespaces/evhns-fdai/eventhubs/aw.pantheon.objects.dlq"
    }
    auxiliary_topic_ids = {
      "aw.hil.decisions"   = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai/providers/Microsoft.EventHub/namespaces/evhns-fdai/eventhubs/aw.hil.decisions"
      "aw.pipeline.stages" = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai/providers/Microsoft.EventHub/namespaces/evhns-fdai/eventhubs/aw.pipeline.stages"
    }
    all_topic_ids = {
      "aw.change.events"        = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai/providers/Microsoft.EventHub/namespaces/evhns-fdai/eventhubs/aw.change.events"
      "aw.dr.events"            = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai/providers/Microsoft.EventHub/namespaces/evhns-fdai/eventhubs/aw.dr.events"
      "aw.finops.events"        = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai/providers/Microsoft.EventHub/namespaces/evhns-fdai/eventhubs/aw.finops.events"
      "aw.pantheon.objects"     = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai/providers/Microsoft.EventHub/namespaces/evhns-fdai/eventhubs/aw.pantheon.objects"
      "aw.change.events.dlq"    = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai/providers/Microsoft.EventHub/namespaces/evhns-fdai/eventhubs/aw.change.events.dlq"
      "aw.dr.events.dlq"        = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai/providers/Microsoft.EventHub/namespaces/evhns-fdai/eventhubs/aw.dr.events.dlq"
      "aw.finops.events.dlq"    = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai/providers/Microsoft.EventHub/namespaces/evhns-fdai/eventhubs/aw.finops.events.dlq"
      "aw.pantheon.objects.dlq" = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai/providers/Microsoft.EventHub/namespaces/evhns-fdai/eventhubs/aw.pantheon.objects.dlq"
      "aw.hil.decisions"        = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai/providers/Microsoft.EventHub/namespaces/evhns-fdai/eventhubs/aw.hil.decisions"
      "aw.pipeline.stages"      = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai/providers/Microsoft.EventHub/namespaces/evhns-fdai/eventhubs/aw.pipeline.stages"
    }
  }
}

override_module {
  target = module.event_bus_auxiliary
  outputs = {
    namespace_id    = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai/providers/Microsoft.EventHub/namespaces/evhns-fdai-ops"
    namespace_name  = "evhns-fdai-ops"
    kafka_bootstrap = "evhns-fdai-ops.servicebus.example.com:9093"
    topics          = ["aw.control.canary", "runtime.startup.probe"]
    topic_ids = {
      "aw.control.canary"     = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai/providers/Microsoft.EventHub/namespaces/evhns-fdai-ops/eventhubs/aw.control.canary"
      "runtime.startup.probe" = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai/providers/Microsoft.EventHub/namespaces/evhns-fdai-ops/eventhubs/runtime.startup.probe"
    }
    dlq_topics = [
      "aw.control.canary.dlq",
      "runtime.startup.probe.dlq",
    ]
    dlq_topic_ids = {
      "aw.control.canary.dlq"     = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai/providers/Microsoft.EventHub/namespaces/evhns-fdai-ops/eventhubs/aw.control.canary.dlq"
      "runtime.startup.probe.dlq" = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai/providers/Microsoft.EventHub/namespaces/evhns-fdai-ops/eventhubs/runtime.startup.probe.dlq"
    }
    auxiliary_topic_ids = {
      "aw.inventory.raw" = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai/providers/Microsoft.EventHub/namespaces/evhns-fdai-ops/eventhubs/aw.inventory.raw"
    }
    all_topic_ids = {
      "aw.control.canary"         = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai/providers/Microsoft.EventHub/namespaces/evhns-fdai-ops/eventhubs/aw.control.canary"
      "runtime.startup.probe"     = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai/providers/Microsoft.EventHub/namespaces/evhns-fdai-ops/eventhubs/runtime.startup.probe"
      "aw.control.canary.dlq"     = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai/providers/Microsoft.EventHub/namespaces/evhns-fdai-ops/eventhubs/aw.control.canary.dlq"
      "runtime.startup.probe.dlq" = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai/providers/Microsoft.EventHub/namespaces/evhns-fdai-ops/eventhubs/runtime.startup.probe.dlq"
      "aw.inventory.raw"          = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai/providers/Microsoft.EventHub/namespaces/evhns-fdai-ops/eventhubs/aw.inventory.raw"
    }
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

  assert {
    condition = (
      output.ingestion_effective_access_evidence.contract_version == "1.0" &&
      output.ingestion_effective_access_evidence.evidence_class == "terraform-static" &&
      output.ingestion_effective_access_evidence.enabled &&
      output.ingestion_effective_access_evidence.topology == "split"
    )
    error_message = "split mode must emit the versioned Terraform static-access evidence contract"
  }

  assert {
    condition = (
      output.ingestion_effective_access_evidence.checks.identities_distinct_from_executor &&
      output.ingestion_effective_access_evidence.checks.runtime_identities_are_distinct &&
      length(output.ingestion_effective_access_evidence.checks.executor_authority_role_overlap) == 0
    )
    error_message = "split ingestion identities must be mutually distinct and exclude executor authority roles"
  }

  assert {
    condition = (
      output.ingestion_effective_access_evidence.identities.api.database_role == "fdai_ingestion_api" &&
      output.ingestion_effective_access_evidence.identities.worker.database_role == "fdai_ingestion_worker" &&
      output.ingestion_effective_access_evidence.identities.migration.database_role == var.postgres_admin_login
    )
    error_message = "split evidence must name the API, worker, and migration database roles"
  }

  assert {
    condition = (
      length(output.ingestion_effective_access_evidence.identities.api.expected_role_assignments) == 5 &&
      toset([
        for assignment in output.ingestion_effective_access_evidence.identities.api.expected_role_assignments :
        assignment.role_name
        ]) == toset([
        "AcrPull",
        "Azure Event Hubs Data Sender",
        "Cognitive Services OpenAI User",
        "Key Vault Secrets User",
        "Storage Blob Data Contributor",
      ]) &&
      contains(
        output.ingestion_effective_access_evidence.identities.api.expected_role_assignments,
        {
          role_name = "Storage Blob Data Contributor"
          scope     = module.document_storage[0].id
        },
      ) &&
      contains(
        output.ingestion_effective_access_evidence.identities.api.expected_role_assignments,
        {
          role_name = "Azure Event Hubs Data Sender"
          scope     = module.event_bus.auxiliary_topic_ids["aw.pipeline.stages"]
        },
      )
    )
    error_message = "the API role ceiling must be exact and retain account-scoped ADLS plus topic-scoped Event Hubs send"
  }

  assert {
    condition = (
      length(output.ingestion_effective_access_evidence.identities.worker.expected_role_assignments) == 6 &&
      toset([
        for assignment in output.ingestion_effective_access_evidence.identities.worker.expected_role_assignments :
        assignment.role_name
        ]) == toset([
        "AcrPull",
        "Azure Event Hubs Data Receiver",
        "Azure Event Hubs Data Sender",
        "Cognitive Services OpenAI User",
        "Key Vault Secrets User",
        "Storage Blob Data Contributor",
      ]) &&
      contains(
        output.ingestion_effective_access_evidence.identities.worker.expected_role_assignments,
        {
          role_name = "Storage Blob Data Contributor"
          scope     = module.document_storage[0].id
        },
      ) &&
      contains(
        output.ingestion_effective_access_evidence.identities.worker.expected_role_assignments,
        {
          role_name = "Azure Event Hubs Data Receiver"
          scope     = module.event_bus.topic_ids["aw.pantheon.objects"]
        },
      ) &&
      contains(
        output.ingestion_effective_access_evidence.identities.worker.expected_role_assignments,
        {
          role_name = "Azure Event Hubs Data Sender"
          scope     = module.event_bus.auxiliary_topic_ids["aw.pipeline.stages"]
        },
      )
    )
    error_message = "the worker role ceiling must be exact and retain account-scoped ADLS plus physical-topic receive and stage send"
  }

  assert {
    condition = (
      length(output.ingestion_effective_access_evidence.identities.migration.expected_role_assignments) == 2 &&
      toset([
        for assignment in output.ingestion_effective_access_evidence.identities.migration.expected_role_assignments :
        assignment.role_name
      ]) == toset(["AcrPull", "Key Vault Secrets User"])
    )
    error_message = "migration authority must remain capped at image pull and administrator-DSN read"
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

  assert {
    condition = (
      output.ingestion_effective_access_evidence.topology == "cohost" &&
      output.ingestion_effective_access_evidence.identities.api.database_role == "fdai_ingestion_cohost" &&
      !output.ingestion_effective_access_evidence.identities.worker.present &&
      output.ingestion_effective_access_evidence.identities.worker.principal_id == "" &&
      length(output.ingestion_effective_access_evidence.identities.worker.expected_role_assignments) == 0
    )
    error_message = "co-host evidence must remove the worker identity and select the co-host database role"
  }

  assert {
    condition = (
      length(output.ingestion_effective_access_evidence.identities.api.expected_role_assignments) == 6 &&
      contains(
        output.ingestion_effective_access_evidence.identities.api.expected_role_assignments,
        {
          role_name = "Azure Event Hubs Data Receiver"
          scope     = module.event_bus.topic_ids["aw.pantheon.objects"]
        },
      ) &&
      contains(
        output.ingestion_effective_access_evidence.identities.api.expected_role_assignments,
        {
          role_name = "Storage Blob Data Contributor"
          scope     = module.document_storage[0].id
        },
      )
    )
    error_message = "co-host rollback must return worker receive authority to the API while preserving the ADLS ceiling"
  }

  assert {
    condition = (
      output.ingestion_effective_access_evidence.checks.identities_distinct_from_executor &&
      output.ingestion_effective_access_evidence.checks.runtime_identities_are_distinct &&
      length(output.ingestion_effective_access_evidence.checks.executor_authority_role_overlap) == 0 &&
      output.ingestion_effective_access_evidence.cohost_rollback.adls_owner == "api" &&
      output.ingestion_effective_access_evidence.cohost_rollback.eventhubs_receive_owner == "api" &&
      output.ingestion_effective_access_evidence.cohost_rollback.migration_identity_preserved &&
      output.ingestion_effective_access_evidence.cohost_rollback.executor_identity_preserved &&
      !output.ingestion_effective_access_evidence.cohost_rollback.worker_identity_present
    )
    error_message = "co-host rollback mapping must preserve migration and executor boundaries without authority overlap"
  }
}

run "worker_scale_to_zero_is_rejected_without_kafka_scaler" {
  command = plan

  variables {
    ingestion_worker_min_replicas = 0
  }

  expect_failures = [var.ingestion_worker_min_replicas]
}

run "disabled_ingestion_emits_inert_evidence" {
  command = plan

  variables {
    enable_document_ingestion = false
    enable_llm                = false
  }

  assert {
    condition = (
      !output.ingestion_effective_access_evidence.enabled &&
      !output.ingestion_effective_access_evidence.identities.api.present &&
      !output.ingestion_effective_access_evidence.identities.worker.present &&
      !output.ingestion_effective_access_evidence.identities.migration.present &&
      output.ingestion_effective_access_evidence.identities.api.principal_id == "" &&
      output.ingestion_effective_access_evidence.identities.worker.principal_id == "" &&
      output.ingestion_effective_access_evidence.identities.migration.principal_id == "" &&
      length(output.ingestion_effective_access_evidence.identities.api.expected_role_assignments) == 0 &&
      length(output.ingestion_effective_access_evidence.identities.worker.expected_role_assignments) == 0 &&
      length(output.ingestion_effective_access_evidence.identities.migration.expected_role_assignments) == 0
    )
    error_message = "disabled ingestion must emit inert evidence without indexing optional identities"
  }
}
