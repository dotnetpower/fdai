output "name" {
  value = azurerm_container_app.ingestion.name
}

output "fqdn" {
  value = azurerm_container_app.ingestion.ingress[0].fqdn
}

output "id" {
  value = azurerm_container_app.ingestion.id
}

output "migrate_job_name" {
  value = azurerm_container_app_job.migrate.name
}

output "worker_name" {
  value = length(azurerm_container_app.worker) > 0 ? azurerm_container_app.worker[0].name : ""
}

output "worker_id" {
  value = length(azurerm_container_app.worker) > 0 ? azurerm_container_app.worker[0].id : ""
}
