output "fqdn" {
  description = "Read-API Container App ingress FQDN. Wire this into the console build (`VITE_READ_API_BASE_URL`)."
  value       = azurerm_container_app.read_api.ingress[0].fqdn
}

output "name" {
  description = "Read-API Container App resource name."
  value       = azurerm_container_app.read_api.name
}

output "migrate_job_name" {
  description = "Schema-migration Container Apps Job name (start it after apply to run `alembic upgrade head`)."
  value       = azurerm_container_app_job.migrate.name
}
