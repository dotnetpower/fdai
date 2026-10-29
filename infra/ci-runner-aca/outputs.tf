output "resource_group_name" {
  value = azurerm_resource_group.ci.name
}

output "registry_name" {
  value = azurerm_container_registry.ci.name
}

output "job_name" {
  value = azurerm_container_app_job.runner.name
}

output "runner_labels" {
  value = concat(["self-hosted", "Linux", "X64"], var.runner_labels)
}
