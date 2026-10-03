output "private_host" {
  description = "Private internal load balancer address used by the managed migration host."
  value       = local.private_host
}

output "database_name" {
  description = "FDAI database name."
  value       = var.database_name
}

output "state_store_secret_id" {
  description = "Versionless Key Vault secret id containing the in-cluster DSN."
  value       = azurerm_key_vault_secret.state_store_dsn.resource_versionless_id
}

output "ingestion_api_dsn_secret_id" {
  description = "Versionless Key Vault secret id containing the in-cluster ingestion API DSN."
  value       = azurerm_key_vault_secret.ingestion_api_dsn.resource_versionless_id
}

output "ingestion_worker_dsn_secret_id" {
  description = "Versionless Key Vault secret id containing the in-cluster ingestion worker DSN."
  value       = azurerm_key_vault_secret.ingestion_worker_dsn.resource_versionless_id
}
