output "controller_resource_id" {
  description = "Only permitted target for set-controller-credential.py."
  value       = azapi_resource.controller.id
}

output "controller_url" {
  description = "Authoritative platform HTTPS origin, not a health or deployment-success claim."
  value       = "https://${azapi_resource.controller.output.properties.configuration.ingress.fqdn}"
}

output "controller_identity_client_id" {
  value = azurerm_user_assigned_identity.controller.client_id
}

output "worker_resource_group_name" {
  value = azurerm_resource_group.workers.name
}

output "jobs" {
  value = { for key, job in azurerm_container_app_job.worker : key => { name = job.name, id = job.id } }
}

output "controller_config" {
  description = "Nonsecret runtime contract; contains no PAT, registration token, webhook key or private key."
  value       = local.config
}

output "worker_name_prefix" {
  description = "Controller must persist ownership for this prefix and drain naturally before terminal cleanup."
  value       = local.name_prefix
}

output "activation_requirements" {
  value = [
    "Set controller-only PAT and webhook HMAC interactively, then restart the controller revision.",
    "Disable legacy scaler dispatch before enabling exclusive Manual Job ownership.",
    "Verify separate environments and that no worker can obtain the controller identity.",
    "AzureRM cannot set worker identitySettings lifecycle None; independently restrict its runtime endpoint before activation where supported.",
    "Docker is explicitly unavailable while vm_image_id is empty; before enabling, verify CI-only unpeered subnet, egress, baked image bootstrap, SSH public key, vCPU quota and SKU capacity.",
    "Controller dispatch defaults to shadow-only; set controller_apply=true only after independent activation checks.",
    "Read back running image digests, exact RBAC, private blob access and independent terminal cleanup before claiming success.",
  ]
}
