# Handles the app config consumes: backend wiring + peering + runner IAM.

output "ops_resource_group_name" {
  value       = azurerm_resource_group.ops.name
  description = "Ops (hub) resource group."
}

output "ops_vnet_id" {
  value       = azurerm_virtual_network.ops.id
  description = "Ops (hub) VNet id. The app config peers its spoke VNet to this and links its private DNS zones here so the runner resolves app private endpoints."
}

output "ops_vnet_name" {
  value       = azurerm_virtual_network.ops.name
  description = "Ops (hub) VNet name (peering back-reference)."
}

output "state_storage_account_name" {
  value       = data.azurerm_storage_account.state.name
  description = "Terraform remote-state storage account. Feed to `terraform init -backend-config` in the app config / CI workflow."
}

output "state_container_name" {
  value       = var.state_container_name
  description = "Blob container holding the app's terraform state. Created from the runner (az storage container create --auth-mode login)."
}

output "runner_principal_id" {
  value       = module.deploy_runner_identity.principal_id
  description = "Stable deploy UAMI object id. Retained as the compatibility output consumed by the app config."
}

output "deploy_runner_client_id" {
  value       = module.deploy_runner_identity.client_id
  description = "Stable deploy UAMI client id used by protected workflows for explicit managed-identity login."
}

output "deploy_runner_principal_id" {
  value       = module.deploy_runner_identity.principal_id
  description = "Stable deploy UAMI object id used for token oid and effective-role verification."
}

output "deploy_runner_identity_id" {
  value       = module.deploy_runner_identity.resource_id
  description = "Stable deploy UAMI Azure resource id attached to current and candidate runner VMs."
}

output "deploy_runner_role_manifest" {
  value       = local.deploy_runner_role_manifest
  description = "Bootstrap-owned role names and scopes that must be exact for the stable deploy UAMI."
}

output "runner_vm_name" {
  value       = var.create_runner_vm ? azurerm_linux_virtual_machine.runner[0].name : null
  description = "Runner VM name (reach via az vm run-command / Bastion; no public IP)."
}

output "backend_config_hint" {
  value       = "resource_group_name=${azurerm_resource_group.ops.name} storage_account_name=${data.azurerm_storage_account.state.name} container_name=${var.state_container_name} key=${var.workload}-${var.env}.tfstate"
  description = "Copy into `terraform init -backend-config=...` for the app config."
}
