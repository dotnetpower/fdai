output "fqdn" {
  description = "Empty after runtime state migration; deployment verification reads the live FQDN from Azure."
  value       = ""
}

output "name" {
  description = "Operator API Container App resource name."
  value       = var.name
}

output "migrate_job_name" {
  description = "Schema-migration Container Apps Job name (start it after apply to run `alembic upgrade head`)."
  value       = azurerm_container_app_job.migrate.name
}

output "catalog_job_name" {
  description = "Authoritative catalog materialization Container Apps Job name."
  value       = azurerm_container_app_job.materialize_catalogs.name
}
