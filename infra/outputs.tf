# Standard output contract - every module surfaces its handles here so
# the composition layer stays swap-blind.

output "resource_group_name" {
  description = "The RG holding every provisioned resource."
  value       = module.resource_group.name
}

output "executor_identity_resource_id" {
  description = "User-assigned Managed Identity resource id (assign roles against this)."
  value       = module.identity.resource_id
}

output "executor_identity_principal_id" {
  description = "OID of the executor MI (used in role assignments)."
  value       = module.identity.principal_id
}

output "isolated_executor_shadow" {
  description = "Shadow-only isolated Executor deployment handles. Null while disabled."
  value = var.enable_isolated_executor ? {
    app_id                = "/subscriptions/${data.azurerm_client_config.current.subscription_id}/resourceGroups/${module.resource_group.name}/providers/Microsoft.App/containerApps/ca-${var.workload}${local.full_suffix}-executor"
    app_name              = "ca-${var.workload}${local.full_suffix}-executor"
    identity_resource_id  = module.isolated_executor_identity[0].resource_id
    identity_principal_id = module.isolated_executor_identity[0].principal_id
  } : null
}

output "log_workspace_id" {
  description = "Log Analytics workspace id (App Insights binds here)."
  value       = module.log_analytics.workspace_id
}

output "log_workspace_customer_id" {
  description = <<-EOT
    Log Analytics workspace **customer GUID** (the ``workspace_id``
    attribute on ``azurerm_log_analytics_workspace``, NOT the ARM
    resource id). Threaded into the core app as
    ``FDAI_MONITOR_WORKSPACE_ID`` so ``wire_azure_container`` auto-binds
    ``AzureMonitorLogsMetricProvider`` at composition time.
  EOT
  value       = module.log_analytics.workspace_customer_id
}

output "container_registry_login_server" {
  description = "ACR login server (pin images by digest via this host)."
  value       = module.container_registry.login_server
}

output "key_vault_uri" {
  description = "Key Vault URI. Runtime reads secrets via Container Apps native secret + KV reference."
  value       = module.key_vault.uri
}

output "event_bus_kafka_bootstrap" {
  description = "Kafka bootstrap host:port for the Event Hubs endpoint on :9093."
  value       = module.event_bus.kafka_bootstrap
}

output "event_bus_operational_kafka_bootstrap" {
  description = "Kafka bootstrap host:port for isolated canary and raw inventory traffic."
  value       = module.event_bus_auxiliary.kafka_bootstrap
}

output "event_bus_topics" {
  description = "Provisioned primary topic names."
  value       = module.event_bus.topics
}

output "event_bus_auxiliary_topics" {
  description = "Provisioned auxiliary topic names used by stage, approval, and inventory ingress."
  value       = keys(module.event_bus.auxiliary_topic_ids)
}

output "event_bus_operational_topics" {
  description = "Provisioned canary, canary DLQ, and raw inventory topic names."
  value       = keys(module.event_bus_auxiliary.all_topic_ids)
}

output "postgres_fqdn" {
  description = "PostgreSQL Flexible Server fully qualified domain name."
  value       = module.state_store.fqdn
}

output "postgres_database" {
  description = "Postgres database name (pgvector-enabled)."
  value       = module.state_store.database_name
}

output "container_app_environment_id" {
  description = "Container Apps Environment resource id."
  value       = module.compute.environment_id
}

output "core_app_name" {
  description = "Core Container App resource name."
  value       = module.compute.core_app_name
}

output "dev_operations_gateway_url" {
  description = "Authenticated development operations gateway URL. Empty when disabled."
  value       = length(azurerm_function_app_flex_consumption.dev_gateway) > 0 ? "https://${azurerm_function_app_flex_consumption.dev_gateway[0].default_hostname}" : ""
}

output "dev_operations_gateway_audience" {
  description = "Microsoft Entra audience for the development operations gateway. Empty when disabled."
  value       = length(azurerm_function_app_flex_consumption.dev_gateway) > 0 ? var.operator_api_audience : ""
}

output "dev_operations_gateway_app_name" {
  description = "Development operations Function App name. Empty when disabled."
  value       = length(azurerm_function_app_flex_consumption.dev_gateway) > 0 ? azurerm_function_app_flex_consumption.dev_gateway[0].name : ""
}

output "email_communication_service_id" {
  description = "ACS resource id for send-only A2/A4 notification delivery. Empty when email notifications are disabled."
  value       = length(azurerm_communication_service.notifications) > 0 ? azurerm_communication_service.notifications[0].id : ""
}

output "email_sender_address" {
  description = "Azure-managed sender address used by FDAI notifications. Empty when email notifications are disabled."
  value       = length(azurerm_email_communication_service_domain.notifications) > 0 ? "DoNotReply@${azurerm_email_communication_service_domain.notifications[0].from_sender_domain}" : ""
}

output "canary_job_name" {
  description = "Synthetic control-loop canary publisher Job name."
  value       = module.compute.canary_job_name
}

output "measurement_baseline_job_name" {
  description = "Automated-baseline regression Container Apps Job name (Phase-4 continuous measurement)."
  value       = module.measurement_runners.baseline_job_name
}

output "measurement_growth_job_name" {
  description = "Pattern-growth intake Container Apps Job name (Phase-4 T1 library growth)."
  value       = module.measurement_runners.growth_job_name
}


# Per-vertical Managed Identities (phase-3 § Unified Control Loop).
output "identity_change_resource_id" {
  description = "Change Safety vertical Managed Identity resource id."
  value       = module.identity_change.resource_id
}

output "identity_change_principal_id" {
  description = "Change Safety vertical MI object id (assign action-whitelist roles here)."
  value       = module.identity_change.principal_id
}

output "identity_resilience_resource_id" {
  description = "Resilience vertical Managed Identity resource id."
  value       = module.identity_resilience.resource_id
}

output "identity_resilience_principal_id" {
  description = "Resilience vertical MI object id."
  value       = module.identity_resilience.principal_id
}

output "identity_finops_resource_id" {
  description = "FinOps vertical Managed Identity resource id."
  value       = module.identity_finops.resource_id
}

output "identity_finops_principal_id" {
  description = "FinOps vertical MI object id."
  value       = module.identity_finops.principal_id
}

# ---------------------------------------------------------------------------
# LLM (Azure OpenAI) - present only when `enable_llm = true`.
# One-of null-coalesce lets composition roots read the values without a
# conditional in every call site: an empty deployments map means "no LLM
# provisioned in this env".
# ---------------------------------------------------------------------------

output "llm_endpoint" {
  description = "AOAI account endpoint (custom-subdomain URL). Empty string when enable_llm=false."
  value       = length(module.llm_azure_openai) > 0 ? module.llm_azure_openai[0].endpoint : ""
}

output "llm_resource_id" {
  description = "Cognitive Services account ARM id. Empty string when enable_llm=false."
  value       = length(module.llm_azure_openai) > 0 ? module.llm_azure_openai[0].resource_id : ""
}

output "llm_deployments" {
  description = "Map of capability name -> deployment name. Empty map when enable_llm=false."
  value       = length(module.llm_azure_openai) > 0 ? module.llm_azure_openai[0].deployments : {}
}

output "llm_capacity_units" {
  description = "Map of capability name -> provisioned capacity units (thousand TPM)."
  value       = length(module.llm_azure_openai) > 0 ? module.llm_azure_openai[0].capacity_units : {}
}

output "foundry_web_search_project_endpoint" {
  description = "Foundry project endpoint. Empty when deployment-owned web search is disabled."
  value       = local.foundry_web_search_enabled ? module.foundry_web_search[0].project_endpoint : ""
}

output "foundry_web_search_agent_name" {
  description = "Foundry prompt-agent name. Empty when deployment-owned web search is disabled."
  value       = local.foundry_web_search_enabled ? module.foundry_web_search[0].agent_name : ""
}

output "foundry_web_search_model_deployment" {
  description = "Foundry model deployment. Empty when deployment-owned web search is disabled."
  value       = local.foundry_web_search_enabled ? module.foundry_web_search[0].model_deployment_name : ""
}

output "model_apim_gateway_endpoint" {
  description = "Optional OpenAI-compatible APIM endpoint. Null when the existing-APIM integration is disabled."
  value       = try(module.model_apim_gateway[0].gateway_endpoint, null)
}

output "monitoring_action_group_id" {
  description = "Action group id for Azure Monitor alerts (null when enable_monitoring = false)."
  value       = var.enable_monitoring ? module.monitoring[0].action_group_id : null
}

output "console_default_hostname" {
  description = "Operator console Static Web App default hostname (e.g. `<name>.azurestaticapps.net`). Empty string when enable_console = false. Use as the origin for MSAL redirect URIs and as the target for the console/dist/ upload."
  value       = length(module.console) > 0 ? module.console[0].default_hostname : ""
}

output "console_static_web_app_id" {
  description = "Operator console Static Web App resource id (empty string when enable_console = false). Used to fetch the deployment token for the console/dist/ upload."
  value       = length(module.console) > 0 ? module.console[0].static_web_app_id : ""
}

output "design_mocks_default_hostname" {
  description = "Design-mocks Static Web App default hostname. Empty string when enable_design_mocks = false."
  value       = length(module.design_mocks) > 0 ? module.design_mocks[0].default_hostname : ""
}

output "design_mocks_static_web_app_id" {
  description = "Design-mocks Static Web App resource id. Empty string when enable_design_mocks = false."
  value       = length(module.design_mocks) > 0 ? module.design_mocks[0].static_web_app_id : ""
}

output "operator_api_fqdn" {
  description = "Console Operator API Container App ingress FQDN (empty string when enable_operator_api = false). Wire into the console build as VITE_OPERATOR_API_BASE_URL=https://<fqdn>."
  value       = length(module.operator_api) > 0 ? module.operator_api[0].fqdn : ""
}

output "operator_api_name" {
  description = "Console Operator API Container App resource name."
  value       = length(module.operator_api) > 0 ? module.operator_api[0].name : ""
}

output "operator_api_migrate_job_name" {
  description = "Schema-migration Container Apps Job name (empty string when enable_operator_api = false). Start it after apply to run `alembic upgrade head`."
  value       = length(module.operator_api) > 0 ? module.operator_api[0].migrate_job_name : ""
}

output "document_storage_account_name" {
  description = "ADLS Gen2 document storage account name (empty when ingestion is disabled)."
  value       = length(module.document_storage) > 0 ? module.document_storage[0].name : ""
}

output "case_history_storage_account_name" {
  description = "Private versioned case-history storage account name."
  value       = length(module.case_history_storage) > 0 ? module.case_history_storage[0].name : ""
}

output "case_history_container_url" {
  description = "Private Blob container URL consumed by the core case-history adapter."
  value       = length(module.case_history_storage) > 0 ? module.case_history_storage[0].container_url : ""
}

output "document_storage_dfs_endpoint" {
  description = "Private ADLS Gen2 DFS endpoint consumed by the ingestion gateway."
  value       = length(module.document_storage) > 0 ? module.document_storage[0].primary_dfs_endpoint : ""
}

output "ingestion_gateway_fqdn" {
  description = "Production ingestion gateway FQDN for VITE_INGESTION_API_BASE_URL."
  value       = length(module.ingestion_gateway) > 0 ? module.ingestion_gateway[0].fqdn : ""
}

output "ingestion_gateway_name" {
  description = "Production ingestion gateway Container App resource name."
  value       = length(module.ingestion_gateway) > 0 ? module.ingestion_gateway[0].name : ""
}

output "ingestion_worker_name" {
  description = "Internal ingestion worker Container App resource name; empty in co-host rollback mode."
  value       = length(module.ingestion_gateway) > 0 ? module.ingestion_gateway[0].worker_name : ""
}

output "ingestion_migrate_job_name" {
  description = "Ingestion schema migration job name."
  value       = length(module.ingestion_gateway) > 0 ? module.ingestion_gateway[0].migrate_job_name : ""
}

output "ingestion_identity_principal_id" {
  description = "Dedicated document-ingestion API Managed Identity object id."
  value       = length(module.ingestion_identity) > 0 ? module.ingestion_identity[0].principal_id : ""
}

output "ingestion_worker_identity_principal_id" {
  description = "Dedicated document-ingestion worker Managed Identity object id; empty in co-host rollback mode."
  value       = length(module.ingestion_worker_identity) > 0 ? module.ingestion_worker_identity[0].principal_id : ""
}

output "ingestion_migration_identity_principal_id" {
  description = "Dedicated document-ingestion migration Managed Identity object id."
  value       = length(module.ingestion_migration_identity) > 0 ? module.ingestion_migration_identity[0].principal_id : ""
}

locals {
  ingestion_executor_authority_role_names = toset([
    "Azure Event Hubs Data Owner",
  ])
  ingestion_api_principal_id       = try(module.ingestion_identity[0].principal_id, "")
  ingestion_worker_principal_id    = try(module.ingestion_worker_identity[0].principal_id, "")
  ingestion_migration_principal_id = try(module.ingestion_migration_identity[0].principal_id, "")
  ingestion_api_role_ceiling = !var.enable_document_ingestion ? [] : concat(
    [
      {
        role_name = azurerm_role_assignment.ingestion_acr_pull[0].role_definition_name
        scope     = azurerm_role_assignment.ingestion_acr_pull[0].scope
      },
      {
        role_name = azurerm_role_assignment.ingestion_eventhubs_sender[0].role_definition_name
        scope     = azurerm_role_assignment.ingestion_eventhubs_sender[0].scope
      },
      {
        role_name = azurerm_role_assignment.ingestion_document_data[0].role_definition_name
        scope     = azurerm_role_assignment.ingestion_document_data[0].scope
      },
      {
        role_name = "Cognitive Services OpenAI User"
        scope     = module.llm_azure_openai[0].resource_id
      },
    ],
    var.ingestion_cohost_worker ? [
      {
        role_name = azurerm_role_assignment.ingestion_eventhubs_receiver[0].role_definition_name
        scope     = azurerm_role_assignment.ingestion_eventhubs_receiver[0].scope
      },
      {
        role_name = azurerm_role_assignment.ingestion_kv_secrets_user[0].role_definition_name
        scope     = azurerm_role_assignment.ingestion_kv_secrets_user[0].scope
      },
      ] : [
      {
        role_name = azurerm_role_assignment.ingestion_api_kv_secrets_user[0].role_definition_name
        scope     = azurerm_role_assignment.ingestion_api_kv_secrets_user[0].scope
      },
    ],
    var.ingestion_cohost_worker && var.document_ocr_resource_id != "" ? [
      {
        role_name = azurerm_role_assignment.ingestion_ocr_user[0].role_definition_name
        scope     = azurerm_role_assignment.ingestion_ocr_user[0].scope
      },
    ] : [],
  )
  ingestion_worker_role_ceiling = !var.enable_document_ingestion || var.ingestion_cohost_worker ? [] : concat(
    [
      {
        role_name = azurerm_role_assignment.ingestion_worker_acr_pull[0].role_definition_name
        scope     = azurerm_role_assignment.ingestion_worker_acr_pull[0].scope
      },
      {
        role_name = azurerm_role_assignment.ingestion_worker_eventhubs_sender[0].role_definition_name
        scope     = azurerm_role_assignment.ingestion_worker_eventhubs_sender[0].scope
      },
      {
        role_name = azurerm_role_assignment.ingestion_worker_pantheon_receiver[0].role_definition_name
        scope     = azurerm_role_assignment.ingestion_worker_pantheon_receiver[0].scope
      },
      {
        role_name = azurerm_role_assignment.ingestion_worker_kv_secrets_user[0].role_definition_name
        scope     = azurerm_role_assignment.ingestion_worker_kv_secrets_user[0].scope
      },
      {
        role_name = azurerm_role_assignment.ingestion_worker_document_data[0].role_definition_name
        scope     = azurerm_role_assignment.ingestion_worker_document_data[0].scope
      },
      {
        role_name = "Cognitive Services OpenAI User"
        scope     = module.llm_azure_openai[0].resource_id
      },
    ],
    var.document_ocr_resource_id != "" ? [
      {
        role_name = azurerm_role_assignment.ingestion_ocr_user[0].role_definition_name
        scope     = azurerm_role_assignment.ingestion_ocr_user[0].scope
      },
    ] : [],
  )
  ingestion_migration_role_ceiling = !var.enable_document_ingestion ? [] : [
    {
      role_name = azurerm_role_assignment.ingestion_migration_acr_pull[0].role_definition_name
      scope     = azurerm_role_assignment.ingestion_migration_acr_pull[0].scope
    },
    {
      role_name = azurerm_role_assignment.ingestion_migration_kv_secrets_user[0].role_definition_name
      scope     = azurerm_role_assignment.ingestion_migration_kv_secrets_user[0].scope
    },
  ]
  ingestion_runtime_role_names = toset([
    for assignment in concat(
      local.ingestion_api_role_ceiling,
      local.ingestion_worker_role_ceiling,
      local.ingestion_migration_role_ceiling,
    ) : assignment.role_name
  ])
}

output "ingestion_effective_access_evidence" {
  description = "Static expected-access contract for ingestion identities; use the read-only evidence gate to compare it with live Azure RBAC and PostgreSQL roles."
  sensitive   = true
  value = {
    contract_version = "1.0"
    evidence_class   = "terraform-static"
    enabled          = var.enable_document_ingestion
    topology         = var.ingestion_cohost_worker ? "cohost" : "split"
    executor = {
      principal_id         = module.identity.principal_id
      authority_role_names = sort(tolist(local.ingestion_executor_authority_role_names))
    }
    identities = {
      api = {
        present                   = var.enable_document_ingestion
        principal_id              = local.ingestion_api_principal_id
        database_role             = var.ingestion_cohost_worker ? "fdai_ingestion_cohost" : "fdai_ingestion_api"
        expected_role_assignments = local.ingestion_api_role_ceiling
      }
      worker = {
        present                   = var.enable_document_ingestion && !var.ingestion_cohost_worker
        principal_id              = local.ingestion_worker_principal_id
        database_role             = "fdai_ingestion_worker"
        expected_role_assignments = local.ingestion_worker_role_ceiling
      }
      migration = {
        present                   = var.enable_document_ingestion
        principal_id              = local.ingestion_migration_principal_id
        database_role             = var.postgres_admin_login
        expected_role_assignments = local.ingestion_migration_role_ceiling
      }
    }
    checks = {
      identities_distinct_from_executor = var.enable_document_ingestion && (
        local.ingestion_api_principal_id != module.identity.principal_id &&
        local.ingestion_migration_principal_id != module.identity.principal_id &&
        (
          var.ingestion_cohost_worker ||
          local.ingestion_worker_principal_id != module.identity.principal_id
        )
      )
      runtime_identities_are_distinct = var.enable_document_ingestion && (
        local.ingestion_api_principal_id != local.ingestion_migration_principal_id &&
        (
          var.ingestion_cohost_worker ||
          (
            local.ingestion_worker_principal_id != local.ingestion_api_principal_id &&
            local.ingestion_worker_principal_id != local.ingestion_migration_principal_id
          )
        )
      )
      executor_authority_role_overlap = sort(tolist(setintersection(
        local.ingestion_runtime_role_names,
        local.ingestion_executor_authority_role_names,
      )))
    }
    cohost_rollback = {
      flag                              = "ingestion_cohost_worker"
      api_database_role                 = "fdai_ingestion_cohost"
      adls_owner                        = "api"
      eventhubs_receive_owner           = "api"
      worker_identity_present           = false
      migration_identity_preserved      = true
      executor_identity_preserved       = true
      independent_worker_restore_target = "split"
    }
    live_evidence_required = [
      "Azure effective role assignments including inherited scopes",
      "PostgreSQL role existence and non-privileged runtime attributes",
    ]
  }
}
