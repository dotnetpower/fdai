output "runner_image" {
  description = "Exact managed image and provenance binding for Foundation input; not apply or readiness authority."
  value = {
    id                 = data.azapi_resource.runner_image.output.id
    location           = data.azapi_resource.runner_image.output.location
    source_commit      = var.source_commit
    toolchain_digest   = local.toolchain_digest
    terraform_root     = "infra/genesis-runner-image"
    mutation_complete  = true
    runner_registered  = false
    subscription_ready = false
  }
}

output "cleanup_scope" {
  description = "Exact root-owned groups removed only by a separately reviewed destroy plan."
  value = {
    image_resource_group_id   = azurerm_resource_group.image.id
    staging_resource_group_id = azurerm_resource_group.staging.id
  }
}
