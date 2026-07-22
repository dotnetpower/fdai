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

output "event_bus_topics" {
  description = "Provisioned primary topic names."
  value       = module.event_bus.topics
}

output "event_bus_auxiliary_topics" {
  description = "Provisioned auxiliary topic names used by stage, approval, and inventory ingress."
  value       = keys(module.event_bus.auxiliary_topic_ids)
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

output "read_api_fqdn" {
  description = "Console read-API Container App ingress FQDN (empty string when enable_read_api = false). Wire into the console build as VITE_READ_API_BASE_URL=https://<fqdn>."
  value       = length(module.read_api) > 0 ? module.read_api[0].fqdn : ""
}

output "read_api_migrate_job_name" {
  description = "Schema-migration Container Apps Job name (empty string when enable_read_api = false). Start it after apply to run `alembic upgrade head`."
  value       = length(module.read_api) > 0 ? module.read_api[0].migrate_job_name : ""
}

output "document_storage_account_name" {
  description = "ADLS Gen2 document storage account name (empty when ingestion is disabled)."
  value       = length(module.document_storage) > 0 ? module.document_storage[0].name : ""
}

output "document_storage_dfs_endpoint" {
  description = "Private ADLS Gen2 DFS endpoint consumed by the ingestion gateway."
  value       = length(module.document_storage) > 0 ? module.document_storage[0].primary_dfs_endpoint : ""
}

output "ingestion_gateway_fqdn" {
  description = "Production ingestion gateway FQDN for VITE_INGESTION_API_BASE_URL."
  value       = length(module.ingestion_gateway) > 0 ? module.ingestion_gateway[0].fqdn : ""
}

output "ingestion_migrate_job_name" {
  description = "Ingestion schema migration job name."
  value       = length(module.ingestion_gateway) > 0 ? module.ingestion_gateway[0].migrate_job_name : ""
}

output "ingestion_identity_principal_id" {
  description = "Dedicated document-ingestion Managed Identity object id."
  value       = length(module.ingestion_identity) > 0 ? module.ingestion_identity[0].principal_id : ""
}
