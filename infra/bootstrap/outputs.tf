# Handles the app config consumes: backend wiring + peering + runner IAM.

output "ops_resource_group_name" {
  value       = azurerm_resource_group.ops.name
  description = "Ops (hub) resource group."
}

output "app_resource_group_name" {
  value       = var.app_resource_group_name
  description = "Foundation-owned application resource group consumed in platform reference mode."
}

output "environment" {
  value       = var.env
  description = "Deployment environment used by repository configuration."
}

output "region" {
  value       = var.region
  description = "Azure region used by the bootstrap deployment."
}

output "region_short" {
  value       = var.region_short
  description = "Short Azure region token used in resource names."
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
  value       = local.state_account_name
  description = "Terraform remote-state storage account. Feed to `terraform init -backend-config` in the app config / CI workflow."
}

output "state_container_name" {
  value       = var.state_container_name
  description = "Blob container holding the app's terraform state. Created from the runner during the approved foundation phase."
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

output "runner_vm_id" {
  value       = var.create_runner_vm ? azurerm_linux_virtual_machine.runner[0].id : null
  description = "Exact private runner VM resource id for approved access transports."
}

output "runner_admin_username" {
  value       = var.create_runner_vm ? var.runner_admin_username : null
  description = "Non-secret SSH username for the private runner."
}

output "runner_parallelism" {
  value       = var.create_runner_vm ? var.runner_parallelism : 0
  description = "Exact number of isolated GitHub Actions slots selected for the runner."
}

output "runner_ssh_public_key_digest" {
  value = var.create_runner_vm ? sha256(join(" ", slice(
    split(" ", trimspace(var.runner_ssh_public_key)), 0, 2
  ))) : null
  description = "SHA-256 of the normalized public SSH key; no private key material is exposed."
}

output "bastion_name" {
  value       = var.enable_bastion ? azurerm_bastion_host.runner[0].name : null
  description = "Optional Standard Bastion host selected explicitly for native runner access."
}

output "bastion_id" {
  value       = var.enable_bastion ? azurerm_bastion_host.runner[0].id : null
  description = "Optional Standard Bastion resource id; absence means no Bastion was provisioned."
}

output "backend_config_hint" {
  value       = "resource_group_name=${azurerm_resource_group.ops.name} storage_account_name=${local.state_account_name} container_name=${var.state_container_name} key=${var.workload}-${var.env}.tfstate"
  description = "Copy into `terraform init -backend-config=...` for the app config."
}
