output "name" {
  value = var.name
}

output "fqdn" {
  value = ""
}

output "id" {
  value = ""
}

output "migrate_job_name" {
  value = azurerm_container_app_job.migrate.name
}

output "worker_name" {
  value = var.cohost_worker ? "" : var.worker_name
}

output "worker_id" {
  value = ""
}
