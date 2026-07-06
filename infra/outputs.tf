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
  description = "Provisioned topic names."
  value       = module.event_bus.topics
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
