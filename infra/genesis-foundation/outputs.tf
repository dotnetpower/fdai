output "app_resource_group_name" {
  description = "Foundation-owned application resource-group reference. The platform must use reference-only mode."
  value       = azapi_resource.app_resource_group.name
}

output "app_resource_group_id" {
  description = "Foundation-owned application resource-group ARM reference; not readiness evidence."
  value       = azapi_resource.app_resource_group.id
}

output "foundation_context_digest" {
  description = "App resource-group context binding for the platform's reference-only mode; not authority or readiness evidence."
  value       = var.foundation_context_digest
}

output "private_handoff" {
  description = "Non-secret references for the attested private host only. Container creation, backend migration, role/network readback, and readiness verification remain separate approved work; do not publish this value as portable status."
  value = {
    terraform_root  = "infra/genesis-foundation"
    source_commit   = var.source_commit
    run_digest      = var.run_digest
    subscription_id = var.subscription_id
    tenant_id       = var.tenant_id
    region          = var.region
    app_resource_group = {
      id                        = azapi_resource.app_resource_group.id
      name                      = azapi_resource.app_resource_group.name
      foundation_context_digest = var.foundation_context_digest
    }
    ops = {
      resource_group_name = module.bootstrap.ops_resource_group_name
      vnet_id             = module.bootstrap.ops_vnet_id
      vnet_name           = module.bootstrap.ops_vnet_name
    }
    state = {
      account_id       = azapi_resource.state.id
      account_name     = azapi_resource.state.name
      blob_service_id  = azapi_update_resource.state_blob_service.id
      container_name   = module.bootstrap.state_container_name
      foundation_key   = "ops/genesis-foundation/${var.env}.tfstate"
      use_azuread_auth = true
    }
    runner = {
      vm_name         = module.bootstrap.runner_vm_name
      bootstrap_mode  = local.runner_bootstrap_mode
      source_image_id = var.runner_source_image_id
      identity_id     = module.bootstrap.deploy_runner_identity_id
      client_id       = module.bootstrap.deploy_runner_client_id
      principal_id    = module.bootstrap.deploy_runner_principal_id
      role_manifest   = module.bootstrap.deploy_runner_role_manifest
    }
  }
}
